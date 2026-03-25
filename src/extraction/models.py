"""
Modelos de datos que fluyen entre módulos.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ProfessionalBlock:
    """
    Resultado intermedio del parser: un profesional con su texto completo.
    Combina *_profesionales_*.md (metadata) + *_texto_*.md (contenido).
    """
    index: int
    cargo: str                           # cargo sin número (e.g. "Gerente De Supervisión")
    cargo_raw: str                       # tal como aparece en el .md
    numero: Optional[str]                # "N°1", "N°2", None si no tiene
    separator_page: int
    page_ranges: list[tuple[int, int]]   # [(2, 4), (98, 102), (300, 304)]
    full_text: str                       # texto OCR concatenado de todas las páginas
    source_profesionales: str            # path del *_profesionales_*.md
    source_texto: str                    # path del *_texto_*.md


@dataclass
class Professional:
    """Paso 2: profesional propuesto (cabecera del certificado)."""
    name: str
    role: str                        # cargo (Jefe de Supervisión, etc.)
    role_number: str                 # N°1, N°2, etc.
    profession: Optional[str]        # Ingeniero Civil, Arquitecto, etc.
    cip: Optional[str]
    registration_date: Optional[date]
    folio: Optional[str]
    source_file: str                 # archivo .md de origen


@dataclass
class Experience:
    """Paso 3: una entrada de experiencia (un certificado de trabajo)."""
    professional_name: str
    dni: Optional[str]
    project_name: Optional[str]
    role: Optional[str]
    company: Optional[str]
    ruc: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]         # None si "a la fecha"
    cert_issue_date: Optional[date]
    folio: Optional[str]
    cui: Optional[str]
    infoobras_code: Optional[str]
    signer: Optional[str]
    raw_text: str                    # texto crudo del bloque
    source_file: str
