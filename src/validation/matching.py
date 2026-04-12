"""
Funciones de normalización y comparación de texto para el motor de reglas.
Usadas por el evaluador RTM (Paso 4) y el pipeline TDR (dedup de cargos).

Sin IA, sin llamadas externas — pura manipulación de strings.
"""
import re
import unicodedata
from typing import Optional


# ---------------------------------------------------------------------------
# Diccionarios de sinónimos sectoriales y de intervención
# ---------------------------------------------------------------------------

SINONIMOS_SECTOR: dict[str, list[str]] = {
    "salud": [
        "hospital", "centro de salud", "establecimiento de salud",
        "posta medica", "posta de salud", "clinica", "policlinico",
        "instituto nacional de salud", "red de salud", "micro red",
        "centro materno", "materno infantil", "inen", "essalud",
    ],
    "educacion": [
        "colegio", "institucion educativa", "escuela", "universidad",
        "centro educativo", "liceo", "i.e.", "ie ", "cetpro",
        "instituto pedagogico", "unidad escolar",
    ],
    "vial": [
        "carretera", "via ", "puente", "autopista", "pista",
        "camino vecinal", "trocha", "avenida", "pavimentacion",
        "vial", "intercambio vial", "ovalo", "bypass",
    ],
    "saneamiento": [
        "agua potable", "alcantarillado", "desague", "planta de tratamiento",
        "saneamiento", "ptar", "ptap", "reservorio", "captacion",
        "sistema de agua", "red de agua", "red de desague",
    ],
    "edificacion": [
        "edificio", "vivienda", "residencial", "condominio",
        "edificacion", "complejo habitacional",
    ],
    "riego": [
        "irrigacion", "riego", "canal", "bocatoma", "represa",
        "presa", "sistema de riego", "drenaje agricola",
    ],
    "transporte": [
        "terminal terrestre", "aeropuerto", "puerto", "muelle",
        "embarcadero", "estacion", "ferrocarril", "metro", "tren",
    ],
    "deportivo": [
        "estadio", "coliseo", "polideportivo", "complejo deportivo",
        "losa deportiva", "campo deportivo",
    ],
    "institucional": [
        "palacio municipal", "municipalidad", "sede institucional",
        "local institucional", "comisaria", "local comunal",
    ],
}

PALABRAS_INTERVENCION: dict[str, list[str]] = {
    "construccion": ["construccion", "construir"],
    "mejoramiento": ["mejoramiento", "mejorar"],
    "ampliacion": ["ampliacion", "ampliar"],
    "rehabilitacion": ["rehabilitacion", "rehabilitar"],
    "remodelacion": ["remodelacion", "remodelar"],
    "supervision": ["supervision", "supervisar", "supervisión"],
    "expediente tecnico": [
        "expediente tecnico", "expediente técnico",
        "elaboracion del expediente", "elaboración del expediente",
        "estudio definitivo",
    ],
    "instalacion": ["instalacion", "instalar"],
    "creacion": ["creacion", "crear"],
    "sustitucion": ["sustitucion", "sustituir", "reposicion"],
    "demolicion": ["demolicion", "demoler"],
    "mantenimiento": ["mantenimiento", "conservacion"],
}

# Artículos y preposiciones a eliminar en normalización genérica
_STOPWORDS = frozenset({
    "de", "del", "la", "las", "los", "el", "en", "al", "con",
    "para", "por", "a", "un", "una", "y", "o", "e",
})


# ---------------------------------------------------------------------------
# Normalización genérica de texto
# ---------------------------------------------------------------------------

def normalizar_texto(texto: str) -> str:
    """
    Normalización básica: minúsculas, sin acentos, sin artículos/preposiciones.

    >>> normalizar_texto("Supervisión de la Obra del Hospital")
    'supervision obra hospital'
    """
    if not texto:
        return ""
    # Minúsculas
    t = texto.lower().strip()
    # Quitar acentos: NFD → filtrar combining → NFC
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = unicodedata.normalize("NFC", t)
    # Quitar caracteres no alfanuméricos excepto espacios
    t = re.sub(r"[^\w\s]", " ", t)
    # Quitar stopwords
    tokens = [w for w in t.split() if w not in _STOPWORDS]
    return " ".join(tokens)


def _strip_acentos(texto: str) -> str:
    """Quita acentos pero mantiene mayúsculas, puntuación y stopwords."""
    t = unicodedata.normalize("NFD", texto)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", t)


