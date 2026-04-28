# Swap a Gemma 4 — guía operativa

Documento del procedimiento para probar Gemma 4 26B como reemplazo de
Qwen 2.5 14B + Qwen-VL 7B en el pipeline.

> **Branch**: `gemma-branch`
> **Riesgo**: bajo — todo el cambio es config, código retro-compatible.
> **Tiempo de prueba**: 30-60 min para validar baseline vs Gemma.

## Por qué probar Gemma 4

| Aspecto | Qwen 2.5 14B (actual) | Gemma 4 26B (propuesta) |
|---------|------------------------|--------------------------|
| Calidad MMMLU multilingüe | ~70% | **86.3%** |
| Document parsing (OmniDocBench, lower=better) | — | **0.149** vs Gemma 3=0.365 |
| Velocidad output (16 GB Quadro) | ~30 tok/s | ~27 tok/s |
| Velocidad prompt eval (warm) | rápida | **~512 tok/s** medido |
| Context window | 16k custom | 256k nativo (usable 32k) |
| Multimodal (texto + imagen) | NO (necesita modelo VL aparte) | **SÍ — un solo modelo** |
| Licencia | Apache 2.0 | Apache 2.0 |

Lo que esto puede mejorar concretamente:
- **F1 profesiones TDR** (hoy ~0.55) → posible ~0.70+
- **F1 cargos similares B.2** (hoy ~0.30) → posible ~0.50+
- **Cross-row contamination** y alucinaciones tipo "Ingeniero de Costos" → menos
- **Unificar modelo texto + visión** (gemma4:26b cubre los dos roles)

## Lo que cambia el código (ya hecho en esta rama)

| Archivo | Cambio |
|---------|--------|
| `src/tdr/config/settings.py` | + `QWEN_TEMPERATURE`, `QWEN_TOP_P`, `QWEN_TOP_K`, `QWEN_KEEP_ALIVE` desde `.env` |
| `src/extraction/ollama_client.py` | Sampling parametrizado, keep_alive, filtrado defensivo de markdown y thinking blocks |
| `src/tdr/extractor/llm.py` | `_build_extra_body()` helper, sampling parametrizado, filtro thinking añadido a `_limpiar_respuesta` |
| `src/tdr/tables/vl_extractor.py` | Sampling de settings, num_ctx VL subido a 16k, filtro thinking de Gemma en bloque markdown |
| `src/tdr/tables/vision.py` | Mismo tratamiento que vl_extractor |
| `.env.example` | Variables nuevas documentadas con recomendaciones por modelo |
| `src/api/main.py` (banner) | Muestra sampling y keep_alive al startup |

**Cero código asume Qwen específicamente** — todo es config-driven.

## Procedimiento en el server

### 1. Pull del modelo en Ollama

```bash
ollama pull gemma4:26b
ollama list   # confirmar
```

Si VRAM insuficiente al cargar (16 GB tight con num_ctx 32k):
```bash
ollama pull gemma4:e4b   # alternativa más chica (9.6 GB)
```

### 2. Pull del código

```bash
cd /ruta/Alpamayo-InfoObras
git fetch
git checkout gemma-branch
git pull
```

### 3. Backup del .env actual

```bash
cp .env .env.qwen-backup
```

### 4. Editar .env con la nueva config

⚠️ **Importante para VRAM 16 GB**: Gemma 4 26B + `num_ctx=32768` + Gemma 4 26B vision NO cabe.
La KV cache (~6-8 GB) más el modelo (~18 GB) excede los 16 GB y Ollama hace spillover a CPU
(prefill cae de ~500 tok/s a ~8 tok/s — pipeline se vuelve inutilizable).

**Combinación que SÍ funciona en 16 GB**:

```env
# ── Modelos: Gemma para texto, Qwen-VL para visión ──
QWEN_MODEL=gemma4:26b
QWEN_VL_MODEL=qwen2.5vl:7b   # mantener Qwen-VL chico (4.5 GB), evita VRAM contention

# ── Context window ──
QWEN_NUM_CTX=12288   # con Gemma 26B en 16 GB. KV cache ~3 GB + modelo 18 GB = entra apretado.

# ── Sampling para Gemma 4 ──
QWEN_TEMPERATURE=0.3
QWEN_TOP_P=0.9
QWEN_TOP_K=40

# ── Keep alive (importante para Gemma, su carga es ~30s) ──
QWEN_KEEP_ALIVE=10m
```

**Si el modelo sigue cayendo a CPU** (mira `prefill=X tok/s (CPU/RAM)` en logs), tienes 2 opciones:

```env
# Opción A: bajar más el context
QWEN_NUM_CTX=8192

# Opción B (más radical): usar la variante chica de Gemma 4
QWEN_MODEL=gemma4:e4b
QWEN_NUM_CTX=32768
# Calidad ~10 puntos menos en MMMLU pero CABE holgado en VRAM
```

### 5. Reiniciar uvicorn

```bash
# Ctrl+C, luego:
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

El banner debe mostrar:

```
======================================================================
  QWEN_MODEL              = gemma4:26b
  QWEN_NUM_CTX            = 32768
  QWEN_VL_MODEL           = gemma4:26b
  Sampling                = T=0.3  top_p=0.9  top_k=40
  Keep alive              = 10m
  .env QWEN_MODEL         = gemma4:26b
  .env QWEN_NUM_CTX       = 32768
  USE_VL_TDR_EXTRACTION   = false (pipeline textual)
  FORCE_MOTOR_OCR         = false (fast-path habilitado)
