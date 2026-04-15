# Módulo: Ollama Client

> `src/extraction/ollama_client.py` — ~60 líneas — ✅ Completo

## Propósito
Wrapper HTTP para llamar a Ollama (LLM local). Usado por Pasos 2-3.

## Funciones

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `call_llm(prompt)` | ~50 | POST a Ollama con JSON guarantee. 3 reintentos con backoff exponencial (15s). Temperature=0 (determinístico). |

## Configuración

| Constante | Valor | Descripción |
|-----------|-------|-------------|
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Endpoint de generación |
| `DEFAULT_MODEL` | `qwen2.5:14b` | Modelo LLM |
| `DEFAULT_TIMEOUT` | `180` | Timeout por request (segundos) |
| `DEFAULT_MAX_RETRIES` | `3` | Reintentos |
| `DEFAULT_BACKOFF` | `15` | Segundos entre reintentos |

## Edge cases manejados
- Timeout errors
- JSON decode errors
- Request exceptions genéricas
- Logging de errores sin crashear

## Limitaciones
- JSON decode errors son irrecuperables (no reintenta)
- No distingue errores transitorios de permanentes
- Backoff fijo (no exponencial real)

## Dependencias
- `requests`
