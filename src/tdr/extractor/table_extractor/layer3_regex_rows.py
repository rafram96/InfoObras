"""
Capa 3 — Segmentacion regex de filas + LLM por fila aislada.

Cuando Capas 1 (pdfplumber) y 2 (PP-Structure) fallan en detectar la
estructura de tabla, esta capa funciona sobre TEXTO OCR plano:

1. Detecta los 17 puntos de inicio de fila usando un catalogo de
   cargos OSCE como anclas (mas robusto que detectar numeros sueltos
   que el OCR puede romper). Fallback: detectar "N° X" patterns.

2. Particiona el texto en chunks, uno por fila identificada.

3. Llama al LLM en PARALELO una vez POR FILA con prompt minimo.
   El LLM solo ve esa fila → cero cross-row contamination posible.

4. Valida post-extraccion: profesiones deben tener prefijo de titulo,
   cargos similares NO pueden ser titulos puros. Si el LLM confundio
   campos, los filtramos.

Trade-off: 17 llamadas LLM en paralelo (4 workers default, ~60-90s
con keep_alive del modelo Qwen). Elimina row-crossing por arquitectura.
"""
from __future__ import annotations
import json
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from openai import OpenAI
from rapidfuzz import fuzz

from src.tdr.config.settings import (
    QWEN_OLLAMA_BASE_URL,
    QWEN_OLLAMA_API_KEY,
    QWEN_MODEL,
    QWEN_MAX_TOKENS,
    QWEN_TIMEOUT,
    QWEN_NUM_CTX,
)
from src.tdr.extractor.table_extractor.models import (
    FilaTDR,
    ExperienciaMinima,
    Confianza,
)
from src.tdr.extractor.table_extractor.cell_parser import (
    parsear_profesiones,
    parsear_tiempo_meses,
    parsear_b2_celda_regex,
    _limpiar_json_raw,
    _PREFIJOS_TITULO,
)

logger = logging.getLogger(__name__)


# ── Catalogo de cargos OSCE como anclas para segmentacion ────────────────────

