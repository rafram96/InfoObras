"""
Scraper de InfoObras (Contraloría General de la República).
Búsqueda por CUI → estado de obra, suspensiones, avances mensuales.
Sin CAPTCHA ni Playwright — solo requests + parsing.
"""
import requests
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class WorkInfo:
    cui: str
    name: Optional[str]
    status: Optional[str]
    suspension_periods: list[tuple[date, date]] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def fetch_by_cui(cui: str) -> Optional[WorkInfo]:
    """Consulta InfoObras por CUI y retorna datos de la obra."""
    raise NotImplementedError