# ---------------------------------------------------------------------------
# Normalización de cargos (extraída de src/tdr/extractor/pipeline.py)
# ---------------------------------------------------------------------------

def normalizar_cargo(cargo: str) -> str:
    """
    Normaliza nombre de cargo para comparación fuzzy.

    Maneja patrones OSCE comunes:
      - "X y/o Y y/o Z" → primera alternativa
      - "en la especialidad de X" → "especialista en X"
      - Frases de acción ("de elaboración del expediente") → se eliminan
      - Correcciones OCR conocidas

    Ejemplos:
      "Jefe de elaboración del expediente técnico" → "jefe"
      "Jefe y/o Gerente y/o Director" → "jefe"
      "Especialista en la especialidad de Estructuras" → "especialista en estructuras"
      "Gestor BIM" → "gestor bim"
    """
    texto = cargo.strip()

    # 0. Caso especial: "en la especialidad de X"
    m_esp = re.search(
        r"especialidad\s+de\s+(.+)$", texto, re.IGNORECASE,
    )
    if m_esp:
        especialidad = m_esp.group(1).strip().lower()
        especialidad = re.split(r"\s+y/o\s+", especialidad, maxsplit=1)[0].strip()
        return f"especialista en {especialidad}"

    # 0b. "Especialista en Instalaciones de X" → "especialista en X"
    m_inst = re.match(
        r"^Especialista\s+en\s+Instalaciones\s+de\s+(.+)$",
        texto, re.IGNORECASE,
    )
    if m_inst:
        especialidad = m_inst.group(1).strip().lower()
        especialidad = re.split(r",\s*|\s+y/o\s+", especialidad, maxsplit=1)[0].strip()
        return f"especialista en {especialidad}"

    # 1. Primera alternativa de "X y/o Y y/o Z"
    base = re.split(r"\s+y/o\s+", texto, maxsplit=1)[0].strip()

    # 2. Quitar frases de acción ("de elaboración del expediente técnico")
    base = re.sub(
        r"\s+(?:de(?:l)?|en)\s+(?:la\s+)?(?:elaboración|desarrollo|supervisión|diseño|expediente)"
        r"(?:\s+\S+)*$",
        "", base, flags=re.IGNORECASE,
    )

    # 2b. "Gestor de BIM" → "Gestor BIM"
    base = re.sub(
        r"^(Gestor|Director|Gerente|Coordinador|Jefe|L[ií]der|Supervisor"
        r"|Responsable|Encargado|Administrador|Representante)\s+de(?:l)?\s+",
        r"\1 ", base, flags=re.IGNORECASE,
    )

    # 3. Corrección OCR: "Seguridad y Ejecución" → "Seguridad y Evacuación"
    base = re.sub(
        r"seguridad\s+y\s+ejecuci[oó]n",
        "seguridad y evacuación", base, flags=re.IGNORECASE,
    )

    return base.strip().lower()


# ---------------------------------------------------------------------------
# Comparación de profesiones (género neutro)
# ---------------------------------------------------------------------------

def _genero_neutro(texto: str) -> str:
    """
    Neutraliza género en profesiones: -o/-a → -@.
    'Ingeniero' y 'Ingeniera' se vuelven idénticos.
    """
    t = _strip_acentos(texto).lower().strip()
    # Reemplazar terminación -o/-a al final de cada palabra
    # pero solo si la palabra tiene 4+ letras (evitar "de" → "d@")
    return re.sub(r"\b(\w{3,})[oa]\b", r"\1@", t)


def es_genero_neutro(a: str, b: str) -> bool:
    """
    Compara dos textos ignorando diferencias de género.

    >>> es_genero_neutro("Ingeniero Civil", "Ingeniera Civil")
    True
    >>> es_genero_neutro("Arquitecto", "Arquitecta")
    True
    """
    return _genero_neutro(a) == _genero_neutro(b)


def match_profesion(
    propuesta: Optional[str],
    aceptadas: Optional[list[str]],
) -> bool:
    """
    Retorna True si la profesión propuesta coincide con alguna aceptada.

    Reglas:
    - Si aceptadas es None o vacía → True (favorabilidad OSCE)
    - Si propuesta es None pero aceptadas tiene valores → False
    - Comparación género-neutral
    """
    if not aceptadas:
        return True
    if not propuesta:
        return False
    for aceptada in aceptadas:
        if es_genero_neutro(propuesta, aceptada):
            return True
    return False


# ---------------------------------------------------------------------------
# Comparación de cargos
# ---------------------------------------------------------------------------

