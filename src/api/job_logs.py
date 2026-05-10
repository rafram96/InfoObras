"""
Logs estructurados por fase + bundles ZIP descargables.

Por cada job se crea un directorio data/logs/{job_id}/ con:
  ├── job.log               (consolidado, todo)
  ├── 01_ocr.log            (FASE 1: OCR de la propuesta)
  ├── 02_extraction.log     (FASE 2: extracción LLM profesionales)
  ├── 03_tdr.log            (FASE 3: TDR + pipeline 3-capas)
  ├── 04_sunat.log          (cruce SUNAT)
  ├── 05_infoobras.log      (cruce InfoObras, cuando se agregue)
  ├── 06_evaluation.log     (motor de reglas — Paso 4)
  ├── 07_excel.log          (writer Lircay)
  └── motor_ocr.log         (subprocess wrapper, capturado del stdout)

`set_current_phase(phase)` rota el handler activo: los logs nuevos van a la fase
y siguen llegando a job.log también (handler consolidado).

`bundle_job_logs(job_id)` arma un ZIP con todos los logs + llm_calls + result.json.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from typing import Optional


JOB_LOGS_DIR = Path("data/logs")
JOB_LOGS_DIR.mkdir(parents=True, exist_ok=True)

LLM_CALLS_DIR = Path("data/llm_calls")


class Phase(str, Enum):
    OCR = "01_ocr"
    EXTRACTION = "02_extraction"
    TDR = "03_tdr"
    SUNAT = "04_sunat"
    INFOOBRAS = "05_infoobras"
    EVALUATION = "06_evaluation"
    EXCEL = "07_excel"


# Phase activa para el job en curso (asigna por contextvar — thread-safe en
# nuestro pool de 1 worker, pero correcto si crece a más).
_CURRENT_PHASE: ContextVar[Optional[Phase]] = ContextVar("current_phase", default=None)

# Map (job_id, phase) -> FileHandler activo, para poder cerrarlo al cambiar
_PHASE_HANDLERS: dict[tuple[str, Phase], logging.FileHandler] = {}


def job_log_dir(job_id: str) -> Path:
    """Devuelve y asegura el directorio data/logs/{job_id}/"""
    p = JOB_LOGS_DIR / job_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def consolidated_log_path(job_id: str) -> Path:
    """Path del log consolidado (todo el job en un solo archivo)."""
    return job_log_dir(job_id) / "job.log"


def phase_log_path(job_id: str, phase: Phase) -> Path:
    """Path del log dedicado a una fase específica."""
    return job_log_dir(job_id) / f"{phase.value}.log"


def motor_ocr_log_path(job_id: str) -> Path:
    """Path para el stdout/stderr del subprocess motor-OCR de este job."""
    return job_log_dir(job_id) / "motor_ocr.log"


def set_current_phase(job_id: str, phase: Phase, log_fmt: str) -> None:
    """
    Cambia la fase activa. Cierra el handler de la fase anterior (si existía)
    y abre uno nuevo para la fase entrante.

    Llamar desde el runner del job al inicio de cada fase. Los logs emitidos
    desde ese punto van al archivo de la fase + al consolidado.
    """
    # Limpiar handlers de fase anterior (si los hay)
    prev = _CURRENT_PHASE.get()
    if prev is not None:
        key = (job_id, prev)
        old = _PHASE_HANDLERS.pop(key, None)
        if old is not None:
            logging.getLogger().removeHandler(old)
            try:
                old.close()
            except Exception:
                pass

    # Abrir handler de la nueva fase
    log_path = phase_log_path(job_id, phase)
    h = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    h.setLevel(logging.DEBUG)
    h.setFormatter(logging.Formatter(log_fmt))
    # Filtrar solo logs de este job
    h.addFilter(lambda r: getattr(r, "job_id", None) == job_id)
    logging.getLogger().addHandler(h)
    _PHASE_HANDLERS[(job_id, phase)] = h

    _CURRENT_PHASE.set(phase)


def cleanup_phase_handlers(job_id: str) -> None:
    """Cierra TODOS los phase handlers asociados a este job. Llamar al terminar."""
    keys_a_borrar = [k for k in _PHASE_HANDLERS if k[0] == job_id]
    for key in keys_a_borrar:
        h = _PHASE_HANDLERS.pop(key, None)
        if h is None:
            continue
        logging.getLogger().removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    _CURRENT_PHASE.set(None)


# ============================================================================
# Lectura / Listado para los endpoints
# ============================================================================

def list_log_files(job_id: str) -> list[dict]:
    """
    Lista los archivos de logs disponibles para un job.

    Returns:
        list[{filename, size_bytes, phase}]
    """
    d = JOB_LOGS_DIR / job_id
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        # Extraer phase si el filename matchea el patron
        phase = None
        for p in Phase:
            if f.stem == p.value:
                phase = p.value
                break
        out.append({
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "phase": phase,
        })
    return out


def read_log_file(job_id: str, filename: str) -> Optional[str]:
    """Lee un archivo de log específico del job. Devuelve None si no existe."""
    # Sanitizar filename — solo permitir archivos directos del directorio del job
    safe = Path(filename).name
    if safe != filename:
        return None
    p = JOB_LOGS_DIR / job_id / safe
    if not p.exists() or not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


# ============================================================================
# Bundle ZIP descargable
# ============================================================================

def bundle_job_logs(
    job_id: str,
    *,
    job_meta: Optional[dict] = None,
    job_result: Optional[dict] = None,
) -> bytes:
    """
    Empaqueta TODO lo relacionado al job en un ZIP en memoria.

    Args:
        job_id: ID del job
        job_meta: dict con metadata (filename, status, fechas...) — opcional
        job_result: el campo `result` de la BD (snapshot del JSON) — opcional

    Returns:
        bytes del ZIP. Listo para servir como StreamingResponse.

    Estructura:
        job-{id}-bundle.zip
          ├── README.txt
          ├── result.json
          ├── logs/
          │   ├── job.log
          │   ├── 01_ocr.log
          │   ├── 02_extraction.log
          │   ├── ...
          │   └── motor_ocr.log
          └── llm_calls/
              ├── 001_extract_block_..json
              └── ...
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # README con metadata
        readme = _build_readme(job_id, job_meta or {})
        zf.writestr("README.txt", readme)

        # Result JSON snapshot (si se pasó)
        if job_result is not None:
            zf.writestr(
                "result.json",
                json.dumps(job_result, ensure_ascii=False, indent=2, default=str),
            )

        # Logs del job
        log_dir = JOB_LOGS_DIR / job_id
        if log_dir.exists():
            for log_file in sorted(log_dir.iterdir()):
                if log_file.is_file():
                    arcname = f"logs/{log_file.name}"
                    try:
                        zf.write(log_file, arcname=arcname)
                    except Exception:
                        # archivo no legible — saltarlo
                        continue

        # Dumps LLM calls
        llm_dir = LLM_CALLS_DIR / job_id
        if llm_dir.exists():
            for llm_file in sorted(llm_dir.iterdir()):
                if llm_file.is_file():
                    arcname = f"llm_calls/{llm_file.name}"
                    try:
                        zf.write(llm_file, arcname=arcname)
                    except Exception:
                        continue

    buf.seek(0)
    return buf.getvalue()


