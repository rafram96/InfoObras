"""
Orquesta la extracción LLM sobre un ProfessionalBlock.
Paso 2: datos del profesional (cabecera)
Paso 3: lista de experiencias (certificados)
"""
from src.extraction.models import ProfessionalBlock
from src.extraction.ollama_client import call_llm
from src.extraction.prompts import PASO2_PROMPT, PASO3_PROMPT

# Límite de caracteres enviados al LLM por llamada.
# qwen2.5:14b maneja bien ~12k tokens; ~4 chars/token → ~48k chars.
# El texto de un profesional rara vez supera 20k chars.
_MAX_TEXT_CHARS = 40_000


def extract_professional_info(block: ProfessionalBlock) -> dict:
    """
    Paso 2: extrae nombre, DNI, CIP, profesión, cargo del profesional.
    Retorna el dict JSON tal como lo devuelve el LLM.
    """
    texto = block.full_text[:_MAX_TEXT_CHARS]
    prompt = PASO2_PROMPT.format(cargo=block.cargo, texto=texto)
    result = call_llm(prompt)
    # Agrega metadata de origen
    result["_cargo"] = block.cargo
    result["_numero"] = block.numero
    result["_paginas"] = block.page_ranges
    return result


def extract_experiences(block: ProfessionalBlock, professional_name: str) -> dict:
    """
    Paso 3: extrae todos los certificados/constancias de experiencia.
    Retorna el dict JSON tal como lo devuelve el LLM.
    """
    texto = block.full_text[:_MAX_TEXT_CHARS]
    prompt = PASO3_PROMPT.format(nombre=professional_name, texto=texto)
    result = call_llm(prompt)
    return result


def extract_block(block: ProfessionalBlock) -> dict:
    """
    Extrae Paso 2 + Paso 3 para un bloque. Retorna dict combinado.
    """
    info = extract_professional_info(block)
    nombre = info.get("nombre") or block.cargo
    experiences = extract_experiences(block, nombre)

    return {
        "profesional": info,
        "experiencias": experiences.get("experiencias", []),
    }
