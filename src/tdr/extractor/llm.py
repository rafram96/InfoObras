from __future__ import annotations
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import OpenAI

from src.tdr.config.settings import (
    QWEN_OLLAMA_BASE_URL, QWEN_OLLAMA_API_KEY,
    QWEN_MODEL, QWEN_MAX_TOKENS, QWEN_TIMEOUT, QWEN_NUM_CTX,
)
from src.tdr.config.signals import PROMPTS
from src.tdr.extractor.scorer import Block

logger = logging.getLogger(__name__)

# Donde se guarda el raw del LLM cuando la reparacion falla — para debug.
_LLM_ERRORS_DIR = Path("data/llm_errors")

# Donde se guarda CADA llamada LLM (prompt + raw + metadatos) para auditoria.
# Permite ver exactamente que vio y que respondio el modelo en cada paso.
_LLM_CALLS_DIR = Path("data/llm_calls")


def _guardar_call_llm(
    block_type: str,
    page_range: tuple,
    prompt: str,
    raw_response: str,
    usage: dict,
    elapsed_s: float,
    num_ctx: int,
    parsed_ok: bool,
    items_extracted: int,
    error: Optional[str] = None,
    model: Optional[str] = None,
    response_model: Optional[str] = None,
) -> Optional[Path]:
    """
    Guarda un dump completo de una llamada LLM para auditoria/debug.
    Usa el contextvar job_id del logger para organizar por job.
    Se invoca SIEMPRE, exitosa o no.
    """
    try:
        # Intentar leer job_id del contextvar de src.api.main (si esta importado)
        job_id = None
        try:
            from src.api.main import _JOB_ID_CTX
            job_id = _JOB_ID_CTX.get()
        except Exception:
            pass

        base = _LLM_CALLS_DIR / (job_id or "sin_job")
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        pags = f"{page_range[0]}-{page_range[1]}" if len(page_range) >= 2 else "x"
        path = base / f"{ts}_{block_type}_pags_{pags}.json"

        payload = {
            "timestamp": datetime.now().isoformat(),
            "job_id": job_id,
            "block_type": block_type,
            "page_range": list(page_range),
            "elapsed_s": round(elapsed_s, 2),
            "num_ctx": num_ctx,
            "model_solicitado": model,           # QWEN_MODEL del .env
            "model_respondido": response_model,   # modelo que Ollama reporta
            "prompt_chars": len(prompt),
            "prompt_tokens_est": len(prompt) // 3,
            "usage": usage,
            "parsed_ok": parsed_ok,
            "items_extracted": items_extracted,
            "error": error,
            "prompt": prompt,
            "raw_response": raw_response,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception as e:
        logger.warning(f"No se pudo guardar LLM call a disco: {e}")
        return None

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


def _limpiar_respuesta(raw: str) -> str:
    """Limpia </think>, texto previo, y bloques markdown."""
    # 1. Quitar bloque <think>...</think>
    if "</think>" in raw:
        raw = raw.split("</think>")[-1].strip()

    # 2. Buscar bloque ```json ... ``` en CUALQUIER parte de la respuesta
    #    (Qwen a veces mete "Basándome en..." antes del JSON)
    import re
    match = re.search(r"```(?:json)?\s*\n?(\{.*?})\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 3. Buscar el primer { ... } directo (sin bloque markdown)
    brace_start = raw.find("{")
    if brace_start > 0:
        raw = raw[brace_start:]

    # 4. Limpiar backticks sueltos
    raw = raw.strip("`").strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()
    return raw


# Patrones que indican que el LLM fabricó datos en vez de extraerlos
_FABRICATION_PATTERNS = [
    r"\bejemplo\b",
    r"\bplantilla\b",
    r"\bpodría ser\b",
    r"\basumiendo\b",
    r"\bgenéric[oa]\b",
    r"\bno se proporcion[aó]\b",
    r"\bno se especific[aó]\b",
    r"\bno se mencion[aó]\b",
    r"\bpara completar\b",
    r"\bnecesitar[ií]amos\b",
    r"\bproporcion[ae]s? más detalles\b",
    r"\bajust[aá][rd][oa]? según\b",
    r"\bcargo similar [A-Z]\b",
]


def _reparar_json(raw: str) -> Optional[dict]:
    """
    Intenta reparar JSON malformado del LLM.

    Reparaciones (en orden):
    1. Coma faltante entre objetos: }{ → },{
    2. Coma faltante entre valor y llave: "valor"  "llave" → "valor", "llave"
    3. Comas trailing antes de cierre: ,} → }  ,] → ]
    4. Cerrar brackets/braces sin cerrar
    5. Fallback final: json_repair (si esta instalado) — mucho mas agresivo
    """
    # 1. Coma faltante entre objetos en arrays: } { o }\n{
    fixed = re.sub(r"\}\s*\{", "},{", raw)

    # 2. Coma faltante entre string/number y nueva key:
    #    "valor"  "key"  →  "valor", "key"
    #    123  "key"      →  123, "key"
    #    null  "key"     →  null, "key"
    #    true  "key"     →  true, "key"
    fixed = re.sub(
        r'("|\d|null|true|false)\s*\n\s*"', r'\1,\n"', fixed
    )

    # 3. Trailing commas
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)

    # 4. Cerrar brackets/braces sin cerrar
    open_braces = fixed.count("{") - fixed.count("}")
    open_brackets = fixed.count("[") - fixed.count("]")
    if open_braces > 0:
        fixed = fixed.rstrip() + "}" * open_braces
    if open_brackets > 0:
        fixed = fixed.rstrip() + "]" * open_brackets

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 5. Ultimo recurso: json_repair library si esta instalada.
    #    `pip install json-repair` — maneja muchos mas casos que los regex de arriba
    #    (comillas sin cerrar, valores truncados, mix de comillas, etc.)
    try:
        from json_repair import repair_json  # type: ignore
        repaired_str = repair_json(raw)
        return json.loads(repaired_str)
    except ImportError:
        logger.debug("json_repair no instalado — saltando fallback agresivo")
    except Exception as e:
        logger.debug(f"json_repair tambien fallo: {e}")

    return None


def _guardar_raw_error(
    block_type: str,
    page_range: tuple,
    raw: str,
    error: Exception,
) -> Optional[Path]:
    """
    Guarda el raw completo de una respuesta LLM cuya reparacion fallo.
    Permite inspeccionar despues para ajustar el reparador o el prompt.
    """
    try:
        _LLM_ERRORS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pags = f"{page_range[0]}-{page_range[1]}" if len(page_range) >= 2 else "x"
        path = _LLM_ERRORS_DIR / f"{block_type}_pags_{pags}_{ts}.txt"
        path.write_text(
            f"# Error de JSON invalido del LLM\n"
            f"Fecha: {datetime.now().isoformat()}\n"
            f"Bloque: {block_type}\n"
            f"Paginas: {page_range}\n"
            f"Error: {error}\n"
            f"Longitud raw: {len(raw)} chars\n"
            f"\n---RAW RESPONSE COMPLETO---\n{raw}\n",
            encoding="utf-8",
        )
        return path
    except Exception as e:
        logger.warning(f"No se pudo guardar raw error a disco: {e}")
        return None


_PROMPT_RETRY_FALTANTES = """Acabas de extraer {n_extraidos} cargos de la tabla de personal clave (B.1 + B.2) pero la tabla tiene {n_esperados} filas numeradas. Faltan aproximadamente {n_faltantes} cargos.

CARGOS YA EXTRAIDOS (no los repitas — busca SOLO los que NO estan en esta lista):
{cargos_extraidos}

Busca en el texto los cargos que FALTAN — pueden estar:
- Al INICIO de la tabla (ej: GERENTE DE CONTRATO, JEFE DE SUPERVISION, INGENIERO DE CAMPO en pags iniciales).
- Al FINAL (ej: ESPECIALISTA EN INSTALACIONES ELECTROMECANICAS) con OCR fragmentado.
- En paginas intermedias donde el OCR partio palabras ("GERENTEDE", "INGENIEROElectricista").

Ignora: "MANTENIMIENTO VIAL", "CONCURSO PUBLICO", numeros de pagina, footnotes como "75", "96".

SCHEMA OBLIGATORIO (NO INVENTES CAMPOS — usa EXACTAMENTE estos nombres):
{{
  "personal_clave": [
    {{
      "cargo": "NOMBRE EXACTO DEL CARGO COMO APARECE",
      "profesiones_aceptadas": ["Ingeniero Civil", "Arquitecto", ...],
      "anos_colegiado": null,
      "experiencia_minima": {{
        "cantidad": <numero de meses>,
        "unidad": "meses",
        "descripcion": "<copia literal de la columna TRABAJOS O PRESTACIONES>",
        "cargos_similares_validos": ["..."],
        "puntaje_por_experiencia": null,
        "puntaje_maximo": null
      }},
      "tipo_obra_valido": "establecimientos de salud",
      "tiempo_adicional_factores": null,
      "capacitacion": {{"tema": null, "tipo": null, "duracion_minima_horas": null, "es_factor_evaluacion": false}},
      "pagina": <numero>
    }}
  ]
}}

NO uses "formacion_academica" ni "titulo_profesional" ni otros nombres. Solo el schema arriba.

TEXTO DEL DOCUMENTO:
{texto}

Responde SOLO JSON con los FALTANTES (sin duplicar los ya extraidos):
/no_think
""".strip()


def retry_cargos_faltantes(
    texto_fuente: str,
    items_ya_extraidos: list,
    n_esperados: int,
) -> list:
    """
    Invoca a Qwen con un prompt especializado pidiendo SOLO los cargos que el
    LLM omitio en la primera pasada. El modelo ya tiene el contexto y puede
    enfocarse en los faltantes (tipicamente los ultimos items que tienen OCR
    fragmentado).

    Retorna lista de items nuevos (sin mezclar con los originales — el caller
    debe concatenar).
    """
    cargos_extraidos = [str(it.get("cargo", "?")) for it in items_ya_extraidos]
    n_extraidos = len(cargos_extraidos)
    n_faltantes = max(0, n_esperados - n_extraidos)
    if n_faltantes <= 0:
        return []

    prompt = _PROMPT_RETRY_FALTANTES.format(
        n_extraidos=n_extraidos,
        n_esperados=n_esperados,
        n_faltantes=n_faltantes,
        cargos_extraidos="\n".join(f"- {c}" for c in cargos_extraidos),
        texto=texto_fuente[:QWEN_NUM_CTX * 3],  # cap conservador
    )

    logger.info(
        f"[llm-retry] Re-invocando LLM para recuperar {n_faltantes} cargos "
        f"faltantes ({n_extraidos}/{n_esperados} extraidos)"
    )

    try:
        client = _get_client()
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=QWEN_MAX_TOKENS,
            extra_body={
                "keep_alive": "10m",
                "options": {"num_gpu": 99, "num_ctx": QWEN_NUM_CTX},
            },
        )
        elapsed = time.perf_counter() - t0
    except Exception as e:
        logger.warning(f"[llm-retry] Qwen fallo en retry: {e}")
        return []

    raw = response.choices[0].message.content.strip()
    cleaned = _limpiar_respuesta(raw)

    # Intentar parsear
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = _reparar_json(cleaned) or {}

    items_nuevos = data.get("personal_clave", []) if isinstance(data, dict) else []
    if not isinstance(items_nuevos, list):
        items_nuevos = []

    # Guardar dump para auditoria
    try:
        _guardar_call_llm(
            block_type="rtm_personal_retry",
            page_range=(0, 0),
            prompt=prompt,
            raw_response=raw,
            usage={
                "prompt_tokens": getattr(getattr(response, "usage", None), "prompt_tokens", 0),
                "completion_tokens": getattr(getattr(response, "usage", None), "completion_tokens", 0),
            },
            elapsed_s=elapsed,
            num_ctx=QWEN_NUM_CTX,
            parsed_ok=bool(items_nuevos),
            items_extracted=len(items_nuevos),
            error=None if items_nuevos else "retry sin items",
            model=QWEN_MODEL,
            response_model=getattr(response, "model", None),
        )
    except Exception:
        pass

    logger.info(
        f"[llm-retry] Recupero {len(items_nuevos)} cargo(s) faltante(s) "
        f"en {elapsed:.1f}s"
    )
    return items_nuevos


