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


# ---------------------------------------------------------------------------
# Clasificación de páginas para Tipo A (bloque único)
# ---------------------------------------------------------------------------
# En documentos Tipo B, motor-OCR ya separa los bloques usando delimitadores
# temáticos (B.1 Calificaciones, B.2 Experiencia, etc.).
# En Tipo A no existen esos delimitadores — todo queda en un solo bloque.
# Estos patrones replican esa separación clasificando por contenido.

_RE_ANEXO16 = re.compile(
    r"ANEXO\s+N[°º]\s*16"
    r"|CALIFICACIONES\s+Y\s+EXPERIENCIA"
    r"|Yo,?\s+[A-ZÁÉÍÓÚÑ\s]{5,},?\s+identificado"
    r"|Formaci[óo]n\s+acad[ée]mica",
    re.IGNORECASE,
)

_RE_DIPLOMA = re.compile(
    r"A\s+NOMBRE\s+DE\s+LA\s+NACI[ÓO]N"
    r"|T[ÍI]TULO\s+(?:PROFESIONAL|de\s+INGENIERO|de\s+ARQUITECTO)"
    r"|MIEMBRO\s+ORDINARIO\s+DE\s+LA\s+ORDEN"
    r"|COLEGIO\s+DE\s+(?:INGENIEROS|ARQUITECTOS)\s+DEL\s+PER[ÚU]"
    r"|REGISTRO\s+N[°º\.]?\s*\d{3,6}"
    r"|EL\s+(?:RECTOR|DECANO)",
    re.IGNORECASE,
)

_RE_CERTIFICADO = re.compile(
    r"CONSTANCIA\s+DE\s+(?:SERVICIOS|TRABAJO|EJECUCI[ÓO]N)"
    r"|CERTIFICA(?:DO|MOS)?\s+(?:DE\s+(?:TRABAJO|SERVICIOS)|QUE)"
    r"|ha\s+(?:prestado|brindado)\s+(?:sus\s+)?servicios"
    r"|Representante\s+(?:Legal|Com[úu]n)"
    r"|DEJA\s+CONSTANCIA",
    re.IGNORECASE,
)

