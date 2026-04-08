"""
Motor de reglas determinístico — 9 alertas + cálculo de días efectivos (Pasos 4 y 5).
Sin IA, sin llamadas externas.
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from src.extraction.models import Experience, RequisitoPersonal
from src.validation.matching import (
    match_profesion,
    match_cargo,
    match_tipo_obra,
)

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fecha_hace_20_anos(proposal_date: date) -> date:
    """Retorna la fecha 20 años antes de proposal_date, manejando Feb 29."""
    try:
        return proposal_date.replace(year=proposal_date.year - 20)
    except ValueError:
        # 29 de febrero en año no bisiesto → usar 28 de febrero
        return proposal_date.replace(year=proposal_date.year - 20, day=28)


def _periodos_solapan(
    inicio_a: date, fin_a: date,
    inicio_b: date, fin_b: date,
) -> bool:
    """Retorna True si los dos periodos se solapan."""
    return inicio_a <= fin_b and fin_a >= inicio_b


# ---------------------------------------------------------------------------
# Motor de alertas
# ---------------------------------------------------------------------------

def check_alerts(
    exp: Experience,
    proposal_date: date,
    requisito: Optional[RequisitoPersonal] = None,
    profesion_propuesta: Optional[str] = None,
    sunat_start_date: Optional[date] = None,
    cip_vigente: Optional[bool] = None,
) -> list[Alert]:
    """
    Aplica las 9 reglas a una experiencia y retorna las alertas generadas.

    Degradación elegante: cuando un dato externo es None (scraper no
    disponible, Paso 1 sin resultado), la alerta correspondiente NO se
    genera — sin falsos positivos.
    """
    alerts: list[Alert] = []

    # ----- ALT01: Fecha fin posterior a fecha emisión del certificado -----
    if (
        exp.end_date is not None
        and exp.cert_issue_date is not None
        and exp.end_date > exp.cert_issue_date
    ):
        alerts.append(Alert(
            code=AlertCode.ALT01,
            severity=Severity.WARNING,
            description=(
                f"Fecha fin ({exp.end_date:%d/%m/%Y}) es posterior a "
                f"fecha emisión ({exp.cert_issue_date:%d/%m/%Y})"
            ),
            experience=exp,
        ))

    # ----- ALT02: Periodo incluye COVID -----
    if (
        exp.start_date is not None
        and exp.end_date is not None
        and _periodos_solapan(exp.start_date, exp.end_date, COVID_START, COVID_END)
    ):
        alerts.append(Alert(
            code=AlertCode.ALT02,
            severity=Severity.WARNING,
            description="Periodo incluye rango COVID (16/03/2020 – 31/12/2021)",
            experience=exp,
        ))

    # ----- ALT03: Experiencia con más de 20 años de antigüedad -----
    if exp.end_date is not None:
        limite_20 = _fecha_hace_20_anos(proposal_date)
        if exp.end_date < limite_20:
            alerts.append(Alert(
                code=AlertCode.ALT03,
                severity=Severity.WARNING,
                description=(
                    f"Experiencia terminó el {exp.end_date:%d/%m/%Y}, "
                    f"más de 20 años antes de la propuesta ({proposal_date:%d/%m/%Y})"
                ),
                experience=exp,
            ))

    # ----- ALT04: Empresa constituida después del inicio de experiencia -----
    # Requiere dato externo de SUNAT — skip si None
    if (
        sunat_start_date is not None
        and exp.start_date is not None
        and sunat_start_date > exp.start_date
    ):
        alerts.append(Alert(
            code=AlertCode.ALT04,
            severity=Severity.CRITICAL,
            description=(
                f"Empresa emisora inició actividades ({sunat_start_date:%d/%m/%Y}) "
                f"después del inicio de experiencia ({exp.start_date:%d/%m/%Y})"
            ),
            experience=exp,
        ))

    # ----- ALT05: Sin fecha de término -----
    if exp.end_date is None:
        alerts.append(Alert(
            code=AlertCode.ALT05,
            severity=Severity.CRITICAL,
            description="Certificado sin fecha de término (\"a la fecha\")",
            experience=exp,
        ))

    # ----- ALT06: Cargo no válido según bases -----
    # Requiere RequisitoPersonal de Paso 1
    if requisito is not None:
        cargos_validos = None
        if requisito.experiencia_minima and requisito.experiencia_minima.cargos_similares_validos:
            cargos_validos = requisito.experiencia_minima.cargos_similares_validos
        # Si no hay cargos_similares_validos, usar el cargo del requisito como referencia
        if not cargos_validos and requisito.cargo:
            cargos_validos = [requisito.cargo]

        if cargos_validos and not match_cargo(exp.role, cargos_validos):
            alerts.append(Alert(
                code=AlertCode.ALT06,
                severity=Severity.CRITICAL,
                description=(
                    f"Cargo \"{exp.role}\" no coincide con "
                    f"cargos válidos: {', '.join(cargos_validos)}"
                ),
                experience=exp,
            ))

    # ----- ALT07: Profesión no coincide -----
    # Requiere RequisitoPersonal + profesión del profesional
    if (
        requisito is not None
        and requisito.profesiones_aceptadas
        and profesion_propuesta is not None
        and not match_profesion(profesion_propuesta, requisito.profesiones_aceptadas)
    ):
        alerts.append(Alert(
            code=AlertCode.ALT07,
            severity=Severity.CRITICAL,
            description=(
                f"Profesión \"{profesion_propuesta}\" no coincide con "
                f"requeridas: {', '.join(requisito.profesiones_aceptadas)}"
            ),
            experience=exp,
        ))

    # ----- ALT08: Tipo de obra no coincide -----
    # Requiere RequisitoPersonal con tipo_obra_valido
    if requisito is not None and requisito.tipo_obra_valido:
        # Usar tipo_obra explícito si existe, sino el nombre del proyecto
        texto_comparar = exp.tipo_obra or exp.project_name
        resultado = match_tipo_obra(texto_comparar, requisito.tipo_obra_valido)
        # Solo alertar si resultado es False (no si es None = indeterminable)
        if resultado is False:
            alerts.append(Alert(
                code=AlertCode.ALT08,
                severity=Severity.CRITICAL,
                description=(
                    f"Tipo de obra del proyecto no coincide con "
                    f"requerido: \"{requisito.tipo_obra_valido}\""
                ),
                experience=exp,
            ))

    # ----- ALT09: CIP no vigente -----
    # Requiere dato externo del scraper CIP — skip si None
    if cip_vigente is not None and cip_vigente is False:
        alerts.append(Alert(
            code=AlertCode.ALT09,
            severity=Severity.WARNING,
            description="CIP/Colegiatura no vigente según consulta al colegio profesional",
            experience=exp,
        ))

    return alerts


def calculate_effective_days(
    experiences: list[Experience],
    proposal_date: date,
    suspension_periods: Optional[list[tuple[date, date]]] = None,
) -> int:
    """
    Paso 5: suma días efectivos descontando COVID y paralizaciones/suspensiones
    obtenidas de InfoObras.

    TODO: implementar en Paso 5.
    """
    raise NotImplementedError
