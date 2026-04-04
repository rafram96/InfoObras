"""
Backend InfoObras — API FastAPI.

Orquesta el pipeline completo:
  - Upload de PDFs (propuesta + bases)
  - Motor-OCR como subprocess
  - Extracción de datos (Pasos 1-3)
  - Validación RTM (Paso 4, por implementar)
  - Scraping InfoObras (por implementar)
  - Generación de Excel (por implementar)

Arrancar:
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import logging
import os
import re
import sqlite3
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
MOTOR_OCR_PYTHON = os.getenv("MOTOR_OCR_PYTHON")
MOTOR_OCR_WRAPPER = os.getenv("MOTOR_OCR_WRAPPER")
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "data/uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data/ocr_outputs"))
DB_PATH = Path(os.getenv("DB_PATH", "data/jobs.db"))

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

if not MOTOR_OCR_PYTHON or not MOTOR_OCR_WRAPPER:
    logging.warning(
        "MOTOR_OCR_PYTHON y/o MOTOR_OCR_WRAPPER no definidos en .env — "
        "los endpoints de OCR no funcionarán hasta configurarlos."
    )

# ── App ───────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="InfoObras API", version="0.1.0")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3002").split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Un solo worker: GPU única en el servidor
_executor = ThreadPoolExecutor(max_workers=1)


# ── DB ────────────────────────────────────────────────────────────────────────
def _init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                filename        TEXT NOT NULL,
                pages_from      INTEGER,
                pages_to        INTEGER,
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                result          TEXT,
                error           TEXT,
                progress_pct    INTEGER DEFAULT 0,
                progress_stage  TEXT,
                doc_total_pages INTEGER
            )
        """)
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        for col, typedef in [
            ("progress_pct", "INTEGER DEFAULT 0"),
            ("progress_stage", "TEXT"),
            ("doc_total_pages", "INTEGER"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typedef}")


_init_db()


def _update_job(job_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", values)


# ── Progress parser ──────────────────────────────────────────────────────────
_RE_TOTAL_PAGES = re.compile(r"(\d+) páginas a procesar")
_RE_QWEN_PROGRESS = re.compile(r"Qwen progreso: (\d+)/(\d+) \(([\d.]+)%\)")


def _parse_progress(job_id: str, line: str) -> None:
    m = _RE_TOTAL_PAGES.search(line)
    if m:
        total = int(m.group(1))
        _update_job(
            job_id,
            doc_total_pages=total,
            progress_stage="Convirtiendo PDF",
            progress_pct=3,
        )
        return

    if "Pasada 1: PaddleOCR" in line:
        _update_job(job_id, progress_stage="PaddleOCR", progress_pct=8)
        return

    if "Pasada 1 completada" in line:
        _update_job(job_id, progress_stage="PaddleOCR completado", progress_pct=55)
        return

    if "no se necesita Qwen" in line:
        _update_job(job_id, progress_stage="Segmentación", progress_pct=90)
        return

    if "Pasada 2: Qwen fallback" in line:
        _update_job(job_id, progress_stage="Qwen fallback", progress_pct=58)
        return

    m = _RE_QWEN_PROGRESS.search(line)
    if m:
        pct_qwen = float(m.group(3))
        scaled = 58 + int(pct_qwen * 0.30)
        current, total = m.group(1), m.group(2)
        _update_job(
            job_id,
            progress_stage=f"Qwen {current}/{total}",
            progress_pct=min(scaled, 88),
        )
        return

    if "segment_document" in line.lower() or "Segmentación" in line:
        _update_job(job_id, progress_stage="Segmentación", progress_pct=92)
        return

    if "[subprocess_wrapper] OK" in line:
        _update_job(job_id, progress_stage="Finalizando", progress_pct=98)
        return


# ── Job runner ────────────────────────────────────────────────────────────────
def _run_job(job_id: str, pdf_path: Path, pages: Optional[list]) -> None:
    _update_job(job_id, status="running", progress_pct=1, progress_stage="Iniciando")

    job_output_dir = str(OUTPUT_DIR / job_id)
    args_file = results_file = None

    try:
        args = {
            "mode": "segmentation",
            "pdf_path": str(pdf_path),
            "pages": pages,
            "output_dir": job_output_dir,
            "keep_images": False,
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(args, f)
            args_file = f.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            results_file = f.name

        logger.info("Job %s: llamando a motor-OCR...", job_id)

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            [MOTOR_OCR_PYTHON, MOTOR_OCR_WRAPPER, args_file, results_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            logger.info("Job %s | %s", job_id, line)
            try:
                _parse_progress(job_id, line)
            except Exception:
                pass

        process.wait(timeout=9000)

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, MOTOR_OCR_WRAPPER)

        with open(results_file, encoding="utf-8") as f:
            raw = json.load(f)

        doc = raw["doc"]
        result = {
            "total_pages": doc["total_pages"],
            "pages_paddle": doc["pages_paddle"],
            "pages_qwen": doc["pages_qwen"],
            "pages_error": doc["pages_error"],
            "conf_promedio": round(doc["conf_promedio_documento"], 3),
            "tiempo_total": round(doc["tiempo_total"], 1),
            "secciones": [
                {
                    "index": s["section_index"],
                    "cargo": s["cargo"],
                    "cargo_raw": s.get("cargo_raw", s["cargo"]),
                    "numero": s["numero"],
                    "total_pages": s["total_pages"],
                    "page_numbers": s.get("page_numbers", []),
                    "bloques": s.get("bloques_origen", []),
                    "es_tipo_b": s.get("es_tipo_b", False),
                }
                for s in raw["secciones"]
            ],
        }
        _update_job(
            job_id,
            status="done",
            progress_pct=100,
            progress_stage="Completado",
            result=json.dumps(result, ensure_ascii=False),
        )
        logger.info(
            "Job %s completado: %d págs, %d profesionales",
            job_id,
            doc["total_pages"],
            len(raw["secciones"]),
        )

    except subprocess.CalledProcessError as e:
        logger.error("Job %s: subprocess falló con código %d", job_id, e.returncode)
        _update_job(
            job_id, status="error", progress_pct=0, progress_stage=None,
            error=f"motor-OCR terminó con error (código {e.returncode})",
        )
    except subprocess.TimeoutExpired:
        logger.error("Job %s: timeout", job_id)
        _update_job(
            job_id, status="error", progress_pct=0, progress_stage=None,
            error="Timeout: el procesamiento superó el límite de tiempo",
        )
    except Exception as e:
        logger.exception("Job %s: error inesperado", job_id)
        _update_job(
            job_id, status="error", progress_pct=0, progress_stage=None,
            error=str(e),
        )
    finally:
        if args_file:
            Path(args_file).unlink(missing_ok=True)
        if results_file:
            Path(results_file).unlink(missing_ok=True)
        pdf_path.unlink(missing_ok=True)


# ── Routes: Jobs (OCR + pipeline) ───────────────────────────────────────────
@app.post("/api/jobs", status_code=201)
async def create_job(
    file: UploadFile = File(...),
    pages_from: Optional[int] = Form(None),
    pages_to: Optional[int] = Form(None),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    if pages_from is not None and pages_to is not None:
        if pages_from < 1 or pages_to < pages_from:
            raise HTTPException(400, "Rango de páginas inválido")
        pages: Optional[list] = list(range(pages_from, pages_to + 1))
    elif pages_from is not None:
        pages = [pages_from]
    else:
        pages = None

    job_id = uuid.uuid4().hex[:8]
    pdf_path = UPLOADS_DIR / f"{job_id}_{file.filename}"
    pdf_path.write_bytes(await file.read())

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (id, filename, pages_from, pages_to) VALUES (?,?,?,?)",
            (job_id, file.filename, pages_from, pages_to),
        )

    _executor.submit(_run_job, job_id, pdf_path, pages)
    return {"id": job_id, "status": "pending"}


@app.get("/api/jobs")
async def list_jobs():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, filename, pages_from, pages_to, status, created_at, progress_pct "
            "FROM jobs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [
        {
            "id": r[0], "filename": r[1], "pages_from": r[2], "pages_to": r[3],
            "status": r[4], "created_at": r[5], "progress_pct": r[6] or 0,
        }
        for r in rows
    ]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, filename, pages_from, pages_to, status, created_at, "
            "result, error, progress_pct, progress_stage, doc_total_pages "
            "FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job no encontrado")
    return {
        "id": row[0], "filename": row[1], "pages_from": row[2], "pages_to": row[3],
        "status": row[4], "created_at": row[5],
        "result": json.loads(row[6]) if row[6] else None,
        "error": row[7], "progress_pct": row[8] or 0,
        "progress_stage": row[9], "doc_total_pages": row[10],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
