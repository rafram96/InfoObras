"""
Motor de validación — Pasos 4 y 5 del pipeline.

Exports públicos:
  - evaluar_propuesta: orquestador top-level (recibe Pasos 1-3, retorna resultados)
  - evaluar_profesional: evaluación de un solo profesional
  - check_alerts: 9 alertas por experiencia
  - Alert, AlertCode, Severity: modelos de alerta
"""
from src.validation.rules import (
    check_alerts,
    Alert,
    AlertCode,
    Severity,
    COVID_START,
    COVID_END,
)
from src.validation.evaluator import (
    evaluar_propuesta,
    evaluar_profesional,
    evaluar_rtm,
)
from src.validation.matching import (
    normalizar_cargo,
    normalizar_texto,
    match_profesion,
    match_cargo,
    match_tipo_obra,
    match_intervencion,
    inferir_tipo_obra,
    inferir_intervencion,
)

__all__ = [
    # Orquestación
    "evaluar_propuesta",
    "evaluar_profesional",
    "evaluar_rtm",
    # Alertas
    "check_alerts",
    "Alert",
    "AlertCode",
    "Severity",
    "COVID_START",
    "COVID_END",
    # Matching
    "normalizar_cargo",
    "normalizar_texto",
    "match_profesion",
    "match_cargo",
    "match_tipo_obra",
    "match_intervencion",
    "inferir_tipo_obra",
    "inferir_intervencion",
]
