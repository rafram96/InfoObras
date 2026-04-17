# Análisis Previo — Revisión del Sábado

> **Fecha:** 2026-04-18 (viernes)
> **Revisión con el jefe:** Sábado AM
> **Foco del jefe:** Procesamiento + Excel/Base de Datos. El frontend NO le importa en detalles, solo funcional.
> **InfoObras scraper:** Pospuesto (ya funciona lo básico)

---

## 1. Backend — Bugs y gaps que afectan el Excel

### 1.1 Regla "a la fecha" no ajusta el cómputo

**Problema:** Cuando el certificado dice "a la fecha" (`end_date = None`):
- ALT05 dispara correctamente (CRITICAL)
- Pero en el Excel:
  - Columna 22 "Dentro 20 años" = NO (porque no hay end_date)
  - Paso 5 no cuenta esa experiencia para años efectivos
- El cliente pidió explícitamente: "la experiencia es válida hasta la fecha de emisión del certificado, no hasta el día de presentación"

**Impacto:** 8 de 41 experiencias del último test quedan mal evaluadas (~20%).

**Fix:** En `evaluator.py`, cuando `end_date is None` y `cert_issue_date` existe, usar `cert_issue_date` como fecha fin efectiva para cols 13, 22 y Paso 5. ALT05 sigue disparando.

**Archivo:** `src/validation/evaluator.py` + `src/validation/rules.py`
**Tiempo:** 30 min

---

### 1.2 Cargo del firmante vacío

**Problema:** Columna 19 "Cargo del Firmante" del Excel siempre vacía.

**Causa:** El prompt `PASO3_PROMPT` extrae `firmante` (nombre) pero no `cargo_firmante`. El modelo `Experience` tampoco tiene ese campo.

**Fix:**
1. Agregar `cargo_firmante` al prompt PASO3
2. Agregar al dataclass `Experience` (opcional, default None)
3. Agregar a `_PASO3_CAMPOS` en llm_extractor
4. Llenar col 19 del Excel con el dato

**Archivo:** `src/extraction/prompts.py`, `models.py`, `llm_extractor.py`, `reporting/excel_writer.py`
**Tiempo:** 20 min

---

### 1.3 Hoja 5 "Verificación InfoObras" siempre vacía

**Problema:** `write_report()` recibe `infoobras_data=None` desde todos los puntos donde se llama. La hoja aparece con "Sin datos de InfoObras (scrapers no ejecutados)".

**Causa:** `_run_full_job` no consulta InfoObras. El endpoint `/evaluate` tampoco.

**Fix opción A (rápida, ~1 hora):** Para cada experiencia con `project_name`, llamar `buscar_obra_por_certificado()`, consolidar resultados y pasarlos a `write_report`.

**Fix opción B (correcta, ~3 horas):** Integrar verificación completa:
- Para cada experiencia → buscar obra en InfoObras
- `verificar_profesional_en_obra()` → comparar nombre + periodo
- Descontar paralizaciones en `calculate_effective_days`
- Llenar hoja 5 con obras verificadas

**Tiempo estimado antes del sábado:** Opción A es viable, Opción B requiere debugging.

---

### 1.4 Pipeline `job_type=full` nunca se probó end-to-end

**Problema:** Todo el flujo integrado (propuesta + bases → OCR + LLM + TDR + Paso 4 + Excel) existe en código pero nunca se ejecutó completo.

**Riesgo:** El sábado el jefe podría pedir "corre uno completo ahora" y fallar.

**Fix:** Hacer una corrida de prueba antes del sábado con Profesionales.pdf + bases_reales.pdf. Identificar fallos.

**Tiempo:** ~40-60 min de ejecución + debug de lo que falle.

---

## 2. Integración desconectada (lógica muerta)

### 2.1 Paso 4 no usa datos de InfoObras automáticamente

`evaluar_propuesta()` acepta `sunat_dates` pero ningún flujo lo llena con datos reales. Tampoco usa `verificar_profesional_en_obra()`. Son código implementado pero huérfano.

### 2.2 Paralizaciones InfoObras no se descuentan

`calculate_effective_days(suspension_periods=...)` acepta el parámetro, pero el endpoint `/evaluate` y `_run_full_job` no lo llenan. Solo descuenta COVID.

