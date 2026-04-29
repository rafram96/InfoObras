"""
Capa 3 — Segmentacion regex de filas + LLM por fila aislada.

Cuando Capas 1 (pdfplumber) y 2 (PP-Structure) fallan en detectar la
estructura de tabla, esta capa funciona sobre TEXTO OCR plano:

1. Detecta los 17 puntos de inicio de fila usando un catalogo de
   cargos OSCE como anclas (mas robusto que detectar numeros sueltos
   que el OCR puede romper).

2. Particiona el texto en chunks, uno por fila identificada.

3. Llama al LLM una vez POR FILA con prompt minimo.
   El LLM solo ve esa fila → cero cross-row contamination posible.

Trade-off: 17 llamadas LLM en vez de 1 (~3-4 min con Qwen). Pero
elimina row-crossing por arquitectura. Es la red de seguridad.
"""
from __future__ import annotations
import json
import logging
import re
import time
import unicodedata
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
    _limpiar_json_raw,
)

logger = logging.getLogger(__name__)


# ── Catalogo de cargos OSCE como anclas para segmentacion ────────────────────

# Estos son los cargos tipicos de personal clave en TDRs OSCE de
# supervision de obras de construccion. La segmentacion se ancla a
# estos cargos porque el OCR puede romper los numeros de fila pero
# raramente rompe el nombre del cargo.
CATALOGO_CARGOS_OSCE = [
    "GERENTE DE CONTRATO",
    "JEFE DE SUPERVISION",
    "JEFE DE SUPERVISIÓN",
    "INGENIERO DE CAMPO",
    "ESPECIALISTA EN ARQUITECTURA",
    "ESPECIALISTA EN ESTRUCTURAS",
    "ESPECIALISTA EN INSTALACIONES SANITARIAS",
    "ESPECIALISTA EN INSTALACIONES ELECTRICAS",
    "ESPECIALISTA EN INSTALACIONES ELÉCTRICAS",
    "ESPECIALISTA EN INSTALACIONES MECANICAS",
    "ESPECIALISTA EN INSTALACIONES MECÁNICAS",
    "ESPECIALISTA EN INSTALACIONES ELECTROMECANICAS",
    "ESPECIALISTA EN INSTALACIONES ELECTROMECÁNICAS",
    "ESPECIALISTA EN COMUNICACIONES",
    "ESPECIALISTA EN EQUIPAMIENTO HOSPITALARIO",
    "ESPECIALISTA EN EQUIPAMIENTO MEDICO",
    "ESPECIALISTA EN EQUIPAMIENTO MÉDICO",
    "ESPECIALISTA EN CONTROL Y ASEGURAMIENTO DE LA CALIDAD",
    "ESPECIALISTA EN CONTROL DE CALIDAD",
    "ESPECIALISTA EN SEGURIDAD Y SALUD EN EL TRABAJO",
    "ESPECIALISTA EN SEGURIDAD Y SALUD",
    "ESPECIALISTA EN SEGURIDAD",
    "ESPECIALISTA EN MEDIO AMBIENTE",
    "ESPECIALISTA AMBIENTAL",
    "ESPECIALISTA EN COSTOS, METRADOS Y VALORIZACIONES",
    "ESPECIALISTA EN COSTOS Y PRESUPUESTOS",
    "ESPECIALISTA EN GEOTECNIA",
    "ESPECIALISTA EN MECANICA DE SUELOS",
    "ESPECIALISTA EN MECÁNICA DE SUELOS",
    "ESPECIALISTA BIM",
    "ESPECIALISTA EN BIM",
    "RESIDENTE DE OBRA",
    "ASISTENTE DE SUPERVISION",
    "ASISTENTE DE SUPERVISIÓN",
]


