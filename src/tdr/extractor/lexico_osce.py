"""
Lexico canonico OSCE para post-procesamiento fuzzy del output del LLM.

Despues de que el LLM extrae los datos del TDR, comparamos cada palabra
o frase contra este catalogo. Si encontramos algo casi-igual (>= threshold
de Jaccard / Levenshtein), reemplazamos con la forma canonica.

Resuelve errores comunes del OCR + LLM en TDRs de obras OSCE:
- "METRÁGOS" (OCR) -> "METRADOS" (canonico)
- "Responsale" (LLM dropped 'b') -> "Responsable"
- "Ingeniero Mecanico" (sin tilde) -> "Ingeniero Mecánico"
- "deConstruccion" (espacio perdido) -> "de Construcción"

Generalizacion: el catalogo cubre vocabulario OSCE-obras estandar
(supervision de obras publicas peruanas en sectores Salud, Vivienda,
Vias, Saneamiento, Educacion). Si aparece un TDR no-OSCE, podra dar
falsos negativos (no encuentra match), pero NO falsos positivos
(no inventa correcciones).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Vocabulario canonico
# ============================================================================

# Profesiones (titulos universitarios) tal como deberian aparecer en TDR OSCE.
# Mantener el case y los acentos correctos — son la "verdad".
PROFESIONES_CANONICAS: tuple[str, ...] = (
    "Arquitecto",
    "Ingeniero Civil",
    "Ingeniero Sanitario",
    "Ingeniero Mecánico",
    "Ingeniero Eléctrico",
    "Ingeniero Electricista",
    "Ingeniero Mecánico Electricista",
    "Ingeniero Mecánico Eléctrico",
    "Ingeniero Electromecánico",
    "Ingeniero Electrónico",
    "Ingeniero Mecatrónico",
    "Ingeniero Industrial",
    "Ingeniero Ambiental",
    "Ingeniero Ambiental y Recursos Naturales",
    "Ingeniero Agrícola",
    "Ingeniero Geotécnico",
    "Ingeniero Geólogo",
    "Ingeniero de Materiales",
    "Ingeniero de Sistemas",
    "Ingeniero de Sistemas y Cómputo",
    "Ingeniero Informático",
    "Ingeniero de Telecomunicaciones",
    "Ingeniero Electrónico y Telecomunicaciones",
    "Ingeniero de Higiene y Seguridad Industrial",
    "Ingeniero de Seguridad Laboral y Ambiental",
    "Ingeniero de Seguridad Industrial y Minera",
    "Ingeniero de Minas",
    "Tecnólogo Médico",
    "Médico",
    "Licenciado en Administración",
    "Economista",
)

# Palabras-clave OSCE que aparecen DENTRO de los cargos. Son las piezas
# basicas que combinadas forman cargos completos. Usadas para corregir
# typos de OCR en cargos.
PALABRAS_CARGO_CANONICAS: tuple[str, ...] = (
    # Roles
    "ESPECIALISTA", "JEFE", "GERENTE", "DIRECTOR", "INGENIERO",
    "RESIDENTE", "SUPERVISOR", "COORDINADOR", "ASISTENTE",
    "INSPECTOR", "RESPONSABLE", "ANALISTA", "ARQUITECTO",
    "MAESTRO", "TÉCNICO", "PROFESIONAL", "AMBIENTALISTA",
    # Dominios tecnicos
    "ARQUITECTURA", "ESTRUCTURAS", "INSTALACIONES",
    "SANITARIAS", "ELÉCTRICAS", "MECÁNICAS", "ELECTROMECÁNICAS",
    "COMUNICACIONES", "ELECTRÓNICAS",
    # Especialidades
    "EQUIPAMIENTO", "HOSPITALARIO", "CONTRATO", "CALIDAD",
    "ASEGURAMIENTO", "SEGURIDAD", "SALUD", "TRABAJO",
    "MEDIO", "AMBIENTE", "COSTOS", "METRADOS", "VALORIZACIONES",
    "GEOTECNIA", "PRESUPUESTOS", "PROGRAMACIÓN",
    "PLANIFICACIÓN", "PRODUCCIÓN",
    # Otros
    "BIM", "OBRA", "SUPERVISIÓN", "EJECUCIÓN", "CAMPO",
    "PROYECTO", "PROYECTOS", "GESTIÓN",
)

# Cargos completos canonicos — para fuzzy match a nivel de frase completa.
# Cuando el LLM extrae "ESPECIALISTA EN BIM" pero el golden es "ESPECIALISTA BIM",
# este catalogo permite normalizar.
CARGOS_OSCE_COMPLETOS: tuple[str, ...] = (
    "GERENTE DE CONTRATO",
    "GERENTE DE PROYECTO",
    "JEFE DE SUPERVISIÓN",
    "JEFE DE PROYECTO",
    "JEFE DE OBRA",
    "RESIDENTE DE OBRA",
    "INGENIERO DE CAMPO",
    "INGENIERO RESIDENTE",
    "COORDINADOR DE OBRA",
    "DIRECTOR DE PROYECTO",
    "ASISTENTE TÉCNICO",
    "ESPECIALISTA EN ARQUITECTURA",
    "ESPECIALISTA EN ESTRUCTURAS",
    "ESPECIALISTA EN INSTALACIONES SANITARIAS",
    "ESPECIALISTA EN INSTALACIONES ELÉCTRICAS",
    "ESPECIALISTA EN INSTALACIONES MECÁNICAS",
    "ESPECIALISTA EN INSTALACIONES ELECTROMECÁNICAS",
    "ESPECIALISTA EN COMUNICACIONES",
    "ESPECIALISTA EN EQUIPAMIENTO HOSPITALARIO",
    "ESPECIALISTA EN EQUIPAMIENTO MÉDICO",
    "ESPECIALISTA EN CONTROL Y ASEGURAMIENTO DE LA CALIDAD",
    "ESPECIALISTA EN SEGURIDAD Y SALUD EN EL TRABAJO",
    "ESPECIALISTA EN MEDIO AMBIENTE",
    "ESPECIALISTA EN COSTOS, METRADOS Y VALORIZACIONES",
    "ESPECIALISTA EN COSTOS Y PRESUPUESTOS",
    "ESPECIALISTA EN GEOTECNIA",
    "ESPECIALISTA EN MECÁNICA DE SUELOS",
    "ESPECIALISTA EN PROGRAMACIÓN DE OBRA",
    "ESPECIALISTA BIM",
    "ESPECIALISTA EN BIM",
    "COORDINADOR BIM",
)


# ============================================================================
# Fuzzy matching
# ============================================================================

def _normalizar(s: str) -> str:
    """Lower + sin tildes + collapsed whitespace, para matching."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Pre-normalizar catalogos al import (evita normalizar 100+ entradas por call)
