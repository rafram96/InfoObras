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

    Estructura típica de bloques por profesional:
      bloque 0 → credenciales: diploma universitario + diploma del colegio profesional
      bloque 1 → ANEXO 16: declaración jurada + tabla resumen de experiencias
      bloque 2 → constancias individuales: certificados emitidos por cada empresa

    Las páginas separadoras (qwen fallback, texto muy corto) encabezan cada bloque.
    Los bloques 1 y 2 tienen el mejor OCR — el bloque 0 suele ser el más ruidoso.
    """
    index: int
    cargo: str                           # cargo sin número (e.g. "Gerente De Supervisión")
    cargo_raw: str                       # tal como aparece en el .md
    numero: Optional[str]                # "N°1", "N°2", None si no tiene
    separator_page: int
    page_ranges: list[tuple[int, int]]   # [(2, 4), (98, 102), (300, 304)]
    block_texts: list[str]               # texto OCR por bloque, en orden (uno por page_range)
    full_text: str                       # todos los bloques concatenados (compatibilidad)
    source_profesionales: str            # path del *_profesionales_*.md
    source_texto: str                    # path del *_texto_*.md


@dataclass
class Professional:
    """Paso 2: profesional propuesto (cabecera del certificado)."""
    name: str
    role: str                        # cargo (Jefe de Supervisión, etc.)
    role_number: str                 # N°1, N°2, etc.
    profession: Optional[str]        # Ingeniero Civil, Arquitecto, etc.
    tipo_colegio: Optional[str]      # CIP, CAP, CBP, CMP, etc.
    registro_colegio: Optional[str]  # número de registro en el colegio
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