# Cargos tipicos del personal clave en TDRs OSCE de obras hospitalarias.
# La segmentacion se ancla a estos cargos porque el OCR puede romper los
# numeros de fila pero raramente rompe el nombre del cargo.
#
# Formato: incluir tildes y sin tildes para que el normalizador maneje ambos.
CATALOGO_CARGOS_OSCE = [
    # Gerencia / direccion
    "GERENTE DE CONTRATO",
    "GERENTE DE PROYECTO",
    "GERENTE DE OBRA",
    "JEFE DE SUPERVISION",
    "JEFE DE SUPERVISIÓN",
    "JEFE DE PROYECTO",
    "JEFE DE OBRA",
    "DIRECTOR DE PROYECTO",
    "COORDINADOR DE OBRA",
    "COORDINADOR DE PROYECTO",

    # Ingenieria de campo
    "INGENIERO DE CAMPO",
    "INGENIERO RESIDENTE",
    "RESIDENTE DE OBRA",
    "RESIDENTE DE SUPERVISION",
    "RESIDENTE DE SUPERVISIÓN",
    "ASISTENTE DE SUPERVISION",
    "ASISTENTE DE SUPERVISIÓN",
    "ASISTENTE TECNICO",
    "ASISTENTE TÉCNICO",

    # Especialistas tecnicos
    "ESPECIALISTA EN ARQUITECTURA",
    "ESPECIALISTA EN ARQUITECTURA HOSPITALARIA",
    "ESPECIALISTA EN ESTRUCTURAS",
    "ESPECIALISTA EN INSTALACIONES SANITARIAS",
    "ESPECIALISTA EN INSTALACIONES ELECTRICAS",
    "ESPECIALISTA EN INSTALACIONES ELÉCTRICAS",
    "ESPECIALISTA EN INSTALACIONES MECANICAS",
    "ESPECIALISTA EN INSTALACIONES MECÁNICAS",
    "ESPECIALISTA EN INSTALACIONES ELECTROMECANICAS",
    "ESPECIALISTA EN INSTALACIONES ELECTROMECÁNICAS",
    "ESPECIALISTA EN INSTALACIONES",
    "ESPECIALISTA EN COMUNICACIONES",
    "ESPECIALISTA EN COMUNICACIONES Y CABLEADO",
    "ESPECIALISTA EN GASES MEDICINALES",
    "ESPECIALISTA EN GAS NATURAL",

    # Equipamiento
    "ESPECIALISTA EN EQUIPAMIENTO HOSPITALARIO",
    "ESPECIALISTA EN EQUIPAMIENTO MEDICO",
    "ESPECIALISTA EN EQUIPAMIENTO MÉDICO",
    "ESPECIALISTA EN EQUIPAMIENTO",

    # Calidad / seguridad / ambiente
    "ESPECIALISTA EN CONTROL Y ASEGURAMIENTO DE LA CALIDAD",
    "ESPECIALISTA EN CONTROL DE CALIDAD",
    "ESPECIALISTA EN ASEGURAMIENTO DE CALIDAD",
    "ESPECIALISTA EN SEGURIDAD Y SALUD EN EL TRABAJO",
    "ESPECIALISTA EN SEGURIDAD Y SALUD",
    "ESPECIALISTA EN SEGURIDAD",
    "ESPECIALISTA EN MEDIO AMBIENTE",
    "ESPECIALISTA AMBIENTAL",
    "ESPECIALISTA EN GESTION AMBIENTAL",
    "ESPECIALISTA EN GESTIÓN AMBIENTAL",

    # Costos / programacion
    "ESPECIALISTA EN COSTOS, METRADOS Y VALORIZACIONES",
    "ESPECIALISTA EN COSTOS Y VALORIZACIONES",
    "ESPECIALISTA EN COSTOS Y PRESUPUESTOS",
    "ESPECIALISTA EN METRADOS Y COSTOS",
    "ESPECIALISTA EN COSTOS",
    "ESPECIALISTA EN PROGRAMACION DE OBRA",
    "ESPECIALISTA EN PROGRAMACIÓN DE OBRA",
    "ESPECIALISTA EN PLANIFICACION",
    "ESPECIALISTA EN PLANIFICACIÓN",

    # Geotecnia / suelos
    "ESPECIALISTA EN GEOTECNIA",
    "ESPECIALISTA EN MECANICA DE SUELOS",
    "ESPECIALISTA EN MECÁNICA DE SUELOS",
    "ESPECIALISTA EN GEOLOGIA",
    "ESPECIALISTA EN GEOLOGÍA",
    "ESPECIALISTA EN PAVIMENTOS",

    # BIM / digital
    "ESPECIALISTA BIM",
    "ESPECIALISTA EN BIM",
    "COORDINADOR BIM",

    # Otros frecuentes en hospitales
    "ESPECIALISTA EN INFRAESTRUCTURA HOSPITALARIA",
    "ESPECIALISTA SOCIAL",
    "ESPECIALISTA EN GESTION SOCIAL",
    "ESPECIALISTA EN GESTIÓN SOCIAL",
    "ESPECIALISTA EN VIGILANCIA TECNOLOGICA",
    "ESPECIALISTA EN PUESTA EN MARCHA",
]


