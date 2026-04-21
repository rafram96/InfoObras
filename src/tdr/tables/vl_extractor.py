"""
Extractor visual estructurado de tablas B.1 y B.2 de TDRs OSCE.

A diferencia de `vision.py` (que retorna markdown), este modulo pide al
VL un JSON directo con los campos que necesita el pipeline:
  - B.1: {numero, cargo, profesiones[]}
  - B.2: {numero, cargo, tiempo_meses, cargos_similares[], descripcion}

Ventaja: Qwen-VL ve el layout visual de la tabla — no depende del OCR
fragmentado que mezcla columnas. Elimina cross-fila y profesiones
incompletas de raiz.

Uso tipico:
    from src.tdr.tables.image_utils import extraer_multiples_paginas
    from src.tdr.tables.vl_extractor import extraer_b1_visual, extraer_b2_visual

    paginas_img = extraer_multiples_paginas(pdf_path, paginas_b1)
    filas_b1 = extraer_b1_visual([pi.imagen for pi in paginas_img])

    paginas_img = extraer_multiples_paginas(pdf_path, paginas_b2)
    filas_b2 = extraer_b2_visual([pi.imagen for pi in paginas_img])
"""
from __future__ import annotations
import base64
import io
import json
import logging
import re
import time
from typing import Optional

import requests
from PIL import Image

from src.tdr.config.settings import (
    QWEN_VL_MODEL,
    QWEN_VL_TIMEOUT,
    OLLAMA_BASE_URL,
    TABLE_VL_MAX_PX,
)

logger = logging.getLogger(__name__)


# ── Utilidades de imagen (copiadas de vision.py para no acoplar) ─────────────

def _redimensionar(imagen: Image.Image, max_px: int = TABLE_VL_MAX_PX) -> Image.Image:
    w, h = imagen.size
    lado_max = max(w, h)
    if lado_max <= max_px:
        return imagen
    escala = max_px / lado_max
    return imagen.resize((int(w * escala), int(h * escala)), Image.LANCZOS)


def _imagen_a_base64(imagen: Image.Image) -> str:
    imagen = _redimensionar(imagen)
    if imagen.mode in ("RGBA", "LA", "P"):
        imagen = imagen.convert("RGB")
    buf = io.BytesIO()
    imagen.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── Llamada al VL esperando JSON ──────────────────────────────────────────────

def _llamar_qwen_vl_json(
    imagenes: list[Image.Image],
    prompt: str,
    max_tokens: int = 4096,
) -> Optional[dict]:
    """
    Llama Qwen-VL con prompt que pide JSON y parsea la respuesta.
    Retorna el dict parseado o None si falla.
    """
    images_b64 = [_imagen_a_base64(img) for img in imagenes]

    logger.info(f"[vl-extractor] Enviando {len(imagenes)} imagen(es) al VL")

    payload = {
        "model": QWEN_VL_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": images_b64,
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0,
            "num_predict": max_tokens,
            "num_ctx": 8192,
        },
    }

    max_reintentos = 2
    for intento in range(max_reintentos + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json=payload,
                timeout=QWEN_VL_TIMEOUT,
            )
            resp.raise_for_status()
            raw = resp.json().get("message", {}).get("content", "").strip()

            # Limpiar bloque ```json ... ```
            raw = _limpiar_bloque_markdown(raw)

            if not raw:
                logger.warning("[vl-extractor] Respuesta vacia")
                return None

            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                # Intento de reparar
                reparado = _extraer_json_de_respuesta(raw)
                if reparado is not None:
                    return reparado
                logger.warning(
                    f"[vl-extractor] JSON invalido: {e}. Raw snippet: {raw[:500]!r}"
                )
                return None

        except requests.Timeout:
            logger.error(f"[vl-extractor] Timeout {QWEN_VL_TIMEOUT}s")
            return None
        except requests.HTTPError as e:
            if resp.status_code == 500 and intento < max_reintentos:
                wait = 5 * (intento + 1)
                logger.warning(
                    f"[vl-extractor] HTTP 500 intento {intento + 1}, reintentando en {wait}s"
                )
                time.sleep(wait)
                continue
            logger.error(f"[vl-extractor] Error HTTP: {e}")
            return None
        except Exception as e:
            logger.error(f"[vl-extractor] Error: {e}")
            return None
    return None


