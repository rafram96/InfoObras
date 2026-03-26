"""
Orquesta la extracción LLM sobre un ProfessionalBlock.
Paso 2: datos del profesional (cabecera)
Paso 3: lista de experiencias (certificados)

Incluye validación de schema y normalización de campos.
"""
import re
from src.extraction.models import ProfessionalBlock
from src.extraction.ollama_client import call_llm
from src.extraction.prompts import PASO2_PROMPT, PASO3_PROMPT

_MAX_TEXT_CHARS = 40_000

# Campos esperados en una respuesta válida de Paso 2
_PASO2_CAMPOS = {"nombre", "dni", "tipo_colegio", "registro_colegio", "fecha_registro", "profesion", "cargo_postulado"}

# Campos obligatorios de cada experiencia en Paso 3
_PASO3_CAMPOS = {
    "proyecto", "cargo", "empresa_emisora", "ruc", "cui",
    "fecha_inicio", "fecha_fin", "fecha_emision", "firmante",
    "cargo_firmante", "folio",
}

# Sinónimos de campo que el LLM a veces usa — se normalizan al nombre estándar
_SINONIMOS_EXP: dict[str, str] = {
    "tipo_de_servicio":       "cargo",
    "tipo_servicio":          "cargo",
    "servicio":               "cargo",
    "empleador":              "empresa_emisora",
    "empresa":                "empresa_emisora",
    "consorcio":              "empresa_emisora",
    "representante_legal":    "firmante",
    "firma":                  "firmante",
    "fecha_constancia":       "fecha_emision",
    "fecha_de_constancia":    "fecha_emision",
    "fecha_certificado":      "fecha_emision",
    "fecha_emision_cert":     "fecha_emision",
}

# Regex para partir un periodo tipo "22.05.2017 al 31.12.2019"
_PERIODO_RE = re.compile(
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})\s+al\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def _es_texto_volcado(valor: str) -> bool:
    """Detecta si el LLM devolvió el texto crudo de la página como valor."""
    return isinstance(valor, str) and len(valor) > 200


def _validar_paso2(result: dict) -> bool:
    """
    Retorna True si el resultado tiene la estructura esperada de Paso 2.
    Falla si faltan campos clave o si los valores son textos volcados.

    Nota: no se exige 'cip' porque los Arquitectos tienen CAP en lugar de CIP.
    El único campo obligatorio real es 'nombre'.
    """
    if not isinstance(result, dict):
        return False
    # Solo exige nombre — CIP/CAP puede ser null (Arquitectos, otros colegios)
    nombre = result.get("nombre")
    if not nombre or not isinstance(nombre, str):
        return False
    # El nombre no debe ser larguísimo (señal de que el LLM volcó texto crudo)
    if _es_texto_volcado(nombre):
        return False
    # Las claves no deben ser textos de página ("Página 350") ni entidades HTML ("&#x27;")
    claves_raras = [k for k in result if k.startswith("Página") or k.startswith("&#")]
    if claves_raras:
        return False
    return True


def _validar_paso3(result: dict) -> bool:
    """Retorna True si el resultado tiene la estructura esperada de Paso 3."""
    if not isinstance(result, dict):
        return False
    if "experiencias" not in result:
        return False
    if not isinstance(result["experiencias"], list):
        return False
    return True


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

def _normalizar_experiencia(exp: dict) -> dict:
    """
    Mapea nombres de campo no estándar al schema definido.
    Maneja el caso especial de 'periodo' que contiene inicio y fin juntos.
    """
    normalizada: dict = {}

    for clave, valor in exp.items():
        clave_norm = _SINONIMOS_EXP.get(clave, clave)
        normalizada[clave_norm] = valor

    # Si el LLM devolvió un campo "periodo" con ambas fechas juntas, lo parte
    if "periodo" in normalizada and "fecha_inicio" not in normalizada:
        periodo = str(normalizada.pop("periodo", ""))
        match = _PERIODO_RE.search(periodo)
        if match:
            normalizada["fecha_inicio"] = match.group(1)
            normalizada["fecha_fin"] = match.group(2)
        else:
            normalizada["fecha_inicio"] = periodo
            normalizada["fecha_fin"] = None

    # Rellena campos faltantes con null para mantener schema consistente
    for campo in _PASO3_CAMPOS:
        normalizada.setdefault(campo, None)

    return normalizada


def _normalizar_paso3(result: dict) -> dict:
    """Normaliza todos los campos de todas las experiencias."""
    experiencias = result.get("experiencias", [])
    return {
        "experiencias": [_normalizar_experiencia(e) for e in experiencias]
    }


# ---------------------------------------------------------------------------
# Extracción con retry de validación
# ---------------------------------------------------------------------------

def extract_professional_info(block: ProfessionalBlock) -> dict:
    """
    Paso 2: extrae nombre, DNI, CIP, profesión, cargo del profesional.
    Reintenta si el resultado no pasa la validación de schema.
    """
    texto = block.full_text[:_MAX_TEXT_CHARS]
    prompt = PASO2_PROMPT.format(cargo=block.cargo, texto=texto)

    for intento in range(1, 3):  # máximo 2 intentos de validación
        result = call_llm(prompt)
        if _validar_paso2(result):
            break
        if intento < 2:
            print(f" [schema inválido, reintentando]", end="", flush=True)
    else:
        # Agotó intentos — devuelve lo que tenga con flag de revisión
        result["_needs_review"] = True

    result["_cargo"] = block.cargo
    result["_numero"] = block.numero
    result["_paginas"] = block.page_ranges
    return result


def extract_experiences(block: ProfessionalBlock, professional_name: str) -> dict:
    """
    Paso 3: extrae todos los certificados/constancias de experiencia.
    Normaliza campos y reintenta si el schema es inválido.
    """
    texto = block.full_text[:_MAX_TEXT_CHARS]
    prompt = PASO3_PROMPT.format(nombre=professional_name, texto=texto)

    for intento in range(1, 3):
        result = call_llm(prompt)
        if _validar_paso3(result):
            return _normalizar_paso3(result)
        if intento < 2:
            print(f" [schema inválido exp, reintentando]", end="", flush=True)

    # Schema inválido tras reintentos — retorna vacío con flag
    return {"experiencias": [], "_needs_review": True}


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
        "_needs_review": info.get("_needs_review") or experiences.get("_needs_review", False),
    }