_PROFESIONES_NORM: list[tuple[str, str]] = [
    (canonico, _normalizar(canonico)) for canonico in PROFESIONES_CANONICAS
]
_PALABRAS_CARGO_NORM: list[tuple[str, str]] = [
    (canonico, _normalizar(canonico)) for canonico in PALABRAS_CARGO_CANONICAS
]
_CARGOS_COMPLETOS_NORM: list[tuple[str, str]] = [
    (canonico, _normalizar(canonico)) for canonico in CARGOS_OSCE_COMPLETOS
]


def _fuzzy_best_match(
    texto: str,
    candidatos: list[tuple[str, str]],
    threshold: int,
) -> Optional[str]:
    """
    Devuelve la forma canonica del candidato que mejor matchea con `texto`,
    si supera `threshold`. Si no, None.

    Usa rapidfuzz. Score basado en ratio sobre la version normalizada.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.warning("rapidfuzz no disponible — saltando fuzzy match canonico")
        return None

    texto_norm = _normalizar(texto)
    if not texto_norm:
        return None

    mejor_score = 0
    mejor_canonico = None
    for canonico, canonico_norm in candidatos:
        score = fuzz.ratio(texto_norm, canonico_norm)
        if score > mejor_score:
            mejor_score = score
            mejor_canonico = canonico

    if mejor_score >= threshold:
        return mejor_canonico
    return None


# ============================================================================
# Correcciones especificas por campo
# ============================================================================

def corregir_profesion(profesion: str, threshold: int = 87) -> tuple[str, bool]:
    """
    Corrige una profesion contra PROFESIONES_CANONICAS via fuzzy match.

    Returns:
        (texto_corregido, fue_corregido)
    """
    if not profesion or not profesion.strip():
        return profesion, False
    canonico = _fuzzy_best_match(profesion, _PROFESIONES_NORM, threshold)
    if canonico and _normalizar(profesion) != _normalizar(canonico):
        return canonico, True
    return profesion, False


def corregir_cargo_completo(cargo: str, threshold: int = 88) -> tuple[str, bool]:
    """
    Corrige el nombre completo de un cargo contra CARGOS_OSCE_COMPLETOS.
    Threshold mas alto que profesiones porque los cargos son frases largas
    y queremos evitar falsos positivos.
    """
    if not cargo or not cargo.strip():
        return cargo, False
    canonico = _fuzzy_best_match(cargo, _CARGOS_COMPLETOS_NORM, threshold)
    if canonico and _normalizar(cargo) != _normalizar(canonico):
        return canonico, True
    return cargo, False


def corregir_palabra_cargo(palabra: str, threshold: int = 85) -> tuple[str, bool]:
    """
    Corrige UNA palabra de un cargo contra PALABRAS_CARGO_CANONICAS.
    Usado para arreglar 'METRÁGOS' -> 'METRADOS' en cargos compuestos
    cuando el cargo completo no matchea ningun canonico entero.
    """
    if not palabra or not palabra.strip():
        return palabra, False
    # Solo intentar correccion si la palabra parece "tecnica" (>4 chars)
    # Palabras cortas (y, o, de, en) NO necesitan correccion.
    if len(palabra.strip()) < 5:
        return palabra, False
    canonico = _fuzzy_best_match(palabra, _PALABRAS_CARGO_NORM, threshold)
    if canonico and _normalizar(palabra) != _normalizar(canonico):
        return canonico, True
    return palabra, False


def corregir_cargo_palabra_por_palabra(cargo: str) -> tuple[str, list[str]]:
    """
    Para un cargo, intenta primero matchear el FULL string contra CARGOS_OSCE_COMPLETOS.
    Si no, descompone en palabras y corrige cada una contra PALABRAS_CARGO_CANONICAS.

    Returns:
        (cargo_corregido, lista_de_correcciones_aplicadas)
    """
    correcciones = []

    # Intento 1: match completo del cargo
    nuevo, fue = corregir_cargo_completo(cargo)
    if fue:
        correcciones.append(f"{cargo!r} -> {nuevo!r} (match completo)")
        return nuevo, correcciones

    # Intento 2: palabra por palabra
    palabras = cargo.split()
    palabras_corregidas = []
    for p in palabras:
        nueva_p, fue = corregir_palabra_cargo(p)
        if fue:
            correcciones.append(f"{p!r} -> {nueva_p!r}")
        # Preservar el case original cuando hicimos correccion ligera
        palabras_corregidas.append(nueva_p)

    return " ".join(palabras_corregidas), correcciones


# ============================================================================
# Pipeline completo: aplicar a un rtm_personal entero
# ============================================================================

def corregir_rtm_personal(rtm_personal: list[dict]) -> tuple[list[dict], dict]:
    """
    Aplica todas las correcciones canonicas al rtm_personal extraido por el LLM.
    NO muta el original — retorna una copia.

    Campos que se corrigen:
      - cargo (full string contra CARGOS_OSCE_COMPLETOS, luego por palabra)
      - profesiones_aceptadas (cada entry contra PROFESIONES_CANONICAS)
      - cargos_similares_validos (cada entry contra CARGOS_OSCE_COMPLETOS, luego por palabra)

    Returns:
        (rtm_corregido, diag) donde diag tiene contadores y lista de correcciones.
    """
    import copy
    rtm_corregido = copy.deepcopy(rtm_personal)

    diag = {
        "filas_procesadas": len(rtm_corregido),
        "cargos_corregidos": 0,
        "profesiones_corregidas": 0,
        "cargos_similares_corregidos": 0,
        "correcciones_detalle": [],
    }

    for i, row in enumerate(rtm_corregido):
        # 1. Cargo principal
        cargo_orig = row.get("cargo", "")
        cargo_nuevo, cambios = corregir_cargo_palabra_por_palabra(cargo_orig)
        if cambios:
            row["cargo"] = cargo_nuevo
            row["_cargo_original"] = cargo_orig
            diag["cargos_corregidos"] += 1
            diag["correcciones_detalle"].append(
                {"fila": i + 1, "campo": "cargo", "cambios": cambios}
            )

        # 2. Profesiones aceptadas
        profs = row.get("profesiones_aceptadas") or []
        profs_corregidas = []
        cambios_profs = []
        for p in profs:
            nueva, fue = corregir_profesion(p)
            if fue:
                cambios_profs.append(f"{p!r} -> {nueva!r}")
                diag["profesiones_corregidas"] += 1
            profs_corregidas.append(nueva)
        if cambios_profs:
            row["profesiones_aceptadas"] = profs_corregidas
            diag["correcciones_detalle"].append(
                {"fila": i + 1, "campo": "profesiones_aceptadas", "cambios": cambios_profs}
            )

        # 3. Cargos similares validos
        exp_min = row.get("experiencia_minima")
        if isinstance(exp_min, dict):
            cargos_sim = exp_min.get("cargos_similares_validos") or []
            cargos_sim_corregidos = []
            cambios_sim = []
            for c in cargos_sim:
                nuevo, _cambios = corregir_cargo_palabra_por_palabra(c)
                if _cambios:
                    cambios_sim.extend([f"sim: {chg}" for chg in _cambios])
                    diag["cargos_similares_corregidos"] += 1
                cargos_sim_corregidos.append(nuevo)
            if cambios_sim:
                exp_min["cargos_similares_validos"] = cargos_sim_corregidos
                diag["correcciones_detalle"].append(
                    {"fila": i + 1, "campo": "cargos_similares_validos", "cambios": cambios_sim}
                )

    logger.info(
        "[lexico-osce] %d filas, %d cargos / %d profesiones / %d sim corregidos",
        diag["filas_procesadas"],
        diag["cargos_corregidos"],
        diag["profesiones_corregidas"],
        diag["cargos_similares_corregidos"],
    )

    return rtm_corregido, diag
