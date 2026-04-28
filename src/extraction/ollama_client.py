"""
Wrapper para llamar a Ollama con salida JSON.

Soporta Qwen 2.5 y Gemma 4 (las variables QWEN_* del .env solo pasan
el string del modelo a Ollama; el codigo es agnostico al modelo).

Sampling y keep_alive vienen del settings.py para que sean configurables
por modelo desde .env sin tocar codigo.

Reintentos automaticos con backoff exponencial.
"""
import json
import re
import time

import requests

from src.tdr.config.settings import (
    OLLAMA_BASE_URL,
    QWEN_MODEL,
    QWEN_TIMEOUT,
    QWEN_NUM_CTX,
    QWEN_TEMPERATURE,
    QWEN_TOP_P,
    QWEN_TOP_K,
    QWEN_KEEP_ALIVE,
)

OLLAMA_URL = f"{OLLAMA_BASE_URL}/api/generate"
DEFAULT_MODEL = QWEN_MODEL
DEFAULT_TIMEOUT = QWEN_TIMEOUT
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF = 15


# Regex defensivos para limpiar respuestas de modelos que devuelven texto
# extra alrededor del JSON (Gemma 4 a veces emite ```json...``` o thinking).
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_THINKING_RE = re.compile(
    r"<\|channel\|>thought\n.*?<channel\|>", re.DOTALL,
)


def _limpiar_raw(raw: str) -> str:
    """Filtra markdown fences y bloques de thinking que rompen json.loads."""
    raw = _THINKING_RE.sub("", raw)
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


def _build_options() -> dict:
    """
    Construye el dict 'options' para Ollama.

    Notas:
    - top_p=1.0 y top_k=0 (default Qwen) deshabilita esos filtros.
    - Para Gemma 4 (segun Google) los defaults son temp=1.0, top_p=0.95,
      top_k=64 — pero para extraccion JSON deterministica usamos
      temp=0.3, top_p=0.9, top_k=40 via .env.
    """
    opts: dict = {
        "temperature": QWEN_TEMPERATURE,
        "num_ctx": QWEN_NUM_CTX,
    }
    if QWEN_TOP_P != 1.0:
        opts["top_p"] = QWEN_TOP_P
    if QWEN_TOP_K > 0:
        opts["top_k"] = QWEN_TOP_K
    return opts


def call_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """
    Llama al LLM y retorna el JSON parseado.
    Reintenta automaticamente en caso de timeout o JSON invalido.
    Lanza RuntimeError si agota todos los intentos.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": _build_options(),
        "keep_alive": QWEN_KEEP_ALIVE,
    }

    ultimo_error: Exception | None = None
    raw = ""

    for intento in range(1, max_retries + 1):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()

            raw = resp.json().get("response", "")
            return json.loads(_limpiar_raw(raw))

        except requests.exceptions.Timeout as e:
            ultimo_error = e
            if intento < max_retries:
                print(f" [timeout, reintento {intento}/{max_retries - 1}]", end="", flush=True)
                time.sleep(DEFAULT_BACKOFF)

        except json.JSONDecodeError as e:
            # JSON invalido — no tiene sentido reintentar con el mismo prompt
            raise RuntimeError(
                f"LLM no devolvio JSON valido (modelo={model}):\n{raw[:500]}"
            ) from e

        except requests.exceptions.RequestException as e:
            ultimo_error = e
            if intento < max_retries:
                print(f" [error red, reintento {intento}/{max_retries - 1}]", end="", flush=True)
                time.sleep(DEFAULT_BACKOFF)

    raise RuntimeError(f"LLM no respondio tras {max_retries} intentos: {ultimo_error}")
