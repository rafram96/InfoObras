# Cache de OCR por hash de PDF — diseño

Documento de planeamiento. No implementado.

## El problema que resuelve

Diagnóstico empírico (mayo 2026, ver tests/jsons/): el mismo PDF de bases (`rtm.18-04-2026-123526.pdf`, sha `f782793725e37143`) procesado 3 veces por motor-OCR produce 3 archivos `.md` con sha256 distinto:

| Run | `_texto_*.md` sha256_16 | size | chars |
|---|---|---|---|
| 1 | `79e830e4a94afb30` | 36548 | 34288 |
| 2 | (sin diagnostic) | ? | ? |
| 3 | `7dd07ca302742c89` | ? | ? |

Esto significa que **motor-OCR es no-determinístico** para PDFs escaneados (camino PaddleOCR + Qwen-VL). La diferencia es de ~12 chars pero se amplifica downstream: el 3-layer cambia de `_fuente_extraccion: layer2` a `merge:textual+layer2`, las extracciones del LLM divergen, los cargos extraídos cambian de fila, y el Excel final difiere.

Causa raíz probable: batching no-determinístico en PaddleOCR (GPU memory layout) + Qwen-VL sin `seed` fijo. Arreglar esto en motor-OCR es riesgoso (memory dice "no tocar el pipeline PaddleOCR/Qwen, dependencias frágiles").

## La solución — cache aditivo en Alpamayo

Interceptar la llamada a motor-OCR antes del subprocess. Si ya procesamos este PDF (mismo hash) con este modo, copiar los `.md` cacheados al `job_output_dir` y saltar el subprocess. Si no, correr motor-OCR normal y guardar el output en el cache para próximas veces.

**Beneficios:**

1. **Determinismo de facto**: el primer run define el output del PDF. Todos los siguientes reusan exactamente esos `.md`. No hay variación entre runs porque NO se re-ejecuta motor-OCR.
2. **Speedup brutal**: motor-OCR tarda 40-100 min para propuestas grandes. Cache hit ≈ 1 segundo (copia de archivos). Re-runs, testing y re-evaluaciones dejan de ser dolorosas.
3. **Comparaciones válidas**: tool TDR vs full pipeline sobre el mismo bases.pdf usan los mismos `.md` del cache. Cualquier divergencia restante es 100% culpa del LLM/lógica downstream, no del OCR.
4. **Respeta "no tocar motor-OCR"**: vive en Alpamayo, intercepta antes del subprocess. Motor-OCR queda intacto.
5. **Beneficia al cliente**: cuando Manuel re-evalúa el mismo PDF con otro TDR o vuelve a un job viejo, no espera otros 40 minutos.

## Cómo funciona — flujo

```
Job arranca con pdf_path
        ↓
_decidir_mode → "segmentation" o "pdfplumber_segmentation"
        ↓
ocr_cache.lookup(pdf_sha, mode, pages, engine_version)
        ↓
   ┌────┴────┐
   ↓         ↓
 HIT       MISS
   ↓         ↓
copiar    invocar motor-OCR (subprocess actual)
.md a       ↓
job_dir   ocr_cache.store(key, job_output_dir)
   ↓         ↓
   └────┬────┘
        ↓
seguir flujo normal (parse_professional_blocks, etc.)
```

## Estructura de directorios

```
data/ocr_cache/
├── {pdf_sha256_16}/                          # 16 chars del sha del PDF
│   └── {mode}__{engine_version}/             # e.g. "segmentation__v1"
│       ├── pages.json                        # {"pages": null} o {"pages": [1,5,10]}
│       ├── result.json                       # snapshot del raw del subprocess
│       └── md/
│           ├── {nombre}_metricas_*.md
│           ├── {nombre}_texto_*.md
│           ├── {nombre}_profesionales_*.md   # solo si mode=segmentation
│           └── {nombre}_segmentacion_*.md
└── index.json                                # opcional: lista de entries para admin endpoint
```

**Por qué la sub-carpeta `{mode}__{engine_version}`**: el mismo PDF puede ser procesado con `pdfplumber_segmentation` o con `segmentation` (forzado). Son outputs distintos. Y el `engine_version` separa por versión del pipeline (ver "Invalidación").

**Por qué `pages.json`**: si el job pidió solo páginas `[1,5,10]`, el cache vale solo para ese subset. Otro job pidiendo páginas distintas debe re-procesar. Cache key incluye un hash del slice de páginas.

## Cache key