# Sinónimos de cargo OSCE: cargos que son equivalentes o variantes del mismo rol.
# Cada grupo es un set de tokens normalizados que se consideran intercambiables.
SINONIMOS_CARGO: list[set[str]] = [
    # BIM
    {"especialista bim", "gestor bim", "coordinador bim", "lider bim",
     "supervisor bim", "bim manager", "ingeniero bim", "arquitecto bim",
     "especialista bim manager", "especialista bim management"},
    # Costos / Metrados / Presupuestos / Valorizaciones
    {"especialista en costos", "especialista en costos y presupuestos",
     "especialista en metrados", "especialista en metrados costos y valorizaciones",
     "especialista en costos metrados y valorizaciones",
     "especialista en metrados costos y presupuestos"},
    # Equipamiento
    {"especialista en equipamiento", "especialista en equipamiento y mobiliario",
     "especialista en equipamiento biomedico",
     "especialista en equipamiento medico hospitalario",
     "ingeniero especialista en equipamiento medico hospitalario"},
    # Seguridad
    {"especialista en seguridad", "especialista en seguridad y medio ambiente",
     "especialista de seguridad y medio ambiente",
     "especialista en seguridad salud y medio ambiente",
     "especialista en seguridad y salud ocupacional",
     "especialista ssoma"},
    # Supervisión / Jefatura
    {"jefe de supervision", "jefe supervisor", "supervisor de obra",
     "jefe de elaboracion del expediente tecnico", "jefe"},
    # Instalaciones eléctricas / electromecánicas
    {"especialista en instalaciones electricas",
     "especialista electromecanico",
     "ingeniero especialista en instalaciones electricas",
     "ingeniero especialista en instalaciones electricas y mecanicas",
     "ingeniero especialista en instalaciones electricas y electromecanicas",
     "ingeniero electrico"},
    # Comunicaciones / TIC
    {"especialista en comunicaciones",
     "especialista en tecnologias de la informacion",
     "especialista en tecnologias de la informacion y comunicacion",
     "especialista en cableado estructurado",
     "especialista en redes de cableado estructurado y comunicaciones",
     "especialista en configuraciones tecnologicas"},
]


def _son_cargos_sinonimos(cargo_a: str, cargo_b: str) -> bool:
    """Retorna True si ambos cargos pertenecen al mismo grupo de sinónimos."""
    norm_a = normalizar_texto(cargo_a)
    norm_b = normalizar_texto(cargo_b)
    for grupo in SINONIMOS_CARGO:
        # Buscar si algún sinónimo del grupo está contenido en cada cargo
        match_a = any(sin in norm_a or norm_a in sin for sin in grupo)
        match_b = any(sin in norm_b or norm_b in sin for sin in grupo)
        if match_a and match_b:
            return True
    return False


def match_cargo(
    cargo_experiencia: Optional[str],
    cargos_validos: Optional[list[str]],
) -> bool:
    """
    Retorna True si el cargo de la experiencia coincide con alguno válido.

    Reglas:
    - Si cargos_validos es None o vacío → True (favorabilidad OSCE)
    - Si cargo_experiencia es None pero hay cargos_validos → False
    - Compara en orden de prioridad:
      1. Match exacto (normalizado)
      2. Substring bidireccional
      3. Sinónimos de cargo OSCE
    """
    if not cargos_validos:
        return True
    if not cargo_experiencia:
        return False

    norm_exp = normalizar_cargo(cargo_experiencia)

    for valido in cargos_validos:
        norm_val = normalizar_cargo(valido)
        # Match exacto
        if norm_exp == norm_val:
            return True
        # Substring bidireccional
        if norm_exp in norm_val or norm_val in norm_exp:
            return True

    # Sinónimos de cargo
    for valido in cargos_validos:
        if _son_cargos_sinonimos(cargo_experiencia, valido):
            return True

    return False


# ---------------------------------------------------------------------------
# Inferencia de tipo de obra e intervención desde nombre del proyecto
# ---------------------------------------------------------------------------

def inferir_tipo_obra(project_name: Optional[str]) -> Optional[str]:
    """
    Intenta determinar el sector de una obra a partir del nombre del proyecto.
    Retorna la clave del sector (e.g. "salud") o None si no puede determinar.

    >>> inferir_tipo_obra("Mejoramiento del Hospital Regional del Cusco")
    'salud'
    >>> inferir_tipo_obra("Construcción de la Carretera Lima-Canta")
    'vial'
    """
    if not project_name:
        return None
    nombre_norm = normalizar_texto(project_name)
    for sector, sinonimos in SINONIMOS_SECTOR.items():
        for sinonimo in sinonimos:
            # Normalizar el sinónimo también
            sin_norm = normalizar_texto(sinonimo)
            if sin_norm and sin_norm in nombre_norm:
                return sector
    return None


