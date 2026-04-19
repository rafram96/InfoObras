# Plan: pdfplumber fast-path para PDFs digitales

> ⚠️ **DOCUMENTO REEMPLAZADO (18-abr-2026):** Su contenido se consolidó en [`../PLAN_MEJORAS_UNIFICADO.md`](../PLAN_MEJORAS_UNIFICADO.md) (sección PARTE 3) junto con el análisis de precisión y los fixes nuevos de la reunión con el cliente. Se deja este archivo solo como referencia histórica del plan detallado.
>
> **Objetivo:** Cuando el PDF ya tiene capa de texto (digital, no escaneado), saltarse el motor-OCR completo y extraer texto con pdfplumber en segundos en vez de horas.
> **Ahorro estimado:** ~30-120 min por propuesta digital (vs 2-3 hrs actualmente).

---

## 1. Situación actual

### Flujo actual (`_run_job`)
```
PDF → motor-OCR subprocess (siempre) → .md files → parse_professional_blocks → LLM → Excel
      └─ PaddleOCR + Qwen VL (lento, GPU, 2-3 hrs)
```

### Lo que ya existe
- `_run_tdr_job` ya usa pdfplumber con fallback a motor-OCR (solo para bases)
- `parse_professional_blocks()` lee archivos `.md` del motor-OCR y los convierte a `ProfessionalBlock[]`
- Los prompts LLM (Pasos 2-3) funcionan sobre `ProfessionalBlock.full_text`

### Lo que motor-OCR produce (formato que debemos emular)

Archivos en `{output_dir}/{pdf_stem}/`:

**`*_texto_*.md`** — texto por página
```markdown
## Página 1
```
[texto de la página 1]
```

## Página 2
```
[texto de la página 2]
```
```

**`*_profesionales_*.md`** — metadata de secciones
```markdown
# Profesionales

## Resumen
| # | Cargo | N° | Págs totales | Bloques | Pág. inicio |
|---|-------|----|----|---------|------------|
| 1 | Jefe De Supervisión | — | 14 | 1–14 | 1 |
| 2 | Especialista Bim | — | 40 | 46–63 · 81–88 · 142–155 | 46 |

## Detalle por profesional

### 1. Jefe De Supervisión
**Total páginas:** 14
**Página separadora:** 1
...
```

Y un JSON de resultados con `doc` + `secciones[]`.

---

## 2. Arquitectura propuesta

### Nuevo flujo con fast-path
```
PDF → ¿digital? ─SÍ→ pdfplumber_fast_path() → .md files (mismo formato)
              └NO→ motor-OCR subprocess     → .md files
                                             ↓
                           parse_professional_blocks [sin cambios]
                                             ↓
                              extract_block (LLM) [sin cambios]
                                             ↓
                                   Excel [sin cambios]
```

**Ventaja:** downstream no se toca. Solo cambiamos cómo se generan los `.md`.

### Detección de PDF digital

Usa la misma lógica que `_run_tdr_job`:
- Abrir con pdfplumber
- Si `chars_per_page ≥ 200` en primeras 5 páginas → digital
- Si `< 50` → escaneado → motor-OCR
- Zona gris (50-200) → motor-OCR conservador

---

## 3. Retos técnicos

### Reto 1: Detección de separadores de profesional

**Motor-OCR** usa páginas cuasi-blancas + fuzzy match contra patrones de cargo ("Jefe de Supervisión", "Especialista en...") para detectar separadores.

**pdfplumber** tiene el texto limpio — debería ser **más fácil**, no más difícil.

**Estrategia:**
1. Para cada página, contar caracteres útiles (sin espacios)
2. Si la página tiene < 50 chars → candidata a separador
3. Aplicar el mismo fuzzy match que motor-OCR contra patrones de cargo
4. Fallback: si no se detecta ningún separador, tratar el PDF entero como un solo profesional

**Reusar código:** el motor-OCR ya tiene esta lógica en `segmentation/detector.py`. Podemos:
- **Opción A:** Copiar los patrones regex + fuzzy a un módulo compartido
- **Opción B:** Importar directamente de motor-OCR (riesgo: acoplamiento entre repos)
- **Opción C (elegida):** Reimplementar simple — los patrones son pocos y estables

### Reto 2: Detección de Tipo A vs Tipo B

**Tipo A** = un bloque contiguo por profesional (caso simple)
**Tipo B** = múltiples bloques por profesional intercalados (ej: Especialista BIM pp. 46-63, 81-88, 142-155)

