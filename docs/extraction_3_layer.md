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

- **Capa 2** — PP-Structure detecta regiones de tabla con un modelo
  específico de layout. Devuelve coordenadas de celdas que se mapean a
  matriz [filas][columnas]. Mismo principio que Capa 1.

- **Capa 3** (fallback robusto) — El catálogo de cargos OSCE actúa de
  ancla. `rapidfuzz` busca dónde empieza cada cargo en el texto OCR
  (umbral 85). Cada fila se segmenta entre dos anclas. El LLM recibe
  el chunk de UNA fila — literalmente no puede contaminar.

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
| Capa 1 falla, cae a Capa 3 | +2-3 min |
| Capa 1 falla, Capa 3 procesa 17 filas | +4-5 min (17 llamadas LLM) |

La Capa 3 es paralelizable (cada fila es independiente). En esta primera
iteración corre serial — si la latencia es bloqueante, se puede paralelizar
con `concurrent.futures.ThreadPoolExecutor` sin tocar la lógica.

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

- **Capa 2 placeholder**: `_esta_disponible_pp_structure()` retorna `False`
  hasta que motor-OCR exponga el mode `table_extract`. Trabajo aditivo
  futuro al motor-OCR (no rompe nada actual).
- **Catálogo OSCE estático**: 33+ cargos canónicos hard-codeados en
  `layer3_regex_rows.py::CATALOGO_CARGOS_OSCE`. Si OSCE agrega cargos
  nuevos, hay que actualizar el catálogo (regla simple, fácil de mantener).
- **n_filas_esperadas=17**: hard-coded en la integración del pipeline.
  Si el TDR tiene 12 cargos, el orchestrator marcará 12/17=71% como "no
  aceptable" y caerá a Capa 3. En la práctica la Capa 3 también devolverá
  12 filas — funciona, solo da un fallback innecesario. Mejora futura:
  detectar n_filas_esperadas leyendo "N° X" del PDF.
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