def _limpiar_bloque_markdown(texto: str) -> str:
    """Remueve ```json ... ``` y similares del raw del LLM."""
    texto = texto.strip()
    # Caso: ```json\n{...}\n```
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", texto, re.DOTALL)
    if m:
        return m.group(1).strip()
    return texto


def _extraer_json_de_respuesta(texto: str) -> Optional[dict]:
    """
    Fallback: extrae el primer {...} balanceado del texto.
    Util cuando el LLM pone preambulo antes del JSON.
    """
    start = texto.find("{")
    if start < 0:
        return None
    # Buscar el cierre balanceado
    depth = 0
    for i in range(start, len(texto)):
        if texto[i] == "{":
            depth += 1
        elif texto[i] == "}":
            depth -= 1
            if depth == 0:
                candidato = texto[start: i + 1]
                try:
                    return json.loads(candidato)
                except json.JSONDecodeError:
                    # Intentar con json_repair si esta instalado
                    try:
                        from json_repair import repair_json  # type: ignore
                        return json.loads(repair_json(candidato))
                    except Exception:
                        return None
    return None


# ── Prompts ───────────────────────────────────────────────────────────────────

_PROMPT_B1 = """You are extracting a table from a Peruvian OSCE tender document (TDR).

The image contains the table "B.1 CALIFICACION DEL PERSONAL CLAVE" with 4 columns:
  N° | CARGO Y/O RESPONSABILIDAD | FORMACION ACADEMICA | GRADO O TITULO PROFESIONAL

For EACH numbered row, extract the data. Be STRICT about column boundaries —
the "FORMACION ACADEMICA" value for row N is ONLY what's written in row N's
cell, never mix with adjacent rows.

Rules for "profesiones":
- They are university titles: "Ingeniero Civil", "Arquitecto", "Tecnologo Medico",
  "Medico", "Ingeniero Electromecanico", "Licenciado en X", etc.
- If the cell says "X y/o Y y/o Z", extract all three as a list.
- Copy EXACTLY what's in the cell. Do NOT infer or invent titles derived from
  the job name (e.g. for "ESPECIALISTA EN COSTOS" do NOT invent "Ingeniero en Costos").
- Never use just "Ingeniero" alone — always with specialty (Civil, Sanitario, etc.).
- "Arquitecto", "Medico", "Tecnologo Medico" alone ARE valid (they are complete titles).
- Include footnote numbers (68, 69, 75) — those are references, ignore them.
- Reconstruct words that the OCR may have fragmented across lines.

Respond ONLY with strict JSON (no preamble, no markdown):
{
  "filas": [
    {"numero": 1, "cargo": "GERENTE DE CONTRATO", "profesiones": ["Ingeniero Civil", "Arquitecto"]},
    {"numero": 2, "cargo": "JEFE DE SUPERVISION", "profesiones": ["Ingeniero Civil", "Arquitecto"]}
  ]
}

If a row has a footnote or unclear cell, include what you can see with the values
available. Do NOT skip numbered rows."""


