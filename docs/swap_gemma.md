# Swap a Gemma 4 — guía operativa

Documento del procedimiento para probar Gemma 4 26B como reemplazo de
Qwen 2.5 14B + Qwen-VL 7B en el pipeline.

> **Branch**: `gemma-branch`
> **Estado**: ❌ **EXPERIMENTO CERRADO** — Gemma 4 NO viable en hardware actual
>            (ver sección "Resultado del experimento" al final).
> **Riesgo**: bajo — todo el cambio es config, código retro-compatible.

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

## Resultado del experimento (2026-04-28)

**Veredicto: ❌ Gemma 4 NO viable en Quadro RTX 5000 16 GB.**

### Lo que probamos

1. **gemma4:26b + num_ctx=32768**
   - VRAM: 15919 / 16384 MiB ocupado solo cargando el modelo (97%)
   - Al llegar request → spillover a CPU/RAM (`prefill 8 tok/s`)
   - Bloque rtm_postor: 251s. rtm_personal: timeout >5 min sin respuesta
   - Inutilizable.

2. **gemma4:26b + num_ctx=12288** (intento de bajar el contexto)
   - Mismo VRAM apretado. Mismo spillover.
   - No mejora.

3. **gemma4:e4b + num_ctx=32178** (modelo más chico, debería caber holgado)
   - VRAM: ~10 GB ocupado, deja margen para context.
   - **Pero**: Ollama NO expande el num_ctx desde su default de 4096 cuando
     llega un request con `options.num_ctx=32178`. Truncó silenciosamente:

     | Bloque | Prompt enviado | Tokens procesados |
     |--------|----------------|-------------------|
     | rtm_postor | ~2440 tok | 2024 (cabe) |
     | rtm_personal | ~10850 tok | **4096 (truncado 60%)** |
     | retry | ~14434 tok | **4096 (truncado 70%)** |
     | factores | ~3811 tok | 3168 (cabe) |

   - Con prompts truncados, Gemma e4b **alucina con confianza**:
     - rtm_personal devolvió cargos inventados ("Estructuras", "Instalaciones
       Hidrosanitarias") con descripciones genéricas tipo manual ("RETIE",
       "sistemas fotovoltaicos"), nada del TDR real.
     - factores_evaluacion devolvió tabla markdown con factores y puntajes
       inventados ("Cumplimiento Legal: 15 puntos") que **no existen en el TDR**.
   - Resultado final del job: 1 postor + **0 cargos** + **0 factores**.
   - Inutilizable para producción.

### Lecciones aprendidas

1. **Hardware**: 16 GB de VRAM no alcanza para Gemma 4 26B con context útil.
   Para usar 26B en este pipeline haría falta GPU con ≥24 GB.

2. **Ollama y num_ctx**: Ollama no siempre expande el contexto en runtime
   aunque le pases `options.num_ctx` por request. Si el modelo se cargó
   con su default, el request se trunca. Solución parcial: definir
   `OLLAMA_NUM_CTX` global en el daemon de Ollama, o crear un Modelfile
   custom (ej: `qwen2.5-14b-16k`) con el num_ctx baked in.

3. **Gemma 4 e4b**: aunque MMMLU multilingüe es 76.6%, su comportamiento
   con prompts truncados es **alucinar en vez de pedir más contexto**.
   Eso lo hace inseguro para extracción estructurada compleja: prefiero
   un modelo que diga "no encontré nada" a uno que invente datos plausibles.

4. **Qwen 2.5 14B sigue siendo el mejor compromiso disponible** en este
   hardware (16 GB). Hasta upgrade de GPU o aparición de modelo
   intermedio (~12-15B) específicamente entrenado para extracción JSON,
   el path es Qwen 14B + iteraciones de prompt.

### Cambios que SÍ vale la pena cherry-pickear a main desde gemma-branch

Aunque el modelo no funcionó, hay infraestructura útil que conviene salvar:

- **Filtros defensivos de markdown y thinking blocks** en `_limpiar_respuesta`
  (llm.py) y `_limpiar_bloque_markdown` (vl_extractor.py) — útiles incluso
  con Qwen si en algún momento un prompt hace que devuelva texto extra.
- **Variables de sampling parametrizadas** (`QWEN_TEMPERATURE`, `TOP_P`,
  `TOP_K`, `KEEP_ALIVE`) en settings.py + `_build_extra_body()` helper en
  llm.py — permite tunear sin tocar código.
- **`format=json` en extra_body** (`_build_extra_body()`) — fuerza JSON
  output en Ollama, útil con cualquier modelo.
- **Banner ampliado** en main.py mostrando sampling efectivo.
- **Fix `delete_job`** en main.py manejando PermissionError de Windows
  cuando el log handler aún tiene el archivo abierto.

Cherry-pick selectivo recomendado:
```bash
git checkout main
git cherry-pick <commit-hashes>
```

### Cuándo retomar

Reabrir este experimento si:
- Hay upgrade de GPU a ≥24 GB VRAM.
- Sale variante intermedia de Gemma 4 (~12-15B).
- Aparece otro modelo open-source competitivo entrenado específicamente
  para extracción JSON estructurada (ej: deepseek-coder-v3, phi-5, etc.).
- Ollama mejora el manejo de num_ctx dinámico.

Hasta entonces: Qwen 2.5 14B + iteraciones de prompt sigue siendo el path.
