"""
Parsea los dos archivos .md que genera el motor-OCR:
  - *_profesionales_*.md  → metadata (cargo, bloques de páginas)
  - *_texto_*.md          → texto OCR página por página

Combina ambos para producir ProfessionalBlock[] con texto completo.
"""
import re
from pathlib import Path
from typing import Optional

from src.extraction.models import ProfessionalBlock

# En-dash (–) que usa el motor-OCR para rangos de páginas
_RANGE_RE = re.compile(r"páginas\s+(\d+)\s*[–\-]\s*(\d+)", re.IGNORECASE)
_SECTION_RE = re.compile(r"^###\s+\d+\.\s+(.+)$")
_SEPARATOR_RE = re.compile(r"\*\*Página separadora:\*\*\s*(\d+)")
_TOTAL_PAGES_RE = re.compile(r"\*\*Total páginas:\*\*\s*(\d+)")
_NUMERO_RE = re.compile(r"N[°º]\s*(\d+)", re.IGNORECASE)
_PAGE_HEADER_RE = re.compile(r"^##\s+Página\s+(\d+)", re.MULTILINE)
# Tabla del resumen — soporta dos formatos:
# Formato viejo (5 cols): | # | Cargo | Págs | Pág. inicio | Pág. fin |
_TABLE_ROW_OLD_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
    re.MULTILINE,
)
# Formato nuevo (6 cols): | # | Cargo | N° | Págs totales | Bloques | Pág. inicio |
_TABLE_ROW_NEW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*[^|]*\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|",
    re.MULTILINE,
)
# Rangos dentro de la columna Bloques: "46–63 · 81–88 · 142–155" o "1–14"
_BLOQUE_RANGE_RE = re.compile(r"(\d+)\s*[–\-]\s*(\d+)")


def parse_page_texts(texto_path: Path) -> dict[int, str]:
    """
    Lee *_texto_*.md y retorna {numero_pagina: texto}.
    Extrae el contenido entre las marcas de código de cada página.
    """
    content = texto_path.read_text(encoding="utf-8")
    pages: dict[int, str] = {}

    # Divide por cabecera de página: ## Página N
    parts = _PAGE_HEADER_RE.split(content)
    # parts = [pre, page_num, body, page_num, body, ...]
    i = 1
    while i < len(parts) - 1:
        page_num = int(parts[i])
        body = parts[i + 1]
        # Extrae texto dentro del primer bloque ```...```
        code_match = re.search(r"```\n(.*?)```", body, re.DOTALL)
        text = code_match.group(1).strip() if code_match else body.strip()
        pages[page_num] = text
        i += 2

    return pages


def _extract_numero(cargo_raw: str) -> Optional[str]:
    """Extrae 'N°1', 'N°2', etc. del nombre del cargo si existe."""
    matches = _NUMERO_RE.findall(cargo_raw)
    if matches:
        return f"N°{matches[-1]}"  # toma el último (evita duplicados como "N°1 N°1")
    return None


def _clean_cargo(cargo_raw: str) -> str:
    """Elimina números de cargo (N°1, N°2) del nombre del cargo."""
    cleaned = _NUMERO_RE.sub("", cargo_raw).strip()
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _parse_summary_table(content: str) -> dict[int, list[tuple[int, int]]]:
    """
    Parsea la tabla de resumen.
    Retorna {indice: [(pag_inicio, pag_fin), ...]}.

    Soporta dos formatos:
    - Viejo (5 cols): | # | Cargo | Págs | Pág. inicio | Pág. fin |
    - Nuevo (6 cols): | # | Cargo | N° | Págs totales | Bloques | Pág. inicio |
    """
    table: dict[int, list[tuple[int, int]]] = {}

    # Intenta formato nuevo primero (tiene columna Bloques con rangos explícitos)
    for match in _TABLE_ROW_NEW_RE.finditer(content):
        idx = int(match.group(1))
        bloques_text = match.group(4)  # e.g. "46–63 · 81–88 · 142–155" o "1–14"
        ranges = [
            (int(m.group(1)), int(m.group(2)))
            for m in _BLOQUE_RANGE_RE.finditer(bloques_text)
        ]
        if ranges:
            table[idx] = ranges

    if table:
        return table

    # Fallback: formato viejo (Pág. inicio / Pág. fin como columnas separadas)
    for match in _TABLE_ROW_OLD_RE.finditer(content):
        idx = int(match.group(1))
        pag_inicio = int(match.group(4))
        pag_fin = int(match.group(5))
        table[idx] = [(pag_inicio, pag_fin)]

    return table


def parse_professional_blocks(
    prof_path: Path,
    texto_path: Path,
) -> list[ProfessionalBlock]:
    """
    Lee *_profesionales_*.md y *_texto_*.md.
    Retorna lista de ProfessionalBlock con texto completo por profesional.
    Soporta formato viejo (bloques con 'páginas X–Y') y nuevo (tabla resumen con Pág. inicio/fin).
    """
    page_texts = parse_page_texts(texto_path)
    content = prof_path.read_text(encoding="utf-8")

    # Parsea tabla de resumen (formato nuevo) como fallback
    summary_table = _parse_summary_table(content)

    # Divide el contenido por secciones ### N. Cargo
    sections = re.split(r"\n(?=###\s+\d+\.)", content)

    blocks: list[ProfessionalBlock] = []

    for section in sections:
        header_match = _SECTION_RE.match(section.strip().splitlines()[0])
        if not header_match:
            continue

        cargo_raw = header_match.group(1).strip()
        numero = _extract_numero(cargo_raw)
        cargo = _clean_cargo(cargo_raw)

        # Índice desde el número en el header (### N. ...)
        idx_match = re.match(r"###\s+(\d+)\.", section.strip().splitlines()[0])
        index = int(idx_match.group(1)) if idx_match else len(blocks) + 1

        # Número de página separadora
        sep_match = _SEPARATOR_RE.search(section)
        separator_page = int(sep_match.group(1)) if sep_match else 0

        # Rangos de páginas: primero intenta formato viejo (bloques con 'páginas X–Y')
        page_ranges: list[tuple[int, int]] = []
        for match in _RANGE_RE.finditer(section):
            page_ranges.append((int(match.group(1)), int(match.group(2))))

        # Si no hay rangos, usa la tabla de resumen
        if not page_ranges and index in summary_table:
            for pag_inicio, pag_fin in summary_table[index]:
                # Excluye la página separadora del rango de contenido
                content_start = separator_page + 1 if separator_page == pag_inicio else pag_inicio
                if content_start <= pag_fin:
                    page_ranges.append((content_start, pag_fin))

        if not page_ranges:
            continue

        # Construye texto separado por bloque (un texto por page_range)
        block_texts: list[str] = []
        for start, end in page_ranges:
            parts: list[str] = []
            for pnum in range(start, end + 1):
                if pnum in page_texts:
                    parts.append(f"[Página {pnum}]\n{page_texts[pnum]}")
            block_texts.append("\n\n".join(parts))

        # full_text = todos los bloques concatenados (compatibilidad hacia atrás)
        full_text = "\n\n".join(block_texts)

        blocks.append(ProfessionalBlock(
            index=index,
            cargo=cargo,
            cargo_raw=cargo_raw,
            numero=numero,
            separator_page=separator_page,
            page_ranges=page_ranges,
            block_texts=block_texts,
            full_text=full_text,
            source_profesionales=str(prof_path),
            source_texto=str(texto_path),
        ))

    return blocks
