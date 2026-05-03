"""
Dataclasses compartidos del pipeline de extraccion TDR de 3 capas.

Una FilaTDR representa un cargo de la tabla B.1 + datos asociados de B.2.
ResultadoExtraccion agrupa todas las filas + diagnostico de que capa
las produjo y con que confianza.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


class Confianza:
    """Niveles canonicos de confianza por capa."""
    LAYER1_PDFPLUMBER = 0.95   # celda exacta del PDF digital
    LAYER2_PADDLE     = 0.80   # celda aproximada de OCR estructural
    LAYER3_REGEX_LLM  = 0.65   # texto recortado por regex + LLM por fila
    LAYER3_LLM_BLOQUE = 0.50   # fallback total: LLM ve todo el texto


@dataclass
class ExperienciaMinima:
    """Bloque de experiencia minima que viene de B.2."""
    cantidad: Optional[int] = None              # numero de meses
    unidad: str = "meses"
    descripcion: Optional[str] = None           # texto literal de B.2
    cargos_similares_validos: list[str] = field(default_factory=list)
    puntaje_por_experiencia: Optional[float] = None
    puntaje_maximo: Optional[float] = None


@dataclass
class Capacitacion:
    """Capacitacion exigida por el TDR (curso, programa, especializacion)."""
    tema: Optional[str] = None
    tipo: Optional[str] = None                  # "Programa/Curso/Diplomado", "Especializacion"
    duracion_minima_horas: Optional[int] = None
    es_factor_evaluacion: bool = False


@dataclass
class FilaTDR:
    """
    Una fila completa del personal clave del TDR.
    Fusiona B.1 (calificacion) + B.2 (experiencia) por numero_fila.
    """
    numero_fila: int                             # N° de la columna N° (1-17)
    cargo: str                                   # nombre del cargo (CAPS literal)
    profesiones_aceptadas: list[str] = field(default_factory=list)
    anos_colegiado: Optional[str] = None         # "48 meses" o similar
    experiencia_minima: ExperienciaMinima = field(default_factory=ExperienciaMinima)
    tipo_obra_valido: Optional[str] = None       # "establecimientos de salud", etc.
    tiempo_adicional_factores: Optional[str] = None
    capacitacion: Optional[Capacitacion] = None
    pagina: Optional[int] = None                 # pagina del PDF donde aparece B.2

    # Metadata de la extraccion (no se serializa al cliente final)
    confianza: float = 0.0                       # Confianza.LAYER1/2/3
    fuente: str = ""                             # "layer1" | "layer2" | "layer3"
    fila_texto_origen: Optional[str] = None      # texto OCR usado (debug)

    def to_dict(self, incluir_metadata: bool = False) -> dict:
        """Serializa para JSON. Por default omite metadata interna."""
        d: dict[str, Any] = {
            "numero_fila": self.numero_fila,
            "cargo": self.cargo,
            "profesiones_aceptadas": list(self.profesiones_aceptadas),
            "anos_colegiado": self.anos_colegiado,
            "experiencia_minima": {
                "cantidad": self.experiencia_minima.cantidad,
                "unidad": self.experiencia_minima.unidad,
                "descripcion": self.experiencia_minima.descripcion,
                "cargos_similares_validos": list(
                    self.experiencia_minima.cargos_similares_validos
                ),
                "puntaje_por_experiencia": self.experiencia_minima.puntaje_por_experiencia,
                "puntaje_maximo": self.experiencia_minima.puntaje_maximo,
            },
            "tipo_obra_valido": self.tipo_obra_valido,
            "tiempo_adicional_factores": self.tiempo_adicional_factores,
            "capacitacion": (
                {
                    "tema": self.capacitacion.tema,
                    "tipo": self.capacitacion.tipo,
                    "duracion_minima_horas": self.capacitacion.duracion_minima_horas,
                    "es_factor_evaluacion": self.capacitacion.es_factor_evaluacion,
                }
                if self.capacitacion
                else None
            ),
            "pagina": self.pagina,
        }
        if incluir_metadata:
            d["_meta"] = {
                "confianza": self.confianza,
                "fuente": self.fuente,
                "fila_texto_origen": self.fila_texto_origen,
            }
        return d


@dataclass
class CeldaTabla:
    """Una celda cruda de tabla extraida por Capa 1 o 2 antes del parsing."""
    fila_idx: int                                # indice de fila en la tabla (0-based)
    col_idx: int                                 # indice de columna (0-based)
    texto: str                                   # contenido literal de la celda
    pagina: int                                  # pagina del PDF


@dataclass
class TablaCruda:
    """Tabla extraida por Capa 1 o 2 antes de identificar B.1 vs B.2."""
    pagina: int
    filas: list[list[str]]                       # matriz de strings (filas x cols)
    fuente: str                                  # "pdfplumber" | "paddle_structure"

    @property
    def n_filas(self) -> int:
        return len(self.filas)

    @property
    def n_cols(self) -> int:
        if not self.filas:
            return 0
        return max(len(r) for r in self.filas)

    def cabecera(self) -> list[str]:
        """Primera fila si existe."""
        return [c.strip() if c else "" for c in self.filas[0]] if self.filas else []


@dataclass
class ResultadoExtraccion:
    """Resultado completo del pipeline de 3 capas."""
    filas: list[FilaTDR] = field(default_factory=list)
    capa_usada: str = ""                         # "layer1" | "layer2" | "layer3"
    capas_intentadas: list[str] = field(default_factory=list)
    diagnostico: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "personal_clave": [f.to_dict() for f in self.filas],
            "_capa_usada": self.capa_usada,
            "_capas_intentadas": self.capas_intentadas,
            "_diagnostico": self.diagnostico,
            "_error": self.error,
        }
