"""
Per-fila quality validation + de-cross-contamination (Fase 2.B).

Despues del extractor y del lexico OSCE (Fase 2.C), este modulo:

1. Score per-fila: evalua la calidad de cada fila del rtm_personal
   contra heuristicas universales OSCE-obras (no atadas a un PDF
   especifico). Inyecta el score y los issues en _calidad de cada
   fila para que sean visibles en result.json.

2. De-cross-contamination conservadora: detecta casos OBVIOS de
   cross-row contamination y los limpia:
   - tiempo_adicional_factores con texto identico en >=50% de filas
     -> probable contam, anular en filas donde no es el origen
   - descripciones que mencionan cargos de otras filas
     -> flag con _descripcion_sospechosa

NO toca:
- Cargo, profesiones, cargos_similares (eso lo arreglan C lexico y D
  self-healing en fase posterior)
- Datos donde no hay evidencia clara de contaminacion
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Score per-fila (universal OSCE-obras)
# ============================================================================

# Keywords OSCE — debe aparecer al menos UNA en cualquier cargo valido.
_OSCE_KEYWORDS = (
    "ESPECIALISTA", "JEFE", "GERENTE", "INGENIERO", "RESIDENTE",
    "SUPERVISOR", "COORDINADOR", "DIRECTOR", "RESPONSABLE",
    "INSPECTOR", "ARQUITECTO", "ANALISTA", "AMBIENTALISTA",
    "MAESTRO", "TÉCNICO", "PROFESIONAL", "ASISTENTE",
)

# Patron de OCR garbage en cargos: numeros colgados, chars raros
_OCR_GARBAGE = re.compile(
    r"\d{2,}\s*$"                       # numeros al final
    r"|[^\w\s,.\-áéíóúñÁÉÍÓÚÑ()/]"      # chars no permitidos
)


def score_fila(fila: dict) -> tuple[float, list[str]]:
    """
    Devuelve (score, issues) para una fila del rtm_personal.

    Score: 0.0 (peor) a 10.0 (mejor). Pondera:
    - Cargo presente y no-vacio:                  +3.0
    - Cargo contiene keyword OSCE:                +1.0
    - Cargo SIN OCR garbage:                      +1.0
    - profesiones_aceptadas no vacio:             +1.5
    - cargos_similares_validos con >=3 entries:   +1.0
    - experiencia_minima.cantidad presente:       +1.0
    - tipo_obra_valido como frase completa:       +1.0
    - descripcion presente:                       +0.5

    Maximo: 10.0
    """
    score = 0.0
    issues = []

    # Cargo
    cargo = (fila.get("cargo") or "").strip()
    if not cargo:
        issues.append("cargo_vacio")
    else:
        score += 3.0
        cargo_upper = cargo.upper()
        if any(kw in cargo_upper for kw in _OSCE_KEYWORDS):
            score += 1.0
        else:
            issues.append("cargo_sin_keyword_osce")
        if not _OCR_GARBAGE.search(cargo):
            score += 1.0
        else:
            issues.append("cargo_con_ocr_garbage")

    # Profesiones aceptadas
    profs = fila.get("profesiones_aceptadas") or []
    if profs:
        score += 1.5
    else:
        issues.append("profesiones_vacias")

    # Cargos similares
    exp_min = fila.get("experiencia_minima") or {}
    cargos_sim = exp_min.get("cargos_similares_validos") or []
    if len(cargos_sim) >= 3:
        score += 1.0
    elif len(cargos_sim) > 0:
        score += 0.5
        issues.append(f"cargos_similares_pocos ({len(cargos_sim)})")
    else:
        issues.append("cargos_similares_vacios")

    # experiencia_minima.cantidad
    if exp_min.get("cantidad"):
        score += 1.0
    else:
        issues.append("experiencia_cantidad_vacia")

    # tipo_obra_valido — penalizar si es palabra corta (e.g. "salud" sin frase)
    tipo_obra = (fila.get("tipo_obra_valido") or "").strip()
    if tipo_obra:
        if len(tipo_obra) >= 10:  # "establecimientos de salud" tiene 26
            score += 1.0
        elif len(tipo_obra) > 0:
            score += 0.3
            issues.append(f"tipo_obra_corto: {tipo_obra!r}")
    else:
        issues.append("tipo_obra_vacio")

    # descripcion
    descripcion = (exp_min.get("descripcion") or "").strip()
    if descripcion:
        score += 0.5
    else:
        issues.append("descripcion_vacia")

    return round(score, 2), issues


# ============================================================================
# Detectar y limpiar cross-row contamination conservadoramente
# ============================================================================

def _es_factor_originalmente_de(cargo: str, texto_factor: str) -> bool:
    """
    Heuristica: el texto de un factor pertenece a un cargo si MENCIONA
    el cargo (o palabras clave de su nombre) explicitamente.
    """
    if not cargo or not texto_factor:
        return False
    palabras = [p for p in cargo.upper().split() if len(p) > 4]
    if not palabras:
        return False
    texto_upper = texto_factor.upper()
    return any(p in texto_upper for p in palabras)


def _detectar_cross_contam_tiempo_adicional(
    rtm_personal: list[dict],
) -> tuple[list[dict], dict]:
    """
    Detecta tiempo_adicional_factores duplicado masivamente.

    Estrategia: si >=50% de las filas tienen exactamente el mismo texto
    en este campo, es contam. Mantener solo en filas donde el texto MENCIONA
    explicitamente al cargo de la fila. Anular el resto.

    Returns (rtm_modificado, diag).
    """
    diag = {
        "filas": len(rtm_personal),
        "duplicado_dominante": None,
        "filas_anuladas": [],
    }

    if not rtm_personal:
        return rtm_personal, diag

    # Normalizar textos (eliminar trailing whitespace) y contar
    tiempos = [
        (i, (r.get("tiempo_adicional_factores") or "").strip())
        for i, r in enumerate(rtm_personal)
    ]
    counter = Counter(t for _, t in tiempos if t)

    if not counter:
        return rtm_personal, diag

    most_common_text, count = counter.most_common(1)[0]
    umbral = max(2, len(rtm_personal) // 2)  # >=50% de las filas

    if count < umbral:
        # No hay duplicacion masiva; nada que limpiar
        return rtm_personal, diag

    diag["duplicado_dominante"] = {
        "texto_preview": most_common_text[:100],
        "count": count,
        "umbral": umbral,
    }

    # Anular en filas donde el texto NO menciona al cargo
    # (excepto si es la PRIMERA aparicion — la conservamos como "origen" probable)
    primera_aparicion_anulada = False
    for i, texto in tiempos:
        if texto != most_common_text:
            continue
        cargo = rtm_personal[i].get("cargo") or ""
        if _es_factor_originalmente_de(cargo, most_common_text):
            # Plausiblemente es su factor real — mantener
            continue
        # No menciona al cargo — probable copia. Anular.
        # Pero conservar la PRIMERA copia si nadie es el origen claro
        # (para no perder el dato completamente).
        if not primera_aparicion_anulada:
            primera_aparicion_anulada = True
            # Marcar como sospechoso pero no anular
            rtm_personal[i]["_tiempo_adicional_sospechoso"] = True
            continue
        rtm_personal[i]["_tiempo_adicional_original"] = most_common_text[:200]
        rtm_personal[i]["tiempo_adicional_factores"] = None
        diag["filas_anuladas"].append({"fila": i + 1, "cargo": cargo})

    return rtm_personal, diag


def _detectar_descripcion_cruzada(
    rtm_personal: list[dict],
) -> tuple[list[dict], dict]:
    """
    Detecta descripciones que mencionan cargos de OTRAS filas.

    Estrategia conservadora: solo flagear, no eliminar. El analista decide
    despues si la descripcion es valida o esta contaminada.

    Returns (rtm_modificado, diag).
    """
    diag = {
        "filas_flageadas": [],
    }

    cargos_por_indice: dict[int, str] = {
        i: (r.get("cargo") or "").upper()
        for i, r in enumerate(rtm_personal)
    }

    for i, r in enumerate(rtm_personal):
        exp_min = r.get("experiencia_minima") or {}
        descripcion = (exp_min.get("descripcion") or "").upper()
        if not descripcion:
            continue

        # Buscar palabras clave de OTROS cargos (palabras >=6 chars, distintivas)
        otros_cargos_mencionados = []
        for j, otro_cargo in cargos_por_indice.items():
            if j == i or not otro_cargo:
                continue
            # Palabras distintivas del otro cargo (no las del cargo propio)
            propio = cargos_por_indice[i]
            propias_palabras = set(propio.split())
            otras_palabras = [
                w for w in otro_cargo.split()
                if len(w) >= 7 and w not in propias_palabras
                and w not in ("CONTRATO", "OBRA", "PROYECTO", "PROYECTOS")
            ]
            mencionadas = [w for w in otras_palabras if w in descripcion]
            if mencionadas:
                otros_cargos_mencionados.append({
                    "otra_fila": j + 1,
                    "otro_cargo": rtm_personal[j].get("cargo"),
                    "palabras_compartidas": mencionadas,
                })

        if otros_cargos_mencionados:
            r["_descripcion_sospechosa"] = otros_cargos_mencionados[:3]
            diag["filas_flageadas"].append({
                "fila": i + 1,
                "cargo": r.get("cargo"),
                "n_otros_mencionados": len(otros_cargos_mencionados),
            })

    return rtm_personal, diag


# ============================================================================
# API publica
# ============================================================================

def validar_y_limpiar_rtm(
    rtm_personal: list[dict],
) -> tuple[list[dict], dict]:
    """
    Pipeline completo de Fase 2.B sobre el rtm_personal extraido + corregido:

    1. Calcula score per-fila y los inyecta en _calidad
    2. Detecta y limpia cross-contam masiva en tiempo_adicional_factores
    3. Flagea descripciones que parecen contener contenido de otras filas

    Returns (rtm_validado, diag_completo)
    """
    import copy
    rtm_copia = copy.deepcopy(rtm_personal)

    diag_full = {
        "filas": len(rtm_copia),
        "score_promedio": 0.0,
        "filas_baja_calidad": 0,
        "filas_score_perfecto": 0,
    }

    # 1. Score per-fila
    scores = []
    for r in rtm_copia:
        score, issues = score_fila(r)
        r["_calidad"] = {"score": score, "issues": issues}
        scores.append(score)
        if score < 6.0:
            diag_full["filas_baja_calidad"] += 1
        if score >= 9.5:
            diag_full["filas_score_perfecto"] += 1

    if scores:
        diag_full["score_promedio"] = round(sum(scores) / len(scores), 2)
        diag_full["score_min"] = min(scores)
        diag_full["score_max"] = max(scores)

    # 2. Limpiar cross-contam de tiempo_adicional
    rtm_copia, diag_tiempo = _detectar_cross_contam_tiempo_adicional(rtm_copia)
    diag_full["cross_contam_tiempo_adicional"] = diag_tiempo

    # 3. Flagear descripciones sospechosas
    rtm_copia, diag_desc = _detectar_descripcion_cruzada(rtm_copia)
    diag_full["descripciones_sospechosas"] = diag_desc

    logger.info(
        "[per-fila] %d filas, score prom %.1f, %d baja calidad, "
        "%d tiempo_adicional anulados, %d descripciones flageadas",
        diag_full["filas"],
        diag_full["score_promedio"],
        diag_full["filas_baja_calidad"],
        len(diag_tiempo["filas_anuladas"]),
        len(diag_desc["filas_flageadas"]),
    )

    return rtm_copia, diag_full
