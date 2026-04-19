# Plan Unificado de Mejoras — Alpamayo-InfoObras

> **Consolida:** análisis de precisión del pipeline (27 issues), plan pdfplumber fast-path, y los 7 fixes nuevos de la reunión con el cliente del 18-abr-2026.
> **Reemplaza:** `docs/ANALISIS_PRECISION_EXTRACCION.md` + `docs/estado_modulos/plan_pdfplumber_fast_path.md` (sus contenidos se integran aquí).
> **Fecha:** 2026-04-18

---

## Resumen ejecutivo

| Bloque | Qué contiene | Tiempo | Criticidad |
|--------|--------------|--------|------------|
| **A'** | Fixes críticos de negocio (reunión 18-abr) | ~1.5 h | 🔴 Pre-demo |
| **A** | Fixes rápidos de precisión TDR (código puro) | 30-45 min | 🔴 Pre-demo |
| **C** | Mejoras de matching (Paso 4) | 1-2 h | 🟠 Pre-demo |
| **B'** | Matching por actividades (LLM adicional) | 3-4 h | 🟠 Post-demo |
| **B** | Mejoras de prompts TDR (requiere re-correr) | 3-4 h | 🟠 Post-demo |
| **D** | Fixes menores de extracción profesionales | 1-2 h | 🟡 Post-demo |
| **FP** | pdfplumber fast-path para PDFs digitales | 6-8 h | 🟢 Mejora |

**Camino recomendado pre-demo (sábado):** A' + A + C (~4 horas) → ~25-30% de mejora visible.

---

## PARTE 1 — Nuevos requisitos de la reunión con el cliente (18-abr-2026)

### N1. 🔴 Fusionar periodos solapados por profesional
**Lo que dijo el cliente:**
> "si estos períodos se transponen no puedo sumar los años porque una persona no puede trabajar dos veces en dos sitios"

**Ejemplo:** Obra A (2015-2020) + Obra B (2014-2016) ≠ 11 años; son ~6 (2015-2016 se solapa).

**Estado actual:** `calculate_effective_days` suma días de cada experiencia por separado.

**Fix:**
- Archivo: `src/validation/rules.py`
- Antes de sumar, agrupar experiencias por `professional_name`
- Fusionar periodos solapados: algoritmo clásico de merge-intervals
- Recién entonces restar COVID/suspensiones

**Tiempo:** 30 min

---

### N2. 🔴 ALT10 — Experiencia antes de la fecha de colegiatura no vale
**Lo que dijo el cliente:**
> "experiencia solo vale desde que inició su colegiatura. Perdimos Pedro Ríz porque Marco le dio experiencia por una fecha antes de su colegiatura"

**Estado actual:** No hay alerta ni ajuste. Se suman todos los días aunque sean previos.

**Fix:**
- Archivo: `src/validation/rules.py`
- Nueva alerta `ALT10`: si `exp.start_date < profesional.fecha_colegiacion` → alerta + ajustar `start_date = fecha_colegiacion` para el cálculo de días
- Requiere que `fecha_colegiacion` esté disponible en el modelo `Professional`

**Tiempo:** 30 min

---

### N3. 🔴 Cambiar umbral de antigüedad de 20 a 25 años
**Lo que dijo el cliente:**
> "ahorita ya no es hasta los 20 años, ahorita es los 25"

**Estado actual:** `calculate_effective_days` y columna 22 del Excel usan 20 años.

**Fix:**
- Archivo: `src/validation/rules.py` (constante `AÑOS_MAX_ANTIGUEDAD`)
- Cambiar 20 → 25
- Actualizar textos en Excel y en `/info/alertas` (ya actualizado en frontend)
- Afecta ALT03 y col 22 del Excel

**Tiempo:** 5 min

---

### N4. 🟠 Match por actividades del certificado (no solo por cargo)
**Lo que dijo el cliente:**
> "el cargo 'asistente' no matchea con 'ingeniero de campo'. Pero el certificado dice: 'personal de administración de actividades de supervisión de campo'. Comparé si las actividades son equivalentes y me dice que sí, cumple"

