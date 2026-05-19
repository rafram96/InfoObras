"""
Self-healing retry para filas con extraccion incompleta (Fase 3.D).

Detecta filas del rtm_personal donde el extractor original dejo listas
muy cortas (sintoma de "el LLM resumio en vez de extraer todo") y las
re-extrae con una llamada LLM FOCUSED solo en esa fila.

La fila re-extraida se mergea con la original: para cada campo de lista
(profesiones_aceptadas, cargos_similares_validos), se queda con la version
MAS COMPLETA. Si la nueva tiene mas elementos, reemplaza; si no, conserva.

Esto ataca el bug observado en runs reales:
- Fila 13: cargos_similares = ["ambientalista"] solo (golden tiene 8)
- Fila 12: profesiones = 4 (golden tiene 6, faltan "Ingeniero de Minas",
  "Ingeniero Civil")
- Fila 17: profesiones = 2 (golden tiene 4, faltan "Ingeniero Electricista",
  "Ingeniero Mecánico Electricista")
- Fila 15: profesion faltante "Ingeniero Geólogo"

Cuesta 1 llamada LLM extra por fila incompleta (~4-8s con keep_alive).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

from openai import OpenAI

from src.tdr.config.settings import (
    QWEN_OLLAMA_BASE_URL, QWEN_OLLAMA_API_KEY,
    QWEN_MODEL, QWEN_MAX_TOKENS, QWEN_TIMEOUT, QWEN_NUM_CTX,
    OLLAMA_SEED,
)

logger = logging.getLogger(__name__)

# Toggle global. Si rompe en algun caso, USE_SELF_HEALING=false en .env.
_USE_SELF_HEALING = os.getenv("USE_SELF_HEALING", "true").lower() == "true"

# Limite de re-extracciones por TDR (evita explosion de costo LLM si
# muchisimas filas son sospechosas).
_MAX_FILAS_REEXTRAIDAS = int(os.getenv("SELF_HEALING_MAX_FILAS", "10"))


# ============================================================================
# Detector de filas incompletas (heuristicas universales OSCE-obras)
# ============================================================================

def _razones_incompleta(fila: dict) -> list[str]:
    """
    Devuelve lista de razones por las que esta fila parece incompleta.
    Vacia => la fila se ve bien, no necesita re-extraccion.
    """
    razones = []

    # 1. profesiones_aceptadas: TDRs OSCE casi siempre tienen >=2 profesiones
    # validas por cargo. 0 o 1 es sospechoso.
    profs = fila.get("profesiones_aceptadas") or []
    if len(profs) == 0:
        razones.append("profesiones_aceptadas vacia")
    elif len(profs) == 1:
        razones.append("profesiones_aceptadas con solo 1 entrada")

    # 2. cargos_similares_validos: B.2 de OSCE tipicamente lista 3-10 cargos
    # similares por fila. <=2 es sospechoso.
    exp_min = fila.get("experiencia_minima") or {}
    cargos_sim = exp_min.get("cargos_similares_validos") or []
    if len(cargos_sim) == 0:
        razones.append("cargos_similares_validos vacio")
    elif len(cargos_sim) <= 2:
        razones.append(f"cargos_similares_validos con solo {len(cargos_sim)} entrada(s)")

    # 3. Strings pegados en cargos_similares (ej: "supervisor coordinador"
    # como UN string en vez de dos)
    for c in cargos_sim:
        if not isinstance(c, str):
            continue
        # Heuristica: una entrada >40 chars con varias palabras tipo "rol"
        # podria ser dos cargos pegados. Tambien si tiene >1 keyword OSCE.
        keywords = ("ESPECIALISTA", "JEFE", "GERENTE", "INGENIERO", "RESIDENTE",
                    "SUPERVISOR", "COORDINADOR", "DIRECTOR", "RESPONSABLE")
        keyword_count = sum(1 for kw in keywords if kw in c.upper())
        if keyword_count >= 2:
            razones.append(f"cargo_sim posiblemente pegado: {c!r}")
            break  # un caso es suficiente

    return razones


# ============================================================================
# Cliente LLM focused
# ============================================================================

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=QWEN_OLLAMA_BASE_URL,
            api_key=QWEN_OLLAMA_API_KEY,
            timeout=QWEN_TIMEOUT,
        )
    return _client


_PROMPT_REEXTRAER = """Eres un extractor especializado de TDRs OSCE peruanos (obras publicas).

Tu unica tarea: re-extraer COMPLETAMENTE los campos profesiones_aceptadas
y cargos_similares_validos para la fila #{numero_fila} cuyo cargo es:

    {cargo_referencia}

La extraccion anterior quedo INCOMPLETA. Razones detectadas:
{razones_str}

REGLAS DURAS:
1. Busca en el texto la fila/seccion correspondiente al cargo
   "{cargo_referencia}" (puede aparecer en tablas B.1 y/o B.2).
2. Extrae TODAS las profesiones (titulos universitarios) de la columna
   FORMACION ACADEMICA de esa fila. Ejemplos: "Ingeniero Civil",
   "Arquitecto", "Ingeniero Sanitario", "Médico", "Tecnólogo Médico",
   "Ingeniero Electromecánico". Si el texto lista 6 profesiones, devuelve
   las 6. NO resumas.