**Resultado:** La columna "Años Efectivos" del Excel es incompleta — no refleja los días perdidos por paralizaciones reales.

### 2.3 `verificar_profesional_en_obra()` no se invoca

Función completa para cruzar nombres con supervisores de InfoObras. Ningún punto del código la llama.

---

## 3. Dudas técnicas sin resolver

| # | Duda | Implicación en el Excel |
|---|------|-------------------------|
| 1 | **Profesionales sin nombre extraído** ("sin nombre - Gerente De Contrato") | Aparecen en Excel con fila casi vacía. ¿Descartar? ¿Marcar para revisión? |
| 2 | **Experiencias duplicadas** (el LLM extrae 3x el mismo certificado) | Filas repetidas en Excel. Vi 3 copias del Hospital Cajamarca en el último test. |
| 3 | **Jobs cancelados** (solo se setea flag, subprocess sigue vivo) | La GPU queda ocupada con trabajo desperdiciado |
| 4 | **Ollama cae durante extracción** | Sección queda `_needs_review=True` pero Excel no distingue "no extraído" vs "no existe" |
| 5 | **Páginas OCR con error** (`pages_error > 0`) | Se cuenta pero no se explica cuáles fallaron ni por qué |
| 6 | **Re-evaluar con CUIs manualmente confirmados** | No hay mecanismo — si el usuario confirma un CUI en la UI, no se re-ejecuta Paso 4 |
| 7 | **Historial de concursos** | Solo tabla `jobs` con JSONB. No hay modelo persistente. Cada job es isla. |
| 8 | **Pipeline full con bases escaneadas** | Código tiene fallback motor-OCR, pero 200 págs escaneadas = ~20 min extra. No probado. |

---

## 4. Frontend — Solo lo fundamental para usar el backend

El jefe **no** valora el frontend. Pero necesita ser **usable durante la demo**.

### 4.1 Botón "Descargar Excel" en `/jobs/[id]`

**Estado actual:** El endpoint `/api/jobs/{id}/excel` existe. La UI tiene botones placeholder ("Exportar PDF", "Descargar Reportes") sin funcionalidad.

**Fix:** Conectar el botón existente con el endpoint real.

**Tiempo:** 15 min

---

### 4.2 Botón "Evaluar RTM" en `/jobs/[id]` para jobs `extraction`

**Estado actual:** Hay que llamar `/api/jobs/{id}/evaluate` con curl pasando `tdr_job_id`. Imposible de usar en demo.

**Fix:** Modal o selector en el panel que lista los jobs TDR completados y permite seleccionar cuál cruzar. Genera Excel descargable.

**Tiempo:** 45 min

---

### 4.3 Visor de logs del job en `/jobs/[id]`

**Estado actual:** El campo `logs` existe en la DB (`_append_job_log` lo llena). No se muestra en el panel. Solo visible en terminal de uvicorn.

**Impacto demo:** El jefe va a preguntar "¿qué está haciendo ahora?" mientras procesa. Sin esto, no hay respuesta visual.

**Fix:** Sección colapsable en `/jobs/[id]` que muestra los logs (modo texto con timestamps).

**Tiempo:** 40 min

---

### 4.4 Páginas de herramientas — ya OK

`/herramientas/extraccion` y `/herramientas/tdr` funcionan: subir PDF → crear job → redirigir a `/jobs/[id]`. No requieren cambios.

---

## 5. Dudas de producto (para hablar con el jefe)

### 5.1 ¿El Excel debe tener hojas "por profesional"?

Hoy: todas las experiencias en Base de Datos (27 cols). Paso 4 en Evaluación RTM (22 cols).
Alternativa: una hoja por profesional con sus experiencias + evaluaciones. Más navegable.

### 5.2 ¿Debe haber "veredicto final" por profesional?

Hoy: 22 columnas crudas, el evaluador deduce si aprueba.
Alternativa: columna "APROBADO / OBSERVADO / RECHAZADO" calculada por severidad de alertas.

### 5.3 ¿Colores semáforo son suficientes?

Hoy: verde/amarillo/rojo en texto SI/NO/NO EVALUABLE.
Alternativa: iconos (✅⚠️❌), mejor visible en impresión.