**Estado actual:** `match_cargo` solo compara títulos.

**Fix:**
- Nuevo campo `actividades_descripcion` en `Experience` (`src/extraction/models.py`)
- Extraerlo en `PASO3_PROMPT` (`src/extraction/prompts.py`)
- Nueva función `match_por_actividades(actividades_cert, actividades_bases)` en `src/validation/matching.py` que llama al LLM (Qwen 14B) si `match_cargo` retorna False
- Si LLM dice CUMPLE → marcar "CUMPLE (por actividades)" en el Excel

**Tiempo:** 3-4 h (requiere cambio de prompt + LLM adicional por certificado)

---

### N5. 🟠 Columnas "Cumple años acumulados" visibles en Excel
**Lo que dijo el cliente:**
> "debería haber una columna aquí que cumple el número de años acumulado... 36 meses + 1 año = 4 años, lo compara con los 5 años y entonces cumple"

**Fix:**
- Archivo: `src/reporting/excel_writer.py` hoja "Resumen"
- Agregar columnas:
  - `Años requeridos RTM` (de `experiencia_minima.cantidad / 12`)
  - `Años requeridos factor` (del factor de evaluación)
  - `Cumple RTM` — verde/rojo
  - `Cumple factor` — verde/rojo
- Semáforo formato condicional openpyxl

**Tiempo:** 30 min

---

### N6. 🟡 Reportar cargos RTM faltantes (profesionales no detectados)
**Lo que dijo el cliente:**
> "falta Cristian, si se ha saltado uno... en el ingeniero de campo fíjate en la página 123"

**Causa raíz:** motor-OCR a veces omite separadores.

**Fix (mitigación en este repo):**
- En hoja "Resumen" del Excel: sección "Cargos RTM sin profesional extraído"
- Comparar lista de cargos en `rtm_personal` vs lista de profesionales extraídos
- Listar los faltantes como alerta manual

**Tiempo:** 20 min

---

### N7. 🟡 Distinción certificado vs constancia
**Lo que dijo el cliente:**
> "si es constancia... certificado debe ser en planilla"

**Estado actual:** Extraemos `tipo_acreditacion` pero no aplicamos reglas diferenciadas.

**Fix:** Pendiente consultar con cliente qué tratamiento específico. De momento solo asegurar que `tipo_acreditacion` se extrae bien.

**Tiempo:** Desconocido — bloqueado por respuesta del cliente.

---

## PARTE 2 — Precisión del pipeline TDR (27 issues)

### Causas raíz del fallo del 18-abr-2026

1. Tablas B.2 entrelazadas → solo 1-2 profesionales de 10+ extraídos
2. Dedup perdió sinónimos → matching posterior falla
3. Páginas válidas filtradas por score bajo → RTM incompleto
4. `_filtrar_asistentes` descartó roles legítimos
5. `tipo_obra_valido` quedó null por regla ambigua

### 🔴 Bloque A — Fixes rápidos de alto impacto (~30-45 min)

| # | Issue | Archivo | Tiempo | Impacto |
|---|-------|---------|--------|---------|
| A.1 | `_dedup_personal` — unir listas en vez de elegir la más larga | `src/tdr/extractor/pipeline.py:360-375` | 10 min | +5-8% |
| A.2 | Bajar `SCORER_MIN_SCORE` a 2.0 para bloques `rtm_personal` | `src/tdr/extractor/scorer.py` | 5 min | +8-12% |
| A.3 | Subir `_MAX_CELDA` a 600 | `src/tdr/extractor/pipeline.py:43` | 2 min | +4-7% |
| A.4 | Detector tabla fragmentada: `len<50` y `ratio>0.4` | `src/tdr/tables/detector.py:40-44` | 10 min | +3-5% |
| A.5 | Eliminar `_filtrar_asistentes` agresivo o condicionarlo | `src/tdr/extractor/pipeline.py:436-437` | 10 min | +2-3% |

