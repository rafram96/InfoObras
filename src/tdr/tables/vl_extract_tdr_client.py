"""
Cliente del worker de extraccion VL TDR.

Se invoca desde extraer_bases() en pipeline.py. Orquesta:
1. Deteccion de paginas B.1 / B.2 usando el texto OCR.
2. Lanzamiento del subprocess vl_extract_tdr_worker.py.
3. Parseo del JSON de salida.
4. Retorna dict con filas B.1 y B.2 estructuradas.

El subprocess asegura que Qwen-VL se libera de VRAM al terminar,
permitiendo que Qwen 14B se cargue sin contencion.
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from src.tdr.config.settings import (
    OLLAMA_BASE_URL,
    QWEN_VL_MODEL,
    QWEN_VL_TIMEOUT,
    QWEN_MODEL,
    TABLE_VL_MAX_PX,
    TABLE_VL_MAX_BATCH,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
_WORKER_PATH = str(Path(__file__).parent / "vl_extract_tdr_worker.py")


def extraer_tdr_con_vl(
    pdf_path: str,
    texto_por_pagina: dict[int, str],
    paginas_rtm_personal: Optional[list[int]] = None,
    timeout: int = 900,
) -> dict:
    """
    Invoca el worker VL para extraer tablas B.1 y B.2 del PDF.

    Args:
        pdf_path: ruta absoluta al PDF del TDR.
        texto_por_pagina: {num_pagina: texto_ocr} para detectar headers B.1/B.2.
        paginas_rtm_personal: fallback si no se detectan headers.
        timeout: segundos maximos de ejecucion del worker (default 15 min).

    Returns:
        {
          "b1": [{"numero": 1, "cargo": "...", "profesiones": [...]}, ...],
          "b2": [{"numero": 1, "cargo": "...", "tiempo_meses": 24,
                  "cargos_similares": [...], "tipo_obra": "...",
                  "descripcion": "..."}, ...],
          "diagnostico": {...}
        }
        Si algo falla, retorna dict con listas vacias y error en diagnostico.
    """
    from src.tdr.tables.vl_page_detector import detectar_paginas_b1_b2

    paginas_b1, paginas_b2 = detectar_paginas_b1_b2(
        texto_por_pagina, paginas_rtm_personal,
    )
    if not paginas_b1 and not paginas_b2:
        logger.warning(
            "[vl-tdr] No se detectaron paginas B.1 ni B.2 — saltando extraccion VL"
        )
        return {
            "b1": [], "b2": [],
            "diagnostico": {
                "error_general": "No se detectaron paginas B.1/B.2",
                "paginas_b1": [], "paginas_b2": [],
            },
        }

    # Settings override (solo los campos que el worker usa)
    settings_override = {
        "OLLAMA_BASE_URL": OLLAMA_BASE_URL,
        "QWEN_VL_MODEL": QWEN_VL_MODEL,
        "QWEN_VL_TIMEOUT": QWEN_VL_TIMEOUT,
        "QWEN_MODEL": QWEN_MODEL,
        "TABLE_VL_MAX_PX": TABLE_VL_MAX_PX,
        "TABLE_VL_MAX_BATCH": TABLE_VL_MAX_BATCH,
    }

    input_data = {
        "pdf_path": str(pdf_path),
        "paginas_b1": paginas_b1,
        "paginas_b2": paginas_b2,
        "settings": settings_override,
    }

    tmp_in = tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fi:
            json.dump(input_data, fi, ensure_ascii=False)
            tmp_in = fi.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fo:
            tmp_out = fo.name

        logger.info(
            f"[vl-tdr] Lanzando worker: B.1={paginas_b1} B.2={paginas_b2}"
        )
        resultado = subprocess.run(
            [sys.executable, _WORKER_PATH, _PROJECT_ROOT, tmp_in, tmp_out],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

        if resultado.returncode != 0:
            logger.warning(
                f"[vl-tdr] Worker fallo con codigo {resultado.returncode}"
            )
            stderr = (resultado.stderr or "").strip()
            if stderr:
                logger.warning(f"[vl-tdr] STDERR:\n{stderr[-3000:]}")
            return {
                "b1": [], "b2": [],
                "diagnostico": {
                    "error_general": f"Worker retorno {resultado.returncode}",
                    "stderr": stderr[-2000:],
                    "paginas_b1": paginas_b1,
                    "paginas_b2": paginas_b2,
                },
            }

        # Leer JSON de salida
        if os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
            with open(tmp_out, "r", encoding="utf-8") as f:
                output = json.load(f)
            logger.info(
                "[vl-tdr] Worker OK: B.1=%d filas, B.2=%d filas",
                len(output.get("b1", [])), len(output.get("b2", [])),
            )
            return output
        else:
            logger.warning("[vl-tdr] Worker no produjo output")
            return {
                "b1": [], "b2": [],
                "diagnostico": {
                    "error_general": "Worker sin output",
                    "paginas_b1": paginas_b1,
                    "paginas_b2": paginas_b2,
                },
            }

    except subprocess.TimeoutExpired:
        logger.error(f"[vl-tdr] Timeout {timeout}s")
        return {
            "b1": [], "b2": [],
            "diagnostico": {
                "error_general": f"Timeout {timeout}s",
                "paginas_b1": paginas_b1,
                "paginas_b2": paginas_b2,
            },
        }
    except Exception as e:
        logger.exception(f"[vl-tdr] Error inesperado: {e}")
        return {
            "b1": [], "b2": [],
            "diagnostico": {
                "error_general": str(e),
                "paginas_b1": paginas_b1,
                "paginas_b2": paginas_b2,
            },
        }
    finally:
        for path in (tmp_in, tmp_out):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