# Ruido institucional — páginas SUSALUD, IPRESS, RENIPRESS que pueden contener
# palabras como "servicios" o "Representante Legal" y colarse como certificados
_RE_INSTITUCIONAL = re.compile(
    r"SUSALUD"
    r"|IPRESS"
    r"|RENIPRESS"
    r"|Registro\s+Nacional\s+de\s+I[Pp]res"
    r"|Categorizaci[óo]n\s+(?:de|del)\s+(?:Establecimiento|EESS)"
    r"|SEACE"
    r"|Buscador\s+de\s+Proveedores",
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


def _clasificar_paginas_tipo_a(texto_bloque: str) -> dict[str, str]:
    """
    Clasifica las páginas de un bloque único (Tipo A) en sub-bloques semánticos.
    Replica la separación que en Tipo B hacen los delimitadores B.1/B.2.

    Retorna dict con claves:
      - "anexo16":      páginas del ANEXO 16 (declaración + tabla experiencias)
      - "diplomas":     páginas de diplomas/credenciales (universidad, CIP/CAP)
      - "certificados": páginas de constancias de servicio
      - "ruido":        páginas no clasificadas (SUSALUD, IPRESS, institucionales)

    Prioridad: anexo16 > certificado > diploma > ruido
    """
    segmentos = re.split(r"(?=\[Página\s+\d+\])", texto_bloque)

    clasificadas: dict[str, list[str]] = {
        "anexo16": [],
        "diplomas": [],
        "certificados": [],
        "ruido": [],
    }

    for seg in segmentos:
        seg = seg.strip()
        if not seg:
            continue

        # Extraer número de página para el log
        pag_match = re.match(r"\[Página\s+(\d+)\]", seg)
        pag_num = pag_match.group(1) if pag_match else "?"

        # Páginas muy cortas son separadores visuales — no aportan
        if len(seg) < 200:
            continue

        # Clasificar por prioridad (ruido institucional se chequea antes que certificados)
        preview = seg[:80].replace("\n", " ").strip()
        if _RE_ANEXO16.search(seg):
            clasificadas["anexo16"].append(seg)
            # print(f"\n    pág {pag_num} → anexo16: {preview}", flush=True)
        elif _RE_INSTITUCIONAL.search(seg):
            clasificadas["ruido"].append(seg)
            # print(f"\n    pág {pag_num} → ruido(institucional): {preview}", flush=True)
        elif _RE_CERTIFICADO.search(seg):
            clasificadas["certificados"].append(seg)
            # print(f"\n    pág {pag_num} → certificado: {preview}", flush=True)
        elif _RE_DIPLOMA.search(seg):
            clasificadas["diplomas"].append(seg)
            # print(f"\n    pág {pag_num} → diploma: {preview}", flush=True)
        elif _RE_EXCLUIR.search(seg):
            clasificadas["ruido"].append(seg)
            # print(f"\n    pág {pag_num} → ruido(excluir): {preview}", flush=True)
        else:
            clasificadas["ruido"].append(seg)
            # print(f"\n    pág {pag_num} → ruido(sin marcador): {preview}", flush=True)

    conteos = {k: len(v) for k, v in clasificadas.items() if v}
    if conteos:
        resumen = ", ".join(f"{k}:{n}" for k, n in conteos.items())
        print(f" [clasificación: {resumen}]", end="", flush=True)

    return {k: "\n\n".join(v) for k, v in clasificadas.items()}


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
    # Campos en inglés (el LLM a veces responde en inglés)
    "project":                "proyecto",
    "project_name":           "proyecto",
    "position":               "cargo",
    "role":                   "cargo",
    "company":                "empresa_emisora",
    "company_name":           "empresa_emisora",
    "start_date":             "fecha_inicio",
    "end_date":               "fecha_fin",
    "issue_date":             "fecha_emision",
    "date_of_constancia":     "fecha_emision",
    "date_of_certificate":    "fecha_emision",
    "certificate_date":       "fecha_emision",
    "constancia_date":        "fecha_emision",
    "signer":                 "firmante",
    "signer_name":            "firmante",
    "signatory":              "firmante",
    "signed_by":              "firmante",
    "signer_position":        "cargo_firmante",
    "signer_role":            "cargo_firmante",
    "position_of_signatory":  "cargo_firmante",
    "signatory_position":     "cargo_firmante",
    "signatory_role":         "cargo_firmante",
}

