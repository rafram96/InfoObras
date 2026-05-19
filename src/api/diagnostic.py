"""
Helpers para capturar metadatos diagnósticos de cada fase del pipeline.

Objetivo: poder comparar dos runs (tool individual vs pipeline completo)
y ubicar exactamente DONDE diverge el output:

  - ¿Mismo PDF de entrada?            → input.pdf_sha256_16
  - ¿Mismo output OCR?                → ocr.md_files[i].sha256_16
  - ¿Mismas llamadas LLM?             → llm.calls_dumped + chars
  - ¿Mismo estado Ollama al arrancar? → llm.ollama_state_at_start
  - ¿Mismas env vars relevantes?      → env

Si el bloque `input` coincide pero `ocr` difiere → motor-OCR no es determinístico.
Si `ocr` coincide pero el `result.secciones` difiere → la divergencia es LLM.
Si todo coincide → bug nuestro o problema de comparación.

El dict se inyecta como `_diagnostic` dentro del `result` del job, y se baja
con `GET /api/jobs/{id}/result.json`.
"""
from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Variables de entorno que afectan el output del pipeline. Si dos runs tienen
# valores distintos aquí, la comparación es manzanas vs naranjas.
_RELEVANT_ENV_VARS = (
    "QWEN_MODEL",
    "QWEN_NUM_CTX",
    "QWEN_VL_MODEL",
    "EXTRACTION_NUM_CTX",
    "EXTRACTION_MAX_RETRIES",
    "EXTRACTION_BACKOFF",
    "USE_3LAYER_EXTRACTION",
    "USE_VL_TDR_EXTRACTION",
    "PDFPLUMBER_CHARS_THRESHOLD",
    "FORCE_MOTOR_OCR",
    "OLLAMA_BASE_URL",
    # Seed para determinismo del LLM (Bloque 1). Si no esta definido el codigo
    # usa default=42 hardcoded en src/tdr/config/settings.py y
    # src/extraction/ollama_client.py. Que aparezca aqui permite verificar
    # de un vistazo si el seed esta activo en runs futuros.
    "OLLAMA_SEED",
)


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def relevant_env() -> dict[str, str]:
    """Snapshot de env vars que afectan el output."""
    return {
        k: os.getenv(k, "(no definido)")
        for k in _RELEVANT_ENV_VARS
    }


def hash_file(path: Path, chunk_size: int = 65536) -> Optional[str]:
    """SHA-256 truncado a 16 chars hex. None si falla."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception as exc:
        logger.warning("hash_file fallo para %s: %s", path, exc)
        return None


def pdf_fingerprint(pdf_path: Path) -> dict:
    """Identifica unívocamente el PDF de entrada. Mismo PDF → mismo dict."""
    try:
        if not pdf_path.exists():
            return {"path": str(pdf_path), "_error": "not_found"}
        st = pdf_path.stat()
        return {
            "path": str(pdf_path),
            "name": pdf_path.name,
            "size_bytes": st.st_size,
            "sha256_16": hash_file(pdf_path),
            "mtime": datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc,
            ).isoformat(),
        }
    except Exception as exc:
        return {"path": str(pdf_path), "_error": str(exc)}


def md_files_fingerprint(output_dir: Path) -> list[dict]:
    """
    Hashes de cada .md generado por motor-OCR o el writer TDR.
    Si dos runs del MISMO PDF dan hashes distintos → OCR no es determinístico.
    """
    try:
        if not output_dir.exists():
            return []
        out: list[dict] = []
        for md in sorted(output_dir.rglob("*.md")):
            try:
                st = md.stat()
                text = md.read_text(encoding="utf-8", errors="replace")
                out.append({
                    "name": md.name,
                    "size_bytes": st.st_size,
                    "sha256_16": hash_file(md),
                    "line_count": text.count("\n"),
                    "char_count": len(text),
                })
            except Exception as exc:
                out.append({"name": md.name, "_error": str(exc)})
        return out
    except Exception as exc:
        return [{"_error": str(exc)}]


def llm_calls_summary(job_id: str) -> dict:
    """
    Resumen de los dumps de llamadas LLM (data/llm_calls/{job_id}/).
    Hoy solo TDR dumpea aquí; extracción de profesionales solo dumpea
    cuando falla. Útil para ver si el LLM fue invocado N veces vs M.
    """
    calls_dir = Path("data/llm_calls") / job_id
    try:
        if not calls_dir.exists():
            return {"count": 0, "dir": str(calls_dir)}
        files = sorted(calls_dir.glob("*.json"))
        total_prompt = 0
        total_response = 0
        for f in files:
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                total_prompt += int(data.get("prompt_chars") or 0)
                raw_resp = data.get("raw_response")
                if raw_resp is not None:
                    total_response += len(str(raw_resp))
            except Exception:
                continue
        return {
            "count": len(files),
            "total_prompt_chars": total_prompt,
            "total_response_chars": total_response,
            "first_file": files[0].name if files else None,
            "last_file": files[-1].name if files else None,
        }
    except Exception as exc:
        return {"_error": str(exc)}


def ollama_state(base_url: Optional[str] = None) -> dict:
    """
    Consulta /api/ps de Ollama. Devuelve qué modelos están cargados AHORA.
    Útil para saber si Qwen-VL o 14B estaba ya cargado al arrancar la fase.
    """
    if base_url is None:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    url = base_url.rstrip("/") + "/api/ps"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("models", []) or []
        return {
            "models_loaded": [
                {
                    "name": m.get("name"),
                    "size_vram_mb": (m.get("size_vram") or 0) // (1024 * 1024),
                    "size_mb": (m.get("size") or 0) // (1024 * 1024),
                    "expires_at": m.get("expires_at"),
                }
                for m in models
            ],
            "model_count": len(models),
            "queried_at": now_iso(),
        }
    except Exception as exc:
        return {"_error": str(exc), "queried_at": now_iso()}


def stopwatch_start() -> dict:
    """Marca de tiempo inicial. Usa con stopwatch_end(state, label)."""
    return {"_t0": time.perf_counter(), "_started_at": now_iso()}


def stopwatch_end(state: dict) -> dict:
    """Cierra un stopwatch — agrega ended_at y duration_ms."""
    duration_ms = int((time.perf_counter() - state["_t0"]) * 1000)
    return {
        "started_at": state["_started_at"],
        "ended_at": now_iso(),
        "duration_ms": duration_ms,
    }