**Total estimado:** +22-35% precisión, sin re-correr TDR.

### 🟠 Bloque B — Mejoras de prompts (3-4 h, requiere re-correr)

| # | Issue | Archivo | Tiempo |
|---|-------|---------|--------|
| B.1 | Regla para tablas entrelazadas en `PROMPT_RTM_PERSONAL` | `src/tdr/config/signals.py` | 30 min |
| B.2 | Simplificar regla `tipo_obra_valido` — extraer sector ignorando público/privado | `src/tdr/config/signals.py:267` | 15 min |
| B.3 | Limitar ventana de búsqueda para `cargos_similares_validos` | `src/tdr/config/signals.py:263` | 15 min |
| B.4 | `anos_colegiado` siempre como string ("36 meses", no 36) | `src/tdr/config/signals.py:258` | 5 min |
| B.5 | Factores `aplica_a: ambos` → dividir en dos objetos | `src/tdr/config/signals.py` PROMPT_FACTORES | 15 min |
| B.6 | "a la fecha" → null en PASO3 (no texto) | `src/extraction/prompts.py:54` | 5 min |
| B.7 | Distinguir CUI vs DNI en PASO2 | `src/extraction/prompts.py:17` | 10 min |

### 🟠 Bloque C — Matching Paso 4 (1-2 h, no requiere re-correr TDR)

| # | Issue | Archivo | Tiempo |
|---|-------|---------|--------|
| C.1 | Agregar sectores faltantes (energía, telecom, residuos, patrimonio) | `src/validation/matching.py:16-58` | 15 min |
| C.2 | Agregar cargos faltantes (Estructuras, Topografía, Acabados, Sistemas) | `src/validation/matching.py:241-279` | 20 min |
| C.3 | `_buscar_requisito` retorna MEJOR match (mayor `experiencia_minima.cantidad`) | `src/validation/evaluator.py:60-73` | 15 min |
| C.4 | `match_cargo` tres-way: True/False/None = CUMPLE/NO CUMPLE/NO EVALUABLE | `src/validation/evaluator.py:157` | 10 min |
| C.5 | Subir umbral Jaccard a 60% en `_buscar_requisito` | `src/validation/evaluator.py:90` | 5 min |
| C.6 | `match_cargo` substring con threshold 80% | `src/validation/matching.py:351` | 10 min |

### 🟡 Bloque D — Fixes menores (1-2 h, pipeline TDR post-LLM)

| # | Issue | Archivo | Tiempo |
|---|-------|---------|--------|
| D.1 | `_filtrar_meta_cargos` regex sin `$` final | `src/tdr/extractor/pipeline.py:479` | 5 min |
| D.2 | `_cruzar_personal_con_factores` aplica TODOS los genéricos | `src/tdr/extractor/pipeline.py:613-643` | 15 min |
| D.3 | `_merge_capacitacion` solo sobrescribe si VL tiene horas | `src/tdr/extractor/pipeline.py:779` | 10 min |
| D.4 | `_filtrar_registros_vacios` requiere 3+ campos | `src/tdr/extractor/pipeline.py:254` | 10 min |
| D.5 | Agrupación de páginas VL: dividir por cambio de tabla | `src/tdr/tables/enhancer.py:277-295` | 30 min |
| D.6 | `_filtrar_paginas` regex `CLÁUSULA\s*\d+\s*[.:-]` | `src/extraction/llm_extractor.py:26-43` | 5 min |
| D.7 | `_normalizar_experiencia` fallback años `(\d{4})\s*al\s*(\d{4})` | `src/extraction/llm_extractor.py:475-483` | 10 min |
| D.8 | `_deduplicar_experiencias` normaliza antes de hashear | `src/extraction/llm_extractor.py:514-530` | 10 min |
| D.9 | Retry Paso 2 con bloques 0+1 unificados si Tipo B | `src/extraction/llm_extractor.py:621-651` | 15 min |

