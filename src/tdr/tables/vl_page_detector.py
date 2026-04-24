"""
Detector de paginas que contienen las tablas B.1 y B.2 de un TDR OSCE.

Estrategias (en orden):
1. Busca headers "B.1" / "B.2" en el texto OCR de las paginas.
2. Si no encuentra, usa el scorer del pipeline textual (bloques rtm_personal).
3. Si todo falla, devuelve todas las paginas scoreadas como rtm_personal.

Retorna dos listas disjuntas (o con overlap si la tabla cruza paginas):
  paginas_b1 = [2, 3, 4]
  paginas_b2 = [5, 6, 7, 8, 9]
"""
from __future__ import annotations
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


_RE_HEADER_B1 = re.compile(
    r"B\s*\.?\s*1\s*\.?\s*CALIFICACI[OÓ]N\s+DEL\s+PERSONAL\s+CLAVE",
    re.IGNORECASE,
)
_RE_HEADER_B2 = re.compile(
    r"B\s*\.?\s*2\s*\.?\s*EXPERIENCIA\s+DEL\s+PERSONAL\s+CLAVE",
    re.IGNORECASE,
)
# Termino "hard" que cierra la seccion del personal clave
_RE_HEADER_B3 = re.compile(
    r"B\s*\.?\s*3|3\.4\.2\s*REQUISITOS\s+DE\s+CALIFICACI",
    re.IGNORECASE,
)


def detectar_paginas_b1_b2(
    texto_por_pagina: dict[int, str],
    paginas_rtm_personal: Optional[list[int]] = None,
) -> tuple[list[int], list[int]]:
    """
    Detecta que paginas contienen B.1 y B.2.

    Args:
        texto_por_pagina: {num_pagina: texto_ocr}.
        paginas_rtm_personal: fallback del scorer si los headers no se detectan.

    Returns:
        (paginas_b1, paginas_b2) — listas de enteros, ordenadas asc.
    """
    if not texto_por_pagina:
        return [], []

    # Detectar inicios con regex
    pag_b1_start = _buscar_primera_pagina(texto_por_pagina, _RE_HEADER_B1)
    pag_b2_start = _buscar_primera_pagina(texto_por_pagina, _RE_HEADER_B2)
    pag_b3_start = _buscar_primera_pagina(texto_por_pagina, _RE_HEADER_B3)

    todas = sorted(texto_por_pagina.keys())

    # Fallback: usar el bloque rtm_personal del scorer
    if pag_b1_start is None and pag_b2_start is None:
        if paginas_rtm_personal:
            logger.warning(
                "[vl-pages] No se detectaron headers B.1/B.2 en el texto. "
                "Usando bloque rtm_personal del scorer: %s",
                paginas_rtm_personal,
            )
            # Heuristica: primera mitad = B.1, segunda = B.2
            sorted_p = sorted(paginas_rtm_personal)
            mid = len(sorted_p) // 2
            return sorted_p[:mid] or sorted_p[:1], sorted_p[mid:] or sorted_p[-1:]
        logger.warning("[vl-pages] Sin headers y sin bloque rtm_personal — devolviendo vacio")
        return [], []

    # B.1 desde pag_b1_start hasta (pag_b2_start o pag_b3_start o final)
    if pag_b1_start is not None:
        fin_b1 = pag_b2_start or pag_b3_start or (max(todas) + 1)
        paginas_b1 = [p for p in todas if pag_b1_start <= p < fin_b1]
    else:
        paginas_b1 = []

    # B.2 desde pag_b2_start hasta (pag_b3_start o "Nota:" o "Acreditacion" al final)
    if pag_b2_start is not None:
        fin_b2 = pag_b3_start or _buscar_fin_b2(texto_por_pagina, pag_b2_start) or (max(todas) + 1)
        paginas_b2 = [p for p in todas if pag_b2_start <= p < fin_b2]
    else:
        paginas_b2 = []

    logger.info(
        "[vl-pages] B.1 = %s | B.2 = %s",
        paginas_b1, paginas_b2,
    )
    return paginas_b1, paginas_b2


def _buscar_primera_pagina(
    texto_por_pagina: dict[int, str],
    regex: re.Pattern,
) -> Optional[int]:
    """Retorna el numero de la primera pagina cuyo texto matchea regex."""
    for pag in sorted(texto_por_pagina.keys()):
        if regex.search(texto_por_pagina.get(pag, "")):
            return pag
    return None


_RE_FIN_B2 = re.compile(
    r"Nota\s*:\s*La\s+experiencia|Acreditaci[oó]n\s*:|3\.4\.2\s",
    re.IGNORECASE,
)


def _buscar_fin_b2(
    texto_por_pagina: dict[int, str],
    start_b2: int,
) -> Optional[int]:
    """Busca la primera pagina >= start_b2 donde aparece un marcador de fin de B.2."""
    for pag in sorted(texto_por_pagina.keys()):
        if pag <= start_b2:
            continue
        if _RE_FIN_B2.search(texto_por_pagina.get(pag, "")):
            # La pagina donde aparece "Nota:" aun puede tener filas de B.2.
            # Devuelve pag + 1 para incluirla.
            return pag + 1
    return None
