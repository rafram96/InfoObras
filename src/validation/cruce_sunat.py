"""
Cruce de experiencias declaradas contra SUNAT — automatiza ALT04.

Detecta cuando una empresa emisora se inscribió en SUNAT *después* del
inicio de la experiencia declarada. Una empresa que no existía todavía
no podía haber emitido un certificado válido.

Para cada experiencia con RUC:
  1. consulta SUNAT (cacheada por RUC durante el cruce)
  2. compara `fecha_inscripcion` con `experience.start_date`
  3. si fecha_inscripcion > start_date → señal ALT04 (severidad: critica)

También genera señales de menor severidad:
  - SIN_RUC: experiencia sin RUC declarado (no cruzable)
  - RUC_NO_ENCONTRADO: SUNAT no devolvió detalle parseable
  - EMPRESA_BAJA: empresa emisora figura en estado BAJA

Pensado para invocarse desde un endpoint dedicado (`/cruce-sunat`) o
embebido en el flujo `/evaluate`. El cache se pasa por parámetro para
poder compartirlo con otros llamadores (p.ej. el endpoint de cruce
InfoObras también podría enriquecerse con datos SUNAT).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Optional

from src.extraction.models import Experience
from src.scraping.sunat import EmpresaSUNAT, consultar_ruc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

@dataclass
class SenalCruceSUNAT:
    """Una señal generada por el cruce SUNAT (una alerta o nota)."""
    severidad: str  # "critica" | "observacion" | "informativa"
    codigo: str     # "ALT04" | "RUC_NO_ENCONTRADO" | "EMPRESA_BAJA" | "SIN_RUC"
    mensaje: str


@dataclass
class ResultadoCruceExperienciaSUNAT:
    """Resultado del cruce de UNA experiencia con SUNAT."""
    profesional: str
    empresa: Optional[str]
    ruc: Optional[str]
    proyecto: Optional[str]
    fecha_inicio_exp: Optional[date]
    empresa_sunat: Optional[EmpresaSUNAT] = None
    senales: list[SenalCruceSUNAT] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profesional": self.profesional,
            "empresa": self.empresa,
            "ruc": self.ruc,
            "proyecto": self.proyecto,
            "fecha_inicio_exp": (
                self.fecha_inicio_exp.isoformat() if self.fecha_inicio_exp else None
            ),
            "empresa_sunat": (
                self.empresa_sunat.to_dict() if self.empresa_sunat else None
            ),
            "senales": [asdict(s) for s in self.senales],
        }


@dataclass
class ResultadoCruceJobSUNAT:
    """Resultado consolidado del cruce de un job completo."""
    cruces: list[ResultadoCruceExperienciaSUNAT]
    rucs_consultados: int
    rucs_encontrados: int
    rucs_no_encontrados: list[str]
    total_senales: int
    total_alt04: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cruces": [c.to_dict() for c in self.cruces],
            "rucs_consultados": self.rucs_consultados,
            "rucs_encontrados": self.rucs_encontrados,
            "rucs_no_encontrados": self.rucs_no_encontrados,
            "total_senales": self.total_senales,
            "total_alt04": self.total_alt04,
        }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

# Cache en memoria proceso-wide (FastAPI worker). Sobrevive entre requests
# pero se pierde al reiniciar el server. Los datos SUNAT cambian muy poco,
# así que persistir en SQLite con TTL 30d sería el siguiente paso.
_CACHE_PROCESO: dict[str, Optional[EmpresaSUNAT]] = {}


def limpiar_cache() -> None:
    """Borra el cache proceso-wide. Para tests o recargas manuales."""
    _CACHE_PROCESO.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalizar_ruc(ruc: Optional[str]) -> Optional[str]:
    """Devuelve el RUC limpio (11 dígitos) o None si no es válido."""
    if not ruc:
        return None
    digits = "".join(c for c in str(ruc) if c.isdigit())
    return digits if len(digits) == 11 else None


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def cruzar_experiencias(
    experiencias: list[Experience],
    *,
    cache: Optional[dict[str, Optional[EmpresaSUNAT]]] = None,
) -> ResultadoCruceJobSUNAT:
    """
    Cruza una lista de experiencias contra SUNAT y genera señales.

    Args:
        experiencias: lista de Experience del Paso 3.
        cache: dict {ruc → EmpresaSUNAT|None} compartido. Si None, usa el
                cache proceso-wide.

    Returns:
        ResultadoCruceJobSUNAT con cruces detallados y resumen agregado.
    """
    if cache is None:
        cache = _CACHE_PROCESO

    cruces: list[ResultadoCruceExperienciaSUNAT] = []
    rucs_no_encontrados: list[str] = []
    rucs_consultados_unicos: set[str] = set()
    total_alt04 = 0

    for exp in experiencias:
        ruc = _normalizar_ruc(exp.ruc)
        cruce = ResultadoCruceExperienciaSUNAT(
            profesional=exp.professional_name,
            empresa=exp.company,
            ruc=ruc,
            proyecto=exp.project_name,
            fecha_inicio_exp=exp.start_date,
        )

        if not ruc:
            cruce.senales.append(SenalCruceSUNAT(
                severidad="informativa",
                codigo="SIN_RUC",
                mensaje="Experiencia sin RUC declarado — no se puede cruzar con SUNAT",
            ))
            cruces.append(cruce)
            continue

        # Lookup cacheado
        if ruc not in cache:
            try:
                cache[ruc] = consultar_ruc(ruc)
            except Exception as exc:
                logger.warning("Error consultando SUNAT para RUC %s: %s", ruc, exc)
                cache[ruc] = None
            rucs_consultados_unicos.add(ruc)

        empresa = cache[ruc]
        cruce.empresa_sunat = empresa

        if empresa is None:
            if ruc not in rucs_no_encontrados:
                rucs_no_encontrados.append(ruc)
            cruce.senales.append(SenalCruceSUNAT(
                severidad="observacion",
                codigo="RUC_NO_ENCONTRADO",
                mensaje=(
                    f"RUC {ruc} no encontrado en SUNAT "
                    f"(puede ser RUC invalido o el portal no respondio)"
                ),
            ))
            cruces.append(cruce)
            continue

        # ALT04: empresa inscrita despues del inicio de experiencia
        if (
            empresa.fecha_inscripcion is not None
            and exp.start_date is not None
            and empresa.fecha_inscripcion > exp.start_date
        ):
            cruce.senales.append(SenalCruceSUNAT(
                severidad="critica",
                codigo="ALT04",
                mensaje=(
                    f"Empresa '{empresa.razon_social or exp.company}' "
                    f"se inscribio en SUNAT el "
                    f"{empresa.fecha_inscripcion:%d/%m/%Y}, "
                    f"posterior al inicio de la experiencia declarada "
                    f"({exp.start_date:%d/%m/%Y})"
                ),
            ))
            total_alt04 += 1

        # Empresa en BAJA → observacion (no critica)
        if empresa.estado and "BAJA" in empresa.estado.upper():
            cruce.senales.append(SenalCruceSUNAT(
                severidad="observacion",
                codigo="EMPRESA_BAJA",
                mensaje=(
                    f"Empresa emisora figura como '{empresa.estado}' en SUNAT"
                ),
            ))

        cruces.append(cruce)

    total_senales = sum(len(c.senales) for c in cruces)

    return ResultadoCruceJobSUNAT(
        cruces=cruces,
        rucs_consultados=len(rucs_consultados_unicos),
        rucs_encontrados=len(rucs_consultados_unicos) - len(rucs_no_encontrados),
        rucs_no_encontrados=rucs_no_encontrados,
        total_senales=total_senales,
        total_alt04=total_alt04,
    )
