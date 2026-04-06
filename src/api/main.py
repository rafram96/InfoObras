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
import shutil
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# ── Extraction modules (optional — may not be installed on dev laptop) ───────
try:
    from src.extraction.md_parser import parse_professional_blocks
    from src.extraction.llm_extractor import extract_block
    _EXTRACTION_AVAILABLE = True
except ImportError:
    _EXTRACTION_AVAILABLE = False

# ── Config ────────────────────────────────────────────────────────────────────
MOTOR_OCR_PYTHON = os.getenv("MOTOR_OCR_PYTHON")
MOTOR_OCR_WRAPPER = os.getenv("MOTOR_OCR_WRAPPER")
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "data/uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "data/ocr_outputs"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://admin:admin123@localhost:5432/infoobras",
)

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not MOTOR_OCR_PYTHON or not MOTOR_OCR_WRAPPER:
    logging.warning(
        "MOTOR_OCR_PYTHON y/o MOTOR_OCR_WRAPPER no definidos en .env — "
        "los endpoints de OCR no funcionarán hasta configurarlos."
    )

if not _EXTRACTION_AVAILABLE:
    logging.warning(
        "Módulos de extracción no disponibles — "
        "se omitirá extracción de datos profesionales."
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


# ── DB (PostgreSQL) ──────────────────────────────────────────────────────────
@contextmanager
def _get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db() -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id              TEXT PRIMARY KEY,
                    filename        TEXT NOT NULL,
                    pages_from      INTEGER,
                    pages_to        INTEGER,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    result          JSONB,
                    error           TEXT,
                    progress_pct    INTEGER DEFAULT 0,
                    progress_stage  TEXT,
                    doc_total_pages INTEGER
                )
            """)


_init_db()


def _update_job(job_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [job_id]
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE jobs SET {sets} WHERE id = %s", values)


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
        _update_job(job_id, progress_stage="Segmentación", progress_pct=90)
        return

    if "[subprocess_wrapper] OK" in line:
        _update_job(job_id, progress_stage="OCR completado", progress_pct=91)
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
        logger.info(
            "Job %s OCR completado: %d págs, %d profesionales",
            job_id,
            doc["total_pages"],
            len(raw["secciones"]),
        )

        # ── Fase 2: Extracción LLM (Pasos 2-3) ─────────────────────────────
        if _EXTRACTION_AVAILABLE:
            _update_job(
                job_id,
                progress_pct=91,
                progress_stage="Buscando archivos de segmentación",
                result=json.dumps(result, ensure_ascii=False),
            )

            prof_files = list(Path(job_output_dir).rglob("*_profesionales_*.md"))
            texto_files = list(Path(job_output_dir).rglob("*_texto_*.md"))

            if prof_files and texto_files:
                try:
                    blocks = parse_professional_blocks(prof_files[0], texto_files[0])
                    total_blocks = len(blocks)
                    logger.info(
                        "Job %s: iniciando extracción de %d profesionales",
                        job_id,
                        total_blocks,
                    )

                    for i, block in enumerate(blocks):
                        pct = 92 + int((i / max(total_blocks, 1)) * 7)
                        _update_job(
                            job_id,
                            progress_pct=pct,
                            progress_stage=f"Extrayendo profesional {i + 1}/{total_blocks}",
                        )

                        try:
                            extraction = extract_block(block)
                        except Exception as exc:
                            logger.warning(
                                "Job %s: extracción falló para bloque %d (%s): %s",
                                job_id,
                                block.index,
                                block.cargo,
                                exc,
                            )
                            extraction = {
                                "profesional": {
                                    "_cargo": block.cargo,
                                    "_needs_review": True,
                                },
                                "experiencias": [],
                                "_needs_review": True,
                            }

                        for seccion in result["secciones"]:
                            if seccion["index"] == block.index:
                                seccion["profesional"] = extraction.get("profesional")
                                seccion["experiencias"] = extraction.get(
                                    "experiencias", []
                                )
                                seccion["_needs_review"] = extraction.get(
                                    "_needs_review", False
                                )
                                break

                    logger.info(
                        "Job %s: extracción completada para %d profesionales",
                        job_id,
                        total_blocks,
                    )
                except Exception:
                    logger.exception(
                        "Job %s: error en fase de extracción — guardando resultado OCR",
                        job_id,
                    )
            else:
                logger.warning(
                    "Job %s: archivos .md no encontrados en %s — omitiendo extracción",
                    job_id,
                    job_output_dir,
                )

        _update_job(
            job_id,
            status="done",
            progress_pct=100,
            progress_stage="Completado",
            result=json.dumps(result, ensure_ascii=False),
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
@app.post("/api/jobs", status_code=201, tags=["Jobs"])
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

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, filename, pages_from, pages_to) VALUES (%s,%s,%s,%s)",
                (job_id, file.filename, pages_from, pages_to),
            )

    _executor.submit(_run_job, job_id, pdf_path, pages)
    return {"id": job_id, "status": "pending"}


@app.get("/api/jobs", tags=["Jobs"])
async def list_jobs():
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, filename, pages_from, pages_to, status, "
                "created_at, progress_pct "
                "FROM jobs ORDER BY created_at DESC LIMIT 50"
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "pages_from": r["pages_from"],
            "pages_to": r["pages_to"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "progress_pct": r["progress_pct"] or 0,
        }
        for r in rows
    ]


@app.get("/api/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str):
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, filename, pages_from, pages_to, status, created_at, "
                "result, error, progress_pct, progress_stage, doc_total_pages "
                "FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Job no encontrado")
    result_data = row["result"]
    if isinstance(result_data, str):
        result_data = json.loads(result_data)
    return {
        "id": row["id"],
        "filename": row["filename"],
        "pages_from": row["pages_from"],
        "pages_to": row["pages_to"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "result": result_data,
        "error": row["error"],
        "progress_pct": row["progress_pct"] or 0,
        "progress_stage": row["progress_stage"],
        "doc_total_pages": row["doc_total_pages"],
    }


@app.delete("/api/jobs/{job_id}", tags=["Jobs"])
async def delete_job(job_id: str):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM jobs WHERE id = %s", (job_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Job no encontrado")
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
    job_dir = OUTPUT_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    return {"ok": True}


# ── Health checks ────────────────────────────────────────────────────────────
REQUIRED_MODELS = ["qwen2.5:14b", "qwen2.5vl:7b"]
OLLAMA_BASE = "http://localhost:11434"


def _check_db() -> dict:
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM jobs")
                count = cur.fetchone()[0]
                cur.execute("SELECT version()")
                pg_version = cur.fetchone()[0]
        return {
            "module": "db",
            "status": "ok",
            "detail": {
                "engine": "postgresql",
                "version": pg_version,
                "jobs_count": count,
                "connection": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
            },
        }
    except Exception as e:
        return {"module": "db", "status": "error", "detail": {"error": str(e)}}


def _check_motor_ocr() -> dict:
    issues = []
    python_path = MOTOR_OCR_PYTHON or "(no definido)"
    wrapper_path = MOTOR_OCR_WRAPPER or "(no definido)"

    if not MOTOR_OCR_PYTHON:
        issues.append("MOTOR_OCR_PYTHON no definido en .env")
    elif not Path(MOTOR_OCR_PYTHON).exists():
        issues.append(f"MOTOR_OCR_PYTHON no existe: {MOTOR_OCR_PYTHON}")

    if not MOTOR_OCR_WRAPPER:
        issues.append("MOTOR_OCR_WRAPPER no definido en .env")
    elif not Path(MOTOR_OCR_WRAPPER).exists():
        issues.append(f"MOTOR_OCR_WRAPPER no existe: {MOTOR_OCR_WRAPPER}")

    py_version = None
    if MOTOR_OCR_PYTHON and Path(MOTOR_OCR_PYTHON).exists():
        try:
            result = subprocess.run(
                [MOTOR_OCR_PYTHON, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            py_version = result.stdout.strip() or result.stderr.strip()
        except Exception as e:
            issues.append(f"No se pudo ejecutar Python: {e}")

    status = "ok" if not issues else "error"
    return {
        "module": "motor_ocr",
        "status": status,
        "detail": {
            "python_path": python_path,
            "wrapper_path": wrapper_path,
            "python_version": py_version,
            "issues": issues or None,
        },
    }


def _check_ollama() -> dict:
    import requests as req
    try:
        resp = req.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]

        def has_model(required: str) -> bool:
            base = required.split(":")[0]
            tag = required.split(":")[1] if ":" in required else ""
            return any(base in m and tag in m for m in models)

        missing = [r for r in REQUIRED_MODELS if not has_model(r)]
        status = "ok" if not missing else "warning"
        return {
            "module": "ollama",
            "status": status,
            "detail": {
                "url": OLLAMA_BASE,
                "models_found": models,
                "models_required": REQUIRED_MODELS,
                "missing": missing or None,
            },
        }
    except Exception as e:
        return {
            "module": "ollama",
            "status": "error",
            "detail": {"url": OLLAMA_BASE, "error": str(e)},
        }


def _check_extraction() -> dict:
    return {
        "module": "extraction",
        "status": "ok" if _EXTRACTION_AVAILABLE else "error",
        "detail": {
            "available": _EXTRACTION_AVAILABLE,
            "functions": (
                ["parse_professional_blocks", "extract_block"]
                if _EXTRACTION_AVAILABLE
                else []
            ),
        },
    }


def _check_validation() -> dict:
    try:
        from src.validation.rules import check_alerts, calculate_effective_days  # noqa: F401
        is_stub = False
        try:
            calculate_effective_days([], None)
        except NotImplementedError:
            is_stub = True
        except Exception:
            pass
        return {
            "module": "validation",
            "status": "warning" if is_stub else "ok",
            "detail": {"available": True, "stub": is_stub},
        }
    except ImportError:
        return {"module": "validation", "status": "error", "detail": {"available": False}}


def _check_scraping() -> dict:
    modules_status = {}
    for name in ["infoobras", "sunat", "cip"]:
        try:
            mod = __import__(f"src.scraping.{name}", fromlist=[name])
            funcs = [a for a in dir(mod) if not a.startswith("_") and callable(getattr(mod, a))]
            is_stub = True
            for fn_name in funcs:
                try:
                    getattr(mod, fn_name)("test")
                except NotImplementedError:
                    break
                except Exception:
                    is_stub = False
                    break
            modules_status[name] = {"available": True, "stub": is_stub}
        except ImportError:
            modules_status[name] = {"available": False, "stub": None}

    all_available = all(m["available"] for m in modules_status.values())
    any_stub = any(m.get("stub") for m in modules_status.values())
    status = "ok" if all_available and not any_stub else "warning" if all_available else "error"
    return {"module": "scraping", "status": status, "detail": modules_status}


@app.get("/health", tags=["Health"])
async def health():
    checks = {
        "db": _check_db(),
        "motor_ocr": _check_motor_ocr(),
        "ollama": _check_ollama(),
        "extraction": _check_extraction(),
        "validation": _check_validation(),
        "scraping": _check_scraping(),
    }
    has_error = any(c["status"] == "error" for c in checks.values())
    has_warning = any(c["status"] == "warning" for c in checks.values())
    overall = "error" if has_error else "warning" if has_warning else "ok"
    return {"status": overall, "modules": checks}


@app.get("/health/db", tags=["Health"])
async def health_db():
    return _check_db()


@app.get("/health/motor-ocr", tags=["Health"])
async def health_motor_ocr():
    return _check_motor_ocr()


@app.get("/health/ollama", tags=["Health"])
async def health_ollama():
    return _check_ollama()


@app.get("/health/extraction", tags=["Health"])
async def health_extraction():
    return _check_extraction()


@app.get("/health/validation", tags=["Health"])
async def health_validation():
    return _check_validation()


@app.get("/health/scraping", tags=["Health"])
async def health_scraping():
    return _check_scraping()
