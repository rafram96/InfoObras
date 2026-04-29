# Rama `feat/extraction-3-layer`

Pipeline alternativo de extracción TDR (tablas B.1 y B.2) que ataca
**cross-row contamination de raíz**, eliminando la responsabilidad del LLM
de identificar límites de fila/columna.

Objetivo declarado: **F1 ≥ 0.90** en profesiones y cargos similares.

## Motivación

El pipeline actual (incluido el experimento `feat/tdr-vl-extraction`) sufre
los mismos síntomas en distinto grado:

```
PDF → OCR → texto fragmentado → LLM ve TODA la tabla → JSON
                                ^^^^^^^^^^^^^^^^^^^^^
                                aquí se mezclan filas/columnas
```

El LLM intenta reconstruir la estructura tabular desde texto que perdió
el layout. Resultados típicos sobre TDR de hospitales (17 cargos):

- **F1 profesiones ~0.55** — la fila 9 hereda profesiones de la 10, etc.
- **F1 cargos similares ~0.30** — peor todavía: B.2 tiene celdas verbosas
- **Profesiones inventadas** — "Ingeniero en Costos" para ESPECIALISTA EN COSTOS
- **Listas truncadas** — solo 2 de 6 profesiones en EQUIPAMIENTO HOSPITALARIO

Causa raíz: **el LLM tiene atención difusa sobre todas las filas a la vez**.
Cualquier prompt engineering ataca síntomas, no la causa.

## Estrategia: 3 capas con fallback automático

```
                     ┌──────────────────────────────────────┐
                     │   PDF de bases (TDR)                 │
                     └──────────────┬───────────────────────┘
                                    │
                                    ▼
        ┌───────────────────────────────────────────────────┐
        │ Capa 1: pdfplumber.extract_tables()               │
        │  • Celdas exactas de PDFs digitales con bordes    │
        │  • Cero LLM para estructura                       │
        │  • Confianza 0.95                                 │
        └───────┬───────────────────────────────────────────┘
                │ ¿aceptable?
                │
        ┌───────┴────────────┐
        │ NO                 │ SÍ → return
        ▼
        ┌───────────────────────────────────────────────────┐
        │ Capa 2: PaddleOCR PP-Structure (escaneados)       │
        │  • Subprocess al motor-OCR (placeholder por ahora)│
        │  • Celdas aproximadas pero estructuradas          │
        │  • Confianza 0.80                                 │
        └───────┬───────────────────────────────────────────┘
                │ ¿aceptable o disponible?
                │
        ┌───────┴────────────┐
        │ NO                 │ SÍ → return
        ▼
        ┌───────────────────────────────────────────────────┐
        │ Capa 3: regex segmentación + LLM por fila aislada │
        │  • Catálogo cargos OSCE como anclas               │
        │  • LLM ve UNA fila por llamada                    │
        │  • Cross-row imposible por construcción           │
        │  • Confianza 0.65                                 │
        └───────────────────────────────────────────────────┘
```

### Por qué cada capa elimina cross-row

- **Capa 1** — `pdfplumber` lee los bordes vectoriales del PDF. Cada celda
  está físicamente delimitada en el archivo. El LLM nunca ve más de una
  celda B.2 a la vez (cuando se necesita parseo verboso).

- **Capa 2** — PP-Structure V3 (PaddleOCR) detecta regiones de tabla con
  un modelo específico de layout y devuelve HTML estructurado por tabla.
  Un parser HTML (con soporte para `colspan`/`rowspan`) lo convierte a
  matriz `[filas][columnas]`. Mismo principio que Capa 1: el LLM nunca
  ve más de una celda B.2 a la vez. Implementado vía subprocess al
  motor-OCR (mode `table_extract`, rama `feat/table-extract-pp-structure`).

- **Capa 3** (fallback robusto) — El catálogo de cargos OSCE (~70 cargos)
  actúa de ancla. `rapidfuzz` busca dónde empieza cada cargo en el texto
  OCR (umbral 85). Si el catálogo encuentra menos de la mitad de los
  esperados, hay un **fallback secundario** por número de fila (`"1.",
  "01)", "N° 1"`). Cada fila se segmenta entre dos anclas. El LLM recibe
  el chunk de UNA fila — literalmente no puede contaminar. Las 17
  llamadas LLM corren en paralelo (default 4 workers) con `keep_alive=10m`
  del modelo Qwen. Pre-warm de la primera llamada serial para que el
  modelo cargue una sola vez en GPU. Después, validación post-LLM:
  profesiones que en realidad son cargos se mueven al campo correcto;
  cargos que son títulos puros (sin "Especialista"/"Jefe"/etc.) se
  descartan.

### Aceptación de capa

`orchestrator._es_resultado_aceptable()` decide si pasar a la siguiente:

