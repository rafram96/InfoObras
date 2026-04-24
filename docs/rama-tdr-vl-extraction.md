# Rama `feat/tdr-vl-extraction`

Experimento para mejorar la precisión de extracción TDR usando Qwen-VL directo
sobre las imágenes de las tablas B.1 y B.2, en vez de depender solo del OCR
textual + Qwen 14B.

## Motivación

El pipeline actual:
```
PDF → OCR (Paddle/Qwen-VL) → texto fragmentado → Qwen 14B → JSON
                              ^^^^^^^^^^^^^^^^^
                              aquí se pierde la estructura de tabla
```

El texto OCR mezcla columnas y filas visualmente adyacentes. Qwen 14B trata
de reconstruirlo pero genera:
- **Cross-fila**: profesiones de la fila 10 aparecen en el 9 (y viceversa)
- **Incompletas**: solo extrae 2 de las 6 profesiones de EQUIPAMIENTO HOSPITALARIO
- **Inventadas**: "Ingeniero en Costos" para el cargo ESPECIALISTA EN COSTOS

Hipótesis: Qwen-VL **viendo la imagen de la tabla** elimina el problema de raíz
porque entiende el layout (columnas, bordes, alineación).

## Qué hace la rama

Agrega un **extractor visual estructurado** paralelo al textual. Cuando
`USE_VL_TDR_EXTRACTION=true`:

1. Detecta páginas B.1 y B.2 (regex sobre headers)
2. Renderiza esas páginas como imagen
3. Las pasa a Qwen-VL con prompts que piden JSON directo:
   - B.1: `{numero, cargo, profesiones[]}`
   - B.2: `{numero, cargo, tiempo_meses, cargos_similares[], ...}`
4. Parsea el JSON
5. Mergea con los items del pipeline textual por `numero_fila`:
   - Profesiones: **reemplazo** con las del VL (si no están vacías)
   - Cargos similares: **reemplazo** con los del VL
   - Tiempo y tipo obra: solo si el textual los tenía vacíos

Todo el pipeline textual sigue corriendo normalmente — VL solo
enriquece/corrige al final.

## Archivos nuevos

```
src/tdr/tables/
  vl_extractor.py            ← funciones extraer_b1_visual / extraer_b2_visual
  vl_page_detector.py        ← detectar_paginas_b1_b2 (regex)
  vl_extract_tdr_worker.py   ← subprocess que corre el VL aislado
  vl_extract_tdr_client.py   ← invoca worker + parsea JSON

tests/
  evaluar_tdr.py             ← script de evaluación vs golden
  golden/
    README.md                ← cómo anotar un TDR
    plantilla.json           ← plantilla del golden

src/tdr/extractor/pipeline.py
  + feature flag USE_VL_TDR_EXTRACTION
  + invocación del worker VL al inicio
  + _mergear_vl_con_items() al final
```

## Cómo probar

### 1. Activar el flag

En `.env` (o variable de entorno):
```
USE_VL_TDR_EXTRACTION=true
```

Reiniciar uvicorn.

### 2. Correr un job TDR

Subir PDF desde `/nuevo-analisis` o re-correr uno desde `/historial`.

En logs verás:
```
[pipeline] VL TDR extraction habilitada — invocando worker
[vl-tdr] Lanzando worker: B.1=[2, 3, 4] B.2=[5, 6, 7, 8, 9]
[vl-tdr] Worker OK: B.1=17 filas, B.2=17 filas
[pipeline] Merge VL: 17 items con profesiones B.1, 17 con cargos B.2 reemplazados
```

### 3. Anotar golden set

Ver `tests/golden/README.md`. Basta con 1 TDR para empezar:
```bash
cp tests/golden/plantilla.json tests/golden/rtm_huancavelica.json
# editar con los datos correctos del PDF
```

### 4. Medir precisión

```bash
# Contra un job de BD:
python tests/evaluar_tdr.py tests/golden/rtm_huancavelica.json --job-id=abc123

# Salida:
# Profesiones:     Precision=94%  Recall=87%  F1=0.903
# Cargos similares: Precision=89%  Recall=82%  F1=0.854
# Tiempo meses correcto: 100%
# Tipo obra correcto:    100%
```

Corre el eval antes (con flag `false`) y después (con flag `true`) para comparar.

## Latencia esperada

| Etapa | Tiempo |
|-------|--------|
| Pipeline actual (sin VL) | ~2-3 min |
| + extracción VL B.1 + B.2 (subprocess) | +90-180s |
| **Total con VL** | **~4-6 min por TDR** |

Aceptable para batch processing, alto para real-time.

## Limitaciones conocidas

- **Qwen-VL:7b** se equivoca con tablas mal escaneadas (baja resolución,
  borrosas). Para esos casos el merge deja las del textual como fallback.
- **VRAM**: el worker libera VL al terminar y pre-carga Qwen 14B. Probado con
  16GB VRAM.
- **Cross-page**: si B.1 o B.2 cruzan muchas páginas (>5), la latencia sube.

## Merge a main

Esperar a:
1. Golden set anotado con 1-3 TDRs
2. Eval que demuestre mejora real (F1 profesiones > 0.85 con flag, idealmente)
3. Smoke test de no-regresión con flag `false` (pipeline actual intacto)

Todo el código nuevo está en archivos nuevos — la única modificación al flujo
existente es el bloque de invocación VL y el merge al final, ambos protegidos
por el feature flag `USE_VL_TDR_EXTRACTION`.

## Rollback

`USE_VL_TDR_EXTRACTION=false` desactiva todo. El pipeline queda idéntico al
de `main`.