---

## PARTE 3 — pdfplumber fast-path para PDFs digitales

### Objetivo
Cuando el PDF ya tiene capa de texto (digital, no escaneado), saltarse el motor-OCR y extraer texto en segundos en vez de horas.

### Ahorro esperado
| Caso | Antes | Después |
|------|-------|---------|
| Propuesta digital 500 págs | ~1 h | ~30 seg (pdfplumber) + 10 min (LLM) |
| Propuesta escaneada 2300 págs | 2-3 h | sin cambio |
| Bases digitales 200 págs | ya usa pdfplumber | — |

### Arquitectura
```
PDF → ¿digital? ─SÍ→ pdfplumber_fast_path() → .md files (mismo formato motor-OCR)
              └NO→ motor-OCR subprocess     → .md files
                                             ↓
                           parse_professional_blocks [sin cambios]
                                             ↓
                              extract_block (LLM) [sin cambios]
                                             ↓
                                   Excel [sin cambios]
```

Downstream NO se toca. Solo cambia cómo se generan los `.md`.

### Detección digital/escaneado
- Abrir con pdfplumber primeras 5 páginas
- `chars_per_page ≥ 200` → digital (usa pdfplumber)
- `< 50` → escaneado (motor-OCR)
- Zona gris 50-200 → motor-OCR conservador

### Retos clave

**Reto 1 — Separadores de profesional:** portar patrones regex de `motor-OCR/src/segmentation/detector.py` a un nuevo módulo compartido (~15 cargos OSCE comunes hardcoded, fuzzy match con RapidFuzz threshold 80+).

**Reto 2 — Tipo A vs B:** por defecto A (un bloque por profesional); si aparecen "B.1"/"B.2" en el texto → marcar B y dividir.

**Reto 3 — Métricas fake:** valores fijos `engine="pdfplumber"`, `conf_promedio=1.0`, `pages_paddle=0`, `pages_qwen=0`, `pages_pdfplumber=N`.

**Reto 4 — PDFs sin separadores detectables:** fallback automático a motor-OCR con notificación en la UI.

### Fases de implementación

| Fase | Qué hace | Tiempo |
|------|----------|--------|
| 1 | Nuevo módulo `src/extraction/pdfplumber_writer.py` (~300 líneas) | 2-3 h |
| 2 | Integración condicional en `_run_job` de `src/api/main.py` (~30 líneas) | 1 h |
| 3 | Portar detector de separadores desde motor-OCR | 2-3 h |
| 4 | Tests con PDFs digitales reales | 1 h |
| 5 | UI: badge "Engine: pdfplumber" + checkbox "Forzar OCR" | 30 min |

**Total:** 6-8 h. Post-demo.

### Decisiones pendientes
1. ¿Copiar patrones de motor-OCR o LLM-asistido? → **A (copiar, estable)**
2. ¿Fallback si pdfplumber no detecta separadores? → **Motor-OCR automático**
3. ¿Usuario puede forzar motor-OCR? → **Sí, checkbox opcional**

### Riesgos
- Detección falla en formatos no-OSCE → fallback motor-OCR
- Tipo B mal detectado → probar casos reales, ajustar heurística
- Encoding (ñ/tildes) → ya funciona en TDR, bajo riesgo

---

## Plan de ataque recomendado

### 🔴 Fase 1 — Pre-demo (~4 horas)

**Orden sugerido:**

1. **N3** — cambiar 20→25 años (5 min). Bug crítico de reglas.
2. **N1** — fusión de periodos solapados (30 min). Impacta años efectivos visibles.
3. **Bloque A** completo (30-45 min) — código puro, sin re-correr TDR.
4. **Bloque C** top 4 (C.1-C.4) — matching, re-correr solo `/evaluate` (segundos).
5. **N2** — ALT10 experiencia antes de colegiatura (30 min).
6. **N5** — columnas cumple años en Resumen Excel (30 min).
7. **Re-correr TDR** una vez con el mismo PDF de la prueba fallida (~15 min) → comparar output vs anterior.

