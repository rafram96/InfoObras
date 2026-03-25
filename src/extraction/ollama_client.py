"""
Wrapper mínimo para llamar a Ollama con salida JSON.
Temperatura 0 — resultados determinísticos.
"""
import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:14b"


def call_llm(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """
    Llama al LLM con el prompt dado y retorna el JSON parseado.
    Lanza RuntimeError si la respuesta no es JSON válido.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()

    raw = resp.json().get("response", "")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM no devolvió JSON válido:\n{raw[:500]}") from e