```python
def cache_key(pdf_path: Path, mode: str, pages: list | None) -> str:
    pdf_sha = sha256_file(pdf_path)[:16]
    pages_part = "all" if pages is None else sha256(json.dumps(pages, sort_keys=True))[:8]
    engine_ver = os.getenv("ENGINE_VERSION", "v1")
    return f"{pdf_sha}/{mode}__{engine_ver}__{pages_part}"
```

Cuatro componentes:
- `pdf_sha`: identifica el contenido del PDF. Mismo PDF → mismo sha aunque cambie el nombre.
- `mode`: el output cambia según el modo (motor-OCR completo vs fast-path pdfplumber).
- `engine_ver`: discriminador de versión del pipeline (ver siguiente sección).
- `pages_part`: si pediste solo unas páginas, el output es distinto al del documento completo.

## Invalidación del cache — explicación detallada

El cache es correcto **solo si motor-OCR no cambió desde que se generaron los `.md`**. Si actualizas motor-OCR (mejor prompt de Qwen-VL, fix de un bug del segmentador, nueva versión de PaddleOCR), los `.md` viejos del cache fueron generados por el motor antiguo. Si los seguimos sirviendo, los re-runs darán resultados desactualizados.

**Mecanismo propuesto:** variable de entorno `ENGINE_VERSION` en `.env`.

```env
ENGINE_VERSION=v1
```

- Por defecto `v1`. El cache key usa este valor.
- Cuando hagas un cambio significativo a motor-OCR (cambio de prompt, nueva versión de PaddleOCR, mejora del segmentador), incrementas a `v2`. Cache key cambia → todos los lookups dan MISS → se regenera con el motor nuevo.
- Los `.md` viejos del cache quedan en disco bajo `{mode}__v1/` pero ya no se usan. Puedes borrarlos o dejarlos para A/B testing.
- Si solo arreglas un typo o cambias un comentario, NO bumpeas — el cache sigue válido.

Tres alternativas que consideré y descarté:

1. **Hash automático del código de motor-OCR**: cada vez que arranca el server, hashea los `.py` de `motor-OCR/src/`. Si cambia, invalida cache. Problema: invalida en cambios irrelevantes (typos, comentarios, formato), y depende de tener motor-OCR accesible al startup.
2. **Solo manual via endpoint**: nunca invalida automático. Si actualizas motor-OCR y se te olvida llamar al endpoint, sirves resultados viejos sin saberlo. Demasiado fácil de equivocarse.
3. **Sin invalidación, asumir motor-OCR estable**: si motor-OCR está "100% HECHO, NO TOCAR", no hace falta. Pero el repo acepta engines aditivos (`engines/pdfplumber/` ya se agregó), así que SÍ va a cambiar.

**Recomendación**: env var manual `ENGINE_VERSION`. Simple, explícito, tú decides cuándo es "significativo". Documentar en CLAUDE.md de motor-OCR: "si tocas el engine, bumpea ENGINE_VERSION en Alpamayo".

## Endpoints administrativos

```
GET    /api/admin/ocr-cache              → lista entries cacheadas (paginado)
GET    /api/admin/ocr-cache/{pdf_sha}    → detalle: modes cacheados, sizes, dates
DELETE /api/admin/ocr-cache              → wipe completo (con ?confirm=true)
DELETE /api/admin/ocr-cache/{pdf_sha}    → invalida un PDF específico
POST   /api/admin/ocr-cache/cleanup      → borra entries de engine_version != actual
```

## Integración con `_diagnostic`

Cada fase de extracción ya emite un `_diagnostic` (en `feat/all-pending-tracing`). Le agregamos:

```python
"ocr_output": {
    "engine": "...",
    "total_pages": 18,
    "cache_hit": true,                          # NUEVO
    "cache_key": "f782793725e37143/...",        # NUEVO
    "cache_age_hours": 4.2,                     # NUEVO — cuándo se generó originalmente
    "md_files": [...],
}
```

En el job log:

```
[ocr_cache] HIT for sha=f782793725e37143 mode=segmentation key=f782.../...__v1__all (5 .md, 248KB)
```

o

```
[ocr_cache] MISS for sha=f782793725e37143 — invocando motor-OCR
[ocr_cache] STORED key=f782.../...__v1__all (5 .md, 248KB) en 4823s
```

## Casos de uso reales

