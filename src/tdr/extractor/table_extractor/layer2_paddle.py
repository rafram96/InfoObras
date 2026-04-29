"""
Capa 2 — Extraccion de tablas con PaddleOCR PP-Structure.

Cuando Capa 1 (pdfplumber) falla porque el PDF es escaneado, esta
capa usa PP-Structure de PaddleOCR (que ya esta instalado en el venv
del motor-OCR) para detectar regiones de tabla en imagenes de pagina
y extraer las celdas como matriz.

Se invoca via subprocess al motor-OCR (mismo patron que el OCR principal).
NO requiere instalar PaddleOCR aqui — se reusa el venv del motor-OCR.

Nota: por ahora esta implementado como placeholder con la signature
correcta. La integracion real con motor-OCR requiere agregar un nuevo
mode "table_extract" al subprocess_wrapper.py del motor-OCR, que es
trabajo aditivo permitido (el flujo existente no se toca).

Si el subprocess no esta disponible, esta capa retorna [] y el
orchestrator cae a Capa 3.
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from src.tdr.extractor.table_extractor.models import (
    FilaTDR,
    Confianza,
    TablaCruda,
)

logger = logging.getLogger(__name__)


def _esta_disponible_pp_structure() -> bool:
    """
    Verifica si el motor-OCR tiene el mode 'table_extract' implementado.

    Hoy: NO esta implementado todavia (es trabajo futuro al motor-OCR).
    Este check evita romper el orchestrator — devuelve False y la
    capa se salta automaticamente.
    """
    motor_ocr_wrapper = os.getenv("MOTOR_OCR_WRAPPER", "")
    if not motor_ocr_wrapper or not os.path.exists(motor_ocr_wrapper):
        return False

    # Por ahora, hardcoded a False hasta que motor-OCR exponga el mode.
    # Cuando se implemente, este check leera de un capability flag.
    return False


def extraer_b1_b2_layer2(
    pdf_path: str,
    paginas_b1: list[int],
    paginas_b2: list[int],
) -> tuple[list[FilaTDR], dict]:
    """
    Extraccion Capa 2: PP-Structure via subprocess al motor-OCR.

    Args:
        pdf_path: ruta absoluta al PDF
        paginas_b1: paginas con la tabla B.1
        paginas_b2: paginas con la tabla B.2

    Returns:
        (filas, diagnostico)

    Estado actual: stub que devuelve [] con motivo en diagnostico.
    Cuando se implemente el mode 'table_extract' en motor-OCR, esta
    funcion lanzara el subprocess y procesara la matriz devuelta.
    """
    diag: dict = {
        "capa": "layer2",
        "implementado": False,
        "motivo_skip": (
            "PP-Structure mode no implementado todavia en motor-OCR. "
            "Capa 2 saltada — orchestrator caera a Capa 3."
        ),
    }

    if not _esta_disponible_pp_structure():
        logger.info("[layer2] %s", diag["motivo_skip"])
        return [], diag

    # ── Cuando este implementado: ─────────────────────────────────────────
    # 1. Lanzar subprocess motor-OCR con mode=table_extract, args:
    #    {pdf_path, paginas: paginas_b1 + paginas_b2, output_format: "matrix"}
    # 2. Recibir lista de TablaCruda con celdas extraidas por PP-Structure
    # 3. Identificar B.1 vs B.2 con cell_parser.es_cabecera_b1/b2
    # 4. Procesar igual que Capa 1 pero con confianza Confianza.LAYER2_PADDLE
    # 5. Retornar filas + diagnostico
    # ──────────────────────────────────────────────────────────────────────

    return [], diag


def _procesar_matriz_paddle(
    matriz: list[list[str]],
    pagina: int,
) -> Optional[TablaCruda]:
    """
    Helper para cuando se implemente: convierte la matriz devuelta por
    PP-Structure en una TablaCruda procesable por la misma logica que
    Capa 1 (cell_parser.es_cabecera_b1/b2 + parsers de celda).

    PP-Structure devuelve celdas con coordenadas que se pueden mapear a
    una matriz [filas][columnas] respetando merged cells.
    """
    if not matriz or len(matriz) < 2:
        return None
    return TablaCruda(
        pagina=pagina,
        filas=[[(c or "").strip() for c in row] for row in matriz],
        fuente="paddle_structure",
    )
