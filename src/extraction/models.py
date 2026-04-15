"""
Modelos de datos que fluyen entre módulos.

Dataclasses organizados por paso del pipeline:
  - ProfessionalBlock: resultado intermedio del parser (pre-LLM)
  - Professional: Paso 2 — profesional propuesto
  - Experience: Paso 3 — certificado de experiencia
  - ExperienciaMinima, RequisitoPersonal: Paso 1 — criterios RTM (wrapper tipado)
  - EvaluacionRTM: Paso 4 — resultado de evaluación (22 columnas)
  - ResultadoProfesional: Paso 4 — agrupa evaluaciones de un profesional
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ---------------------------------------------------------------------------
# Resultado intermedio del parser (pre-LLM)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Paso 2: profesionales propuestos
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Paso 3: experiencias (certificados de trabajo)
# ---------------------------------------------------------------------------

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
    # --- Campos agregados para Paso 4 (extraídos por LLM o inferidos) ---
    tipo_obra: Optional[str] = None           # sector: salud, educacion, vial, etc.
    tipo_intervencion: Optional[str] = None   # accion: construccion, mejoramiento, etc.
    tipo_acreditacion: Optional[str] = None   # tipo doc: certificado, constancia, contrato


# ---------------------------------------------------------------------------
# Paso 1: criterios RTM — wrappers tipados sobre los dicts del TDR extractor
# ---------------------------------------------------------------------------

@dataclass
class ExperienciaMinima:
    """Requisito de experiencia mínima para un cargo, extraído de las bases."""
    cantidad: Optional[int] = None                   # meses
    unidad: str = "meses"
    descripcion: Optional[str] = None                # texto literal del requisito
    cargos_similares_validos: Optional[list[str]] = None
    puntaje_por_experiencia: Optional[int] = None
    puntaje_maximo: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict | None) -> ExperienciaMinima | None:
        """Construye desde el dict anidado del TDR extractor. None si d es None."""
        if not d:
            return None
        return cls(
            cantidad=d.get("cantidad"),
            unidad=d.get("unidad", "meses"),
            descripcion=d.get("descripcion"),
            cargos_similares_validos=d.get("cargos_similares_validos"),
            puntaje_por_experiencia=d.get("puntaje_por_experiencia"),
            puntaje_maximo=d.get("puntaje_maximo"),
        )


@dataclass
class RequisitoPersonal:
    """
    Requisito por cargo profesional, extraído de las bases del concurso (Paso 1).
    Wrapper tipado sobre el dict `rtm_personal` del TDR extractor.
    """
    cargo: str = ""
    profesiones_aceptadas: Optional[list[str]] = None
    anos_colegiado: Optional[str] = None            # e.g. "48 meses"
    experiencia_minima: Optional[ExperienciaMinima] = None
    tipo_obra_valido: Optional[str] = None
    tiempo_adicional_factores: Optional[str] = None
    capacitacion: Optional[dict] = None
    pagina: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> RequisitoPersonal:
        """Construye desde un dict de rtm_personal del TDR extractor."""
        return cls(
            cargo=d.get("cargo", ""),
            profesiones_aceptadas=d.get("profesiones_aceptadas"),
            anos_colegiado=d.get("anos_colegiado"),
            experiencia_minima=ExperienciaMinima.from_dict(
                d.get("experiencia_minima"),
            ),
            tipo_obra_valido=d.get("tipo_obra_valido"),
            tiempo_adicional_factores=d.get("tiempo_adicional_factores"),
            capacitacion=d.get("capacitacion"),
            pagina=d.get("pagina"),
        )


# ---------------------------------------------------------------------------
# Paso 4: evaluación RTM — resultado de 22 columnas
# ---------------------------------------------------------------------------

@dataclass
class EvaluacionRTM:
    """
    Resultado de evaluar UNA experiencia contra los criterios RTM.
    Corresponde a las 22 columnas del manual (Paso 4).
    """
    # Identificación (cols 1-6)
    cargo_postulado: str = ""
    nombre: str = ""
    profesion_propuesta: Optional[str] = None
    profesion_requerida: Optional[str] = None        # de RequisitoPersonal
    cumple_profesion: str = ""                        # "SI" / "NO" / "NO EVALUABLE"
    folio_certificado: Optional[str] = None

    # Cargo (cols 7-9)
    cargo_experiencia: Optional[str] = None          # de Experience.role
    cargos_validos_bases: Optional[str] = None       # texto plano de la lista
    cumple_cargo: str = ""                           # "CUMPLE" / "NO CUMPLE" / "NO EVALUABLE"

    # Proyecto (cols 10-12)
    proyecto_propuesto: Optional[str] = None         # de Experience.project_name
    proyecto_valido_bases: Optional[str] = None      # de RequisitoPersonal.tipo_obra_valido
    cumple_proyecto: str = ""                        # "SI" / "NO" / "NO EVALUABLE"

    # Fecha de término (cols 13-14)
    fecha_termino: Optional[date] = None
    alerta_fecha_termino: str = ""                   # "NO VALE" / ""

    # Tipo de obra (cols 15-17)
    tipo_obra_certificado: Optional[str] = None
    tipo_obra_requerido: Optional[str] = None
    cumple_tipo_obra: str = ""                       # "CUMPLE" / "NO CUMPLE" / "NO EVALUABLE"

    # Intervención (cols 18-20)
    intervencion_certificado: Optional[str] = None
    intervencion_requerida: Optional[str] = None
    cumple_intervencion: str = ""                    # "CUMPLE" / "NO CUMPLE" / "NO EVALUABLE"

    # Validaciones finales (cols 21-22)
    acredita_complejidad: str = ""                   # "SI" / "NO"
    dentro_20_anos: str = ""                         # "SI" / "NO"

    # Metadata interna (no se exporta a Excel directamente)
    alertas: list = field(default_factory=list)       # list[Alert]
    experiencia_ref: Optional[Experience] = None      # referencia a la Experience original


@dataclass
class ResultadoProfesional:
    """Agrupa todas las evaluaciones RTM de un profesional."""
    profesional: Professional = field(default_factory=lambda: Professional(
        name="", role="", role_number="", profession=None,
        tipo_colegio=None, registro_colegio=None,
        registration_date=None, folio=None, source_file="",
    ))
    requisito: Optional[RequisitoPersonal] = None
    requisito_encontrado: bool = False
    evaluaciones: list[EvaluacionRTM] = field(default_factory=list)
    alertas_globales: list = field(default_factory=list)  # list[Alert]
