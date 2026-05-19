"""
JSON Schemas para los prompts TDR. Si Ollama soporta JSON schema (>=0.5),
fuerza al modelo a generar output con estructura estricta. Previene:

- cargo vacio en rtm_personal (cumplimos Regla Dura #1)
- listas vacias donde debe haber items
- campos con tipos incorrectos

Pasados a Ollama via extra_body["format"] = SCHEMA en cada llamada
chat.completions.create. Toggle via USE_JSON_SCHEMA=false en .env.
"""
from __future__ import annotations


# ============================================================================
# Schema: rtm_personal — personal clave del TDR
# ============================================================================
# Cargo es obligatorio y minLength=3 (previene strings vacios).
# Lista personal_clave puede estar vacia (TDR sin tabla B.1).

RTM_PERSONAL_SCHEMA: dict = {
    "type": "object",
    "required": ["personal_clave"],
    "properties": {
        "personal_clave": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["cargo"],
                "properties": {
                    "numero_fila": {"type": ["integer", "null"]},
                    "cargo": {"type": "string", "minLength": 3},
                    "profesiones_aceptadas": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 2},
                    },
                    "anos_colegiado": {"type": ["string", "null"]},
                    "experiencia_minima": {
                        "type": ["object", "null"],
                        "properties": {
                            "cantidad": {"type": ["integer", "null"]},
                            "unidad": {"type": ["string", "null"]},
                            "descripcion": {"type": ["string", "null"]},
                            "cargos_similares_validos": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "puntaje_por_experiencia": {"type": ["number", "null"]},
                            "puntaje_maximo": {"type": ["number", "null"]},
                        },
                    },
                    "tipo_obra_valido": {"type": ["string", "null"]},
                    "tiempo_adicional_factores": {"type": ["string", "null"]},
                    "capacitacion": {
                        "type": ["object", "null"],
                        "properties": {
                            "tema": {"type": ["string", "null"]},
                            "tipo": {"type": ["string", "null"]},
                            "duracion_minima_horas": {"type": ["integer", "null"]},
                            "es_factor_evaluacion": {"type": ["boolean", "null"]},
                        },
                    },
                    "pagina": {"type": ["integer", "null"]},
                },
            },
        }
    },
}


# ============================================================================
# Schema: rtm_postor — experiencia del postor (siempre 1 entrada o 0)
# ============================================================================

RTM_POSTOR_SCHEMA: dict = {
    "type": "object",
    "required": ["postor"],
    "properties": {
        "postor": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": ["string", "null"]},
                    "pagina": {"type": ["integer", "null"]},
                    "archivo": {"type": ["string", "null"]},
                    "seccion": {"type": ["string", "null"]},
                    "cita_exacta": {"type": ["string", "null"]},
                    "sector_valido": {"type": ["string", "null"]},
                    "tipo_experiencia_valida": {"type": ["string", "null"]},
                    "otros_factores_postor": {"type": ["string", "null"]},
                    "experiencia_adicional_factores": {"type": ["string", "null"]},
                },
            },
        }
    },
}


# ============================================================================
# Schema: factores_evaluacion — factores con puntajes
# ============================================================================

FACTORES_SCHEMA: dict = {
    "type": "object",
    "required": ["factores_evaluacion"],
    "properties": {
        "factores_evaluacion": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["factor"],
                "properties": {
                    "factor": {"type": "string", "minLength": 3},
                    "aplica_a": {"type": ["string", "null"]},
                    "cargo_personal": {"type": ["string", "null"]},
                    "puntaje_maximo": {"type": ["number", "null"]},
                    "metodologia": {"type": ["string", "null"]},
                    "pagina": {"type": ["integer", "null"]},
                },
            },
        }
    },
}


# ============================================================================
# Schema: capacitaciones (requisitos por cargo)
# ============================================================================

CAPACITACION_SCHEMA: dict = {
    "type": "object",
    "required": ["capacitaciones"],
    "properties": {
        "capacitaciones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cargo": {"type": ["string", "null"]},
                    "tipo": {"type": ["string", "null"]},
                    "duracion_minima_horas": {"type": ["integer", "null"]},
                    "tema": {"type": ["string", "null"]},
                    "pagina": {"type": ["integer", "null"]},
                },
            },
        }
    },
}


# ============================================================================
# Mapa por tipo de bloque (mismas claves que PROMPTS en signals.py)
# ============================================================================

SCHEMAS_POR_BLOCK_TYPE: dict[str, dict] = {
    "rtm_postor":          RTM_POSTOR_SCHEMA,
    "rtm_personal":        RTM_PERSONAL_SCHEMA,
    "factores_evaluacion": FACTORES_SCHEMA,
    "capacitacion":        CAPACITACION_SCHEMA,
}