def _normalizar_para_match(texto: str) -> str:
    """Normaliza texto: mayusculas, sin tildes, espacios colapsados."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFD", texto.upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\s+", " ", t).strip()
    return t


# Catalogo pre-normalizado para evitar normalizar 70+ entradas en cada match
_CATALOGO_NORMALIZADO: list[tuple[str, str]] = [
    (cargo, _normalizar_para_match(cargo)) for cargo in CATALOGO_CARGOS_OSCE
]


# ── Detector de inicios de fila ──────────────────────────────────────────────

def _es_inicio_de_fila(linea: str, threshold: int = 85) -> Optional[str]:
    """
    Si la linea es probablemente el inicio de una fila B.1, retorna
    el cargo canonicalizado del catalogo. Si no, retorna None.

    Usa fuzzy match para tolerar OCR ruidoso ("GERENTEDE CONTRATO" → "GERENTE DE CONTRATO").
    """
    linea_norm = _normalizar_para_match(linea)
    if len(linea_norm) < 8:
        return None

    mejor_score = 0
    mejor_cargo = None

    for cargo, cargo_norm in _CATALOGO_NORMALIZADO:
        # partial_ratio acepta substring fuzzy (linea puede tener prefijo numero)
        score = fuzz.partial_ratio(cargo_norm, linea_norm)
        # Prioriza match mas largo si tienen mismo score
        if score > mejor_score or (
            score == mejor_score
            and mejor_cargo
            and len(cargo) > len(mejor_cargo)
        ):
            mejor_score = score
            mejor_cargo = cargo

    if mejor_score >= threshold:
        return mejor_cargo
    return None


# Patron para detectar numero de fila al inicio de linea: "1", "01", "1)", "1.", "N° 1"
_NUM_INICIO_RE = re.compile(
    r"^\s*(?:N[°º]\.?\s*)?(\d{1,2})\s*[\.\)\-\s]+\s*([A-ZÁÉÍÓÚÑ])"
)


def _es_inicio_por_numero(linea: str) -> Optional[int]:
    """
    Fallback: detecta si la linea empieza con "1.", "01)", "N° 1 -" etc.
    Util cuando el cargo no matchea el catalogo (cargo nuevo no listado).
    """
    if not linea or len(linea) < 4:
        return None
    m = _NUM_INICIO_RE.match(linea.strip())
    if m:
        n = int(m.group(1))
        if 1 <= n <= 30:  # asumimos max 30 cargos en un TDR
            return n
    return None


def segmentar_filas_b1(texto: str, esperados: int = 17) -> list[tuple[int, str, str]]:
    """
    Segmenta el texto en chunks, uno por fila B.1.

    Returns:
        list de (numero_fila, cargo_canonical, texto_chunk)

    Estrategia (en orden de prioridad):
    1. Catalogo OSCE — detecta inicios por nombre de cargo (fuzzy match)
    2. Si segmentacion por catalogo da < 50% de los esperados, fallback a
       deteccion por numero al inicio de linea ("1.", "01)", etc.)
    3. Cada chunk va desde su linea de inicio hasta la siguiente (exclusiva)
    """
    lineas = texto.split("\n")

    # ── Pasada 1: anclaje por catalogo OSCE ──────────────────────────────
    inicios_catalogo: list[tuple[int, str]] = []  # (linea_idx, cargo_canonical)
    for i, linea in enumerate(lineas):
        cargo = _es_inicio_de_fila(linea)
        if cargo:
            # Evitar duplicados consecutivos (cuando el cargo se rompe en
            # 2 lineas, ambas matchean)
            if (
                inicios_catalogo
                and inicios_catalogo[-1][1] == cargo
                and (i - inicios_catalogo[-1][0]) < 3
            ):
                continue
            inicios_catalogo.append((i, cargo))

    # ── Pasada 2 (fallback): si catalogo encontro pocos, usar numeros ────
    inicios_finales = inicios_catalogo
    if len(inicios_catalogo) < max(3, esperados // 2):
        logger.info(
            "[layer3] Catalogo solo encontro %d/%d cargos — intentando "
            "fallback por numero de fila",
            len(inicios_catalogo), esperados,
        )
        inicios_numero: list[tuple[int, str]] = []
        for i, linea in enumerate(lineas):
            n = _es_inicio_por_numero(linea)
            if n is not None:
                # Buscar el cargo en la misma linea (despues del numero)
                m = _NUM_INICIO_RE.match(linea.strip())
                if m:
                    resto = linea.strip()[m.end() - 1:].strip()  # incluir letra inicial
                    cargo_inferido = resto[:80].strip()
                else:
                    cargo_inferido = f"FILA_{n}"
                inicios_numero.append((i, cargo_inferido))

        # Solo usar si encontramos mas que con catalogo
        if len(inicios_numero) > len(inicios_catalogo):
            inicios_finales = inicios_numero
            logger.info(
                "[layer3] Fallback numero encontro %d filas — usando esa segmentacion",
                len(inicios_numero),
            )

    logger.info(
        "[layer3] Segmentacion: %d cargos detectados (esperados %d)",
        len(inicios_finales), esperados,
    )

    if not inicios_finales:
        return []

    # ── Construir chunks ────────────────────────────────────────────────
    chunks: list[tuple[int, str, str]] = []
    for j, (idx_actual, cargo) in enumerate(inicios_finales):
        idx_fin = (
            inicios_finales[j + 1][0]
            if j + 1 < len(inicios_finales)
            else len(lineas)
        )
        # Tomar tambien 1 linea antes por si el numero quedo en linea separada
        idx_inicio = max(0, idx_actual - 1)
        chunk_texto = "\n".join(lineas[idx_inicio:idx_fin]).strip()
        chunks.append((j + 1, cargo, chunk_texto))

    return chunks


# ── LLM por fila aislada ─────────────────────────────────────────────────────

_PROMPT_FILA_AISLADA = """Eres extractor de UNA SOLA fila del personal clave de un TDR OSCE peruano.

