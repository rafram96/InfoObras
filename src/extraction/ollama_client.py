"""
Wrapper para llamar a Ollama con salida JSON.
Temperatura 0 — resultados determinísticos.
Reintentos automáticos con backoff exponencial.
"""
import json
import time
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:14b"
DEFAULT_TIMEOUT = 180      # segundos por intento
DEFAULT_MAX_RETRIES = 3    # intentos totales (1 original + 2 reintentos)
DEFAULT_BACKOFF = 15       # segundos de espera entre reintentos


def call_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """
    Llama al LLM y retorna el JSON parseado.
    Reintenta automáticamente en caso de timeout o JSON inválido.
    Lanza RuntimeError si agota todos los intentos.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }

    ultimo_error: Exception | None = None

    for intento in range(1, max_retries + 1):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()

            raw = resp.json().get("response", "")
            return json.loads(raw)

        except requests.exceptions.Timeout as e:
            ultimo_error = e
            if intento < max_retries:
                print(f" [timeout, reintento {intento}/{max_retries - 1}]", end="", flush=True)
                time.sleep(DEFAULT_BACKOFF)

        except json.JSONDecodeError as e:
            # JSON inválido — no tiene sentido reintentar con el mismo prompt
            raise RuntimeError(f"LLM no devolvió JSON válido:\n{raw[:500]}") from e

        except requests.exceptions.RequestException as e:
            ultimo_error = e
            if intento < max_retries:
                print(f" [error red, reintento {intento}/{max_retries - 1}]", end="", flush=True)
                time.sleep(DEFAULT_BACKOFF)

    raise RuntimeError(f"LLM no respondió tras {max_retries} intentos: {ultimo_error}")