def _build_readme(job_id: str, meta: dict) -> str:
    lines = [
        f"InfoObras — Bundle de diagnostico del job {job_id}",
        "=" * 60,
        "",
    ]
    if meta:
        for k in (
            "filename", "job_type", "status", "created_at", "started_at",
            "progress_pct", "progress_stage", "doc_total_pages", "error",
            "source_job_id",
        ):
            if k in meta and meta[k] is not None:
                lines.append(f"{k}: {meta[k]}")
        lines.append("")
    lines.extend([
        "Estructura del bundle:",
        "  README.txt        — este archivo",
        "  result.json       — snapshot del campo result de la BD (si aplica)",
        "  logs/job.log      — log consolidado de TODO el job",
        "  logs/01_ocr.log   — FASE 1: OCR de la propuesta",
        "  logs/02_extraction.log — FASE 2: extraccion LLM profesionales",
        "  logs/03_tdr.log   — FASE 3: TDR + pipeline 3-capas",
        "  logs/04_sunat.log — cruce con SUNAT (si aplica)",
        "  logs/05_infoobras.log — cruce con InfoObras (si aplica)",
        "  logs/06_evaluation.log — motor de reglas (Paso 4)",
        "  logs/07_excel.log — writer Lircay",
        "  logs/motor_ocr.log — stdout/stderr del subprocess motor-OCR",
        "  llm_calls/*.json  — dumps de cada llamada LLM (Qwen 14B)",
        "",
    ])
    return "\n".join(lines)