3. Extrae TODOS los cargos similares (puestos) de la columna TRABAJOS O
   PRESTACIONES (B.2). Ejemplos: "Especialista en X", "Jefe de Y",
   "Coordinador de Z". Si el texto enumera 8 cargos, devuelve los 8.
   NO resumas, no agrupes, no inventes.
4. NO mezcles datos de OTRAS filas — solo lo que pertenece al cargo
   "{cargo_referencia}".
5. NO inventes profesiones o cargos. Si el texto no los lista, devuelve
   lista vacia. Mejor vacio que inventado.

Texto del TDR completo (busca la fila del cargo "{cargo_referencia}"):

{texto}

Responde SOLO con este JSON estricto, sin texto antes ni despues:

{{
  "cargo": "{cargo_referencia}",
  "profesiones_aceptadas": [...],
  "cargos_similares_validos": [...]
}}
"""


# JSON schema para forzar estructura
_SCHEMA_REEXTRACCION = {
    "type": "object",
    "required": ["cargo", "profesiones_aceptadas", "cargos_similares_validos"],
    "properties": {
        "cargo": {"type": "string"},
        "profesiones_aceptadas": {
            "type": "array",
            "items": {"type": "string"},
        },
        "cargos_similares_validos": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def _llm_reextraer_fila(
    full_text: str,
    numero_fila: int,
    cargo_referencia: str,
    razones: list[str],
) -> Optional[dict]:
    """
    Llama al LLM con prompt focused para re-extraer solo esta fila.
    Returns dict con cargo, profesiones_aceptadas, cargos_similares_validos
    o None si falla.
    """
    razones_str = "\n".join(f"- {r}" for r in razones) or "- (sin detalle)"
    prompt = _PROMPT_REEXTRAER.format(
        numero_fila=numero_fila,
        cargo_referencia=cargo_referencia,
        razones_str=razones_str,
        texto=full_text[:60_000],  # cap para no exceder num_ctx
    )

    use_schema = os.getenv("USE_JSON_SCHEMA", "true").lower() == "true"
    extra_body: dict = {
        "keep_alive": "10m",
        "options": {
            "num_gpu": 99,
            "num_ctx": QWEN_NUM_CTX,
            "seed": OLLAMA_SEED,
        },
    }
    if use_schema:
        extra_body["format"] = _SCHEMA_REEXTRACCION

    try:
        client = _get_client()
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=QWEN_MAX_TOKENS,
            extra_body=extra_body,
        )
        elapsed = time.perf_counter() - t0
        logger.info(
            "[self-healing] Re-extraccion fila %d (%s) en %.1fs",
            numero_fila, cargo_referencia[:40], elapsed,
        )
    except Exception as e:
        logger.warning("[self-healing] LLM fallo: %s", e)
        return None

    raw = response.choices[0].message.content.strip()
    # Limpiar bloques markdown ```json ... ``` por si los pone
    m = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(
            "[self-healing] JSON invalido para fila %d: %s\nRaw: %s",
            numero_fila, e, raw[:300],
        )
        return None


# ============================================================================
# Merge inteligente: quedarse con la version mas completa
# ============================================================================

def _es_lista_mas_completa(nueva: list, actual: list) -> bool:
    """
    True si la lista 'nueva' tiene MAS contenido util que 'actual'.

    Criterio: mas entries non-vacias. Empate por cantidad: mas total chars.
    """
    if not nueva:
        return False
    actual_non_vacios = [x for x in actual if x and str(x).strip()]
    nuevos_non_vacios = [x for x in nueva if x and str(x).strip()]
    if len(nuevos_non_vacios) > len(actual_non_vacios):
        return True
    if len(nuevos_non_vacios) == len(actual_non_vacios):
        # Empate: comparar por chars total (mas contenido = mejor)
        chars_actual = sum(len(str(x)) for x in actual_non_vacios)
        chars_nuevos = sum(len(str(x)) for x in nuevos_non_vacios)
        return chars_nuevos > chars_actual
    return False


def _mergear_fila(
    fila_actual: dict,
    fila_nueva: dict,
) -> tuple[dict, list[str]]:
    """
    Combina fila_actual con fila_nueva, quedandose con los campos mas
    completos de cada uno.

    Returns (fila_combinada, lista_de_campos_actualizados).
    """
    campos_actualizados = []

    profs_actual = fila_actual.get("profesiones_aceptadas") or []
    profs_nuevas = fila_nueva.get("profesiones_aceptadas") or []
    if _es_lista_mas_completa(profs_nuevas, profs_actual):
        fila_actual["_profesiones_originales"] = profs_actual
        fila_actual["profesiones_aceptadas"] = profs_nuevas
        campos_actualizados.append(
            f"profesiones_aceptadas: {len(profs_actual)} -> {len(profs_nuevas)}"
        )

    exp_actual = fila_actual.get("experiencia_minima") or {}
    cargos_sim_actual = exp_actual.get("cargos_similares_validos") or []
    cargos_sim_nuevos = fila_nueva.get("cargos_similares_validos") or []
    if _es_lista_mas_completa(cargos_sim_nuevos, cargos_sim_actual):
        if not isinstance(exp_actual, dict):
            exp_actual = {}
        exp_actual["_cargos_similares_originales"] = cargos_sim_actual
        exp_actual["cargos_similares_validos"] = cargos_sim_nuevos
        fila_actual["experiencia_minima"] = exp_actual
        campos_actualizados.append(
            f"cargos_similares_validos: {len(cargos_sim_actual)} -> {len(cargos_sim_nuevos)}"
        )

    return fila_actual, campos_actualizados


# ============================================================================
# API publica
# ============================================================================

def aplicar_self_healing(
    rtm_personal: list[dict],
    full_text: str,
) -> tuple[list[dict], dict]:
    """
    Aplica self-healing retry sobre rtm_personal:

    1. Detecta filas con campos sospechosamente cortos (heuristicas universales).
    2. Para cada fila marcada, llama al LLM con prompt focused solo en esa fila.
    3. Mergea la respuesta del LLM con la fila actual, quedandose con la
       version mas completa por campo.

    Args:
        rtm_personal: lista de filas tal como vienen post-lexico+per_fila.
        full_text: texto OCR completo del TDR (para re-prompting).

    Returns:
        (rtm_curado, diagnostico_completo)
    """
    import copy
    rtm_curado = copy.deepcopy(rtm_personal)

    diag: dict = {
        "habilitado": _USE_SELF_HEALING,
        "filas_evaluadas": len(rtm_curado),
        "filas_detectadas_incompletas": 0,
        "filas_reextraidas": 0,
        "filas_mejoradas": 0,
        "filas_sin_mejora": 0,
        "filas_llm_fallidas": 0,
        "max_filas_limit": _MAX_FILAS_REEXTRAIDAS,
        "detalle": [],
    }

    if not _USE_SELF_HEALING:
        diag["motivo_skip"] = "USE_SELF_HEALING=false en env"
        return rtm_curado, diag

    if not rtm_curado:
        return rtm_curado, diag

    # 1. Detectar filas incompletas
    candidatas: list[tuple[int, list[str]]] = []  # (idx, razones)
    for i, fila in enumerate(rtm_curado):
        razones = _razones_incompleta(fila)
        if razones:
            candidatas.append((i, razones))

    diag["filas_detectadas_incompletas"] = len(candidatas)

    if not candidatas:
        return rtm_curado, diag

    # Cap por env var (evita explosion si extraccion original fallo masivo)
    if len(candidatas) > _MAX_FILAS_REEXTRAIDAS:
        logger.warning(
            "[self-healing] %d filas incompletas exceden limite %d — "
            "procesando solo las primeras %d",
            len(candidatas), _MAX_FILAS_REEXTRAIDAS, _MAX_FILAS_REEXTRAIDAS,
        )
        diag["candidatas_truncadas"] = len(candidatas) - _MAX_FILAS_REEXTRAIDAS
        candidatas = candidatas[:_MAX_FILAS_REEXTRAIDAS]

    # 2. Re-extraer cada candidata
    for idx, razones in candidatas:
        fila = rtm_curado[idx]
        cargo_ref = fila.get("cargo") or f"(fila #{idx + 1} sin cargo)"
        numero_fila = fila.get("numero_fila") or (idx + 1)

        logger.info(
            "[self-healing] Re-extrayendo fila %d (cargo=%r) por: %s",
            numero_fila, cargo_ref, razones,
        )
        diag["filas_reextraidas"] += 1

        fila_nueva = _llm_reextraer_fila(
            full_text=full_text,
            numero_fila=numero_fila,
            cargo_referencia=cargo_ref,
            razones=razones,
        )
        if fila_nueva is None:
            diag["filas_llm_fallidas"] += 1
            diag["detalle"].append({
                "fila": idx + 1,
                "cargo": cargo_ref,
                "razones": razones,
                "resultado": "llm_fallo",
            })
            continue

        # 3. Mergear
        rtm_curado[idx], campos = _mergear_fila(fila, fila_nueva)
        if campos:
            diag["filas_mejoradas"] += 1
            rtm_curado[idx]["_self_healing_aplicado"] = {
                "razones": razones,
                "campos_actualizados": campos,
            }
            diag["detalle"].append({
                "fila": idx + 1,
                "cargo": cargo_ref,
                "razones": razones,
                "resultado": "mejorado",
                "campos": campos,
            })
        else:
            diag["filas_sin_mejora"] += 1
            diag["detalle"].append({
                "fila": idx + 1,
                "cargo": cargo_ref,
                "razones": razones,
                "resultado": "sin_mejora",
            })

    logger.info(
        "[self-healing] %d filas evaluadas, %d incompletas, %d reextraidas, "
        "%d mejoradas, %d sin cambio, %d fallaron LLM",
        diag["filas_evaluadas"],
        diag["filas_detectadas_incompletas"],
        diag["filas_reextraidas"],
        diag["filas_mejoradas"],
        diag["filas_sin_mejora"],
        diag["filas_llm_fallidas"],
    )

    return rtm_curado, diag