1. **Cobertura de filas**: ≥ 80% de las esperadas (default 17 cargos)
2. **Cobertura de campos**: ≥ 70% de las filas con `profesiones_aceptadas`
   no vacías o `cargos_similares_validos` no vacíos

Si ambos se cumplen → la capa "gana" y se devuelve. Si no, fallback.

## Archivos nuevos

```
src/tdr/extractor/table_extractor/
  __init__.py             ← API pública (extraer_tdr_3_capas, FilaTDR, …)
  models.py               ← dataclasses: FilaTDR, ResultadoExtraccion, Confianza
  cell_parser.py          ← parsers de celda + LLM mini-prompt para B.2 verbosa
  layer1_pdfplumber.py    ← pdfplumber.extract_tables + mapeo de columnas
  layer2_paddle.py        ← PP-Structure subprocess (stub por ahora)
  layer3_regex_rows.py    ← catálogo cargos OSCE + LLM por fila aislada
  orchestrator.py         ← decide capa, fallback, mergea con textual

docs/extraction_3_layer.md ← este archivo
```

### Archivos modificados

```
src/tdr/extractor/pipeline.py
  + bloque opt-in: invocación 3-capas si USE_3LAYER_EXTRACTION=true
  + bloque opt-in: merge con rtm_personal por numero_fila

.env.example
  + variable USE_3LAYER_EXTRACTION (default false)
```

### Cambios en motor-OCR (rama `feat/table-extract-pp-structure`)

**Aditivos, no rompen nada existente.** Para usar Capa 2 en producción
hay que pullear esta rama (o mergearla a main) en el servidor:

```
motor-OCR/src/engines/table_extract/
  __init__.py            ← exposes extract_tables_from_pdf
  pp_structure.py        ← singleton PPStructureV3 + parser HTML colspan/rowspan
  pipeline.py            ← orquesta PDF -> imágenes -> PP-Structure -> matrices

motor-OCR/subprocess_wrapper.py
  + nuevo mode 'table_extract' (sólo disposition; los modes existentes
    ocr_only / segmentation / pdfplumber_segmentation no se tocan)

motor-OCR/CLAUDE.md
  + entrada del mode 'table_extract' en la tabla de modes
  + documentación del nuevo engine
```

**Cero cambios destructivos.** Todo es aditivo y protegido por feature flag.

## Cómo probar

### 1. Activar el flag en el servidor

En `.env` del servidor (no en la laptop):

```
USE_3LAYER_EXTRACTION=true
```

Reiniciar uvicorn.

### 2. Correr un job TDR

Subir PDF desde `/nuevo-analisis` o re-correr uno desde `/historial`
(`POST /api/jobs/:id/rerun`).

Logs esperados:

```
[pipeline] 3-LAYER habilitado: B.1=[2, 3] B.2=[4, 5, 6]
[orchestrator] Intentando Capa 1 (pdfplumber)
[orchestrator] Capa 1 ACEPTADA: 17 filas, cobertura 100%
[pipeline] 3-LAYER OK: capa=layer1 filas=17 intentadas=['layer1']
[pipeline] Merge 3-LAYER: actualizados=17, agregados=0, solo_textuales=0
```

Si Capa 1 no es aceptable verás:

```
[orchestrator] Capa 1 no aceptable: cobertura_baja: 5/17 = 29% < 80% — fallback a Capa 2
[orchestrator] Intentando Capa 2 (PP-Structure)
[layer2] PP-Structure mode no implementado todavia en motor-OCR. Capa 2 saltada — orchestrator caera a Capa 3.
[orchestrator] Intentando Capa 3 (regex + LLM por fila)
```

### 3. Combinar con `USE_VL_TDR_EXTRACTION`

Ambos flags pueden estar activos a la vez. Orden de aplicación en `pipeline.py`:

```
pipeline textual (siempre)
  ↓
extracción 3-capas → merge      (si USE_3LAYER_EXTRACTION)
  ↓
extracción VL → merge           (si USE_VL_TDR_EXTRACTION)
```

VL corre después y puede sobreescribir lo del 3-capas si el VL devuelve
profesiones/cargos no vacíos. Para A/B limpio, dejar **uno solo activo**.

### 4. Forzar una capa (debug)

```python
from src.tdr.extractor.table_extractor import extraer_tdr_3_capas

resultado = extraer_tdr_3_capas(
    pdf_path="data/uploads/.../bases.pdf",
    texto_por_pagina={2: "...", 3: "..."},
    paginas_b1=[2, 3],
    paginas_b2=[4, 5, 6],
    forzar_capa="layer3",   # salta 1 y 2, va directo a 3
)
print(resultado.filas)
print(resultado.diagnostico)
```

## Latencia esperada