Texto de la fila (puede tener ruido OCR, footnotes, palabras pegadas):
---
{texto_fila}
---

Cargo esperado: {cargo}
Numero esperado: {numero}

Extrae:
- numero_fila (entero, debe ser {numero})
- cargo (literal, mayusculas como aparece)
- profesiones_aceptadas (titulos universitarios separados por "y/o" en la columna FORMACION ACADEMICA): lista
- experiencia_minima_meses (numero, busca "(N) meses" en el texto): integer o null
- cargos_similares (puestos en la columna TRABAJOS O PRESTACIONES separados por "y/o"): lista
- tipo_obra_valido (subespecialidad: "establecimientos de salud", etc.): string o null
- descripcion_b2 (copia literal del parrafo de TRABAJOS O PRESTACIONES): string

REGLAS CRITICAS:
1. profesiones_aceptadas son TITULOS UNIVERSITARIOS: "Ingeniero Civil", "Arquitecto", "Tecnologo Medico", "Medico", "Bachiller en X".
   PROHIBIDO: "Especialista en X", "Jefe de Y", "Gerente de Z" — esos son cargos, NO profesiones.
2. cargos_similares son PUESTOS LABORALES: "Especialista en Instalaciones", "Jefe de Supervision", "Gerente de Obra", "Coordinador BIM".
   PROHIBIDO: "Ingeniero", "Arquitecto", "Bachiller" — esos son titulos, NO cargos.
3. Solo extrae lo que esta literal en el texto. Si un campo no aparece, usa null o lista vacia.
4. NO inventes datos. NO sugieras profesiones similares. NO completes con "etc."
5. Si la celda B.2 dice "y/o la combinacion de estos" u "en la supervision/ejecucion", esas frases NO son cargos — descartalas.

