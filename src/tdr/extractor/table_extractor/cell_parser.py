"""
Parsers de contenido de celda — el LLM solo procesa una celda aislada.

Esto es lo que hace que el pipeline de 3 capas elimine cross-row contamination:
el LLM nunca ve mas de una celda a la vez. Si recibe la celda de "FORMACION
ACADEMICA" para la fila 9, NO puede contaminar con datos de la fila 10.

Para celdas simples (profesiones B.1), usamos regex puro — no necesita LLM.
Para celdas verbosas (TRABAJOS O PRESTACIONES de B.2), usamos LLM con prompt
acotado a esa unica celda.
"""
from __future__ import annotations
import json
import logging
import re
import time
from typing import Optional

from openai import OpenAI

from src.tdr.config.settings import (
    QWEN_OLLAMA_BASE_URL,
    QWEN_OLLAMA_API_KEY,
    QWEN_MODEL,
    QWEN_MAX_TOKENS,
    QWEN_TIMEOUT,
    QWEN_NUM_CTX,
)

logger = logging.getLogger(__name__)


# ── Cliente Ollama compartido ────────────────────────────────────────────────

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


# ── Parser de profesiones (regex puro, sin LLM) ──────────────────────────────

# Footnotes superscript que el OCR captura como numeros sueltos en celda.
_FOOTNOTE_RE = re.compile(r"\b\d{2,4}\b")

# Separadores tipicos entre profesiones en la columna FORMACION ACADEMICA
_SEPARADORES_PROFESION = re.compile(r"\s*y/o\s*|\s*,\s*|\s+o\s+(?=Ingeniero|Arquitecto|Médico|Tecnólogo|Licenciado|Bachiller)")

# Prefijos validos de titulo profesional
_PREFIJOS_TITULO = (
    "INGENIERO", "INGENIERA", "ARQUITECTO", "ARQUITECTA",
    "MÉDICO", "MEDICO", "TECNÓLOGO", "TECNOLOGO",
    "LICENCIADO", "LICENCIADA", "BACHILLER", "DOCTOR", "DOCTORA",
    "BIÓLOGO", "BIOLOGO", "ABOGADO", "ABOGADA",
    "ECONOMISTA", "CONTADOR", "CONTADORA",
)


def _limpiar_typos_ocr_comunes(texto: str) -> str:
    """
    Normaliza typos comunes que introduce el OCR (PaddleOCR / PP-Structure).

    Patrones observados en TDRs reales:
    - "y/0" → "y/o"  (cero en vez de letra o tras el slash)
    - "Eléctricc" → "Eléctrico"  (consonante doblada al final, OCR pierde la 'o')
    - "Industrialy" / "Laboraly" → "Industrial y" / "Laboral y" (falta espacio)
    - Doble espacio o no-break space → espacio simple
    """
    if not texto:
        return texto

    # 0. Normalizar non-break space y otros whitespace exoticos
    texto = texto.replace(" ", " ").replace(" ", " ").replace(" ", " ")

    # 1. "y/0" / "Y/0" / "y/O" → "y/o" (cero o O confundidos)
    texto = re.sub(r"\by\s*/\s*0\b", "y/o", texto)
    texto = re.sub(r"\by\s*/\s*O\b", "y/o", texto, flags=re.IGNORECASE)

    # 2. Espacio faltante antes de "y/o" cuando viene pegado a una palabra:
    #    "Industrialy/o" → "Industrial y/o"
    #    "Laboraly/o"    → "Laboral y/o"
    texto = re.sub(r"(?<=[a-záéíóúñ])y/o", " y/o", texto, flags=re.IGNORECASE)

    # 3. Consonante final duplicada en titulos comunes (typo OCR conocido):
    #    "Eléctricc" → "Eléctrico", "Mecánicc" → "Mecánico", "Electronicc" → "Electronico"
    #    Solo aplica al final de palabra para no romper palabras legitimas.
    texto = re.sub(
        r"(?<![a-záéíóúñ])([A-Za-záéíóúñ]+)(c)c\b",
        r"\1\2o",
        texto,
    )

    # 4. Colapsar espacios multiples
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def parsear_profesiones(texto_celda: str) -> list[str]:
    """
    Parsea el contenido de la celda FORMACION ACADEMICA de B.1.

    Casos:
    - "Ingeniero Civil y/o Arquitecto" → ["Ingeniero Civil", "Arquitecto"]
    - "Ingeniero Sanitario y/o Ingeniero Civil" → ["Ingeniero Sanitario", "Ingeniero Civil"]
    - "Tecnólogo Médico y/o Médico y/o Ingeniero Mecatrónico..." → split correctly
    - "Ingeniero civil" → ["Ingeniero civil"]
    - "Ingeniero Eléctricc y/0 Ingeniero Electronico" → ["Ingeniero Eléctrico", "Ingeniero Electronico"]
      (typos OCR normalizados antes del split)

    Filtra footnotes (numeros sueltos) y normaliza espacios.
    """
    if not texto_celda or not texto_celda.strip():
        return []

    # 1. Quitar footnotes (numeros sueltos como "68", "75", "136")
    texto = _FOOTNOTE_RE.sub("", texto_celda)

    # 2. Normalizar espacios y newlines
    texto = re.sub(r"\s+", " ", texto).strip()

    # 2b. Limpiar typos OCR comunes ANTES del split (sin esto el split de "y/0"
    #     no funciona y profesiones quedan pegadas)
    texto = _limpiar_typos_ocr_comunes(texto)

    # 3. Split por "y/o" o ","
    items = _SEPARADORES_PROFESION.split(texto)

    # 4. Limpiar y validar
    profesiones = []
    for item in items:
        item = item.strip(" ,.;:-")
        if not item or len(item) < 4:
            continue
        # Validar que empiece con prefijo de titulo profesional
        item_upper = item.upper()
        if any(item_upper.startswith(p) for p in _PREFIJOS_TITULO):
            profesiones.append(item)

    # Dedup case-insensitive preservando primer caso
    seen = set()
    result = []
    for p in profesiones:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            result.append(p)

    return result


