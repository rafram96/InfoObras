"""
Consulta SUNAT por RUC → fecha de inicio de actividades (ALT04).
"""
from datetime import date
from typing import Optional


def fetch_start_date(ruc: str) -> Optional[date]:
    """Retorna la fecha de inicio de actividades de la empresa."""
    raise NotImplementedError
