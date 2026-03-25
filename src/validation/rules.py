"""
Motor de reglas determinístico — 9 alertas + evaluación RTM (Pasos 4 y 5).
Sin IA, sin llamadas externas.
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from src.extraction.models import Experience

COVID_START = date(2020, 3, 16)
COVID_END = date(2021, 12, 31)


class AlertCode(str, Enum):
    ALT01 = "ALT01"  # Fecha fin > fecha emisión certificado
    ALT02 = "ALT02"  # Periodo COVID
    ALT03 = "ALT03"  # Experiencia > 20 años
    ALT04 = "ALT04"  # Empresa constituida después del inicio
    ALT05 = "ALT05"  # Sin fecha de término ("a la fecha")
    ALT06 = "ALT06"  # Cargo no válido según bases
    ALT07 = "ALT07"  # Profesión no coincide
    ALT08 = "ALT08"  # Tipo de obra no coincide
    ALT09 = "ALT09"  # CIP no vigente


class Severity(str, Enum):
    CRITICAL = "CRITICO"
    WARNING = "OBSERVACION"


@dataclass
class Alert:
    code: AlertCode
    severity: Severity
    description: str
    experience: Optional[Experience] = None


def check_alerts(exp: Experience, proposal_date: date) -> list[Alert]:
    """Aplica las 9 reglas a una experiencia y retorna las alertas generadas."""
    alerts: list[Alert] = []
    # TODO: implementar cada regla
    return alerts


def calculate_effective_days(experiences: list[Experience], proposal_date: date) -> int:
    """
    Paso 5: suma días efectivos descontando COVID y paralizaciones/suspensiones
    obtenidas de InfoObras.
    """
    raise NotImplementedError