======================================================================
```

### 6. Smoke test

Subir el TDR de Huancavelica como análisis "TDR únicamente" desde
`/nuevo-analisis`. Esperar a que termine.

**En logs deberías ver tiempos comparables a Qwen** (3-6 min total) si el
modelo está caliente. Primer job puede tardar +30s por carga inicial.

### 7. Eval contra el golden

```bash
python tests/evaluar_tdr.py tests/golden/rtm_huancavelica.json --job-id=<job_id_gemma>
```

Comparar contra baseline Qwen (último eval guardado):

| Métrica | Baseline Qwen | Gemma | Δ |
|---------|---------------|-------|---|
| Profesiones F1 | 0.596 | ? | ? |
| Cargos similares F1 | 0.308 | ? | ? |
| Tiempo total | ? min | ? min | ? |

### 8. Decisión

| Resultado | Acción |
|-----------|--------|
| F1 profesiones sube ≥ 0.10 y latencia comparable | **Mergear gemma-branch a main**. Documentar nuevo baseline. |
| F1 igual o sube poco (<0.05), latencia comparable | Mantener Qwen, descartar Gemma 26B. Probar `gemma4:e4b` para ver si la chica mejora algo. |
| F1 baja | Revertir a Qwen (paso 9). Reportar resultados para entender por qué. |
| Latencia >> 2x más lenta | Revertir y considerar Gemma 4 e4b o quedarse con Qwen. |

## Probar el path VL (opcional, segunda iteración)

Si la prueba con texto sale bien y querés probar Gemma 4 también para B.1/B.2 visual:

```env
USE_VL_TDR_EXTRACTION=true
```

Reiniciar uvicorn, re-correr el TDR. Comparar precisión de profesiones B.1.

⚠️ **Nota**: el worker `vl_extract_tdr_worker.py` tiene lógica para descargar
el modelo VL y cargar el modelo de texto separados. Si `QWEN_MODEL == QWEN_VL_MODEL`
(ambos gemma4:26b), esa lógica de swap es innecesaria y puede generar
warnings inocuos. Ignorar.

## Rollback completo

Si Gemma no funciona y querés volver a Qwen:

```bash
cp .env.qwen-backup .env
# reiniciar uvicorn
```

Cero cambio de código necesario. Las variables aceptan tanto Qwen como Gemma.

Si querés además volver a `main`:
```bash
git checkout main
```

La rama `gemma-branch` queda viva como histórico del experimento.

## Consideraciones técnicas

### Sampling: por qué 0.3 / 0.9 / 40 y no los defaults de Gemma

Gemma 4 fue entrenado con `temp=1.0, top_p=0.95, top_k=64`. Esos valores
generan respuestas creativas pero **no reproducibles entre runs**, lo cual
rompe el eval contra golden y causa variabilidad en producción.

`0.3 / 0.9 / 40` es el compromiso: suficientemente bajo para que el modelo
sea casi determinista en extracción JSON, suficientemente alto para que no
entre en modo "stuck on first token" que algunos modelos sufren con `temp=0`.

Si Gemma alucina demasiado en este valor, bajar a `0.1 / 0.8 / 20`.
Si es demasiado rígido y trunca, subir a `0.5 / 0.95 / 64` (defaults de Google).

### Filtrado del bloque thinking de Gemma 4

Gemma 4 con thinking activado emite:
```
<|channel|>thought
[razonamiento interno...]
<channel|>
{respuesta JSON real}
```

El filtro en `_limpiar_respuesta` (llm.py) y `_limpiar_bloque_markdown`
(vl_extractor.py) extrae solo la respuesta. **Thinking NO está activado por
defecto** — solo si pones `<|think|>` al inicio del system prompt. Hoy
ningún prompt lo hace; la limpieza es defensiva.

Si querés activar thinking en una iteración futura, ver
`docs/proximas-mejoras-tdr.md` sección "Evaluar cambio de Qwen 2.5 por Gemma 4".

### Keep alive y descargas entre llamadas

`QWEN_KEEP_ALIVE=10m` mantiene el modelo en VRAM 10 min después del último
request. Para batches de 50 profesionales en una propuesta, el modelo se
mantiene caliente y la latencia es óptima.

Si VRAM ajustada y se necesita descargar Qwen-VL para cargar Qwen 14B
(escenario actual con Qwen), el worker `vl_extract_tdr_worker.py` fuerza
descarga con `keep_alive=0`. Con Gemma 4 unificado (mismo modelo para texto
y visión), ese swap es innecesario y se puede simplificar más adelante.

## Próximos pasos si Gemma gana

1. Mergear `gemma-branch` a `main`
2. Actualizar baseline del golden (re-correr eval con Gemma como referencia)
3. Considerar activar thinking mode para tareas críticas (TDR principal) y
   medir si el delta de calidad justifica el costo de latencia
4. Considerar bajar a `gemma4:e4b` si VRAM aprieta y E4B alcanza calidad
   suficiente (10pts MMMLU menos pero 2x VRAM libre)
5. Reescribir prompts para usar `role="system"` separado (Gemma 4 lo soporta
   nativo y produce respuestas más limpias)
