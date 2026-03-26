"""
Orquesta la extracción LLM sobre un ProfessionalBlock.
Paso 2: datos del profesional (cabecera)
Paso 3: lista de experiencias (certificados)

Incluye validación de schema, normalización de campos y filtro
de páginas irrelevantes (contratos, resoluciones, SEACE).
"""
import re
from src.extraction.models import ProfessionalBlock
from src.extraction.ollama_client import call_llm
from src.extraction.prompts import PASO2_PROMPT, PASO3_PROMPT

_MAX_TEXT_CHARS = 40_000

# ---------------------------------------------------------------------------
# Filtro de páginas irrelevantes (Opción C)
# ---------------------------------------------------------------------------
# Algunos profesionales (e.g. Coordinadores BIM) tienen bloques con 20+
# páginas de contratos de obra, resoluciones administrativas y páginas SEACE
# mezcladas con sus certificados reales.  El LLM de 14B no puede ignorar
# tanto ruido y falla el schema.  Este filtro descarta esas páginas ANTES
# de enviar el texto al LLM.

# Patrones que identifican páginas de contrato / legal / administrativo
_RE_EXCLUIR = re.compile(
    r"CL[ÁA]USULA"
    r"|CONTRATO\s+N[°º\.]"
    r"|PENALIDAD"
    r"|SE\s+RESUELVE"
    r"|VALORIZACI[ÓO]N"
    r"|Ley\s+(?:N.\s*30225|de\s+Contrataciones)"
    r"|CONSIDERANDO:"
    r"|VISTO:"
    r"|El\s+Contratista\s+(?:deber[áa]|est[áa]\s+obligado|tiene\s+la\s+obligaci[óo]n)"
    r"|LA\s+ENTIDAD\s+(?:se\s+obliga|puede\s+solicitar|no\s+asume)"
    r"|RECEPCI[ÓO]N\s+DE\s+LA\s+OBRA"
    r"|LIQUIDACI[ÓO]N\s+(?:FINAL|DEL\s+CONTRATO|DE\s+OBRA)"
    r"|PROGRAMA\s+DE\s+TRABAJOS"
    r"|Objeto\s+de\s+Contrataci[óo]n"
    r"|Bases\s+Integradas"
    r"|Adjudicaci[óo]n\s+Simplificada",
    re.IGNORECASE,
)

# Patrones que identifican páginas útiles (certificados, ANEXO 16, etc.)
_RE_INCLUIR = re.compile(
    r"CERTIFICA"
    r"|CONSTANCIA"
    r"|ha\s+prestado\s+servicios"
    r"|ANEXO\s+N[°º]"
    r"|identificado\s+con\s+documento"
    r"|desempe[ñn][áa]ndose\s+como"
    r"|Calificaciones\s+y\s+Experiencia"
    r"|Formaci[óo]n\s+acad[ée]mica",
    re.IGNORECASE,
)


def _filtrar_paginas(texto_bloque: str) -> str:
    """
    Filtra páginas irrelevantes (contratos, resoluciones, SEACE)
    de un bloque de texto OCR.

    Lógica por página:
      - Páginas cortas (<200 chars) → conservar (separadores, bajo costo)
      - Si tiene marcadores de contenido útil → conservar siempre
      - Si tiene marcadores de contrato/legal sin marcadores útiles → descartar
      - Páginas ambiguas (sin ningún marcador) → conservar (precaución)

    Si el filtro elimina todo, retorna el texto original (safety).
    """
    segmentos = re.split(r"(?=\[Página\s+\d+\])", texto_bloque)

    filtradas: list[str] = []
    excluidas = 0

    for seg in segmentos:
        seg = seg.strip()
        if not seg:
            continue

        # Páginas muy cortas son separadores — conservar sin costo
        if len(seg) < 200:
            filtradas.append(seg)
            continue

        tiene_incluir = bool(_RE_INCLUIR.search(seg))
        tiene_excluir = bool(_RE_EXCLUIR.search(seg))

        if tiene_incluir:
            # Contenido útil confirmado → conservar siempre
            filtradas.append(seg)
        elif tiene_excluir:
            # Contrato/legal sin contenido útil → descartar
            excluidas += 1
        else:
            # Ambigua → conservar por precaución
            filtradas.append(seg)

    if excluidas > 0:
        print(f" [filtro: -{excluidas} págs]", end="", flush=True)

    resultado = "\n\n".join(filtradas)

    # Safety: si el filtro eliminó todo, devolver el original
    if len(resultado.strip()) < 100 and len(texto_bloque.strip()) >= 100:
        return texto_bloque

    return resultado

# Campos esperados en una respuesta válida de Paso 2
_PASO2_CAMPOS = {"nombre", "dni", "tipo_colegio", "registro_colegio", "fecha_registro", "profesion", "cargo_postulado"}

