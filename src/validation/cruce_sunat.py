"""
Cruce de experiencias declaradas contra SUNAT — automatiza ALT04 y otras alertas.

Cubre los siguientes casos:

  Caso 1 — RUC declarado válido:
    1.1 Lookup directo (con cache DB persistente, TTL 30d).
    1.2 ALT04 si fecha_inscripcion > start_date.
    1.3 Fuzzy match nombre_declarado vs razon_social_sunat:
        - score < 70  → MISMATCH_NOMBRE_RUC (crítica): el RUC declarado pertenece
                        a otra empresa (typo o fraude).
        - 70 ≤ score < 85 → NOMBRE_DIFERENTE (observación): nombres difieren
                            parcialmente, verificar.
        - score ≥ 85 → match silencioso, no genera señal.
    1.4 EMPRESA_BAJA si SUNAT marca estado de baja.

  Caso 2 — Sin RUC pero con nombre:
    2.1 buscar_por_razon_social → lista de candidatos.
    2.2 Ranking por fuzzy contra el nombre declarado.
    2.3 Si el mejor candidato supera score 85 y la diferencia con el segundo
        es ≥ 5 puntos → match único confiable, se usa su RUC.
    2.4 Si hay empate cercano → AMBIGUO_REQUIERE_HUMANO con candidatos.
    2.5 Si nadie supera score 70 → NO_ENCONTRADO_POR_NOMBRE.

  Caso 3 — Ni RUC ni nombre → SIN_DATOS_EMPRESA.

Configurable via env:
  SUNAT_FUZZY_THRESHOLD_CRITICAL  (default 70)
  SUNAT_FUZZY_THRESHOLD_WARNING   (default 85)
  SUNAT_AMBIGUO_DELTA             (default 5)  — diferencia mínima entre top1 y top2
  SUNAT_CACHE_TTL_DAYS            (default 30)
  SUNAT_NEG_CACHE_TTL_DAYS        (default 1)
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Optional

from src.extraction.models import Experience
from src.scraping import sunat_cache
from src.scraping.sunat import (
    EmpresaSUNAT,
    buscar_por_razon_social,
    consultar_ruc,
    score_match_empresa,
)

logger = logging.getLogger(__name__)

THRESHOLD_CRITICAL = int(os.getenv("SUNAT_FUZZY_THRESHOLD_CRITICAL", "70"))
THRESHOLD_WARNING = int(os.getenv("SUNAT_FUZZY_THRESHOLD_WARNING", "85"))
AMBIGUO_DELTA = int(os.getenv("SUNAT_AMBIGUO_DELTA", "5"))


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

@dataclass
class SenalCruceSUNAT:
    """Una señal generada por el cruce SUNAT."""
    severidad: str  # "critica" | "observacion" | "informativa"
    codigo: str
    mensaje: str


@dataclass
class CandidatoEmpresa:
    """Un candidato resultante de buscar_por_razon_social."""
    ruc: str
    razon_social: str
    score: int  # 0-100, fuzzy match contra el nombre declarado
    estado: Optional[str] = None
    ubicacion: Optional[str] = None


@dataclass
class ResultadoCruceExperienciaSUNAT:
    """Resultado del cruce de UNA experiencia con SUNAT."""
    profesional: str
    empresa_declarada: Optional[str]
    ruc_declarado: Optional[str]
    ruc_resuelto: Optional[str]  # puede ser != ruc_declarado si vino por fallback
    proyecto: Optional[str]
    fecha_inicio_exp: Optional[date]
    empresa_sunat: Optional[EmpresaSUNAT] = None
    score_match_nombre: Optional[int] = None  # 0-100
    candidatos_ambiguos: list[CandidatoEmpresa] = field(default_factory=list)
    senales: list[SenalCruceSUNAT] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profesional": self.profesional,
            "empresa_declarada": self.empresa_declarada,
            "ruc_declarado": self.ruc_declarado,
            "ruc_resuelto": self.ruc_resuelto,
            "proyecto": self.proyecto,
            "fecha_inicio_exp": (
                self.fecha_inicio_exp.isoformat() if self.fecha_inicio_exp else None
            ),
            "empresa_sunat": (
                self.empresa_sunat.to_dict() if self.empresa_sunat else None
            ),
            "score_match_nombre": self.score_match_nombre,
            "candidatos_ambiguos": [asdict(c) for c in self.candidatos_ambiguos],
            "senales": [asdict(s) for s in self.senales],
        }


@dataclass
class ResultadoCruceJobSUNAT:
    """Resultado consolidado del cruce de un job completo."""
    cruces: list[ResultadoCruceExperienciaSUNAT]
    rucs_consultados: int          # llamadas live a SUNAT
    rucs_servidos_de_cache: int    # cache hits
    rucs_encontrados: int          # con datos válidos al final
    rucs_no_encontrados: list[str]
    total_senales: int
    total_alt04: int
    total_mismatches: int  # MISMATCH_NOMBRE_RUC
    total_ambiguos: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cruces": [c.to_dict() for c in self.cruces],
            "rucs_consultados": self.rucs_consultados,
            "rucs_servidos_de_cache": self.rucs_servidos_de_cache,
            "rucs_encontrados": self.rucs_encontrados,
            "rucs_no_encontrados": self.rucs_no_encontrados,
            "total_senales": self.total_senales,
            "total_alt04": self.total_alt04,
            "total_mismatches": self.total_mismatches,
            "total_ambiguos": self.total_ambiguos,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalizar_ruc(ruc: Optional[str]) -> Optional[str]:
    if not ruc:
        return None
    digits = "".join(c for c in str(ruc) if c.isdigit())
    return digits if len(digits) == 11 else None


def _aplicar_match_nombre(
    cruce: ResultadoCruceExperienciaSUNAT,
    nombre_declarado: Optional[str],
    empresa: EmpresaSUNAT,
) -> int:
    """
    Calcula score y genera señales de match nombre↔RUC.
    Devuelve el score (0-100). Modifica cruce in-place.
    """
    if not nombre_declarado or not empresa.razon_social:
        return -1  # No comparable

    score = score_match_empresa(nombre_declarado, empresa.razon_social)
    cruce.score_match_nombre = score

    if score < THRESHOLD_CRITICAL:
        cruce.senales.append(SenalCruceSUNAT(
            severidad="critica",
            codigo="MISMATCH_NOMBRE_RUC",
            mensaje=(
                f"RUC {empresa.ruc} corresponde a '{empresa.razon_social}' "
                f"pero el certificado declara '{nombre_declarado}' "
                f"(similitud: {score}/100). El RUC declarado no coincide con "
                f"la empresa nombrada."
            ),
        ))
    elif score < THRESHOLD_WARNING:
        cruce.senales.append(SenalCruceSUNAT(
            severidad="observacion",
            codigo="NOMBRE_DIFERENTE",
            mensaje=(
                f"Nombre declarado '{nombre_declarado}' y razon social SUNAT "
                f"'{empresa.razon_social}' difieren parcialmente "
                f"(similitud: {score}/100)"
            ),
        ))
    return score


def _check_alt04(
    cruce: ResultadoCruceExperienciaSUNAT,
    empresa: EmpresaSUNAT,
    fecha_inicio_exp: Optional[date],
) -> bool:
    """Genera señal ALT04 si aplica. Devuelve True si se disparó."""
    if (
        empresa.fecha_inscripcion is None
        or fecha_inicio_exp is None
        or empresa.fecha_inscripcion <= fecha_inicio_exp
    ):
        return False

    cruce.senales.append(SenalCruceSUNAT(
        severidad="critica",
        codigo="ALT04",
        mensaje=(
            f"Empresa '{empresa.razon_social or empresa.ruc}' "
            f"se inscribio en SUNAT el {empresa.fecha_inscripcion:%d/%m/%Y}, "
            f"posterior al inicio de la experiencia declarada "
            f"({fecha_inicio_exp:%d/%m/%Y})"
        ),
    ))
    return True


def _check_estado_baja(
    cruce: ResultadoCruceExperienciaSUNAT,
    empresa: EmpresaSUNAT,
) -> None:
    if empresa.estado and "BAJA" in empresa.estado.upper():
        cruce.senales.append(SenalCruceSUNAT(
            severidad="observacion",
            codigo="EMPRESA_BAJA",
            mensaje=f"Empresa emisora figura como '{empresa.estado}' en SUNAT",
        ))


# ---------------------------------------------------------------------------
# Lookup con cache (DB + memoria)
# ---------------------------------------------------------------------------

class _LookupContext:
    """Encapsula estado del cruce: cache en memoria + conexion DB opcional."""

    def __init__(self, conn=None):
        self.conn = conn
        self.cache_memoria: dict[str, Optional[EmpresaSUNAT]] = {}
        self.consultas_live = 0
        self.cache_hits = 0
        if conn is not None:
            try:
                sunat_cache.init_table(conn)
            except Exception as exc:
                logger.warning("No se pudo inicializar tabla sunat_cache: %s", exc)
                self.conn = None

    def lookup_ruc(self, ruc: str) -> Optional[EmpresaSUNAT]:
        # Memoria
        if ruc in self.cache_memoria:
            return self.cache_memoria[ruc]

        # DB cache
        if self.conn is not None:
            try:
                hit, empresa = sunat_cache.get(self.conn, ruc)
                if hit:
                    self.cache_memoria[ruc] = empresa
                    self.cache_hits += 1
                    return empresa
            except Exception as exc:
                logger.warning("Error leyendo cache SUNAT para %s: %s", ruc, exc)

        # Live SUNAT
        try:
            empresa = consultar_ruc(ruc)
        except Exception as exc:
            logger.warning("Error consultando SUNAT para RUC %s: %s", ruc, exc)
            empresa = None

        self.cache_memoria[ruc] = empresa
        self.consultas_live += 1

        if self.conn is not None:
            try:
                sunat_cache.set(self.conn, ruc, empresa)
            except Exception as exc:
                logger.warning("Error guardando cache SUNAT para %s: %s", ruc, exc)

        return empresa


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def cruzar_experiencias(
    experiencias: list[Experience],
    *,
    conn=None,
) -> ResultadoCruceJobSUNAT:
    """
    Cruza una lista de experiencias contra SUNAT y genera señales.

    Args:
        experiencias: lista de Experience del Paso 3.
        conn: conexión PostgreSQL opcional. Si se provee, se usa cache
              persistente en tabla `sunat_cache` (TTL 30d positivo, 1d negativo).
              Sin conn, solo cache en memoria del proceso.

    Returns:
        ResultadoCruceJobSUNAT con cruces detallados y resumen agregado.
    """
    ctx = _LookupContext(conn=conn)

    cruces: list[ResultadoCruceExperienciaSUNAT] = []
    rucs_no_encontrados: list[str] = []
    total_alt04 = 0
    total_mismatches = 0
    total_ambiguos = 0

    for exp in experiencias:
        ruc_declarado = _normalizar_ruc(exp.ruc)
        cruce = ResultadoCruceExperienciaSUNAT(
            profesional=exp.professional_name,
            empresa_declarada=exp.company,
            ruc_declarado=ruc_declarado,
            ruc_resuelto=ruc_declarado,
            proyecto=exp.project_name,
            fecha_inicio_exp=exp.start_date,
        )

        empresa: Optional[EmpresaSUNAT] = None
        resuelto_por_nombre = False  # True si llegamos al empresa por fuzzy nombre

        # ─── Paso 1: lookup directo por RUC declarado (si lo hay) ──────────
        if ruc_declarado:
            empresa = ctx.lookup_ruc(ruc_declarado)
            if empresa is not None:
                cruce.empresa_sunat = empresa
                cruce.ruc_resuelto = ruc_declarado

        # ─── Paso 2: fallback por nombre ────────────────────────────────────
        # Se intenta SIEMPRE si tenemos nombre y todavia no tenemos empresa.
        # Aplica a 2 casos:
        #   (a) sin RUC declarado
        #   (b) con RUC declarado pero SUNAT no devolvio datos (RUC mal escrito)
        if empresa is None and exp.company:
            try:
                candidatos_raw = buscar_por_razon_social(exp.company)
            except Exception as exc:
                logger.warning(
                    "Error buscando por razon social '%s': %s", exp.company, exc
                )
                candidatos_raw = []

            candidatos = sorted([
                CandidatoEmpresa(
                    ruc=c["ruc"],
                    razon_social=c.get("razon_social", ""),
                    score=score_match_empresa(exp.company, c.get("razon_social", "")),
                    estado=c.get("estado"),
                    ubicacion=c.get("ubicacion"),
                )
                for c in candidatos_raw
            ], key=lambda c: c.score, reverse=True)

            if candidatos and candidatos[0].score >= THRESHOLD_CRITICAL:
                top1 = candidatos[0]
                top2_score = candidatos[1].score if len(candidatos) >= 2 else 0
                es_ambiguo = (
                    top1.score < THRESHOLD_WARNING
                    or (top1.score - top2_score) < AMBIGUO_DELTA
                )

                if es_ambiguo:
                    cruce.candidatos_ambiguos = candidatos[:5]
                    cruce.senales.append(SenalCruceSUNAT(
                        severidad="observacion",
                        codigo="AMBIGUO_REQUIERE_HUMANO",
                        mensaje=(
                            f"Multiples candidatos para '{exp.company}': "
                            f"top score={top1.score} ({top1.razon_social}), "
                            f"requiere confirmacion humana"
                        ),
                    ))
                    total_ambiguos += 1
                else:
                    # Match unico confiable → consultar el RUC del top1
                    empresa = ctx.lookup_ruc(top1.ruc)
                    if empresa is not None:
                        cruce.empresa_sunat = empresa
                        cruce.ruc_resuelto = top1.ruc
                        cruce.score_match_nombre = top1.score
                        resuelto_por_nombre = True

                        # Senal segun el caso:
                        if ruc_declarado:
                            # RUC declarado fallo, pero por nombre encontramos
                            # OTRO RUC. Critico: RUC mal escrito en certificado.
                            cruce.senales.append(SenalCruceSUNAT(
                                severidad="critica",
                                codigo="RUC_DECLARADO_INCORRECTO",
                                mensaje=(
                                    f"RUC declarado {ruc_declarado} no se "
                                    f"encontro en SUNAT, pero por nombre "
                                    f"matchea '{top1.razon_social}' con RUC "
                                    f"{top1.ruc} (score: {top1.score}/100). "
                                    f"El RUC del certificado puede tener typo."
                                ),
                            ))
                            total_mismatches += 1
                        else:
                            cruce.senales.append(SenalCruceSUNAT(
                                severidad="informativa",
                                codigo="RUC_INFERIDO_POR_NOMBRE",
                                mensaje=(
                                    f"RUC {top1.ruc} inferido por fuzzy match "
                                    f"(score: {top1.score}/100) — el "
                                    f"certificado no lo declaraba"
                                ),
                            ))
            else:
                # Busqueda por nombre tampoco dio resultados utiles
                cruce.senales.append(SenalCruceSUNAT(
                    severidad="observacion",
                    codigo="NO_ENCONTRADO_POR_NOMBRE",
                    mensaje=(
                        f"No se encontro empresa parecida a '{exp.company}' "
                        f"en SUNAT (busqueda devolvio {len(candidatos)} "
                        f"resultados, mejor score: "
                        f"{candidatos[0].score if candidatos else 0})"
                    ),
                ))

        # ─── Paso 3: empresa encontrada → validaciones ──────────────────────
        if empresa is not None:
            if _check_alt04(cruce, empresa, exp.start_date):
                total_alt04 += 1
            # Match nombre↔razon social: solo aplicar si vino por RUC declarado.
            # Si vino por busqueda de nombre, el match ya esta garantizado >= 85.
            if not resuelto_por_nombre:
                score = _aplicar_match_nombre(cruce, exp.company, empresa)
                if score >= 0 and score < THRESHOLD_CRITICAL:
                    total_mismatches += 1
            _check_estado_baja(cruce, empresa)

        # ─── Paso 4: no encontramos empresa por ningun camino ───────────────
        elif ruc_declarado and not exp.company:
            # RUC declarado pero sin nombre para fallback
            if ruc_declarado not in rucs_no_encontrados:
                rucs_no_encontrados.append(ruc_declarado)
            cruce.senales.append(SenalCruceSUNAT(
                severidad="observacion",
                codigo="RUC_NO_ENCONTRADO",
                mensaje=(
                    f"RUC {ruc_declarado} no encontrado en SUNAT "
                    f"(no hay nombre declarado para fallback por razon social)"
                ),
            ))
        elif ruc_declarado and exp.company:
            # Ambos fallaron. Registrar el RUC fallido.
            if ruc_declarado not in rucs_no_encontrados:
                rucs_no_encontrados.append(ruc_declarado)
            # La senal NO_ENCONTRADO_POR_NOMBRE ya fue agregada arriba.
        elif not ruc_declarado and not exp.company:
            cruce.senales.append(SenalCruceSUNAT(
                severidad="informativa",
                codigo="SIN_DATOS_EMPRESA",
                mensaje=(
                    "Experiencia sin RUC ni nombre de empresa — "
                    "no se puede cruzar con SUNAT"
                ),
            ))

        cruces.append(cruce)

    total_senales = sum(len(c.senales) for c in cruces)
    rucs_encontrados = sum(
        1 for c in cruces
        if c.empresa_sunat is not None and c.empresa_sunat.razon_social
    )

    return ResultadoCruceJobSUNAT(
        cruces=cruces,
        rucs_consultados=ctx.consultas_live,
        rucs_servidos_de_cache=ctx.cache_hits,
        rucs_encontrados=rucs_encontrados,
        rucs_no_encontrados=rucs_no_encontrados,
        total_senales=total_senales,
        total_alt04=total_alt04,
        total_mismatches=total_mismatches,
        total_ambiguos=total_ambiguos,
    )
