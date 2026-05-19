"""
JSON Schemas para forzar al LLM (vía Ollama) a generar JSON con estructura
estricta. Ollama 0.5+ soporta el parametro "format" con un schema completo,
lo cual FUERZA al modelo a producir output que cumple el schema — no es
una sugerencia, es una restriccion a nivel de decoding.

Esto previene:
- Campos requeridos faltantes
- Strings vacios en campos obligatorios (minLength)
- Listas vacias donde debe haber elementos (minItems)
- Tipos incorrectos (string vs int, etc.)

Si Ollama es vieja (<0.5) o el schema rompe, el caller debe atrapar el
error y caer a `format: "json"` plano (degradacion elegante).
"""
from __future__ import annotations


# ============================================================================
# Schema para Paso 2 — extraccion de datos del profesional
# ============================================================================
# Campos obligatorios: nombre. Resto opcional/null.

PASO2_SCHEMA: dict = {
    "type": "object",
    "required": ["nombre"],
    "properties": {
        "nombre": {
            "type": "string",
            "minLength": 2,
            "maxLength": 120,
            "description": "Nombre completo del profesional",
        },
        "dni": {
            "type": ["string", "null"],
            "description": "DNI de 8 digitos o null",
        },
        "tipo_colegio": {
            "type": ["string", "null"],
            "description": "Sigla del colegio profesional (CIP, CAP, CBP, CMP)",
        },
        "registro_colegio": {
            "type": ["string", "null"],
            "description": "Numero de registro 4-6 digitos",
        },
        "fecha_registro": {
            "type": ["string", "null"],
        },
        "profesion": {
            "type": ["string", "null"],
            "description": "Titulo profesional completo",
        },
        "cargo_postulado": {
            "type": ["string", "null"],
        },
    },
}


# ============================================================================
# Schema para Paso 3 — extraccion de experiencias
# ============================================================================
# Lista de experiencias. Cada una requiere proyecto.

PASO3_SCHEMA: dict = {
    "type": "object",
    "required": ["experiencias"],
    "properties": {
        "experiencias": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["proyecto"],
                "properties": {
                    "proyecto": {"type": "string", "minLength": 3},
                    "cargo": {"type": ["string", "null"]},
                    "empresa_emisora": {"type": ["string", "null"]},
                    "ruc": {"type": ["string", "null"]},
                    "fecha_inicio": {"type": ["string", "null"]},
                    "fecha_fin": {"type": ["string", "null"]},
                    "fecha_emision": {"type": ["string", "null"]},
                    "firmante": {"type": ["string", "null"]},
                    "cargo_firmante": {"type": ["string", "null"]},
                    "folio": {"type": ["string", "null"]},
                    "tipo_obra": {"type": ["string", "null"]},
                    "tipo_intervencion": {"type": ["string", "null"]},
                    "tipo_acreditacion": {"type": ["string", "null"]},
                },
            },
        }
    },
}