| Caso | Tiempo agregado |
|------|-----------------|
| PDF digital con bordes (Capa 1 acepta) | +30-60s |
| PDF escaneado (Capa 2 — PP-Structure subprocess) | +60-120s |
| Capa 1 y 2 fallan, cae a Capa 3 (paralelo, 4 workers) | +60-120s |
| Capa 3 con 1 worker (legacy serial) | +3-5 min |

Capa 3 corre las 17 llamadas LLM **en paralelo** con `ThreadPoolExecutor`
(default 4 workers, configurable via `LAYER3_MAX_WORKERS`). La primera
llamada va serial (pre-warm) para que el modelo Qwen cargue una sola vez
en GPU. `keep_alive=10m` mantiene el modelo cargado entre llamadas.

## Métricas esperadas

Sobre el TDR de Tambobamba/Lircay (golden set existente):

| Métrica           | Pipeline actual | + VL flag | + 3-capas (Capa 1) | + 3-capas (Capa 3) |
|-------------------|-----------------|-----------|---------------------|---------------------|
| F1 profesiones    | 0.55            | 0.78      | **0.95+**           | **0.85-0.90**       |
| F1 cargos sim.    | 0.30            | 0.65      | **0.90+**           | **0.75-0.80**       |
| Tiempo correcto   | 70%             | 95%       | 100%                | 95%                 |
| Cargos inventados | sí (3-5)        | raro      | **cero**            | **raro**            |

Capa 1 es el gold standard cuando el PDF lo permite (tablas con bordes).
Capa 3 el seguro de fondo. Capa 2 cubre el hueco entre ambos cuando
PP-Structure se implemente en motor-OCR.

## Limitaciones conocidas

- **Capa 2 requiere motor-OCR actualizado**: la rama
  `feat/table-extract-pp-structure` del repo motor-OCR debe estar
  pulleada en el servidor (`D:\proyectos\motor-OCR`) para que el mode
  `table_extract` esté disponible. Si está en `main` viejo, la Capa 2
  detectará `mode=ocr_only`/segmentation y devolverá `[]` con motivo en
  diagnóstico — el orchestrator cae a Capa 3 sin romper.
- **Catálogo OSCE estático**: ~70 cargos canónicos hard-codeados en
  `layer3_regex_rows.py::CATALOGO_CARGOS_OSCE`. Si OSCE agrega cargos
  nuevos, hay que actualizar el catálogo (regla simple, fácil de mantener).
  La Capa 3 ya tiene un **fallback por número de fila** que funciona
  incluso si el catálogo no encuentra los cargos.
- **n_filas_esperadas=17**: hard-coded en la integración del pipeline.
  Si el TDR tiene 12 cargos, el orchestrator marcará 12/17=71% como "no
  aceptable" y caerá a Capa 3. En la práctica la Capa 3 también devolverá
  12 filas — funciona, solo da un fallback innecesario. Mejora futura:
  detectar n_filas_esperadas leyendo "N° X" del PDF.
- **Paralelismo Capa 3 vs VRAM**: el default de `LAYER3_MAX_WORKERS=4`
  asume 16 GB VRAM con Qwen 14B Q4. Si hay OOM, bajar a 2. Si hay 24+ GB,
  subir a 6-8. La primera llamada va serial (pre-warm) para evitar que
  4 workers compitan por cargar el modelo.
- **PDFs con bordes mal renderizados**: pdfplumber a veces detecta tablas
  fantasma o pierde columnas. La heurística de aceptación de la Capa 1
  filtra esos casos.

## Configuración

Variable única en `.env`:

```
USE_3LAYER_EXTRACTION=false   # default seguro
```

No requiere variables nuevas adicionales — reusa `QWEN_MODEL`,
`QWEN_NUM_CTX`, `QWEN_TIMEOUT`, `OLLAMA_BASE_URL` ya existentes.

## Merge a main

Esperar a:

1. Smoke test con flag `false` — pipeline actual idéntico (no-regresión)
2. Smoke test con flag `true` sobre 1 TDR digital — Capa 1 acepta, F1 sube
3. Smoke test con flag `true` sobre 1 TDR escaneado — Capa 3 acepta, F1 sube
4. Validación con golden set: F1 profesiones ≥ 0.85, cargos similares ≥ 0.75

Cuando Capa 2 se implemente en motor-OCR (`mode: table_extract` en
`subprocess_wrapper.py`), basta con cambiar `_esta_disponible_pp_structure()`
para que retorne `True` cuando el wrapper lo exponga — el orchestrator ya
está conectado.

## Rollback

`USE_3LAYER_EXTRACTION=false` desactiva todo. El pipeline queda idéntico
al de `main`. Como el flag está protegido con `if pdf_path and …`, ni
siquiera importa si los archivos del módulo `table_extractor/` existen.