### 5.4 Formato de fechas

Hoy: `DD/MM/YYYY` (15/07/2020).
Manual del cliente: `DD/MES/AAAA` (15/JUL/2020).

### 5.5 ¿Distinción alertas críticas vs informativas?

Hoy: columna "Severidad" dice CRITICO/OBSERVACION.
¿Suficiente visualmente? ¿Necesita algún tipo de agrupación?

---

## 6. Deuda técnica real (no urgente para sábado)

| # | Qué | Riesgo actual |
|---|-----|---------------|
| 1 | **0 tests** | Cada refactor del matching rompe casos |
| 2 | **Jobs cancelados no matan subprocess** | Si se cancela, GPU ocupada hasta que termine el OCR |
| 3 | **Sin modelo persistente** (solo jobs) | No se puede hacer dashboard histórico, comparar concursos, etc. |
| 4 | **Re-procesamiento parcial imposible** | Si falla Paso 4, hay que re-correr desde OCR (40+ min) |
| 5 | **Prompts frágiles sin versionado** | Cualquier cambio en el OCR rompe extracción silenciosamente |

---

## 7. Priorización sugerida — para el sábado

### Viernes (hoy) — hay ~6 horas útiles

**Bloque 1: Fixes del Excel (~1.5 horas)**
- [ ] 1.1 Regla "a la fecha" — 30 min
- [ ] 1.2 Cargo del firmante — 20 min
- [ ] Deduplicar experiencias repetidas — 30 min

**Bloque 2: UX mínima para demo (~1.5 horas)**
- [ ] 4.1 Botón "Descargar Excel" — 15 min
- [ ] 4.3 Visor de logs — 40 min
- [ ] 4.2 Selector de TDR para evaluar — 45 min

**Bloque 3: Validación end-to-end (~1.5 horas)**
- [ ] 1.4 Corrida completa `job_type=full` — 60 min (ejecución + debug)
- [ ] Revisar el Excel generado hoja por hoja — 30 min

**Bloque 4: Opcional si hay tiempo (~1 hora)**
- [ ] 1.3 Opción A: llenar Hoja 5 con datos de InfoObras (búsqueda simple por experiencia)

### Sábado AM — revisión con el jefe

- Mostrar el Excel generado con datos reales
- Demo en vivo: subir propuesta + bases → ver logs en tiempo real → descargar Excel
- Discutir dudas de producto (sección 5)
- Definir prioridades post-sábado

---

## 8. Lo que NO se hace antes del sábado

Estos puntos quedan pospuestos explícitamente:

- ❌ InfoObras: descarga de documentos + ZIP
- ❌ InfoObras: Informes de Control CGR
- ❌ RF-07: Verificación de nombre en valorizaciones descargadas
- ❌ Tests unitarios
- ❌ Cancelación real de subprocess (kill GPU)
- ❌ Base de datos de profesionales/obras (modelo persistente)
- ❌ Organización de docs .md
- ❌ Chat IA (descartado)

---

## 9. Notas de contexto

- **Servidor:** Windows 11, NVIDIA Quadro RTX 5000 16GB, Docker PostgreSQL
- **Tiempo de procesamiento típico:**
  - Propuesta 165 págs: ~20 min (OCR) + ~10 min (LLM) = 30 min
  - Bases 192 págs escaneadas: ~15 min (OCR) + ~2 min (TDR)
  - Paso 4 + Excel: <1 min
  - **Pipeline full estimado:** ~50-60 min por concurso
- **Datos disponibles para demo:**
  - Propuesta.pdf (165 págs) — job `6c1f0fe9` o re-correr
  - Bases TDR — job `1a5495be`
  - Excel de evaluación ya generado en `data/test_paso4_resultado.xlsx`

---

## 10. Preguntas abiertas para ti

1. ¿Comenzamos con el Bloque 1 (fixes del Excel) o el Bloque 2 (UX demo) primero?
2. ¿Hacemos la corrida `job_type=full` ahora para identificar fallos tempranos, o al final una vez arreglados los fixes?
3. ¿La hoja 5 InfoObras (sección 1.3 Opción A) la incluimos o se descarta?
4. ¿Alguna de las dudas de producto (sección 5) vale pre-validar con el jefe vía WhatsApp hoy?
