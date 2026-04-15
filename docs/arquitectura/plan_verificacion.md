# Plan de Verificación — Pipeline Completo

> Basado en `docs/analisis/validacion_sugerida.md` y el estado actual del sistema.
> Fecha: 2026-04-13

---

## Flujo completo de verificación por certificado

```
Certificado extraído (Paso 3)
    │
    ├─ nombre_proyecto
    ├─ cargo (supervisor / residente / etc.)
    ├─ nombre_profesional
    ├─ fecha_inicio, fecha_fin
    ├─ empresa_emisora, ruc
    └─ cui (si lo tiene)
         │
         ▼
    ┌─────────────────────────────────────┐
    │  FASE 1: Resolver CUI              │
    │  ¿Tiene CUI explícito?             │
    │   ├─ SI → fetch_by_cui(cui)        │
    │   └─ NO → buscar_obra_por_cert()   │
    │        ├─ Score > 15 → auto-select │
    │        └─ Score < 15 → UI manual   │
    └─────────────────────────────────────┘
         │
         ▼  WorkInfo (obra, supervisores, avances, paralizaciones)
         │
    ┌─────────────────────────────────────┐
    │  FASE 2: Verificar nombre          │  ← NUEVO
    │  ¿El profesional aparece como      │
    │  supervisor/residente en InfoObras? │
    │   ├─ Jaccard > 0.75 → SI           │
    │   ├─ Jaccard 0.5-0.75 → REVISAR   │
    │   └─ Jaccard < 0.5 → NO COINCIDE  │
    │  ¿El periodo del certificado       │
    │  solapa con el periodo en InfoObras?│
    │   ├─ SI → periodo_valido = true    │
    │   └─ NO → ALERTA                  │
    └─────────────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────────────┐
    │  FASE 3: Calcular días efectivos   │  ← IMPLEMENTADO
    │  1. Días brutos = fin - inicio     │
    │  2. Descontar COVID solapado       │
    │  3. Descontar paralizaciones       │
    │  4. Fusionar periodos solapados    │
    │  Resultado: días_efectivos         │
    └─────────────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────────────┐
    │  FASE 4: Validar días declarados   │  ← NUEVO
    │  ¿Días declarados en certificado   │
    │  coinciden con días calculados?     │
    │   ├─ Diferencia < 5 días → OK      │
    │   └─ Diferencia > 5 días → ALT10  │
    └─────────────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────────────┐
    │  FASE 5: Descargar documentos      │  ← FUTURO
    │  De InfoObras:                     │
    │  - Actas de entrega de terreno     │
    │  - Valorizaciones del periodo      │
    │  - Actas de suspensión             │
    │  - Informes de Control (CGR)       │
    │  → Almacenar en estructura ZIP     │
    └─────────────────────────────────────┘
         │
         ▼
    ┌─────────────────────────────────────┐
    │  FASE 6: Consultas externas        │  ← PARCIAL
    │  - SUNAT: verificación manual      │  (tiene CAPTCHA)
    │  - Colegios prof.: verificación     │  → MANUAL (CIP, CAP, etc.)
    │  - RNP: historial de contratos     │  → FUTURO
    └─────────────────────────────────────┘
```

---

## Estado de implementación por fase

| Fase | Componente | Estado | Archivo |
|------|-----------|--------|---------|
| 1 | Resolver CUI por nombre | ✅ Implementado | `src/scraping/infoobras.py` → `buscar_obra_por_certificado()` |
| 1 | Resolver CUI explícito | ✅ Implementado | `src/scraping/infoobras.py` → `fetch_by_cui()` |
| 1 | UI confirmación manual | ✅ Implementado | Panel: `/herramientas/infoobras` |
| 1 | API búsqueda | ✅ Implementado | `POST /api/infoobras/search` |
| 2 | Verificar nombre en InfoObras | ❌ No implementado | Necesita función `verificar_profesional_en_obra()` |
| 2 | Verificar periodo solapa | ❌ No implementado | Parte de la misma función |
| 3 | Calcular días efectivos | ✅ Implementado | `src/validation/rules.py` → `calculate_effective_days()` |
| 3 | Descuento COVID | ✅ Implementado | Integrado en `calculate_effective_days()` |
| 3 | Descuento paralizaciones | ✅ Implementado | Integrado en `calculate_effective_days()` |
| 4 | Validar días vs declarados | ❌ No implementado | Nueva alerta ALT10 |
| 5 | Descargar documentos | ❌ No implementado | Pendiente estructura ZIP |
| 6 | SUNAT (fecha constitución empresa) | ⏭️ Manual | Tiene CAPTCHA — verificación manual en e-consultaruc.sunat.gob.pe |
| 6 | Colegios profesionales (CIP, CAP, etc.) | ⏭️ Manual | Cada colegio tiene portal distinto — verificación manual |
| 6 | RNP consulta | ❌ No existe | Portal público rnp.gob.pe |

---

## Siguiente implementación: Fase 2 — `verificar_profesional_en_obra()`

```python
def verificar_profesional_en_obra(
    obra: WorkInfo,
    nombre_profesional: str,
    cargo_tipo: str,           # "supervisor" | "residente"
    fecha_inicio_cert: date,
    fecha_fin_cert: date,
) -> dict:
    """
    Verifica si un profesional aparece en InfoObras para la obra dada.
    
    Retorna:
        nombre_coincide: bool
        score_nombre: float (0-1, Jaccard)
        nombre_encontrado: str (mejor match en InfoObras)
        periodo_valido: bool
        alertas: list[str]
    """
```

Esta función ya existe como blueprint en `variety/infoobras/SCRAPER.md` §10 (`verificar_certificado_infobras`). Solo falta migrarla a `src/scraping/infoobras.py`.

---

## Nueva alerta: ALT10 — Días declarados vs calculados

Cuando el certificado declara un número de días/meses y el cálculo propio del sistema no coincide (diferencia > 5 días), se genera ALT10 como OBSERVACIÓN.

Requiere: que el LLM extraiga "duración declarada" del certificado (campo adicional en Paso 3).

---

## Pipeline completo (job_type=full) — diseño

```
POST /api/jobs  (file=propuesta.pdf, bases=bases.pdf, job_type=full)
    │
    ├─ Paso 1: motor-OCR bases (si escaneado) → extraer_bases() → rtm_personal
    ├─ Paso 2-3: motor-OCR propuesta → extracción LLM → profesionales + experiencias
    ├─ Paso 4: evaluar_propuesta(profesionales, experiencias, rtm)
    │
    ├─ Para cada experiencia con nombre_proyecto:
    │   ├─ buscar_obra_por_certificado() → WorkInfo
    │   ├─ verificar_profesional_en_obra() → alertas nombre/periodo
    │   └─ calculate_effective_days() con suspension_periods
    │
    │  (SUNAT: verificación manual por el evaluador — tiene CAPTCHA)
    │  (Colegios profesionales: verificación manual por el evaluador)
    │
    ├─ Generar Excel con 5 hojas + datos InfoObras
    └─ Guardar resultado en DB
```

Tiempo estimado: ~30-45 min para 165 páginas (20 min OCR + 10 min LLM + 5 min scraping + <1s validación)

---

## Prioridad de implementación restante

1. **verificar_profesional_en_obra()** — Fase 2, migrar blueprint
2. **Pipeline completo (job_type=full)** — encadenar todo en un solo job
3. ~~Scraper SUNAT~~ — verificación manual (tiene CAPTCHA)
4. **ALT10** — días declarados vs calculados
6. **Descarga documentos + ZIP** — Fase 5
7. **RNP** — consulta adicional (no prioritaria)