| Escenario | Comportamiento |
|---|---|
| Primera vez con un PDF nuevo | MISS → corre motor-OCR (~40 min) → store cache |
| Mismo PDF, mismo modo | HIT → 1 segundo, mismo `.md` siempre |
| Mismo PDF, modo distinto (force motor-OCR vs pdfplumber) | MISS para el modo nuevo (son outputs diferentes) |
| Mismo PDF, subset de páginas distinto | MISS (cache key cambia) |
| Mismo PDF después de bumpear `ENGINE_VERSION` | MISS → regenera con motor nuevo |
| Re-run de un job viejo (POST /jobs/:id/rerun) | HIT (si no cambió engine version) → re-run en segundos en vez de horas |
| Compare tool TDR vs full pipeline con el mismo bases | Ambos HIT después de la primera vez → mismos `.md` → comparación válida |

## Lo que NO hace

- **No deduplica resultados parciales**: si motor-OCR crashea a media corrida, no hay cache parcial.
- **No comparte cache entre máquinas**: vive en `data/ocr_cache/` local. Si el cliente tiene varios servidores, cada uno tiene su propio cache.
- **No comprime**: los `.md` se guardan tal cual. Para 50 PDFs típicos son ~250 MB. Si crece mucho, agregar gzip es trivial.
- **No expira automáticamente**: una entry cacheada vive para siempre hasta que la borren explícitamente o cambien `ENGINE_VERSION`.

## Implementación — archivos a tocar

| Archivo | Cambio | Estimado |
|---|---|---|
| `src/api/ocr_cache.py` (nuevo) | Helpers `cache_key`, `lookup`, `store`, `list_entries`, `delete` | ~120 líneas |
| `src/api/main.py` | En `_pipeline_extraccion_profesionales` y `_pipeline_extraccion_tdr`: check cache antes de `_ejecutar_ocr_con_fallback`, store después. Endpoints admin. | ~60 líneas |
| `src/api/diagnostic.py` | Función `cache_hit_info()` que se inyecta en `ocr_output` del diag | ~15 líneas |
| `.env.example` | Documentar `ENGINE_VERSION=v1` | 2 líneas |
| `CLAUDE.md` (Alpamayo) | Sección "Cache de OCR" explicando cuándo bumpear engine version | ~20 líneas |
| `docs/ocr_cache.md` | Este doc + nota "implementado" cuando se haga | — |

Total estimado: ~220 líneas de código + docs. 1 día de trabajo focused.

## Casos borde a manejar

1. **`pdf_path` no existe**: lookup retorna None (no cachear errores).
2. **Cache directory corrupto/incompleto**: si falta algún `.md` esperado, invalidar esa entry y re-correr.
3. **Disk full al store**: log error, no romper el job (la copia falla pero el .md original sigue en job_output_dir).
4. **Concurrencia**: dos jobs distintos con el mismo PDF arrancando casi al mismo tiempo. Solución simple: lock file `{key}/.lock` mientras se escribe. El segundo job espera.
5. **Cache hit pero el `.md` cacheado tiene un error que ya arreglamos**: bumpear `ENGINE_VERSION` o borrar esa entry.

## Combinación con el fix de `seed=42`

Independiente del cache, agregar `"seed": 42` a las opciones de Ollama en Alpamayo (NO en motor-OCR) sigue valiendo la pena:

- Llamadas LLM en `src/extraction/ollama_client.py` (extracción profesionales)
- Llamadas LLM en `src/tdr/extractor/llm.py` (extracción TDR textual)
- Llamadas LLM en `src/tdr/extractor/table_extractor/*.py`

Por qué: aunque el cache resuelve el OCR, las llamadas LLM siguen siendo no-deterministas. Con seed=42 garantizamos que para el mismo prompt, Ollama da la misma respuesta. Combina con cache OCR → determinismo end-to-end.

NO tocar motor-OCR para el seed — esa parte queda como está.

## Decisión pendiente antes de implementar

1. ¿`ENGINE_VERSION` manual está OK como mecanismo de invalidación? → recomendado SÍ.
2. ¿Limitar tamaño máximo del cache? (e.g., LRU eviction al pasar de 5 GB) → por ahora no, el servidor tiene SSD 3TB.
3. ¿El cache se versiona en git? → NO, agregarlo a `.gitignore` (es output regenerable).
4. ¿Borrar el cache antes de un release/entrega al cliente? → opcional, lo decides tú.

## Próximo paso cuando se priorice

1. Confirmar las 4 decisiones de arriba
2. Implementar `src/api/ocr_cache.py` + integración mínima en los dos helpers de main.py
3. Probar en el servidor con el `rtm.18-04-2026-123526.pdf` que sabemos es no-determinístico — verificar que el segundo run da cache HIT
4. Agregar endpoints admin
5. Documentar en CLAUDE.md
