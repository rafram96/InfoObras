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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# ── Extraction modules (optional — may not be installed on dev laptop) ───────
try:
    from src.extraction.md_parser import parse_professional_blocks
    from src.extraction.llm_extractor import extract_block
    _EXTRACTION_AVAILABLE = True
except ImportError:
    _EXTRACTION_AVAILABLE = False

# ── TDR modules (optional) ──────────────────────────────────────────────────
try:
    from src.tdr.extractor.pipeline import extraer_bases
    _TDR_AVAILABLE = True
except ImportError:
    _TDR_AVAILABLE = False

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

if not _TDR_AVAILABLE:
    logging.warning(
        "Módulos TDR no disponibles — "
        "los jobs de tipo 'tdr' no funcionarán."
    )

# ── App ───────────────────────────────────────────────────────────────────────
_LOG_FMT = "%(asctime)s %(levelname)s %(name)s — %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FMT)

# Log a archivo para debug persistente
_LOG_FILE = Path("data/backend.log")
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(_LOG_FMT))
logging.getLogger().addHandler(_file_handler)

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
# Jobs cancelados — los runners revisan este set y abortan si encuentran su ID
_cancelled_jobs: set[str] = set()


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
                    job_type        TEXT NOT NULL DEFAULT 'extraction',
                    pages_from      INTEGER,
                    pages_to        INTEGER,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    started_at      TIMESTAMPTZ,
                    result          JSONB,
                    error           TEXT,
                    progress_pct    INTEGER DEFAULT 0,
                    progress_stage  TEXT,
                    doc_total_pages INTEGER,
                    logs            TEXT
                )
            """)
            # Migraciones: agregar columnas si la tabla ya existe sin ellas
            for col, definition in [
                ("job_type", "TEXT NOT NULL DEFAULT 'extraction'"),
                ("started_at", "TIMESTAMPTZ"),
                ("logs", "TEXT"),
            ]:
                cur.execute(f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'jobs' AND column_name = '{col}'
                        ) THEN
                            ALTER TABLE jobs ADD COLUMN {col} {definition};
                        END IF;
                    END $$;
                """)


_init_db()


def _check_cancelled(job_id: str) -> None:
    """Lanza excepción si el job fue cancelado (borrado mientras estaba en cola/running)."""
    if job_id in _cancelled_jobs:
        _cancelled_jobs.discard(job_id)
        raise RuntimeError("Job cancelado por el usuario")