def parsear_tiempo_meses(texto_celda: str) -> Optional[int]:
    """
    Parsea la celda TIEMPO DE EXPERIENCIA de B.2.

    Casos:
    - "Experiencia mínima de (24) meses" → 24
    - "Experiencia mínima de (36) meses" → 36
    - "24 meses" → 24
    - texto basura → None
    """
    if not texto_celda:
        return None
    # Buscar patron "(N)" entre parentesis (formato OSCE estandar)
    m = re.search(r"\((\d{1,3})\)\s*meses", texto_celda, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Fallback: cualquier numero seguido de "meses" o "mes"
    m = re.search(r"\b(\d{1,3})\s*meses?\b", texto_celda, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


# ── Parser de B.2 verbosa con LLM mini-prompt ────────────────────────────────

_PROMPT_PARSE_CELDA_B2 = """Eres parser LITERAL de UNA celda de la columna "TRABAJOS O PRESTACIONES" de la tabla B.2 de un TDR OSCE peruano.

REGLA CRITICA: Solo extrae palabras que estan LITERALMENTE en el texto entre "y/o". NO inventes, NO sugieras variantes, NO completes con sinonimos.

ESTRUCTURA TIPICA DE LA CELDA:
La celda puede tener UNA de estas dos formas:

  FORMA A — Lista de cargos completos:
    "[Cargo1] y/o [Cargo2] y/o [Cargo3] ... [y/o la combinacion de estos], en la supervision/ejecucion..."
    Aqui cada [Cargo] ya es un puesto laboral completo.
    -> cargos_similares = TODOS los [Cargo] literales, sin tocar.

  FORMA B — Roles + areas separados por "en/de:":
    "[Rol1] y/o [Rol2] y/o ... y/o [RolN] [o la combinacion] en/de: [Area1] y/o [Area2] y/o ..."
    Aqui los [Rol] son cargos genericos (Ingeniero, Especialista, jefe, etc.)
    y las [Area] son especialidades tecnicas (Medio Ambiente, Cableado Estructurado, etc.)
    -> cargos_similares = SOLO los [Rol] que estan ANTES de "en/de:".
    -> Las [Area] NO son cargos. NO las incluyas como cargos. NO las combines con los roles.

REGLAS ESPECIFICAS:
1. NO inventes cargos. Si la palabra NO aparece literal en el texto entre "y/o", NO la incluyas.
2. NO crees variantes. Si el texto dice "Medio Ambiente", NO escribas "Mitigacion Ambiental" ni "Monitoreo Ambiental" ni "ambientalista".
3. NO combines roles con areas. Si el texto dice "Ingeniero en/de: Medio Ambiente", NO devuelvas "Ingeniero Ambiental".
4. Frases que NO son cargos (descartar):
   - "la combinacion de estos" / "o la combinacion de las mismas"
   - "en la supervision y/o ejecucion de obras"
   - "en la especialidad ..." / "subespecialidad ..."
5. Tipo de obra: extrae lo que viene despues de "subespecialidad" (ej: "establecimientos de salud").

EJEMPLO 1 (Forma A — cargos completos):
Texto: "Gerente de Obra y/o Gerente de Proyecto y/o Coordinador de Obra y/o Director de Proyectos y/o la combinacion de estos, en la supervision y/o ejecucion de obras en la especialidad 'edificaciones y afines' y la subespecialidad 'establecimientos de salud'."

Respuesta:
{
  "cargos_similares": ["Gerente de Obra", "Gerente de Proyecto", "Coordinador de Obra", "Director de Proyectos"],
  "tipo_obra": "establecimientos de salud"
}

EJEMPLO 2 (Forma A — cargos completos con sufijo de especialidad):
Texto: "Especialista en Instalaciones Sanitarias y/o Jefe en Instalaciones Sanitarias y/o Ingeniero Sanitario y/o Especialista Sanitario y/o Ingeniero en Instalaciones Sanitarias y/o la combinacion de estos, en la supervision y/o ejecucion de obras en la especialidad 'edificaciones y afines' y la subespecialidad 'establecimientos de salud'."

Respuesta:
{
  "cargos_similares": ["Especialista en Instalaciones Sanitarias", "Jefe en Instalaciones Sanitarias", "Ingeniero Sanitario", "Especialista Sanitario", "Ingeniero en Instalaciones Sanitarias"],
  "tipo_obra": "establecimientos de salud"
}

EJEMPLO 3 (Forma B — roles + areas con "en/de:"):
Texto: "Ingeniero y/o Especialista y/o supervisor y/o jefe y/o Responsable y/o Coordinador en/de: Medio Ambiente y/o la combinacion de estos, en la supervision y/o ejecucion de obras en la especialidad 'edificaciones y afines' y la subespecialidad 'establecimientos de salud'."

Respuesta CORRECTA (solo los roles antes de "en/de:"):
{
  "cargos_similares": ["Ingeniero", "Especialista", "supervisor", "jefe", "Responsable", "Coordinador"],
  "tipo_obra": "establecimientos de salud"
}

Respuestas INCORRECTAS (NO hagas esto):
✗ {"cargos_similares": ["ambientalista", "Mitigacion Ambiental", "Monitoreo Ambiental"]}  ← inventaste palabras que no estan
✗ {"cargos_similares": ["Ingeniero Ambiental", "Especialista Ambiental"]}  ← combinaste rol + area
✗ {"cargos_similares": ["Medio Ambiente"]}  ← "Medio Ambiente" es area, NO cargo

EJEMPLO 4 (Forma B — roles + multiples areas con "en/de:"):
Texto: "Ingeniero y/o Especialista y/o jefe y/o Supervisor y/o Responsable y/o Coordinador o la combinacion de estos en/de: Instalaciones de telecomunicaciones y/o redes de datos y/o voz y data y/o Tecnologia de la informacion y/o sistemas de informacion o la combinacion de estos, en la supervision y/o ejecucion de obras."

Respuesta CORRECTA:
{
  "cargos_similares": ["Ingeniero", "Especialista", "jefe", "Supervisor", "Responsable", "Coordinador"],
  "tipo_obra": null
}

Respuesta INCORRECTA:
✗ Incluir "Instalaciones de telecomunicaciones", "redes de datos", "voz y data", etc. ← son areas, no cargos

Responde SOLO con JSON valido, sin explicacion. Si la celda esta vacia o no tiene cargos:
{"cargos_similares": [], "tipo_obra": null}

CELDA A PARSEAR:
"""


def _build_extra_body() -> dict:
    """extra_body para chat.completions.create (Ollama OpenAI-compat)."""
    return {
        "format": "json",
        "keep_alive": "10m",
        "options": {"num_gpu": 99, "num_ctx": QWEN_NUM_CTX},
    }


def _limpiar_json_raw(raw: str) -> str:
    """Limpia bloques markdown y thinking del raw LLM."""
    # Quitar bloque de thinking de Qwen
    if "</think>" in raw:
        raw = raw.split("</think>")[-1].strip()
    # Quitar markdown fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Buscar primer brace
    start = raw.find("{")
    if start > 0:
        raw = raw[start:]
    return raw.strip("`").strip()


def _normalizar_para_busqueda(texto: str) -> str:
    """Normaliza para busqueda fuzzy: lowercase + sin tildes + espacios colapsados."""
    if not texto:
        return ""
    import unicodedata
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _filtrar_alucinaciones(
    cargos_llm: list[str],
    texto_celda: str,
) -> tuple[list[str], list[str]]:
    """
    Red de seguridad anti-alucinacion.

    El LLM puede inventar cargos que no estan literal en el texto. Para cada
    cargo devuelto, verifica que aparezca en el texto de la celda (con
    tolerancia a typos OCR via fuzzy match >= 80).

    Returns:
        (cargos_validos, alucinaciones_descartadas)

    Ej: si el texto dice "Ingeniero y/o Especialista en/de: Medio Ambiente"
    y el LLM devuelve ["Ingeniero", "Especialista", "Mitigacion Ambiental"],
    "Mitigacion Ambiental" se filtra porque no aparece en el texto.
    """
    if not cargos_llm:
        return [], []

    texto_norm = _normalizar_para_busqueda(texto_celda)
    if not texto_norm:
        return cargos_llm, []

    # Si rapidfuzz disponible, usar partial_ratio para tolerar typos OCR
    try:
        from rapidfuzz import fuzz as _fuzz
        usar_fuzzy = True
    except ImportError:
        usar_fuzzy = False

    validos: list[str] = []
    descartados: list[str] = []

    for cargo in cargos_llm:
        cargo_norm = _normalizar_para_busqueda(cargo)
        if not cargo_norm or len(cargo_norm) < 3:
            descartados.append(cargo)
            continue

        # Match directo (rapido)
        if cargo_norm in texto_norm:
            validos.append(cargo)
            continue

        # Match fuzzy (tolera typos OCR como "electricc" vs "electrico")
        if usar_fuzzy:
            score = _fuzz.partial_ratio(cargo_norm, texto_norm)
            if score >= 85:
                validos.append(cargo)
                continue

        descartados.append(cargo)

    return validos, descartados


def parsear_b2_celda_con_llm(texto_celda: str) -> dict:
    """
    Parsea la celda TRABAJOS O PRESTACIONES de B.2 con LLM aislado.

    Recibe SOLO el texto de la celda (no la tabla entera) → cero
    cross-row contamination posible por construccion.

    Returns:
        {"cargos_similares": [str], "tipo_obra": str | None}
        En caso de error: {"cargos_similares": [], "tipo_obra": None, "_error": str}
    """
    if not texto_celda or not texto_celda.strip():
        return {"cargos_similares": [], "tipo_obra": None}

    # Limpiar footnotes superscript del texto antes de mandarlo
    texto_limpio = _FOOTNOTE_RE.sub("", texto_celda)
    texto_limpio = re.sub(r"\s+", " ", texto_limpio).strip()

    prompt = _PROMPT_PARSE_CELDA_B2 + texto_limpio

    try:
        client = _get_client()
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=2048,
            extra_body=_build_extra_body(),
        )
        elapsed = time.perf_counter() - t0
        raw = response.choices[0].message.content.strip()
        cleaned = _limpiar_json_raw(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(
                "[cell-parser] B.2 celda JSON invalido (%s) — raw: %r",
                e, cleaned[:200],
            )
            return {
                "cargos_similares": [],
                "tipo_obra": None,
                "_error": f"json_decode: {e}",
            }

        cargos = data.get("cargos_similares", [])
        if not isinstance(cargos, list):
            cargos = []
        cargos_limpios = [
            str(c).strip() for c in cargos
            if isinstance(c, str) and c.strip()
        ]
        tipo_obra = data.get("tipo_obra")
        if tipo_obra and not isinstance(tipo_obra, str):
            tipo_obra = None

        # Red de seguridad anti-alucinacion: cada cargo debe aparecer
        # literalmente en el texto de la celda. Si el LLM invento variantes
        # ("Mitigacion Ambiental" cuando el texto solo dice "Medio Ambiente"),
        # las descartamos aqui.
        cargos_validos, alucinaciones = _filtrar_alucinaciones(
            cargos_limpios, texto_limpio,
        )

        if alucinaciones:
            logger.warning(
                "[cell-parser] B.2: %d alucinacion(es) descartadas: %s",
                len(alucinaciones), alucinaciones[:5],
            )

        logger.info(
            "[cell-parser] B.2 parseada: %d cargos validos (%d filtrados) en %.1fs",
            len(cargos_validos), len(alucinaciones), elapsed,
        )
        return {
            "cargos_similares": cargos_validos,
            "tipo_obra": tipo_obra,
            "_elapsed_s": round(elapsed, 2),
            "_alucinaciones_descartadas": alucinaciones,
        }

    except Exception as e:
        logger.warning("[cell-parser] B.2 LLM fallo: %s", e)
        return {
            "cargos_similares": [],
            "tipo_obra": None,
            "_error": str(e),
        }


# ── Parser de B.2 verbosa con regex puro (fallback sin LLM) ──────────────────

# Marcadores que indican el final de la lista de cargos en B.2
_FIN_LISTA_CARGOS_RE = re.compile(
    r"\s+o\s+la\s+combinaci[oó]n\s+de\s+est[oa]s|"
    r"\s+y/o\s+la\s+combinaci[oó]n\s+de\s+est[oa]s|"
    r"\s+en\s+la\s+supervisi[oó]n|"
    r"\s+en\s+la\s+ejecuci[oó]n",
    re.IGNORECASE,
)

# Marcadores de tipo de obra (subespecialidad)
_TIPO_OBRA_RE = re.compile(
    r"subespecialidad\s+[\"']?([^\"'\.]+)[\"']?",
    re.IGNORECASE,
)


def parsear_b2_celda_regex(texto_celda: str) -> dict:
    """
    Parser regex puro para B.2 — fallback sin LLM.

    Menos preciso que el LLM (no entiende patrones prefijo+sufijo) pero
    sirve cuando el LLM falla o queremos respuesta inmediata.
    """
    if not texto_celda:
        return {"cargos_similares": [], "tipo_obra": None}

    texto = _FOOTNOTE_RE.sub("", texto_celda)
    texto = re.sub(r"\s+", " ", texto).strip()

    # Cortar al inicio de la frase de cierre
    m_fin = _FIN_LISTA_CARGOS_RE.search(texto)
    if m_fin:
        lista_cargos_raw = texto[:m_fin.start()].strip()
        sufijo = texto[m_fin.end():]
    else:
        lista_cargos_raw = texto
        sufijo = ""

    # Split por "y/o"
    cargos = [
        c.strip(" ,.;:-")
        for c in re.split(r"\s*y/o\s*", lista_cargos_raw, flags=re.IGNORECASE)
    ]
    cargos = [c for c in cargos if c and len(c) > 3]

    # Tipo de obra
    tipo_obra = None
    m_tipo = _TIPO_OBRA_RE.search(texto)
    if m_tipo:
        tipo_obra = m_tipo.group(1).strip(" \"'.;:")

    return {
        "cargos_similares": cargos,
        "tipo_obra": tipo_obra,
    }


# ── Helper para identificar tipo de tabla ────────────────────────────────────

def es_cabecera_b1(cabecera: list[str]) -> bool:
    """Detecta si la primera fila de una tabla es B.1 CALIFICACION."""
    texto = " ".join(c.upper() for c in cabecera if c)
    tiene_cargo = any(k in texto for k in ["CARGO", "RESPONSABILIDAD"])
    tiene_formacion = any(k in texto for k in ["FORMACION", "FORMACIÓN", "ACADEMICA", "ACADÉMICA"])
    return tiene_cargo and tiene_formacion


def es_cabecera_b2(cabecera: list[str]) -> bool:
    """Detecta si la primera fila de una tabla es B.2 EXPERIENCIA."""
    texto = " ".join(c.upper() for c in cabecera if c)
    tiene_cargo = any(k in texto for k in ["CARGO", "ROL"])
    tiene_tiempo = any(k in texto for k in ["TIEMPO", "EXPERIENCIA"])
    tiene_trabajos = any(k in texto for k in ["TRABAJOS", "PRESTACIONES", "ACTIVIDAD"])
    return tiene_cargo and (tiene_tiempo or tiene_trabajos)