def _es_respuesta_fabricada(raw_response: str) -> bool:
    """Detecta si el LLM generó un 'ejemplo' en vez de extraer datos reales."""
    texto = raw_response.lower()
    for pattern in _FABRICATION_PATTERNS:
        if re.search(pattern, texto, re.IGNORECASE):
            return True
    return False


def extraer_bloque(block: Block) -> tuple[Optional[dict], dict]:
    """
    Wrapper que invoca _extraer_bloque_impl y SIEMPRE guarda un dump del
    prompt + raw response + metadatos en data/llm_calls/{job_id}/ para
    auditoria y debug. Util cuando el LLM extrae pocos cargos, alucina,
    o responde raro — se puede inspeccionar exactamente que paso.
    """
    result, diag = _extraer_bloque_impl(block)
    try:
        _guardar_call_llm(
            block_type=block.block_type,
            page_range=block.page_range,
            prompt=diag.get("prompt_enviado", ""),
            raw_response=diag.get("raw_response", ""),
            usage=diag.get("usage", {}),
            elapsed_s=diag.get("elapsed_s", 0.0),
            num_ctx=QWEN_NUM_CTX,
            parsed_ok=bool(diag.get("parsed_ok")),
            items_extracted=int(diag.get("items_extracted", 0) or 0),
            error=diag.get("error") or None,
            model=QWEN_MODEL,
            response_model=diag.get("response_model"),
        )
    except Exception as e:
        logger.debug(f"No se pudo guardar dump LLM: {e}")
    return result, diag