Motor-OCR detecta Tipo B por análisis de delimitadores "B.1", "B.2" en el texto.

**Estrategia pdfplumber:**
- Por defecto asumir Tipo A (un bloque por profesional)
- Si en el texto de una sección aparece "B.1" o "B.2" → marcar Tipo B y dividir
- Esto cubre la mayoría de casos; los pocos falsos positivos los maneja el LLM

### Reto 3: Métricas fake

Motor-OCR retorna `conf_promedio_documento`, `pages_paddle`, `pages_qwen`, etc.

**Estrategia:** valores fijos que indiquen "pdfplumber":
```python
{
    "total_pages": N,
    "pages_paddle": 0,
    "pages_qwen": 0,
    "pages_error": 0,
    "pages_pdfplumber": N,  # nuevo campo
    "conf_promedio_documento": 1.0,  # texto nativo = confianza máxima
    "tiempo_total": elapsed,
    "engine": "pdfplumber",  # nuevo campo discriminador
}
```

En el Excel: la hoja "Métricas OCR" mostraría "pdfplumber: N págs" en vez de PaddleOCR/Qwen.

### Reto 4: Profesionales no detectables

Si ningún patrón de cargo matchea (PDF con formato raro), el fallback actual es motor-OCR. Pero motor-OCR tampoco encontraría separadores en ese caso.

**Estrategia:** si pdfplumber no encuentra separadores, tratar todo como un solo profesional con cargo "Desconocido" y que el LLM decida. Log de warning al usuario.

---

## 4. Implementación por fases

### Fase 1 — Módulo de conversión (2-3 horas)

**Archivo nuevo:** `src/extraction/pdfplumber_writer.py`

Funciones:
- `extraer_texto_por_pagina(pdf_path) -> dict[int, str]`
- `detectar_separadores(pages_texts) -> list[dict]` — retorna `[{page, cargo, numero}]`
- `detectar_tipo_b(texto_seccion) -> bool`
- `generar_md_texto(pages_texts, output_path)` — escribe `*_texto_*.md`
- `generar_md_profesionales(separadores, total_pages, output_path)` — escribe `*_profesionales_*.md`
- `procesar_pdf_digital(pdf_path, output_dir) -> dict` — orquestador

### Fase 2 — Integración en `_run_job` (1 hora)

**Archivo:** `src/api/main.py`

Agregar rama condicional al inicio de `_run_job`:

```python
def _run_job(job_id, pdf_path, pages):
    _check_cancelled(job_id)
    _update_job(job_id, status="running", ...)

    # NUEVO: detectar PDF digital
    is_digital = _detectar_pdf_digital(pdf_path)
    _append_job_log(job_id, f"Tipo PDF: {'digital' if is_digital else 'escaneado'}")

    if is_digital:
        # Fast-path pdfplumber
        _update_job(job_id, progress_pct=5, progress_stage="Extrayendo con pdfplumber")
        result = procesar_pdf_digital(pdf_path, job_output_dir)
        _append_job_log(job_id, f"pdfplumber completado — {result['total_pages']} págs")
    else:
        # Flujo actual motor-OCR
        ... (código existente sin cambios)

    # Fase 2 (extracción LLM) sin cambios — lee los .md igual
```

### Fase 3 — Detección de separadores (2-3 horas)

**Reto más difícil.** Hay que portar/reimplementar la lógica de `motor-OCR/src/segmentation/detector.py`:
- Regex para cargos OSCE comunes (Jefe de Supervisión, Especialista en *, Gerente de Contrato, etc.)
- Fuzzy match con RapidFuzz contra el texto de cada página candidata
- Filtro de frases descarte ("SEGURO SOCIAL", "CERTIFICA", etc.)

**Estrategia pragmática:**
- Empezar con los ~15 cargos más comunes (hardcoded)
- Fuzzy match con threshold 80+
- Iterar agregando cargos conforme salgan casos nuevos

### Fase 4 — Tests con PDFs reales (1 hora)

- Probar con una propuesta digital real
- Comparar output de pdfplumber vs motor-OCR para el mismo PDF
- Verificar que el Excel sale igual o mejor
- Medir tiempos

### Fase 5 — UI opcional (30 min)

- Badge en `/jobs/[id]` mostrando "Engine: pdfplumber" vs "PaddleOCR + Qwen"
- Opción en `/nuevo-analisis` para forzar motor-OCR (checkbox "Forzar OCR de precisión")