# Sinónimos para la clave raíz de la respuesta de Paso 3
_SINONIMOS_RAIZ_PASO3 = {"services", "certificates", "experiences", "certifications"}

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
    """
    Retorna True si el resultado tiene la estructura esperada de Paso 3.
    Acepta sinónimos en inglés de la clave raíz y los normaliza a 'experiencias'.
    """
    if not isinstance(result, dict):
        return False

    # Normalizar clave raíz: si usó "services", "certificates", etc. → "experiencias"
    if "experiencias" not in result:
        for sinonimo in _SINONIMOS_RAIZ_PASO3:
            if sinonimo in result and isinstance(result[sinonimo], list):
                result["experiencias"] = result.pop(sinonimo)
                break

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

    Tipo B (2+ bloques — separados por delimitadores B.1/B.2):
      Prioridad: bloque 1 (ANEXO 16) → bloque 0 (credenciales)

    Tipo A (1 bloque — todo contiguo):
      Clasifica páginas y envía: ANEXO 16 + diplomas
      Fallback: todo el bloque filtrado
    """
    if len(block.block_texts) >= 2:
        # Tipo B — comportamiento existente
        return _filtrar_paginas(block.block_texts[1])[:_MAX_TEXT_CHARS]

    # Tipo A — clasificar páginas del bloque único
    clasificadas = _clasificar_paginas_tipo_a(block.block_texts[0])

    # Paso 2 necesita: declaración (nombre, DNI, cargo) + diplomas (CIP, profesión)
    partes: list[str] = []
    if clasificadas["anexo16"]:
        partes.append(clasificadas["anexo16"])
    if clasificadas["diplomas"]:
        partes.append(clasificadas["diplomas"])

    if partes:
        return "\n\n".join(partes)[:_MAX_TEXT_CHARS]

    # Fallback: clasificación no encontró nada → enviar todo filtrado
    return _filtrar_paginas(block.block_texts[0])[:_MAX_TEXT_CHARS]


def _texto_paso3(block: ProfessionalBlock) -> str:
    """
    Selecciona el texto más útil para extraer experiencias (Paso 3).

    Tipo B (3+ bloques — separados por delimitadores B.1/B.2):
      Prioridad: bloque 2 (constancias) → bloque 1 (ANEXO 16)

    Tipo A (1 bloque — todo contiguo):
      Clasifica páginas y envía: solo certificados
      Fallback 1: ANEXO 16 (tiene tabla resumen de experiencias)
      Fallback 2: todo el bloque filtrado
    """
    if len(block.block_texts) >= 3:
        return _filtrar_paginas(block.block_texts[2])[:_MAX_TEXT_CHARS]
    if len(block.block_texts) >= 2:
        return _filtrar_paginas(block.block_texts[1])[:_MAX_TEXT_CHARS]

    # Tipo A — clasificar páginas del bloque único
    clasificadas = _clasificar_paginas_tipo_a(block.block_texts[0])

    if clasificadas["certificados"]:
        return clasificadas["certificados"][:_MAX_TEXT_CHARS]

    # Fallback: ANEXO 16 tiene tabla resumen de experiencias
    if clasificadas["anexo16"]:
        return clasificadas["anexo16"][:_MAX_TEXT_CHARS]

    # Último fallback: todo filtrado
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
        # Texto primario agotó intentos → fallback
        if len(block.block_texts) >= 2:
            # Tipo B: fallback a bloque 0 (credenciales)
            texto_fb = _filtrar_paginas(block.block_texts[0])[:_MAX_TEXT_CHARS]
            print(f" [fallback bloque 0]", end="", flush=True)
            prompt_fb = PASO2_PROMPT.format(cargo=block.cargo, texto=texto_fb)
            result_fb = call_llm(prompt_fb)
            if _validar_paso2(result_fb):
                result = result_fb
            else:
                result["_needs_review"] = True
        else:
            # Tipo A: si clasificación parcial falló, intentar con todo filtrado
            texto_completo = _filtrar_paginas(block.block_texts[0])[:_MAX_TEXT_CHARS]
            if texto_completo != texto:
                print(f" [fallback texto completo]", end="", flush=True)
                prompt_fb = PASO2_PROMPT.format(cargo=block.cargo, texto=texto_completo)
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
        # # DEBUG: mostrar qué devolvió el LLM cuando falla
        # import json
        # preview = json.dumps(result, ensure_ascii=False, default=str)[:500]
        # print(f"\n    DEBUG respuesta LLM (intento {intento}): {preview}", flush=True)
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

    # Fallback si schema inválido o lista vacía
    if resultado is None or not resultado.get("experiencias"):
        razon = "schema inválido" if resultado is None else "lista vacía"

        if len(block.block_texts) >= 3:
            # Tipo B: fallback a bloque 1 (ANEXO 16)
            texto_fallback = _filtrar_paginas(block.block_texts[1])[:_MAX_TEXT_CHARS]
            print(f" [fallback ANEXO 16 ({razon})]", end="", flush=True)
            resultado_fallback = _extraer_experiencias_de_texto(texto_fallback, professional_name)
            if resultado_fallback and resultado_fallback.get("experiencias"):
                return resultado_fallback

        elif len(block.block_texts) == 1:
            # Tipo A: probar ANEXO 16 clasificado (tiene tabla resumen de experiencias)
            clasificadas = _clasificar_paginas_tipo_a(block.block_texts[0])
            if clasificadas["anexo16"] and clasificadas["anexo16"] != texto_principal:
                print(f" [fallback ANEXO 16 clasificado ({razon})]", end="", flush=True)
                resultado_fallback = _extraer_experiencias_de_texto(
                    clasificadas["anexo16"][:_MAX_TEXT_CHARS], professional_name
                )
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