def inferir_intervencion(project_name: Optional[str]) -> Optional[str]:
    """
    Intenta determinar el tipo de intervención desde el nombre del proyecto.
    Retorna la clave (e.g. "construccion") o None.

    >>> inferir_intervencion("Mejoramiento y Ampliación del Hospital")
    'mejoramiento'
    """
    if not project_name:
        return None
    nombre_norm = normalizar_texto(project_name)
    for tipo, variantes in PALABRAS_INTERVENCION.items():
        for variante in variantes:
            var_norm = normalizar_texto(variante)
            if var_norm and var_norm in nombre_norm:
                return tipo
    return None


# ---------------------------------------------------------------------------
# Comparación de tipo de obra (sector)
# ---------------------------------------------------------------------------

def match_tipo_obra(
    proyecto_o_tipo: Optional[str],
    tipo_requerido: Optional[str],
) -> Optional[bool]:
    """
    Compara el tipo de obra del certificado contra el requerido por las bases.

    Args:
        proyecto_o_tipo: tipo de obra explícito (Experience.tipo_obra) o
                         nombre del proyecto si el tipo no fue extraído.
        tipo_requerido: tipo de obra requerido (RequisitoPersonal.tipo_obra_valido).

    Returns:
        True  — coincide
        False — no coincide
        None  — no se puede determinar (datos insuficientes)

    Si tipo_requerido es None → True (bases no especifican restricción).
    """
    if not tipo_requerido:
        return True
    if not proyecto_o_tipo:
        return None

    # Normalizar ambos
    norm_req = normalizar_texto(tipo_requerido)
    norm_cert = normalizar_texto(proyecto_o_tipo)

    # 1. Match directo (ambos normalizados)
    if norm_req in norm_cert or norm_cert in norm_req:
        return True

    # 2. Buscar sector del requerido
    sector_req = _buscar_sector(tipo_requerido)
    if not sector_req:
        # No pudimos clasificar el requerido — no determinable
        return None

    # 3. Buscar sector del certificado
    sector_cert = _buscar_sector(proyecto_o_tipo)
    if not sector_cert:
        return None

    return sector_req == sector_cert


def _buscar_sector(texto: str) -> Optional[str]:
    """Busca a qué sector pertenece un texto."""
    norm = normalizar_texto(texto)
    # Primero buscar si el texto ES una clave de sector
    for sector in SINONIMOS_SECTOR:
        if normalizar_texto(sector) == norm:
            return sector
    # Luego buscar sinónimos dentro del texto
    for sector, sinonimos in SINONIMOS_SECTOR.items():
        for sinonimo in sinonimos:
            sin_norm = normalizar_texto(sinonimo)
            if sin_norm and sin_norm in norm:
                return sector
    return None


def match_intervencion(
    intervencion_cert: Optional[str],
    intervencion_req: Optional[str],
) -> Optional[bool]:
    """
    Compara el tipo de intervención del certificado contra el requerido.

    Returns:
        True  — coincide
        False — no coincide
        None  — no determinable o bases no lo exigen

    Si intervencion_req es None o contiene "no importa" → True.
    """
    if not intervencion_req:
        return True
    # "El tipo de intervención no importa" → cumple
    if "no importa" in intervencion_req.lower():
        return True
    if not intervencion_cert:
        return None

    norm_req = normalizar_texto(intervencion_req)
    norm_cert = normalizar_texto(intervencion_cert)

    # Match directo
    if norm_req in norm_cert or norm_cert in norm_req:
        return True

    # Buscar por clave de intervención
    clave_req = _buscar_intervencion(intervencion_req)
    clave_cert = _buscar_intervencion(intervencion_cert)

    if clave_req and clave_cert:
        return clave_req == clave_cert

    return None


def _buscar_intervencion(texto: str) -> Optional[str]:
    """Busca a qué tipo de intervención pertenece un texto."""
    norm = normalizar_texto(texto)
    for tipo, variantes in PALABRAS_INTERVENCION.items():
        for variante in variantes:
            var_norm = normalizar_texto(variante)
            if var_norm and var_norm in norm:
                return tipo
    return None