_PROMPT_B2 = """You are extracting a table from a Peruvian OSCE tender document (TDR).

The image contains the table "B.2 EXPERIENCIA DEL PERSONAL CLAVE" with 4 columns:
  N° | CARGO/ROL | TIEMPO DE EXPERIENCIA | TRABAJOS O PRESTACIONES EN LA ACTIVIDAD REQUERIDA

For EACH numbered row, extract:

(a) "numero": integer from column N°.

(b) "cargo": exact text from "CARGO/ROL".

(c) "tiempo_meses": integer months from "TIEMPO DE EXPERIENCIA". The cell says
    things like "Experiencia minima de (24) meses" — extract 24 as number.

(d) "cargos_similares": list of job titles from "TRABAJOS O PRESTACIONES",
    separated by "y/o". Examples: "Gerente de Obra", "Jefe de Supervision",
    "Especialista en Instalaciones Sanitarias". Stop when you reach phrases like
    "o la combinacion de estos" or "en la supervision y/o ejecucion" (those mark
    the end of the list). Do NOT include the sector/specialty text.

(e) "tipo_obra": the sector mentioned AFTER the list of jobs, e.g.
    "establecimientos de salud", "edificaciones y afines". Extract the most
    specific subespecialidad if both appear.

(f) "descripcion": literal copy of the complete "TRABAJOS O PRESTACIONES" cell
    text, exactly as written (including "y/o", quotes, etc.).

Be STRICT about column boundaries — each row's data comes only from that row.

Respond ONLY with strict JSON (no preamble, no markdown):
{
  "filas": [
    {
      "numero": 1,
      "cargo": "GERENTE DE CONTRATO",
      "tiempo_meses": 24,
      "cargos_similares": ["Gerente de Obra", "Gerente de Proyecto", "Coordinador de Obra"],
      "tipo_obra": "establecimientos de salud",
      "descripcion": "Gerente de Obra, y/o Gerente de Proyecto y/o..."
    }
  ]
}

Do NOT skip numbered rows. If a row has OCR fragmentation, include the visible
data with the fields you can infer."""


# ── API publica ───────────────────────────────────────────────────────────────

def extraer_b1_visual(imagenes: list[Image.Image]) -> list[dict]:
    """
    Extrae la tabla B.1 CALIFICACION DEL PERSONAL CLAVE de las imagenes.
    Retorna lista de filas con {numero, cargo, profesiones}.
    """
    if not imagenes:
        return []
    data = _llamar_qwen_vl_json(imagenes, _PROMPT_B1)
    if not data:
        return []
    filas = data.get("filas", [])
    if not isinstance(filas, list):
        return []
    # Normalizar
    resultado = []
    for f in filas:
        if not isinstance(f, dict):
            continue
        numero = f.get("numero")
        if not isinstance(numero, int):
            try:
                numero = int(numero)
            except (TypeError, ValueError):
                continue
        profs = f.get("profesiones") or []
        if not isinstance(profs, list):
            profs = []
        resultado.append({
            "numero": numero,
            "cargo": str(f.get("cargo") or "").strip(),
            "profesiones": [str(p).strip() for p in profs if isinstance(p, str) and p.strip()],
        })
    logger.info(f"[vl-extractor] B.1: {len(resultado)} filas extraidas")
    return resultado


def extraer_b2_visual(imagenes: list[Image.Image]) -> list[dict]:
    """
    Extrae la tabla B.2 EXPERIENCIA DEL PERSONAL CLAVE de las imagenes.
    Retorna lista de filas con {numero, cargo, tiempo_meses, cargos_similares,
    tipo_obra, descripcion}.
    """
    if not imagenes:
        return []
    data = _llamar_qwen_vl_json(imagenes, _PROMPT_B2, max_tokens=6144)
    if not data:
        return []
    filas = data.get("filas", [])
    if not isinstance(filas, list):
        return []
    resultado = []
    for f in filas:
        if not isinstance(f, dict):
            continue
        numero = f.get("numero")
        if not isinstance(numero, int):
            try:
                numero = int(numero)
            except (TypeError, ValueError):
                continue
        cargos_sim = f.get("cargos_similares") or []
        if not isinstance(cargos_sim, list):
            cargos_sim = []
        tiempo = f.get("tiempo_meses")
        if not isinstance(tiempo, int):
            try:
                tiempo = int(tiempo) if tiempo is not None else None
            except (TypeError, ValueError):
                tiempo = None
        resultado.append({
            "numero": numero,
            "cargo": str(f.get("cargo") or "").strip(),
            "tiempo_meses": tiempo,
            "cargos_similares": [
                str(c).strip() for c in cargos_sim
                if isinstance(c, str) and c.strip()
            ],
            "tipo_obra": str(f.get("tipo_obra") or "").strip() or None,
            "descripcion": str(f.get("descripcion") or "").strip() or None,
        })
    logger.info(f"[vl-extractor] B.2: {len(resultado)} filas extraidas")
    return resultado