def _normalizar_para_match(texto: str) -> str:
    """Normaliza texto: mayusculas, sin tildes, espacios colapsados."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFD", texto.upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\s+", " ", t).strip()
    return t


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

    for cargo in CATALOGO_CARGOS_OSCE:
        cargo_norm = _normalizar_para_match(cargo)
        # partial_ratio acepta substring fuzzy (linea puede tener prefijo numero, etc.)
        score = fuzz.partial_ratio(cargo_norm, linea_norm)
        if score > mejor_score:
            mejor_score = score
            mejor_cargo = cargo

    if mejor_score >= threshold:
        return mejor_cargo
    return None


def segmentar_filas_b1(texto: str, esperados: int = 17) -> list[tuple[int, str, str]]:
    """
    Segmenta el texto en chunks, uno por fila B.1.

    Returns:
        list de (numero_fila, cargo_canonical, texto_chunk)

    Estrategia:
    1. Recorre lineas
    2. Detecta inicios de fila por match contra catalogo de cargos
    3. Asigna numero secuencial (1, 2, ..., 17) en orden de aparicion
    4. Cada chunk va desde su linea de inicio hasta la siguiente (exclusiva)
    """
    lineas = texto.split("\n")

    # Encontrar lineas que son inicio de fila
    inicios: list[tuple[int, str]] = []  # (linea_idx, cargo_canonical)
    for i, linea in enumerate(lineas):
        cargo = _es_inicio_de_fila(linea)
        if cargo:
            # Evitar duplicados consecutivos (cuando el cargo se rompe en
            # 2 lineas, ambas matchean)
            if inicios and inicios[-1][1] == cargo and (i - inicios[-1][0]) < 3:
                continue
            inicios.append((i, cargo))

    logger.info(
        "[layer3] Segmentacion: %d cargos detectados (esperados %d)",
        len(inicios), esperados,
    )

    if not inicios:
        return []

    # Construir chunks
    chunks: list[tuple[int, str, str]] = []
    for j, (idx_actual, cargo) in enumerate(inicios):
        idx_fin = inicios[j + 1][0] if j + 1 < len(inicios) else len(lineas)
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

REGLAS:
1. profesiones_aceptadas son TITULOS: "Ingeniero Civil", "Arquitecto", "Tecnologo Medico".
   NUNCA "Ingeniero" a secas. NUNCA puestos como "Especialista en X" en este campo.
2. cargos_similares son PUESTOS: "Especialista en X", "Jefe de Y", "Gerente de Z".
   NUNCA titulos academicos en este campo.
3. Solo extrae lo que esta literal en el texto. Si un campo no aparece, usa null o lista vacia.
4. NO inventes datos.

Responde SOLO con JSON valido:
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


def _llm_extraer_fila_aislada(
    numero: int,
    cargo_esperado: str,
    texto_chunk: str,
) -> Optional[FilaTDR]:
    """
    Llamada LLM con SOLO el chunk de UNA fila.
    El LLM no puede ver otras filas → cero cross-contamination.
    """
    if not texto_chunk.strip():
        return None

    prompt = _PROMPT_FILA_AISLADA.format(
        texto_fila=texto_chunk[:6000],   # cap de seguridad
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
                "[layer3] Fila %d JSON invalido (%s): %r",
                numero, e, cleaned[:300],
            )
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
            cargo=cargo.upper().strip(),
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

        logger.info(
            "[layer3] Fila %d (%s): %d profs, %d cargos similares en %.1fs",
            numero, cargo[:40], len(profs), len(cargos_sim), elapsed,
        )
        return fila

    except Exception as e:
        logger.warning("[layer3] Fila %d LLM fallo: %s", numero, e)
        return None


# ── API publica de la Capa 3 ─────────────────────────────────────────────────

def extraer_b1_b2_layer3(
    texto_b1: str,
    texto_b2: str,
    n_filas_esperadas: int = 17,
) -> tuple[list[FilaTDR], dict]:
    """
    Extraccion Capa 3: segmentacion regex + LLM por fila aislada.

    Args:
        texto_b1: texto OCR de las paginas que contienen la tabla B.1
        texto_b2: texto OCR de las paginas que contienen la tabla B.2
        n_filas_esperadas: cuantas filas se esperan (default 17 para hospitales OSCE)

    Returns:
        (filas, diagnostico)
    """
    diag: dict = {
        "capa": "layer3",
        "filas_segmentadas_b1": 0,
        "filas_segmentadas_b2": 0,
        "filas_extraidas_llm": 0,
        "errores": [],
    }

    # Segmentar B.1
    chunks_b1 = segmentar_filas_b1(texto_b1, esperados=n_filas_esperadas)
    diag["filas_segmentadas_b1"] = len(chunks_b1)

    if not chunks_b1:
        diag["errores"].append("Segmentacion B.1 no detecto cargos en el texto")
        # Si no detectamos B.1, intentar combinar texto B.1+B.2 y reintentar
        chunks_b1 = segmentar_filas_b1(texto_b1 + "\n" + texto_b2, esperados=n_filas_esperadas)
        diag["filas_segmentadas_b1"] = len(chunks_b1)

    # Tambien segmentar B.2 — los cargos aparecen igual en B.2
    chunks_b2_dict: dict[str, str] = {}
    if texto_b2 and texto_b2 != texto_b1:
        chunks_b2 = segmentar_filas_b1(texto_b2, esperados=n_filas_esperadas)
        diag["filas_segmentadas_b2"] = len(chunks_b2)
        chunks_b2_dict = {cargo: texto for _, cargo, texto in chunks_b2}

    # Para cada fila B.1 segmentada, fusionar con su correspondiente B.2 si existe
    filas: list[FilaTDR] = []
    for numero, cargo_canonical, texto_chunk_b1 in chunks_b1:
        # Buscar el chunk B.2 correspondiente al mismo cargo
        texto_b2_chunk = chunks_b2_dict.get(cargo_canonical, "")

        # Combinar B.1 + B.2 chunks para que el LLM tenga ambos contextos
        # pero AISLADO de las otras filas
        if texto_b2_chunk and texto_b2_chunk != texto_chunk_b1:
            texto_combinado = (
                f"=== TABLA B.1 (fila {numero}) ===\n"
                f"{texto_chunk_b1}\n\n"
                f"=== TABLA B.2 (fila {numero}) ===\n"
                f"{texto_b2_chunk}"
            )
        else:
            texto_combinado = texto_chunk_b1

        fila = _llm_extraer_fila_aislada(numero, cargo_canonical, texto_combinado)
        if fila:
            filas.append(fila)
        else:
            # Si LLM fallo, crear fila minima con regex sobre el chunk
            from src.tdr.extractor.table_extractor.cell_parser import (
                parsear_b2_celda_regex,
            )
            fallback = FilaTDR(
                numero_fila=numero,
                cargo=cargo_canonical,
                profesiones_aceptadas=[],
                pagina=None,
                confianza=Confianza.LAYER3_LLM_BLOQUE * 0.5,
                fuente="layer3-fallback",
                fila_texto_origen=texto_combinado[:500],
            )
            # Intento ultimo: regex sobre cargos similares
            datos_b2 = parsear_b2_celda_regex(texto_b2_chunk or texto_chunk_b1)
            fallback.experiencia_minima = ExperienciaMinima(
                cantidad=parsear_tiempo_meses(texto_combinado),
                cargos_similares_validos=datos_b2.get("cargos_similares", []),
            )
            fallback.tipo_obra_valido = datos_b2.get("tipo_obra")
            filas.append(fallback)

    diag["filas_extraidas_llm"] = len(filas)
    logger.info(
        "[layer3] Resultado: %d filas extraidas (esperadas %d)",
        len(filas), n_filas_esperadas,
    )

    return filas, diag