**Criterio de éxito:** +3-5 cargos detectados, +2-4 cargos_similares por cargo, tipo_obra_valido lleno en ≥80% de RTMs.

### 🟠 Fase 2 — Post-demo inmediato (1-2 días)

1. **Bloque B** completo (prompts TDR) — cada cambio requiere re-correr
2. **N4** — match por actividades (prompt PASO3 + LLM adicional)
3. **N6** — reporte de cargos faltantes en Excel
4. **Bloque D** — fixes menores

### 🟢 Fase 3 — Mejora continua (semana siguiente)

1. **pdfplumber fast-path** completo
2. **N7** — tratamiento constancia vs certificado (requiere input del cliente)

---

## Qué NO se puede arreglar con código/prompt

- OCR de mala calidad en el PDF original → motor-OCR ya entrega lo mejor posible
- Bases con formato atípico no-OSCE → requiere review manual
- Tablas con >4 niveles de anidación → fallback "NO EVALUABLE" + flag

---

## Medición de mejora

**Baseline:** guardar JSON del último job TDR fallido (ID del 18-abr) antes de aplicar fixes.

**Métricas:**
| Métrica | Antes | Objetivo post-A |
|---------|-------|-----------------|
| Cargos RTM extraídos | X | X + 3-5 |
| `cargos_similares_validos` promedio por cargo | Y | Y + 2-4 |
| `tipo_obra_valido` no-null ratio | Z% | ≥80% |
| Profesionales con match RTM | 11/12 | ≥12/12 |
| Alertas generadas totales | N | N + ALT10 casos |

**Validación final:** comparar Excel contra la revisión manual del cliente para el mismo PDF (si está disponible).

---

## Preguntas abiertas para el cliente

1. **N7:** ¿Qué tratamiento específico se da a una constancia vs certificado en planilla?
2. **N1:** ¿Los periodos solapados se fusionan SIEMPRE, o hay casos donde sí se permite (ej: trabajo a tiempo parcial en dos obras)?
3. **N2:** ¿La fecha de colegiatura es la de la colegiación inicial, o hay una fecha de re-colegiación si hubo suspensión?
4. **N4:** Si el LLM dice "cumple por actividades" pero el cargo es formalmente inválido, ¿se marca CUMPLE o solo OBSERVACIÓN?

---

## Archivos tocados (resumen)

### Parte 1 (negocio)
- `src/validation/rules.py` — fusión solapados, ALT10, AÑOS_MAX_ANTIGUEDAD=25
- `src/extraction/models.py` — campo `actividades_descripcion`
- `src/extraction/prompts.py` — PASO3 extrae actividades
- `src/validation/matching.py` — función `match_por_actividades` (LLM)
- `src/reporting/excel_writer.py` — columnas cumple años, cargos RTM faltantes
- `Panel-InfoObras/.../info/alertas/page.tsx` — ALT10 documentada (pendiente)

### Parte 2 (precisión)
- `src/tdr/extractor/pipeline.py` — dedup, filtros, compresión, capacitación
- `src/tdr/extractor/scorer.py` — umbral score
- `src/tdr/tables/detector.py` — ratio tabla fragmentada
- `src/tdr/tables/enhancer.py` — agrupación páginas VL
- `src/tdr/config/signals.py` — prompts TDR
- `src/validation/matching.py` — sectores y cargos
- `src/validation/evaluator.py` — buscar_requisito, tres-way
- `src/extraction/prompts.py` — PASO2, PASO3
- `src/extraction/llm_extractor.py` — filtros, dedup, normalización

### Parte 3 (pdfplumber)
- `src/extraction/pdfplumber_writer.py` — NUEVO
- `src/api/main.py` — rama condicional en `_run_job`
- `Panel-InfoObras/.../jobs/[id]/page.tsx` — badge engine
- `.env.example` — `FORCE_MOTOR_OCR` opcional