---

## 5. Archivos a modificar

| Archivo | Acción | Líneas aprox. |
|---------|--------|---------------|
| `src/extraction/pdfplumber_writer.py` | NUEVO | ~300 |
| `src/api/main.py` | MODIFICAR `_run_job` | ~30 |
| `src/extraction/prompts.py` | Sin cambios | — |
| `src/extraction/md_parser.py` | Sin cambios (ya soporta el formato) | — |
| `Panel-InfoObras/.../jobs/[id]/page.tsx` | Badge opcional | ~10 |
| `.env.example` | Documentar nueva variable opcional `FORCE_MOTOR_OCR` | ~3 |

---

## 6. Dependencias

### Python (ya instaladas)
- `pdfplumber` ✅
- `rapidfuzz` (para fuzzy match) — verificar si está, si no agregar

### Lógica a portar de motor-OCR

Si no queremos re-inventar la rueda, se puede:

1. Leer `motor-OCR/src/segmentation/detector.py`
2. Extraer la lista de patrones de cargo + filtros de descarte
3. Copiarlos a `pdfplumber_writer.py` como constantes

**Lista típica de cargos (OSCE):**
```python
CARGOS_COMUNES = [
    "Gerente de Contrato", "Jefe de Supervisión",
    "Especialista en Arquitectura", "Especialista BIM",
    "Especialista en Instalaciones Sanitarias",
    "Especialista en Instalaciones Eléctricas",
    "Especialista en Equipamiento Hospitalario",
    "Especialista en Control y Aseguramiento de Calidad",
    "Especialista en Seguridad Salud y Medio Ambiente",
    "Especialista en Metrados Costos y Valorizaciones",
    "Especialista en Implementación de Soluciones TI",
    "Especialista en Configuraciones Tecnológicas",
    "Residente de Obra",
    ...
]
```

---

## 7. Decisiones pendientes antes de implementar

1. **¿Cómo detectar separadores?** (ver Reto 1)
   - Opción A: Copiar patrones de motor-OCR (seguro, estable)
   - Opción B: LLM-asistido (pide al Qwen "identifica las secciones") — más flexible pero lento
   - **Recomiendo A**

2. **¿Qué pasa si pdfplumber falla en detectar separadores?**
   - Opción A: Fallback automático a motor-OCR (seguro, pero pierde la ventaja de velocidad)
   - Opción B: Tratar todo como un solo profesional y que el LLM se arregle
   - **Recomiendo A con notificación clara al usuario**

3. **¿Mantenemos compatibilidad con `job_type=full`?**
   - Sí, el fast-path aplica automáticamente si el PDF es digital
   - Tanto para propuesta como para bases

4. **¿Timeline?**
   - Post-sábado (después de la demo)
   - Tiempo total: ~6-8 horas

---

## 8. Beneficios esperados

| Caso | Antes | Después |
|------|-------|---------|
| Propuesta escaneada 2300 págs | 2-3 hrs | 2-3 hrs (sin cambio) |
| Propuesta digital 500 págs | 1 hr | **~30 seg pdfplumber + 10 min LLM** |
| Bases digitales 200 págs | Ya usa pdfplumber ✅ | — |
| Bases escaneadas 200 págs | 15 min | 15 min (sin cambio) |

**Ahorro masivo en propuestas digitales.** El cuello de botella pasa a ser el LLM (Qwen 14B), que se puede paralelizar parcialmente en el futuro.

---

## 9. Riesgos

| Riesgo | Probabilidad | Mitigación |
|--------|--------------|------------|
| Detección de separadores falla en PDFs con formato raro | Media | Fallback a motor-OCR automático |
| Texto de pdfplumber tiene encoding raro (ñ, tildes) | Baja | Ya funciona en TDR |
| Tipo B mal detectado (secciones intercaladas) | Media | Probar con casos reales, ajustar heurística |
| Propuestas con formato no-OSCE | Alta para casos raros | Documentar limitaciones; motor-OCR como fallback |

---

## 10. Preguntas para decidir

1. ¿Proceder con Opción A (copiar lógica de motor-OCR) o diseñar desde cero?
2. ¿Se implementa después del sábado o es prioridad inmediata?
3. ¿Usuario puede forzar motor-OCR o la decisión es 100% automática?
4. ¿Agregar un badge en el UI mostrando qué engine se usó?
