"""
Wrapper para llamar a Ollama con salida JSON.
Temperatura 0 — resultados determinísticos.
Reintentos automáticos con backoff exponencial.

Configurable via env:
  QWEN_MODEL            (default "qwen2.5:14b")
  QWEN_TIMEOUT          (default 300 segundos por intento)
  EXTRACTION_MAX_RETRIES (default 3 intentos totales)
  EXTRACTION_BACKOFF    (default 15 segundos entre reintentos)
  EXTRACTION_NUM_CTX    (default 16384 — ventana de contexto Qwen)
  EXTRACTION_DUMP_FAILED_PROMPTS (default true — dump a data/logs/extraction_failures/)
"""
import json
import logging
import os
import time
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/generate"
DEFAULT_MODEL = os.getenv("QWEN_MODEL", "qwen2.5:14b")
DEFAULT_TIMEOUT = int(os.getenv("QWEN_TIMEOUT", "300"))
DEFAULT_MAX_RETRIES = int(os.getenv("EXTRACTION_MAX_RETRIES", "3"))
DEFAULT_BACKOFF = int(os.getenv("EXTRACTION_BACKOFF", "15"))
DEFAULT_NUM_CTX = int(os.getenv("EXTRACTION_NUM_CTX", os.getenv("QWEN_NUM_CTX", "16384")))
# Seed fijo para que Ollama sea determinístico con temperature=0. Sin seed,
# greedy decoding puede producir tokens distintos entre sesiones por orden de
# batching/KV cache. Mismo prompt -> misma respuesta. Override via OLLAMA_SEED.
DEFAULT_SEED = int(os.getenv("OLLAMA_SEED", "42"))
DUMP_FAILED_PROMPTS = os.getenv(
    "EXTRACTION_DUMP_FAILED_PROMPTS", "true"
).lower() == "true"

_FAILED_DUMP_DIR = Path("data/logs/extraction_failures")


def _dump_failed_prompt(prompt: str, error: str) -> Path | None:
    """Guarda prompt + error a disco para diagnostico de bloques fallidos."""
    if not DUMP_FAILED_PROMPTS:
        return None
    try:
        _FAILED_DUMP_DIR.mkdir(parents=True, exist_ok=True)
        fname = _FAILED_DUMP_DIR / f"failed_{int(time.time())}_{uuid.uuid4().hex[:8]}.txt"
        fname.write_text(
            f"# Error: {error}\n# Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# Prompt length: {len(prompt)} chars\n"
            f"# Model: {DEFAULT_MODEL}, timeout: {DEFAULT_TIMEOUT}s, "
            f"num_ctx: {DEFAULT_NUM_CTX}\n"
            f"# ────────────────────────────────────────────────────────────\n"
            f"{prompt}",
            encoding="utf-8",
        )
        return fname
    except Exception as exc:
        logger.warning("No se pudo guardar dump del prompt fallido: %s", exc)
        return None


def call_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = None,
    max_retries: int = None,
) -> dict:
    """
    Llama al LLM y retorna el JSON parseado.
    Reintenta automaticamente en caso de timeout o JSON invalido.
    Lanza RuntimeError si agota todos los intentos. En ese caso, dumpea
    el prompt a data/logs/extraction_failures/ para diagnostico posterior
    (controlable via env EXTRACTION_DUMP_FAILED_PROMPTS=false).
    """
    # Lectura tardia para que respete env vars actualizadas en runtime
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    if max_retries is None:
        max_retries = DEFAULT_MAX_RETRIES

    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0,
            "num_ctx": DEFAULT_NUM_CTX,
            "seed": DEFAULT_SEED,
        },
    }

    ultimo_error: Exception | None = None
    raw = ""

    for intento in range(1, max_retries + 1):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()

            raw = resp.json().get("response", "")
            return json.loads(raw)

        except requests.exceptions.Timeout as e:
            ultimo_error = e
            if intento < max_retries:
                print(
                    f" [timeout {timeout}s, reintento {intento}/{max_retries - 1}]",
                    end="", flush=True,
                )
                time.sleep(DEFAULT_BACKOFF)

        except json.JSONDecodeError as e:
            # JSON invalido — no tiene sentido reintentar con el mismo prompt
            dump_path = _dump_failed_prompt(prompt, f"JSON invalido: {e}")
            extra = f" (prompt dump: {dump_path})" if dump_path else ""
            raise RuntimeError(
                f"LLM no devolvio JSON valido{extra}:\n{raw[:500]}"
            ) from e

        except requests.exceptions.RequestException as e:
            ultimo_error = e
            if intento < max_retries:
                print(
                    f" [error red, reintento {intento}/{max_retries - 1}]",
                    end="", flush=True,
                )
                time.sleep(DEFAULT_BACKOFF)

    # Agotamos los intentos — dumpear el prompt para diagnostico
    dump_path = _dump_failed_prompt(prompt, str(ultimo_error))
    extra = f" (prompt dump: {dump_path})" if dump_path else ""
    raise RuntimeError(
        f"LLM no respondio tras {max_retries} intentos: {ultimo_error}{extra}"
    )