# Campos obligatorios de cada experiencia en Paso 3
_PASO3_CAMPOS = {
    "proyecto", "cargo", "empresa_emisora", "ruc",
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

def _texto_paso2(block: ProfessionalBlock) -> str:
    """
    Selecciona el texto más útil para extraer datos del profesional (Paso 2).

    Prioridad:
      1. Bloque 1 (índice 1) = ANEXO 16 — siempre tiene "Yo NOMBRE identificado..."
         en OCR limpio (conf ~0.97) y también incluye el registro del colegio.
      2. Bloque 0 (índice 0) = credenciales — diplomas, más ruidoso, como fallback.

    Se aplica filtro de páginas para eliminar contratos/resoluciones que el
    segmentador haya incluido erróneamente en el bloque.
    """
    if len(block.block_texts) >= 2:
        return _filtrar_paginas(block.block_texts[1])[:_MAX_TEXT_CHARS]
    return _filtrar_paginas(block.block_texts[0])[:_MAX_TEXT_CHARS]


def _texto_paso3(block: ProfessionalBlock) -> str:
    """
    Selecciona el texto más útil para extraer experiencias (Paso 3).

    Prioridad:
      1. Bloque 2 (índice 2) = constancias individuales — certificados emitidos
         por cada empresa, OCR limpio (conf ~0.97-0.99).
      2. Bloque 1 (índice 1) = ANEXO 16 — tiene tabla resumen de experiencias,
         útil cuando no hay bloque 2 separado.

    Se aplica filtro de páginas para eliminar contratos/resoluciones.
    """
    if len(block.block_texts) >= 3:
        return _filtrar_paginas(block.block_texts[2])[:_MAX_TEXT_CHARS]
    if len(block.block_texts) >= 2:
        return _filtrar_paginas(block.block_texts[1])[:_MAX_TEXT_CHARS]
    return _filtrar_paginas(block.block_texts[0])[:_MAX_TEXT_CHARS]


def extract_professional_info(block: ProfessionalBlock) -> dict:
    """
    Paso 2: extrae nombre, DNI, registro colegio, profesión, cargo del profesional.
    Usa el bloque 1 (ANEXO 16) como fuente primaria — es el más limpio.
    Reintenta si el resultado no pasa la validación de schema.
    Si bloque 1 falla → fallback a bloque 0 (credenciales: diplomas + CIP).
    """
    texto = _texto_paso2(block)
    prompt = PASO2_PROMPT.format(cargo=block.cargo, texto=texto)

    for intento in range(1, 3):  # máximo 2 intentos de validación
        result = call_llm(prompt)
        if _validar_paso2(result):
            break
        if intento < 2:
            print(f" [schema inválido, reintentando]", end="", flush=True)
    else:
        # Bloque 1 agotó intentos → fallback a bloque 0 (credenciales)
        if len(block.block_texts) >= 2:
            texto_fb = _filtrar_paginas(block.block_texts[0])[:_MAX_TEXT_CHARS]
            print(f" [fallback bloque 0]", end="", flush=True)
            prompt_fb = PASO2_PROMPT.format(cargo=block.cargo, texto=texto_fb)
            result_fb = call_llm(prompt_fb)
            if _validar_paso2(result_fb):
                result = result_fb
            else:
                result["_needs_review"] = True
        else:
            result["_needs_review"] = True

    # Problema 1: si registro_colegio tiene 7+ dígitos, es probablemente un CUI
    # (los registros CIP/CAP tienen 4-6 dígitos) → descarta y marca para revisión
    registro = result.get("registro_colegio")
    if isinstance(registro, str):
        solo_digitos = re.sub(r"\D", "", registro)
        if len(solo_digitos) >= 7:
            result["_registro_sospechoso"] = registro
            result["registro_colegio"] = None
            result["_needs_review"] = True

    result["_cargo"] = block.cargo
    result["_numero"] = block.numero
    result["_paginas"] = block.page_ranges
    return result


def _extraer_experiencias_de_texto(texto: str, professional_name: str) -> dict | None:
    """
    Llama al LLM con el texto dado y retorna el resultado normalizado,
    o None si el schema es inválido tras los reintentos.
    """
    prompt = PASO3_PROMPT.format(nombre=professional_name, texto=texto)
    for intento in range(1, 3):
        result = call_llm(prompt)
        if _validar_paso3(result):
            return _normalizar_paso3(result)
        if intento < 2:
            print(f" [schema inválido exp, reintentando]", end="", flush=True)
    return None


def extract_experiences(block: ProfessionalBlock, professional_name: str) -> dict:
    """
    Paso 3: extrae todos los certificados/constancias de experiencia.
    Usa el bloque 2 (constancias individuales) como fuente primaria.
    Problema 3: si bloque 2 devuelve lista vacía, reintenta con bloque 1 (ANEXO 16).
    Normaliza campos y reintenta si el schema es inválido.
    """
    texto_principal = _texto_paso3(block)
    resultado = _extraer_experiencias_de_texto(texto_principal, professional_name)

    # Fallback a bloque 1 (ANEXO 16) si:
    #   - schema inválido (resultado is None), o
    #   - schema válido pero lista vacía
    # Condición: solo si existe bloque 3 (len >= 3), es decir que el primario era bloque 2
    if (resultado is None or not resultado.get("experiencias")) and len(block.block_texts) >= 3:
        texto_fallback = _filtrar_paginas(block.block_texts[1])[:_MAX_TEXT_CHARS]
        razon = "schema inválido" if resultado is None else "lista vacía"
        print(f" [fallback ANEXO 16 ({razon})]", end="", flush=True)
        resultado_fallback = _extraer_experiencias_de_texto(texto_fallback, professional_name)
        if resultado_fallback and resultado_fallback.get("experiencias"):
            return resultado_fallback

    if resultado is None:
        return {"experiencias": [], "_needs_review": True}

    return resultado


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