Responde SOLO con JSON valido (sin markdown, sin explicacion):
{{
  "numero_fila": {numero},
  "cargo": "...",
  "profesiones_aceptadas": [...],
  "experiencia_minima_meses": ...,
  "cargos_similares": [...],
  "tipo_obra_valido": "...",
  "descripcion_b2": "..."
}}"""


_client_layer3: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client_layer3
    if _client_layer3 is None:
        _client_layer3 = OpenAI(
            base_url=QWEN_OLLAMA_BASE_URL,
            api_key=QWEN_OLLAMA_API_KEY,
            timeout=QWEN_TIMEOUT,
        )
    return _client_layer3


def _build_extra_body() -> dict:
    return {
        "format": "json",
        "keep_alive": "10m",
        "options": {"num_gpu": 99, "num_ctx": QWEN_NUM_CTX},
    }


# ── Validacion post-LLM ──────────────────────────────────────────────────────

# Palabras clave que indican que un texto es un CARGO (no una profesion)
_KEYWORDS_CARGO = (
    "ESPECIALISTA", "JEFE", "GERENTE", "RESIDENTE", "SUPERVISOR",
    "COORDINADOR", "DIRECTOR", "ASISTENTE", "INSPECTOR", "ENCARGADO",
    "RESPONSABLE",
)


def _es_titulo_profesional(texto: str) -> bool:
    """True si el texto empieza con un prefijo de titulo (Ingeniero, Arquitecto, etc.)."""
    if not texto:
        return False
    return any(texto.upper().startswith(p) for p in _PREFIJOS_TITULO)


def _es_cargo(texto: str) -> bool:
    """True si el texto contiene una keyword de cargo."""
    if not texto:
        return False
    upper = texto.upper()
    return any(kw in upper for kw in _KEYWORDS_CARGO)


def _validar_y_normalizar_fila(
    fila: FilaTDR,
    cargo_esperado: str,
) -> FilaTDR:
    """
    Aplica reglas de validacion post-LLM:

    1. profesiones_aceptadas: filtra entradas que NO sean titulos profesionales.
       Si una "profesion" claramente es un cargo (contiene "Especialista", "Jefe", etc.),
       la mueve a cargos_similares.

    2. cargos_similares: filtra entradas que claramente sean titulos puros
       ("Ingeniero", "Arquitecto" sin sufijo), sin embargo, mantiene "Ingeniero
       Sanitario" o similares por ser cargos validos.

    3. Si el cargo del LLM diverge mucho del esperado por catalogo, usar el esperado.
    """
    # ── 1. Filtrar profesiones — solo titulos validos ────────────────────
    profs_validas: list[str] = []
    profs_movidas_a_cargos: list[str] = []
    for p in fila.profesiones_aceptadas:
        p_clean = p.strip().strip(",.;:-")
        if not p_clean or len(p_clean) < 4:
            continue
        if _es_titulo_profesional(p_clean):
            profs_validas.append(p_clean)
        elif _es_cargo(p_clean):
            # Ej: el LLM puso "Especialista en X" en profesiones — mover a cargos
            profs_movidas_a_cargos.append(p_clean)
            logger.debug(
                "[layer3] Validacion: '%s' movido de profesiones a cargos_similares",
                p_clean,
            )
        # Si no es ni titulo ni cargo, descartarlo (basura del LLM)

    # Dedup case-insensitive
    seen = set()
    profs_dedup = []
    for p in profs_validas:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            profs_dedup.append(p)
    fila.profesiones_aceptadas = profs_dedup

    # ── 2. Filtrar cargos similares — descartar titulos puros ────────────
    cargos_actuales = list(fila.experiencia_minima.cargos_similares_validos)
    cargos_actuales.extend(profs_movidas_a_cargos)

    cargos_validos: list[str] = []
    for c in cargos_actuales:
        c_clean = c.strip().strip(",.;:-")
        if not c_clean or len(c_clean) < 5:
            continue
        # Descartar frases de relleno
        if re.search(
            r"(la combinaci[oó]n|en la supervisi[oó]n|en la ejecuci[oó]n)",
            c_clean.lower(),
        ):
            continue
        # Si parece un titulo puro (sin "Especialista" / "Jefe" / etc.) y
        # es muy corto, descartarlo
        if _es_titulo_profesional(c_clean) and not _es_cargo(c_clean):
            # Excepcion: "Ingeniero Sanitario" o "Ingeniero Residente" SI son cargos
            # Pero "Ingeniero" o "Arquitecto" solos NO
            palabras = c_clean.split()
            if len(palabras) <= 2:
                logger.debug(
                    "[layer3] Validacion: '%s' parece titulo puro, descartado de cargos",
                    c_clean,
                )
                continue
        cargos_validos.append(c_clean)

    # Dedup
    seen.clear()
    cargos_dedup = []
    for c in cargos_validos:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            cargos_dedup.append(c)
    fila.experiencia_minima.cargos_similares_validos = cargos_dedup

    # ── 3. Sanity check del cargo principal ──────────────────────────────
    cargo_actual_norm = _normalizar_para_match(fila.cargo)
    cargo_esperado_norm = _normalizar_para_match(cargo_esperado)
    if cargo_esperado_norm and cargo_actual_norm:
        score = fuzz.partial_ratio(cargo_esperado_norm, cargo_actual_norm)
        if score < 50 and not cargo_esperado.startswith("FILA_"):
            logger.warning(
                "[layer3] Cargo divergente fila %d: LLM='%s' vs esperado='%s' (score %d) — usando esperado",
                fila.numero_fila, fila.cargo, cargo_esperado, score,
            )
            fila.cargo = cargo_esperado.upper().strip()

    return fila


def _llm_extraer_fila_aislada(
    numero: int,
    cargo_esperado: str,
    texto_chunk: str,
    intento: int = 1,
) -> Optional[FilaTDR]:
    """
    Llamada LLM con SOLO el chunk de UNA fila.
    El LLM no puede ver otras filas → cero cross-contamination.

    Si el LLM devuelve JSON invalido, intenta una vez mas con prompt mas estricto.
    """
    if not texto_chunk.strip():
        return None

    prompt = _PROMPT_FILA_AISLADA.format(
        texto_fila=texto_chunk[:6000],
        cargo=cargo_esperado,
        numero=numero,
    )

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
                "[layer3] Fila %d JSON invalido (intento %d, %s): %r",
                numero, intento, e, cleaned[:300],
            )
            if intento == 1:
                # Reintento con prompt mas explicito
                logger.info("[layer3] Fila %d: reintentando", numero)
                return _llm_extraer_fila_aislada(numero, cargo_esperado, texto_chunk, intento=2)
            return None

        # Construir FilaTDR
        cargo = data.get("cargo") or cargo_esperado
        profs = data.get("profesiones_aceptadas") or []
        if not isinstance(profs, list):
            profs = []
        profs = [str(p).strip() for p in profs if isinstance(p, str) and p.strip()]

        exp_meses = data.get("experiencia_minima_meses")
        try:
            exp_meses = int(exp_meses) if exp_meses is not None else None
        except (ValueError, TypeError):
            exp_meses = None

        cargos_sim = data.get("cargos_similares") or []
        if not isinstance(cargos_sim, list):
            cargos_sim = []
        cargos_sim = [
            str(c).strip() for c in cargos_sim
            if isinstance(c, str) and c.strip()
        ]

        descripcion = data.get("descripcion_b2")
        tipo_obra = data.get("tipo_obra_valido")

        fila = FilaTDR(
            numero_fila=numero,
            cargo=cargo.upper().strip() if cargo else cargo_esperado,
            profesiones_aceptadas=profs,
            experiencia_minima=ExperienciaMinima(
                cantidad=exp_meses,
                unidad="meses",
                descripcion=descripcion,
                cargos_similares_validos=cargos_sim,
            ),
            tipo_obra_valido=tipo_obra,
            confianza=Confianza.LAYER3_REGEX_LLM,
            fuente="layer3",
            fila_texto_origen=texto_chunk[:500],
        )

        # Aplicar validacion post-LLM
        fila = _validar_y_normalizar_fila(fila, cargo_esperado)

        logger.info(
            "[layer3] Fila %d (%s): %d profs, %d cargos similares en %.1fs",
            numero, fila.cargo[:40],
            len(fila.profesiones_aceptadas),
            len(fila.experiencia_minima.cargos_similares_validos),
            elapsed,
        )
        return fila

    except Exception as e:
        logger.warning("[layer3] Fila %d LLM fallo: %s", numero, e)
        return None


# ── API publica de la Capa 3 ─────────────────────────────────────────────────

# Configuracion de paralelismo. Ollama puede correr varios prompts en paralelo
# pero como Qwen 14B es pesado, limitamos a 4 para no saturar la VRAM.
LAYER3_MAX_WORKERS = 4


def extraer_b1_b2_layer3(
    texto_b1: str,
    texto_b2: str,
    n_filas_esperadas: int = 17,
    max_workers: int = LAYER3_MAX_WORKERS,
) -> tuple[list[FilaTDR], dict]:
    """
    Extraccion Capa 3: segmentacion regex + LLM por fila aislada (paralelo).

    Args:
        texto_b1: texto OCR de las paginas que contienen la tabla B.1
        texto_b2: texto OCR de las paginas que contienen la tabla B.2
        n_filas_esperadas: cuantas filas se esperan (default 17 para hospitales OSCE)
        max_workers: llamadas LLM en paralelo (default 4, no exceder por VRAM)

    Returns:
        (filas, diagnostico)
    """
    diag: dict = {
        "capa": "layer3",
        "filas_segmentadas_b1": 0,
        "filas_segmentadas_b2": 0,
        "filas_extraidas_llm": 0,
        "filas_fallback_regex": 0,
        "max_workers": max_workers,
        "errores": [],
    }

    # ── Segmentar B.1 ────────────────────────────────────────────────────
    chunks_b1 = segmentar_filas_b1(texto_b1, esperados=n_filas_esperadas)
    diag["filas_segmentadas_b1"] = len(chunks_b1)

    if not chunks_b1:
        diag["errores"].append("Segmentacion B.1 no detecto cargos")
        # Si no detectamos B.1, intentar combinar texto B.1+B.2 y reintentar
        chunks_b1 = segmentar_filas_b1(
            texto_b1 + "\n" + texto_b2, esperados=n_filas_esperadas,
        )
        diag["filas_segmentadas_b1"] = len(chunks_b1)

    # Tambien segmentar B.2 — los cargos aparecen igual en B.2
    chunks_b2_dict: dict[str, str] = {}
    if texto_b2 and texto_b2 != texto_b1:
        chunks_b2 = segmentar_filas_b1(texto_b2, esperados=n_filas_esperadas)
        diag["filas_segmentadas_b2"] = len(chunks_b2)
        chunks_b2_dict = {cargo: texto for _, cargo, texto in chunks_b2}

    if not chunks_b1:
        diag["errores"].append("Sin chunks B.1 para procesar — capa 3 fallo total")
        return [], diag

    # ── Preparar tareas ──────────────────────────────────────────────────
    tareas: list[tuple[int, str, str]] = []
    for numero, cargo_canonical, texto_chunk_b1 in chunks_b1:
        # Buscar el chunk B.2 correspondiente al mismo cargo
        texto_b2_chunk = chunks_b2_dict.get(cargo_canonical, "")

        # Combinar B.1 + B.2 chunks AISLADO de las otras filas
        if texto_b2_chunk and texto_b2_chunk != texto_chunk_b1:
            texto_combinado = (
                f"=== TABLA B.1 (fila {numero}) ===\n"
                f"{texto_chunk_b1}\n\n"
                f"=== TABLA B.2 (fila {numero}) ===\n"
                f"{texto_b2_chunk}"
            )
        else:
            texto_combinado = texto_chunk_b1

        tareas.append((numero, cargo_canonical, texto_combinado))

    # ── Lanzar LLM por fila EN PARALELO ──────────────────────────────────
    logger.info(
        "[layer3] Lanzando %d tareas LLM con %d workers (Qwen keep_alive=10m)",
        len(tareas), max_workers,
    )
    t0 = time.perf_counter()

    filas_por_numero: dict[int, FilaTDR] = {}
    fallidas: list[tuple[int, str, str]] = []

    # Pre-warm: lanzar la primera tarea sola para que Ollama cargue Qwen.
    # Esto evita que las primeras N tareas paralelas timeouten esperando
    # por la carga del modelo.
    if tareas:
        primera = tareas[0]
        logger.info("[layer3] Pre-warm fila %d para cargar Qwen en GPU", primera[0])
        fila_primera = _llm_extraer_fila_aislada(*primera)
        if fila_primera:
            filas_por_numero[primera[0]] = fila_primera
        else:
            fallidas.append(primera)
        tareas_restantes = tareas[1:]
    else:
        tareas_restantes = []

    if tareas_restantes:
        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futuros = {
                exe.submit(_llm_extraer_fila_aislada, num, cargo, texto): (num, cargo, texto)
                for num, cargo, texto in tareas_restantes
            }
            for future in as_completed(futuros):
                num, cargo, texto = futuros[future]
                try:
                    fila = future.result()
                    if fila:
                        filas_por_numero[num] = fila
                    else:
                        fallidas.append((num, cargo, texto))
                except Exception as e:
                    logger.warning("[layer3] Future fila %d excepcion: %s", num, e)
                    fallidas.append((num, cargo, texto))

    elapsed_paralelo = time.perf_counter() - t0
    logger.info(
        "[layer3] %d/%d filas extraidas en %.1fs (paralelo)",
        len(filas_por_numero), len(tareas), elapsed_paralelo,
    )

    # ── Fallback regex para las que el LLM fallo ─────────────────────────
    for num, cargo, texto in fallidas:
        datos_b2 = parsear_b2_celda_regex(texto)
        fallback = FilaTDR(
            numero_fila=num,
            cargo=cargo if not cargo.startswith("FILA_") else "",
            profesiones_aceptadas=parsear_profesiones(texto),
            experiencia_minima=ExperienciaMinima(
                cantidad=parsear_tiempo_meses(texto),
                cargos_similares_validos=datos_b2.get("cargos_similares", []),
            ),
            tipo_obra_valido=datos_b2.get("tipo_obra"),
            pagina=None,
            confianza=Confianza.LAYER3_LLM_BLOQUE * 0.5,
            fuente="layer3-fallback",
            fila_texto_origen=texto[:500],
        )
        # Validar tambien el fallback
        fallback = _validar_y_normalizar_fila(fallback, cargo)
        filas_por_numero[num] = fallback
        diag["filas_fallback_regex"] += 1

    # ── Ordenar por numero_fila ──────────────────────────────────────────
    filas = [filas_por_numero[n] for n in sorted(filas_por_numero.keys())]

    diag["filas_extraidas_llm"] = len(tareas) - len(fallidas)
    diag["tiempo_paralelo_s"] = round(elapsed_paralelo, 1)
    logger.info(
        "[layer3] Resultado final: %d filas (LLM=%d, fallback=%d, esperadas=%d)",
        len(filas), diag["filas_extraidas_llm"], diag["filas_fallback_regex"],
        n_filas_esperadas,
    )

    return filas, diag
