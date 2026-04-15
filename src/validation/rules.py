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
    ALT04 = "ALT04"  # Empresa constituida después del inicio (verificación manual SUNAT)
    ALT05 = "ALT05"  # Sin fecha de término ("a la fecha")
    ALT06 = "ALT06"  # Cargo no válido según bases
    ALT07 = "ALT07"  # Profesión no coincide
    ALT08 = "ALT08"  # Tipo de obra no coincide
    ALT09 = "ALT09"  # Colegiatura no vigente (verificación manual)


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
    # Verificación manual SUNAT (tiene CAPTCHA, no se automatiza).
    # El evaluador puede pasar sunat_start_date manualmente si lo verificó.
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

    # ----- ALT09: Colegiatura no vigente -----
    # Verificación manual — el evaluador ingresa el dato desde la UI.
    # Cada colegio (CIP, CAP, CBP, CMP, etc.) tiene su propio portal.
    if cip_vigente is not None and cip_vigente is False:
        alerts.append(Alert(
            code=AlertCode.ALT09,
            severity=Severity.WARNING,
            description="Colegiatura no vigente según verificación del evaluador",
            experience=exp,
        ))

    return alerts


def _overlap_days(a_start: date, a_end: date, b_start: date, b_end: date) -> int:
    """Retorna días de solapamiento entre dos periodos (0 si no solapan)."""
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    if overlap_start > overlap_end:
        return 0
    return (overlap_end - overlap_start).days + 1


def calculate_effective_days(
    experiences: list[Experience],
    proposal_date: date,
    suspension_periods: Optional[list[tuple[date, date]]] = None,
) -> int:
    """
    Paso 5: suma días efectivos de experiencia.

    Por cada experiencia con fecha_inicio y fecha_fin:
    1. Calcula días brutos = (fin - inicio).days
    2. Descuenta días solapados con periodo COVID (16/03/2020 – 31/12/2021)
    3. Descuenta días solapados con paralizaciones/suspensiones de InfoObras
    4. Suma los días netos de todas las experiencias

    No descuenta doble: si COVID y una paralización solapan, solo se descuenta una vez.

    Args:
        experiences: experiencias del profesional (con fechas parseadas)
        proposal_date: fecha de presentación de la propuesta
        suspension_periods: periodos de suspensión [(inicio, fin), ...] de InfoObras

    Returns:
        Días efectivos totales (puede ser 0, nunca negativo)
    """
    total_effective = 0

    for exp in experiences:
        if not exp.start_date or not exp.end_date:
            continue

        # Días brutos
        brutos = (exp.end_date - exp.start_date).days
        if brutos <= 0:
            continue

        # Colectar todos los periodos a descontar (sin duplicar)
        descuentos: list[tuple[date, date]] = []

        # COVID
        covid_overlap = _overlap_days(exp.start_date, exp.end_date, COVID_START, COVID_END)
        if covid_overlap > 0:
            descuentos.append((
                max(exp.start_date, COVID_START),
                min(exp.end_date, COVID_END),
            ))

        # Paralizaciones de InfoObras
        if suspension_periods:
            for sus_start, sus_end in suspension_periods:
                overlap = _overlap_days(exp.start_date, exp.end_date, sus_start, sus_end)
                if overlap > 0:
                    descuentos.append((
                        max(exp.start_date, sus_start),
                        min(exp.end_date, sus_end),
                    ))

        # Fusionar periodos de descuento para no descontar doble
        # (ej: si COVID y una paralización solapan)
        if descuentos:
            descuentos.sort()
            fusionados: list[tuple[date, date]] = [descuentos[0]]
            for start, end in descuentos[1:]:
                prev_start, prev_end = fusionados[-1]
                if start <= prev_end:
                    # Solapan — fusionar
                    fusionados[-1] = (prev_start, max(prev_end, end))
                else:
                    fusionados.append((start, end))

            total_descuento = sum((e - s).days + 1 for s, e in fusionados)
        else:
            total_descuento = 0

        netos = max(0, brutos - total_descuento)
        total_effective += netos

    return total_effective


def calculate_effective_years(
    experiences: list[Experience],
    proposal_date: date,
    suspension_periods: Optional[list[tuple[date, date]]] = None,
) -> float:
    """Convierte días efectivos a años (redondeado a 1 decimal)."""
    days = calculate_effective_days(experiences, proposal_date, suspension_periods)
    return round(days / 365.25, 1)