def _update_job(job_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [job_id]
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE jobs SET {sets} WHERE id = %s", values)


def _append_job_log(job_id: str, message: str) -> None:
    """Agrega una línea al campo logs del job (para debug en la UI)."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {message}\n"
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET logs = COALESCE(logs, '') || %s WHERE id = %s",
                (line, job_id),
            )


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
    _check_cancelled(job_id)
    _update_job(
        job_id, status="running", progress_pct=1,
        progress_stage="Iniciando",
        started_at=datetime.now(timezone.utc),
    )
    _append_job_log(job_id, "Job iniciado — modo extracción")

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
        _append_job_log(job_id, "Iniciando motor-OCR subprocess")

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

        _append_job_log(job_id, f"OCR completado — {doc['total_pages']} págs, {len(raw['secciones'])} profesionales")

        # ── Fase 2: Extracción LLM (Pasos 2-3) ─────────────────────────────
        if _EXTRACTION_AVAILABLE:
            _update_job(
                job_id,
                progress_pct=91,
                progress_stage="Buscando archivos de segmentación",
                result=json.dumps(result, ensure_ascii=False),
            )

            # Buscar archivos específicos — el prefijo contiene "Profesionales"
            # así que hay que filtrar para que no matchee métricas/segmentación
            all_md = list(Path(job_output_dir).rglob("*.md"))
            prof_files = [f for f in all_md if "_profesionales_" in f.name.lower() and "_metricas_" not in f.name.lower() and "_segmentacion_" not in f.name.lower() and "_texto_" not in f.name.lower()]
            texto_files = [f for f in all_md if "_texto_" in f.name.lower()]

            logger.info(
                "Job %s: archivos encontrados — prof=%s, texto=%s",
                job_id,
                [f.name for f in prof_files],
                [f.name for f in texto_files],
            )

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
        _append_job_log(job_id, f"ERROR: motor-OCR falló con código {e.returncode}")
        _update_job(
            job_id, status="error", progress_pct=0, progress_stage=None,
            error=f"motor-OCR terminó con error (código {e.returncode})",
        )
    except subprocess.TimeoutExpired:
        logger.error("Job %s: timeout", job_id)
        _append_job_log(job_id, "ERROR: timeout — procesamiento excedió límite de tiempo")
        _update_job(
            job_id, status="error", progress_pct=0, progress_stage=None,
            error="Timeout: el procesamiento superó el límite de tiempo",
        )
    except Exception as e:
        logger.exception("Job %s: error inesperado", job_id)
        _append_job_log(job_id, f"ERROR: {e}")
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


# ── TDR Job runner ─────────────────────────────────────────────────────────
def _run_tdr_job(job_id: str, pdf_path: Path) -> None:
    """Ejecuta extracción TDR (Paso 1) sobre un PDF de bases."""
    _check_cancelled(job_id)
    _update_job(
        job_id, status="running", progress_pct=1,
        progress_stage="Iniciando TDR",
        started_at=datetime.now(timezone.utc),
    )
    _append_job_log(job_id, "Job iniciado — modo TDR")

    try:
        # ── Paso 1: Extraer texto del PDF de bases ──────────────────────────
        _update_job(job_id, progress_pct=5, progress_stage="Extrayendo texto del PDF")
        _append_job_log(job_id, "Extrayendo texto con pdfplumber...")

        import pdfplumber
        full_text = ""
        num_pages = 0
        with pdfplumber.open(str(pdf_path)) as pdf:
            num_pages = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += f"\n--- Página {page.page_number} ---\n{text}"

        chars_per_page = len(full_text.strip()) / max(num_pages, 1)
        _append_job_log(
            job_id,
            f"pdfplumber: {num_pages} páginas, {int(chars_per_page)} chars/pág promedio",
        )

        if chars_per_page < 50:
            _append_job_log(job_id, "Texto insuficiente — PDF probablemente escaneado")
            _update_job(
                job_id, progress_pct=10,
                progress_stage="PDF escaneado — ejecutando OCR",
            )
            # Fallback a motor-OCR (mismo flujo que _run_job pero solo para texto)
            try:
                from src.tdr.clients.motor_ocr_client import invoke_motor_ocr
                _append_job_log(job_id, "Invocando motor-OCR para bases escaneadas...")
                full_text = invoke_motor_ocr(
                    str(pdf_path), output_dir=str(OUTPUT_DIR),
                )
                _append_job_log(job_id, f"motor-OCR completado — {len(full_text)} chars")
            except Exception as ocr_err:
                _append_job_log(job_id, f"ERROR motor-OCR: {ocr_err}")
                raise RuntimeError(
                    f"PDF escaneado y motor-OCR falló: {ocr_err}"
                ) from ocr_err

        # ── Paso 2: Extraer requisitos RTM ──────────────────────────────────
        _update_job(job_id, progress_pct=30, progress_stage="Analizando requisitos TDR")
        _append_job_log(job_id, "Llamando a extraer_bases()...")

        tdr_result = extraer_bases(
            full_text,
            nombre_archivo=pdf_path.name,
            pdf_path=str(pdf_path),
        )

        _update_job(job_id, progress_pct=90, progress_stage="Procesando resultados TDR")

        # Estructurar resultado
        result = {
            "job_type": "tdr",
            "rtm_personal": tdr_result.get("rtm_personal", []),
            "rtm_postor": tdr_result.get("rtm_postor", []),
            "factores_evaluacion": tdr_result.get("factores_evaluacion", []),
            "total_cargos": len(tdr_result.get("rtm_personal", [])),
            "total_factores": len(tdr_result.get("factores_evaluacion", [])),
        }

        _append_job_log(
            job_id,
            f"TDR completado — {result['total_cargos']} cargos, "
            f"{result['total_factores']} factores",
        )
        logger.info(
            "Job %s (TDR): completado — %d cargos, %d factores",
            job_id, result["total_cargos"], result["total_factores"],
        )

        _update_job(
            job_id,
            status="done",
            progress_pct=100,
            progress_stage="Completado",
            result=json.dumps(result, ensure_ascii=False, default=str),
        )

    except Exception as e:
        logger.exception("Job %s (TDR): error", job_id)
        _append_job_log(job_id, f"ERROR: {e}")
        _update_job(
            job_id, status="error", progress_pct=0, progress_stage=None,
            error=str(e),
        )
    finally:
        pdf_path.unlink(missing_ok=True)


# ── Full Pipeline Job runner ───────────────────────────────────────────────
def _run_full_job(job_id: str, pdf_path: Path, bases_path: Path, pages: Optional[list]) -> None:
    """
    Pipeline completo: propuesta + bases → OCR → Pasos 1-4 → Excel.

    Fases:
    1. OCR + extracción de profesionales (propuesta) — Pasos 2-3
    2. Extracción TDR (bases) — Paso 1
    3. Evaluación RTM — Paso 4
    4. Generación de Excel
    """
    from datetime import date as _date
    from src.extraction.llm_extractor import _parsear_fecha

    def _try_iso(iso_str, raw_str):
        if iso_str and isinstance(iso_str, str):
            try:
                return _date.fromisoformat(iso_str)
            except ValueError:
                pass
        return _parsear_fecha(raw_str)

    _check_cancelled(job_id)
    _update_job(
        job_id, status="running", progress_pct=1,
        progress_stage="Iniciando pipeline completo",
        started_at=datetime.now(timezone.utc),
    )
    _append_job_log(job_id, "Job iniciado — pipeline completo (propuesta + bases)")

    try:
        # ════════════════════════════════════════════════════════════════
        # FASE 1: OCR + Extracción de profesionales (propuesta)
        # ════════════════════════════════════════════════════════════════
        _append_job_log(job_id, "FASE 1: OCR + Extracción de propuesta")
        _update_job(job_id, progress_pct=2, progress_stage="OCR propuesta")

        # Reusar _run_job internamente pero capturar el resultado
        job_output_dir = str(OUTPUT_DIR / job_id)

        # Motor-OCR subprocess
        args = {
            "mode": "segmentation",
            "pdf_path": str(pdf_path),
            "pages": pages,
            "output_dir": job_output_dir,
            "keep_images": False,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(args, f)
            args_file = f.name

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            results_file = f.name

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            [MOTOR_OCR_PYTHON, MOTOR_OCR_WRAPPER, args_file, results_file],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
        )
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line:
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
        extraction_result = {
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

        Path(args_file).unlink(missing_ok=True)
        Path(results_file).unlink(missing_ok=True)

        _append_job_log(job_id, f"OCR completado — {doc['total_pages']} págs, {len(raw['secciones'])} profesionales")

        # Extracción LLM (Pasos 2-3)
        if _EXTRACTION_AVAILABLE:
            _update_job(job_id, progress_pct=40, progress_stage="Extrayendo profesionales (LLM)")
            _append_job_log(job_id, "Extracción LLM — Pasos 2-3")

            all_md = list(Path(job_output_dir).rglob("*.md"))
            prof_files = [f for f in all_md if "_profesionales_" in f.name.lower() and "_metricas_" not in f.name.lower() and "_segmentacion_" not in f.name.lower() and "_texto_" not in f.name.lower()]
            texto_files = [f for f in all_md if "_texto_" in f.name.lower()]

            if prof_files and texto_files:
                blocks = parse_professional_blocks(prof_files[0], texto_files[0])
                total_blocks = len(blocks)
                _append_job_log(job_id, f"Extrayendo {total_blocks} profesionales")

                for i, block in enumerate(blocks):
                    pct = 40 + int((i / max(total_blocks, 1)) * 20)
                    _update_job(job_id, progress_pct=pct, progress_stage=f"Profesional {i+1}/{total_blocks}")

                    try:
                        extraction = extract_block(block)
                    except Exception as exc:
                        logger.warning("Job %s: extracción falló bloque %d: %s", job_id, block.index, exc)
                        extraction = {"profesional": {"_cargo": block.cargo, "_needs_review": True}, "experiencias": [], "_needs_review": True}

                    for seccion in extraction_result["secciones"]:
                        if seccion["index"] == block.index:
                            seccion["profesional"] = extraction.get("profesional")
                            seccion["experiencias"] = extraction.get("experiencias", [])
                            seccion["_needs_review"] = extraction.get("_needs_review", False)
                            break

        _check_cancelled(job_id)

        # ════════════════════════════════════════════════════════════════
        # FASE 2: Extracción TDR (bases)
        # ════════════════════════════════════════════════════════════════
        _update_job(job_id, progress_pct=65, progress_stage="Extrayendo requisitos TDR")
        _append_job_log(job_id, "FASE 2: Extracción TDR de bases")

        import pdfplumber
        full_text = ""
        num_pages = 0
        with pdfplumber.open(str(bases_path)) as pdf:
            num_pages = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text() or ""
                full_text += f"\n--- Página {page.page_number} ---\n{text}"

        chars_per_page = len(full_text.strip()) / max(num_pages, 1)
        _append_job_log(job_id, f"Bases: {num_pages} págs, {int(chars_per_page)} chars/pág")

        if chars_per_page < 50:
            _append_job_log(job_id, "Bases escaneadas — invocando motor-OCR")
            try:
                from src.tdr.clients.motor_ocr_client import invoke_motor_ocr
                full_text = invoke_motor_ocr(str(bases_path), output_dir=str(OUTPUT_DIR))
            except Exception as ocr_err:
                _append_job_log(job_id, f"ERROR motor-OCR bases: {ocr_err}")
                raise RuntimeError(f"Bases escaneadas y motor-OCR falló: {ocr_err}") from ocr_err

        _update_job(job_id, progress_pct=75, progress_stage="Analizando requisitos RTM")
        tdr_result = extraer_bases(full_text, nombre_archivo=bases_path.name, pdf_path=str(bases_path))
        rtm_personal = tdr_result.get("rtm_personal", [])
        _append_job_log(job_id, f"TDR completado — {len(rtm_personal)} cargos, {len(tdr_result.get('factores_evaluacion', []))} factores")

        _check_cancelled(job_id)

        # ════════════════════════════════════════════════════════════════
        # FASE 3: Evaluación RTM (Paso 4)
        # ════════════════════════════════════════════════════════════════
        _update_job(job_id, progress_pct=85, progress_stage="Evaluación RTM")
        _append_job_log(job_id, "FASE 3: Evaluación RTM — Paso 4")

        from src.extraction.models import Professional, Experience
        from src.validation.evaluator import evaluar_propuesta

        profesionales = []
        experiencias = []

        for sec in extraction_result.get("secciones", []):
            prof_data = sec.get("profesional") or {}
            nombre = prof_data.get("nombre") or f"(sin nombre - {sec['cargo']})"

            prof = Professional(
                name=nombre, role=sec.get("cargo", ""), role_number=sec.get("numero") or "",
                profession=prof_data.get("profesion"), tipo_colegio=prof_data.get("tipo_colegio"),
                registro_colegio=prof_data.get("registro_colegio"), registration_date=None,
                folio=None, source_file="pipeline",
            )
            profesionales.append(prof)

            for exp_data in sec.get("experiencias", []):
                exp = Experience(
                    professional_name=nombre, dni=prof_data.get("dni"),
                    project_name=exp_data.get("proyecto"), role=exp_data.get("cargo"),
                    company=exp_data.get("empresa_emisora"), ruc=exp_data.get("ruc"),
                    start_date=_try_iso(exp_data.get("fecha_inicio_parsed"), exp_data.get("fecha_inicio")),
                    end_date=_try_iso(exp_data.get("fecha_fin_parsed"), exp_data.get("fecha_fin")),
                    cert_issue_date=_try_iso(exp_data.get("fecha_emision_parsed"), exp_data.get("fecha_emision")),
                    folio=exp_data.get("folio"), cui=None, infoobras_code=None,
                    signer=exp_data.get("firmante"), raw_text="", source_file="pipeline",
                    tipo_obra=exp_data.get("tipo_obra"), tipo_intervencion=exp_data.get("tipo_intervencion"),
                    tipo_acreditacion=exp_data.get("tipo_acreditacion"),
                    cargo_firmante=exp_data.get("cargo_firmante"),
                )
                experiencias.append(exp)

        resultados_eval = evaluar_propuesta(
            profesionales=profesionales, experiencias=experiencias,
            requisitos_rtm=rtm_personal, proposal_date=_date.today(),
        )

        total_alertas = sum(len(ev.alertas) for r in resultados_eval for ev in r.evaluaciones)
        con_rtm = sum(1 for r in resultados_eval if r.requisito_encontrado)
        _append_job_log(job_id, f"Evaluación: {len(profesionales)} prof, {con_rtm} con RTM, {total_alertas} alertas")

        # ════════════════════════════════════════════════════════════════
        # FASE 4: Generar Excel
        # ════════════════════════════════════════════════════════════════
        _update_job(job_id, progress_pct=95, progress_stage="Generando Excel")
        _append_job_log(job_id, "FASE 4: Generando Excel")

        from src.reporting.excel_writer import write_report

        excel_dir = OUTPUT_DIR / job_id
        excel_dir.mkdir(parents=True, exist_ok=True)
        excel_path = excel_dir / f"evaluacion_{job_id}.xlsx"

        write_report(
            resultados=resultados_eval, output_path=excel_path,
            proposal_date=_date.today(), filename=pdf_path.name,
        )
        _append_job_log(job_id, f"Excel generado: {excel_path.name}")

        # Resultado final combinado
        result = {
            "job_type": "full",
            **extraction_result,
            "tdr": {
                "rtm_personal": rtm_personal,
                "factores_evaluacion": tdr_result.get("factores_evaluacion", []),
                "total_cargos": len(rtm_personal),
            },
            "evaluacion": {
                "profesionales": len(resultados_eval),
                "con_rtm": con_rtm,
                "total_evaluaciones": sum(len(r.evaluaciones) for r in resultados_eval),
                "total_alertas": total_alertas,
            },
            "excel_path": str(excel_path),
        }

        _update_job(
            job_id, status="done", progress_pct=100,
            progress_stage="Completado",
            result=json.dumps(result, ensure_ascii=False, default=str),
        )
        _append_job_log(job_id, "Pipeline completo finalizado")

    except subprocess.CalledProcessError as e:
        _append_job_log(job_id, f"ERROR: motor-OCR código {e.returncode}")
        _update_job(job_id, status="error", progress_pct=0, progress_stage=None, error=f"motor-OCR error (código {e.returncode})")
    except Exception as e:
        logger.exception("Job %s (full): error", job_id)
        _append_job_log(job_id, f"ERROR: {e}")
        _update_job(job_id, status="error", progress_pct=0, progress_stage=None, error=str(e))
    finally:
        pdf_path.unlink(missing_ok=True)
        if bases_path:
            bases_path.unlink(missing_ok=True)


# ── Routes: Jobs (OCR + pipeline) ───────────────────────────────────────────
@app.post("/api/jobs", status_code=201, tags=["Jobs"])
async def create_job(
    file: UploadFile = File(...),
    bases_file: Optional[UploadFile] = File(None),
    job_type: str = Form("extraction"),
    pages_from: Optional[int] = Form(None),
    pages_to: Optional[int] = Form(None),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")

    if job_type not in ("extraction", "tdr", "full"):
        raise HTTPException(400, f"job_type inválido: {job_type}. Usar: extraction, tdr, full")

    if job_type == "tdr" and not _TDR_AVAILABLE:
        raise HTTPException(503, "Módulos TDR no disponibles en el servidor")

    if job_type == "full" and not bases_file:
        raise HTTPException(400, "job_type 'full' requiere bases_file (PDF de bases)")

    if job_type == "full" and not _TDR_AVAILABLE:
        raise HTTPException(503, "Módulos TDR no disponibles — requeridos para pipeline completo")

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

    bases_path = None
    if bases_file:
        bases_path = UPLOADS_DIR / f"{job_id}_bases_{bases_file.filename}"
        bases_path.write_bytes(await bases_file.read())

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, filename, job_type, pages_from, pages_to) "
                "VALUES (%s,%s,%s,%s,%s)",
                (job_id, file.filename, job_type, pages_from, pages_to),
            )

    # Bifurcar según tipo de job
    if job_type == "tdr":
        _executor.submit(_run_tdr_job, job_id, pdf_path)
    elif job_type == "full":
        _executor.submit(_run_full_job, job_id, pdf_path, bases_path, pages)
    else:
        _executor.submit(_run_job, job_id, pdf_path, pages)

    return {"id": job_id, "status": "pending", "job_type": job_type}


@app.get("/api/jobs", tags=["Jobs"])
async def list_jobs():
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, filename, job_type, pages_from, pages_to, status, "
                "created_at, progress_pct, "
                "CASE "
                "  WHEN job_type = 'tdr' THEN (result->>'total_cargos')::int "
                "  ELSE jsonb_array_length(COALESCE(result->'secciones', '[]'::jsonb)) "
                "END AS profesionales_count "
                "FROM jobs ORDER BY created_at DESC LIMIT 50"
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "job_type": r.get("job_type", "extraction"),
            "pages_from": r["pages_from"],
            "pages_to": r["pages_to"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "progress_pct": r["progress_pct"] or 0,
            "profesionales_count": r.get("profesionales_count"),
        }
        for r in rows
    ]


@app.get("/api/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str):
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, filename, job_type, pages_from, pages_to, status, "
                "created_at, started_at, result, error, progress_pct, "
                "progress_stage, doc_total_pages, logs "
                "FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Job no encontrado")
    result_data = row["result"]
    if isinstance(result_data, str):
        result_data = json.loads(result_data)
    started = row.get("started_at")
    return {
        "id": row["id"],
        "filename": row["filename"],
        "job_type": row.get("job_type", "extraction"),
        "pages_from": row["pages_from"],
        "pages_to": row["pages_to"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "started_at": started.isoformat() if started else None,
        "result": result_data,
        "error": row["error"],
        "progress_pct": row["progress_pct"] or 0,
        "progress_stage": row["progress_stage"],
        "doc_total_pages": row["doc_total_pages"],
        "logs": row.get("logs"),
    }


# ── Evaluación RTM (Paso 4) + Excel ──────────────────────────────────────────

@app.post("/api/jobs/{extraction_job_id}/evaluate", tags=["Evaluation"])
async def evaluate_job(
    extraction_job_id: str,
    tdr_job_id: str = Form(...),
):
    """
    Ejecuta el Paso 4 (evaluación RTM) cruzando un job de extracción con un job TDR.
    Genera un Excel descargable con los resultados.

    Requiere:
    - extraction_job_id: ID de un job tipo 'extraction' completado
    - tdr_job_id: ID de un job tipo 'tdr' completado
    """
    from datetime import date as _date

    # Cargar ambos jobs
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, job_type, status, result, filename FROM jobs WHERE id = %s",
                (extraction_job_id,),
            )
            ext_row = cur.fetchone()
            cur.execute(
                "SELECT id, job_type, status, result FROM jobs WHERE id = %s",
                (tdr_job_id,),
            )
            tdr_row = cur.fetchone()

    if not ext_row:
        raise HTTPException(404, f"Job de extracción {extraction_job_id} no encontrado")
    if not tdr_row:
        raise HTTPException(404, f"Job TDR {tdr_job_id} no encontrado")
    if ext_row["status"] != "done":
        raise HTTPException(400, f"Job de extracción no está completado (status={ext_row['status']})")
    if tdr_row["status"] != "done":
        raise HTTPException(400, f"Job TDR no está completado (status={tdr_row['status']})")

    ext_result = ext_row["result"]
    tdr_result = tdr_row["result"]
    if isinstance(ext_result, str):
        ext_result = json.loads(ext_result)
    if isinstance(tdr_result, str):
        tdr_result = json.loads(tdr_result)

    # Construir objetos Professional y Experience
    from src.extraction.models import Professional, Experience
    from src.extraction.llm_extractor import _parsear_fecha

    def _try_iso_or_parse(iso_str, raw_str):
        """Intenta ISO primero, luego parseo del string crudo."""
        if iso_str and isinstance(iso_str, str):
            try:
                return _date.fromisoformat(iso_str)
            except ValueError:
                pass
        return _parsear_fecha(raw_str)

    profesionales = []
    experiencias = []

    for sec in ext_result.get("secciones", []):
        prof_data = sec.get("profesional") or {}
        nombre = prof_data.get("nombre") or f"(sin nombre - {sec['cargo']})"

        prof = Professional(
            name=nombre,
            role=sec.get("cargo", ""),
            role_number=sec.get("numero") or "",
            profession=prof_data.get("profesion"),
            tipo_colegio=prof_data.get("tipo_colegio"),
            registro_colegio=prof_data.get("registro_colegio"),
            registration_date=None,
            folio=None,
            source_file="db",
        )
        profesionales.append(prof)

        for exp_data in sec.get("experiencias", []):
            # Usar fechas pre-parseadas (ISO) si existen, sino parsear el string crudo
            start = _try_iso_or_parse(exp_data.get("fecha_inicio_parsed"), exp_data.get("fecha_inicio"))
            end = _try_iso_or_parse(exp_data.get("fecha_fin_parsed"), exp_data.get("fecha_fin"))
            cert = _try_iso_or_parse(exp_data.get("fecha_emision_parsed"), exp_data.get("fecha_emision"))

            exp = Experience(
                professional_name=nombre,
                dni=prof_data.get("dni"),
                project_name=exp_data.get("proyecto"),
                role=exp_data.get("cargo"),
                company=exp_data.get("empresa_emisora"),
                ruc=exp_data.get("ruc"),
                start_date=start,
                end_date=end,
                cert_issue_date=cert,
                folio=exp_data.get("folio"),
                cui=None,
                infoobras_code=None,
                signer=exp_data.get("firmante"),
                raw_text="",
                source_file="db",
                tipo_obra=exp_data.get("tipo_obra"),
                tipo_intervencion=exp_data.get("tipo_intervencion"),
                tipo_acreditacion=exp_data.get("tipo_acreditacion"),
                cargo_firmante=exp_data.get("cargo_firmante"),
            )
            experiencias.append(exp)

    # Ejecutar Paso 4
    from src.validation.evaluator import evaluar_propuesta
    rtm_personal = tdr_result.get("rtm_personal", [])

    resultados = evaluar_propuesta(
        profesionales=profesionales,
        experiencias=experiencias,
        requisitos_rtm=rtm_personal,
        proposal_date=_date.today(),
    )

    # Generar Excel
    from src.reporting.excel_writer import write_report

    excel_dir = OUTPUT_DIR / extraction_job_id
    excel_dir.mkdir(parents=True, exist_ok=True)
    excel_path = excel_dir / f"evaluacion_{extraction_job_id}.xlsx"

    write_report(
        resultados=resultados,
        output_path=excel_path,
        proposal_date=_date.today(),
        filename=ext_row.get("filename", ""),
    )

    # Resumen
    total_ev = sum(len(r.evaluaciones) for r in resultados)
    total_alertas = sum(len(ev.alertas) for r in resultados for ev in r.evaluaciones)
    con_rtm = sum(1 for r in resultados if r.requisito_encontrado)

    return {
        "ok": True,
        "profesionales": len(resultados),
        "con_rtm": con_rtm,
        "evaluaciones": total_ev,
        "alertas": total_alertas,
        "excel_path": str(excel_path),
        "download_url": f"/api/jobs/{extraction_job_id}/excel",
    }


@app.get("/api/jobs/{job_id}/excel", tags=["Evaluation"])
async def download_excel(job_id: str):
    """Descarga el Excel de evaluación RTM de un job."""
    from fastapi.responses import FileResponse

    excel_path = OUTPUT_DIR / job_id / f"evaluacion_{job_id}.xlsx"
    if not excel_path.exists():
        raise HTTPException(404, "Excel no encontrado. Ejecute la evaluación primero.")

    return FileResponse(
        path=str(excel_path),
        filename=f"evaluacion_{job_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── InfoObras: búsqueda y confirmación de CUIs ──────────────────────────────

@app.post("/api/infoobras/search", tags=["InfoObras"])
async def search_infoobras(
    project_name: str = Form(...),
    cert_date: Optional[str] = Form(None),
    entidad: Optional[str] = Form(None),
):
    """
    Busca una obra en InfoObras por nombre del proyecto.
    Retorna candidatos con score para confirmación manual.
    """
    from src.scraping.infoobras import (
        buscar_obras_por_nombre, _extraer_palabras_clave,
        _score_candidata, _parse_timestamp_json,
    )
    from datetime import date as _date

    cert_d = None
    if cert_date:
        try:
            cert_d = _date.fromisoformat(cert_date)
        except ValueError:
            pass

    queries = _extraer_palabras_clave(project_name)
    resultados = []
    for q in queries:
        resultados = buscar_obras_por_nombre(q)
        if resultados:
            break

    if not resultados:
        return {"candidates": [], "query": queries[0] if queries else ""}

    candidatos = [
        _score_candidata(obra, project_name, cert_d, entidad)
        for obra in resultados
    ]
    candidatos.sort(key=lambda c: c.score, reverse=True)

    return {
        "candidates": [
            {
                "obra_id": c.obra_id,
                "nombre": c.nombre,
                "cui": c.cui,
                "estado": c.estado,
                "entidad": c.entidad,
                "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else None,
                "score": round(c.score, 1),
                "motivos": c.motivos,
            }
            for c in candidatos[:10]
        ],
    }


@app.get("/api/infoobras/obra/{cui}", tags=["InfoObras"])
async def get_obra_infoobras(cui: str):
    """Obtiene datos completos de una obra por CUI."""
    from src.scraping.infoobras import fetch_by_cui

    obra = fetch_by_cui(cui)
    if not obra:
        raise HTTPException(404, f"Obra con CUI {cui} no encontrada en InfoObras")

    return {
        "cui": obra.cui,
        "obra_id": obra.obra_id,
        "nombre": obra.nombre,
        "estado": obra.estado,
        "tipo_obra": obra.tipo_obra,
        "entidad": obra.entidad,
        "ejecutor": obra.ejecutor,
        "fecha_inicio": obra.fecha_inicio.isoformat() if obra.fecha_inicio else None,
        "fecha_fin": obra.fecha_fin.isoformat() if obra.fecha_fin else None,
        "plazo_dias": obra.plazo_dias,
        "supervisores": [
            {
                "nombre": f"{s.nombre} {s.apellido_paterno} {s.apellido_materno or ''}".strip(),
                "tipo": s.tipo,
                "fecha_inicio": s.fecha_inicio.isoformat() if s.fecha_inicio else None,
                "fecha_fin": s.fecha_fin.isoformat() if s.fecha_fin else None,
            }
            for s in obra.supervisores
        ],
        "residentes": [
            {
                "nombre": f"{r.nombre} {r.apellido_paterno} {r.apellido_materno or ''}".strip(),
                "fecha_inicio": r.fecha_inicio.isoformat() if r.fecha_inicio else None,
                "fecha_fin": r.fecha_fin.isoformat() if r.fecha_fin else None,
            }
            for r in obra.residentes
        ],
        "paralizaciones": len(obra.suspension_periods),
        "suspension_periods": [
            {"inicio": p[0].isoformat(), "fin": p[1].isoformat()}
            for p in obra.suspension_periods
        ],
        "total_avances": len(obra.avances),
    }


@app.delete("/api/jobs/{job_id}", tags=["Jobs"])
async def delete_job(job_id: str):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, status FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Job no encontrado")
            # Si el job está pending o running, marcarlo como cancelado
            # para que el worker lo aborte cuando lo tome o en su próximo checkpoint
            if row[1] in ("pending", "running"):
                _cancelled_jobs.add(job_id)
                logger.info("Job %s: marcado como cancelado", job_id)
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
    job_dir = OUTPUT_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    return {"ok": True}


# ── WebSocket para progreso en tiempo real ───────────────────────────────────

@app.websocket("/ws/jobs/{job_id}")
async def ws_job_progress(websocket: WebSocket, job_id: str):
    """
    WebSocket que envía actualizaciones de progreso de un job cada 2 segundos.
    El cliente se conecta y recibe JSON con status, progress_pct, progress_stage.
    Se cierra automáticamente cuando el job termina (done/error).
    """
    await websocket.accept()
    import asyncio

    try:
        last_pct = -1
        last_status = ""
        while True:
            try:
                with _get_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            "SELECT status, progress_pct, progress_stage, started_at "
                            "FROM jobs WHERE id = %s",
                            (job_id,),
                        )
                        row = cur.fetchone()
            except Exception:
                await websocket.send_json({"error": "DB error"})
                break

            if not row:
                await websocket.send_json({"error": "Job not found"})
                break

            status = row["status"]
            pct = row["progress_pct"] or 0
            stage = row["progress_stage"]

            # Solo enviar si cambió algo
            if pct != last_pct or status != last_status:
                started = row.get("started_at")
                await websocket.send_json({
                    "status": status,
                    "progress_pct": pct,
                    "progress_stage": stage,
                    "started_at": started.isoformat() if started else None,
                })
                last_pct = pct
                last_status = status

            # Cerrar si el job terminó
            if status in ("done", "error"):
                break

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


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
    for name in ["infoobras"]:
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