def _extraer_bloque_impl(block: Block) -> tuple[Optional[dict], dict]:
    """
    Envía un bloque ya clasificado a Qwen y retorna el JSON extraído
    junto con información diagnóstica de la interacción.

    Returns:
        (parsed_result_or_None, diagnostic_info_dict)
    """
    diag = {
        "block_type": block.block_type,
        "page_range": list(block.page_range),
        "pages_included": [p.page_num for p in block.pages],
        "prompt_chars": 0,
        "text_preview": block.text[:2000],
        "raw_response": "",
        "cleaned_response": "",
        "parsed_ok": False,
        "parsed_keys": [],
        "items_extracted": 0,
        "error": "",
    }

    prompt_template = PROMPTS.get(block.block_type)
    if not prompt_template:
        diag["error"] = f"Sin prompt para tipo: {block.block_type}"
        logger.warning(f"[llm] {diag['error']}")
        return None, diag

    prompt = prompt_template.format(texto=block.text)
    diag["prompt_chars"] = len(prompt)
    diag["prompt_enviado"] = prompt  # para dump a disco

    # Estimacion conservadora: 1 token ≈ 3 chars en espanol con numeros/puntuacion
    approx_tokens = len(prompt) // 3
    logger.info(
        f"[llm] Enviando bloque '{block.block_type}' "
        f"págs {block.page_range} ({len(prompt)} chars ≈ {approx_tokens} tok, "
        f"num_ctx={QWEN_NUM_CTX})"
    )
    if approx_tokens > QWEN_NUM_CTX:
        logger.warning(
            f"[llm] ⚠ Prompt ≈ {approx_tokens} tok SUPERA num_ctx={QWEN_NUM_CTX} — "
            f"Ollama truncara. Considerar subir QWEN_NUM_CTX o reducir el bloque."
        )

    try:
        client = _get_client()
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=QWEN_MAX_TOKENS,
            extra_body={
                "keep_alive": "10m",
                "options": {
                    "num_gpu": 99,
                    # Ventana de contexto completa. Default de Ollama es 4096 tok
                    # que trunca prompts largos silenciosamente → causa principal
                    # de alucinaciones en tablas TDR multi-pagina.
                    "num_ctx": QWEN_NUM_CTX,
                },
            },
        )
        elapsed = time.perf_counter() - t0
    except Exception as e:
        diag["error"] = f"Qwen falló: {e}"
        logger.warning(f"[llm] {diag['error']}")
        return None, diag

    raw = response.choices[0].message.content.strip()
    diag["raw_response"] = raw
    diag["elapsed_s"] = elapsed
    # Modelo que Ollama realmente resolvio (confirma si tomo el modelo nuevo o cacheado)
    diag["response_model"] = getattr(response, "model", None)

    # ── Métricas de rendimiento ──────────────────────────────────────────
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    total_tokens = prompt_tokens + completion_tokens
    diag["usage"] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }

    # Velocidad de prefill (prompt processing) — indicador real de GPU vs CPU
    # GPU 14b: ~300-1000 tok/s prefill | CPU/RAM: ~30-100 tok/s
    prefill_tps = prompt_tokens / elapsed if elapsed > 0 and prompt_tokens > 0 else 0
    dispositivo = "GPU" if prefill_tps > 200 else "CPU/RAM" if prefill_tps > 0 else "?"
    logger.info(
        f"[llm] ✓ '{block.block_type}' págs {block.page_range}: "
        f"{elapsed:.1f}s · prefill={prefill_tps:.0f} tok/s ({dispositivo}) · "
        f"prompt={prompt_tokens}tok resp={completion_tokens}tok"
    )

    # Detectar respuestas fabricadas en el preámbulo (texto ANTES del JSON).
    # Pero SOLO descartar si el JSON resultante también está vacío — de lo contrario
    # el LLM razonó sobre no fabricar y aún así extrajo datos válidos, que son los
    # que importan. Los validadores _marcar_cargos_no_en_fuente y
    # _detectar_copy_paste_fabricacion en pipeline.py se encargan de marcar items
    # sospechosos SIN descartar toda la respuesta.
    _pre_json = raw[: raw.find("{")] if "{" in raw else raw
    if _es_respuesta_fabricada(_pre_json):
        # Verificar si el JSON resultante tiene items reales
        json_vacio = True
        try:
            _peek = json.loads(_limpiar_respuesta(raw))
            items_peek = (
                _peek.get("items_concurso")
                or _peek.get("personal_clave")
                or _peek.get("factores_evaluacion")
                or []
            )
            if isinstance(items_peek, list) and len(items_peek) > 0:
                json_vacio = False
        except (json.JSONDecodeError, AttributeError, TypeError):
            # Si no parseó, dejar que el flujo caiga al reparador de abajo
            json_vacio = False

        if json_vacio:
            diag["error"] = "Respuesta fabricada detectada (JSON vacio + preambulo sospechoso)"
            logger.warning(
                f"[llm] Bloque '{block.block_type}' págs {block.page_range}: "
                f"respuesta fabricada descartada (preambulo + JSON vacio)"
            )
            empty = {
                "rtm_postor": {"items_concurso": []},
                "rtm_personal": {"personal_clave": []},
                "factores_evaluacion": {"factores_evaluacion": []},
            }.get(block.block_type, {})
            return empty, diag
        else:
            logger.info(
                f"[llm] Bloque '{block.block_type}' págs {block.page_range}: "
                f"preambulo con patrones de fabricacion PERO JSON con items — "
                f"procediendo (validadores deterministicos filtraran alucinaciones)"
            )

    raw = _limpiar_respuesta(raw)
    diag["cleaned_response"] = raw

    try:
        result = json.loads(raw)
        result["_meta"] = {
            "block_type": block.block_type,
            "page_range": list(block.page_range),
        }
        diag["parsed_ok"] = True
        diag["parsed_keys"] = [k for k in result.keys() if not k.startswith("_")]

        # Contar items extraídos según tipo de bloque
        if block.block_type == "rtm_postor":
            diag["items_extracted"] = len(result.get("items_concurso", []))
        elif block.block_type == "rtm_personal":
            diag["items_extracted"] = len(result.get("personal_clave", []))
        elif block.block_type == "factores_evaluacion":
            diag["items_extracted"] = len(result.get("factores_evaluacion", []))

        return result, diag
    except json.JSONDecodeError as e:
        logger.warning(
            f"[llm] JSON inválido en '{block.block_type}' págs {block.page_range}: {e}"
        )
        # Intentar reparación automática
        repaired = _reparar_json(raw)
        if repaired is not None:
            logger.info(
                f"[llm] ✓ JSON reparado para '{block.block_type}' págs {block.page_range}"
            )
            repaired["_meta"] = {
                "block_type": block.block_type,
                "page_range": list(block.page_range),
            }
            diag["parsed_ok"] = True
            diag["parsed_keys"] = [k for k in repaired.keys() if not k.startswith("_")]
            diag["error"] = f"JSON reparado (error original: {e})"

            if block.block_type == "rtm_postor":
                diag["items_extracted"] = len(repaired.get("items_concurso", []))
            elif block.block_type == "rtm_personal":
                diag["items_extracted"] = len(repaired.get("personal_clave", []))
            elif block.block_type == "factores_evaluacion":
                diag["items_extracted"] = len(repaired.get("factores_evaluacion", []))

            return repaired, diag

        raw_file = _guardar_raw_error(block.block_type, block.page_range, raw, e)
        # Log con snippet mas amplio (1500 chars vs 200) para diagnostico inmediato,
        # y ruta al archivo con el raw completo para inspeccion offline.
        diag["error"] = (
            f"JSON inválido (reparación falló): {e}"
            + (f" — raw completo en {raw_file}" if raw_file else "")
            + f"\nsnippet (primeros 1500 chars): {raw[:1500]!r}"
        )
        logger.warning(f"[llm] {diag['error']}")
        return None, diag