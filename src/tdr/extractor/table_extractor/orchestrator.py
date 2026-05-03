"""
Orchestrator del pipeline de extraccion TDR de 3 capas.

Estrategia:
1. Intenta Capa 1 (pdfplumber.extract_tables) — la mas precisa para
   PDFs digitales con bordes de tabla detectables.

2. Si Capa 1 no detecta tablas o detecta menos del minimo esperado,
   intenta Capa 2 (PP-Structure de PaddleOCR via subprocess al motor-OCR).

3. Si Capa 2 falla o no esta disponible, cae a Capa 3 (segmentacion
   regex por catalogo de cargos + LLM por fila aislada).

La logica de fallback se basa en metricas concretas:
- Numero de filas detectadas vs esperado (~17 para hospitales OSCE)
- Cobertura de campos clave (cargo, profesiones, experiencia_minima)
- Confianza promedio del extractor
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

from src.tdr.extractor.table_extractor.models import (
    FilaTDR,
    ResultadoExtraccion,
    Confianza,
)

logger = logging.getLogger(__name__)


# ── Heuristicas de aceptacion de capa ────────────────────────────────────────

def _es_resultado_aceptable(
    filas: list[FilaTDR],
    n_esperadas: int,
    cobertura_minima: float = 0.80,
) -> tuple[bool, dict]:
    """
    Decide si un resultado de capa es aceptable o hay que hacer fallback.

    Criterios:
    1. Numero de filas: >= cobertura_minima * n_esperadas
       (default 80% de las filas detectadas)
    2. Cobertura de campos: >= 70% de las filas tienen profesiones_aceptadas
       no vacias o cargos_similares no vacios
    """
    diag: dict = {}

    if not filas:
        diag["motivo"] = "sin_filas"
        return False, diag

    diag["filas_detectadas"] = len(filas)
    diag["filas_esperadas"] = n_esperadas
    diag["cobertura_filas"] = len(filas) / n_esperadas if n_esperadas > 0 else 0

    if len(filas) < n_esperadas * cobertura_minima:
        diag["motivo"] = (
            f"cobertura_baja: {len(filas)}/{n_esperadas} = "
            f"{diag['cobertura_filas']:.0%} < {cobertura_minima:.0%}"
        )
        return False, diag

    # Cobertura de campos: profesiones_aceptadas no vacias
    con_profs = sum(1 for f in filas if f.profesiones_aceptadas)
    con_cargos_sim = sum(1 for f in filas if f.experiencia_minima.cargos_similares_validos)

    diag["filas_con_profesiones"] = con_profs
    diag["filas_con_cargos_similares"] = con_cargos_sim
    diag["pct_con_profesiones"] = con_profs / len(filas) if filas else 0
    diag["pct_con_cargos_similares"] = con_cargos_sim / len(filas) if filas else 0

    # Aceptamos si al menos 70% tiene profesiones O cargos similares
    score_campos = max(diag["pct_con_profesiones"], diag["pct_con_cargos_similares"])
    if score_campos < 0.70:
        diag["motivo"] = (
            f"campos_pobres: max(profs={diag['pct_con_profesiones']:.0%}, "
            f"cargos_sim={diag['pct_con_cargos_similares']:.0%}) < 70%"
        )
        return False, diag

    diag["motivo"] = "aceptable"
    return True, diag


# ── API publica ──────────────────────────────────────────────────────────────

def extraer_tdr_3_capas(
    pdf_path: str,
    texto_por_pagina: dict[int, str],
    paginas_b1: list[int],
    paginas_b2: list[int],
    n_filas_esperadas: int = 17,
    forzar_capa: Optional[str] = None,
) -> ResultadoExtraccion:
    """
    Extraccion TDR usando pipeline de 3 capas con fallback automatico.

    Args:
        pdf_path: ruta absoluta al PDF del TDR
        texto_por_pagina: {num_pagina: texto_OCR} para Capa 3
        paginas_b1: paginas que contienen la tabla B.1
        paginas_b2: paginas que contienen la tabla B.2
        n_filas_esperadas: cuantos cargos se esperan (~17 para hospitales OSCE).
                            Usado para decidir si una capa "fallo" o no.
        forzar_capa: "layer1" | "layer2" | "layer3" para forzar una capa
                     especifica (debug). None = auto con fallback.

    Returns:
        ResultadoExtraccion con filas + capa usada + diagnostico.
    """
    resultado = ResultadoExtraccion()
    pdf_existe = pdf_path and Path(pdf_path).exists()

    if not pdf_existe and forzar_capa in (None, "layer1", "layer2"):
        logger.warning(
            "[orchestrator] PDF no disponible — saltando capas 1 y 2, ir directo a Capa 3"
        )
        forzar_capa = "layer3"

    # ── Capa 1: pdfplumber.extract_tables ────────────────────────────────
    if forzar_capa in (None, "layer1"):
        logger.info("[orchestrator] Intentando Capa 1 (pdfplumber)")
        from src.tdr.extractor.table_extractor.layer1_pdfplumber import (
            extraer_b1_b2_layer1,
        )
        try:
            filas_l1, diag_l1 = extraer_b1_b2_layer1(
                pdf_path=pdf_path,
                paginas_b1=paginas_b1,
                paginas_b2=paginas_b2,
                usar_llm_para_b2=True,
            )
            resultado.capas_intentadas.append("layer1")
            resultado.diagnostico["layer1"] = diag_l1

            aceptable, diag_check = _es_resultado_aceptable(
                filas_l1, n_filas_esperadas,
            )
            resultado.diagnostico["layer1_check"] = diag_check

            if aceptable or forzar_capa == "layer1":
                resultado.filas = filas_l1
                resultado.capa_usada = "layer1"
                logger.info(
                    "[orchestrator] Capa 1 ACEPTADA: %d filas, cobertura %.0f%%",
                    len(filas_l1), diag_check.get("cobertura_filas", 0) * 100,
                )
                return resultado

            logger.info(
                "[orchestrator] Capa 1 no aceptable: %s — fallback a Capa 2",
                diag_check.get("motivo", ""),
            )

        except Exception as e:
            logger.warning("[orchestrator] Capa 1 fallo con excepcion: %s", e)
            resultado.diagnostico["layer1_error"] = str(e)
            resultado.capas_intentadas.append("layer1")

    # ── Capa 2: PP-Structure (placeholder por ahora) ─────────────────────
    if forzar_capa in (None, "layer2"):
        logger.info("[orchestrator] Intentando Capa 2 (PP-Structure)")
        from src.tdr.extractor.table_extractor.layer2_paddle import (
            extraer_b1_b2_layer2,
        )
        try:
            filas_l2, diag_l2 = extraer_b1_b2_layer2(
                pdf_path=pdf_path,
                paginas_b1=paginas_b1,
                paginas_b2=paginas_b2,
            )
            resultado.capas_intentadas.append("layer2")
            resultado.diagnostico["layer2"] = diag_l2

            if filas_l2:
                aceptable, diag_check = _es_resultado_aceptable(
                    filas_l2, n_filas_esperadas,
                )
                resultado.diagnostico["layer2_check"] = diag_check

                if aceptable or forzar_capa == "layer2":
                    resultado.filas = filas_l2
                    resultado.capa_usada = "layer2"
                    logger.info(
                        "[orchestrator] Capa 2 ACEPTADA: %d filas",
                        len(filas_l2),
                    )
                    return resultado

        except Exception as e:
            logger.warning("[orchestrator] Capa 2 fallo: %s", e)
            resultado.diagnostico["layer2_error"] = str(e)
            resultado.capas_intentadas.append("layer2")

    # ── Capa 3: regex + LLM por fila ──────────────────────────────────────
    logger.info("[orchestrator] Intentando Capa 3 (regex + LLM por fila)")
    from src.tdr.extractor.table_extractor.layer3_regex_rows import (
        extraer_b1_b2_layer3,
    )

    # Concatenar texto OCR de las paginas relevantes
    texto_b1 = "\n".join(
        texto_por_pagina.get(p, "") for p in sorted(set(paginas_b1))
    ).strip()
    texto_b2 = "\n".join(
        texto_por_pagina.get(p, "") for p in sorted(set(paginas_b2))
    ).strip()

    if not texto_b1 and not texto_b2:
        resultado.error = (
            "Capa 3: sin texto OCR en las paginas B.1 ni B.2 — "
            "imposible segmentar"
        )
        logger.error("[orchestrator] %s", resultado.error)
        return resultado

    try:
        filas_l3, diag_l3 = extraer_b1_b2_layer3(
            texto_b1=texto_b1,
            texto_b2=texto_b2,
            n_filas_esperadas=n_filas_esperadas,
        )
        resultado.capas_intentadas.append("layer3")
        resultado.diagnostico["layer3"] = diag_l3
        resultado.filas = filas_l3
        resultado.capa_usada = "layer3"
        logger.info(
            "[orchestrator] Capa 3 RESULTADO: %d filas extraidas",
            len(filas_l3),
        )

    except Exception as e:
        logger.exception("[orchestrator] Capa 3 fallo: %s", e)
        resultado.error = f"Capa 3 fallo: {e}"
        resultado.diagnostico["layer3_error"] = str(e)

    return resultado


# ── Merge con resultado del pipeline textual existente ───────────────────────

def mergear_con_pipeline_textual(
    items_textuales: list[dict],
    resultado_3_capas: ResultadoExtraccion,
) -> tuple[list[dict], dict]:
    """
    Mergea las filas extraidas por el pipeline 3-capas con los items
    del pipeline textual existente (extraccion LLM tradicional).

    Estrategia:
    - Si el pipeline 3-capas tiene una fila con numero_fila N que
      coincide con un item del pipeline textual, REEMPLAZA los campos
      profesiones_aceptadas, cargos_similares_validos, tipo_obra_valido
      del item textual con los del 3-capas (mas precisos por construccion).
    - Si una fila solo aparece en 3-capas, se agrega a la lista.
    - Si solo aparece en textual, se mantiene.

    Returns:
        (items_mergeados, diagnostico_merge)
    """
    diag: dict = {
        "items_textuales_originales": len(items_textuales),
        "filas_3capas": len(resultado_3_capas.filas),
        "items_actualizados": 0,
        "items_agregados": 0,
        "items_solo_textuales": 0,
    }

    # Indexar por numero_fila
    por_numero_3capas: dict[int, FilaTDR] = {
        f.numero_fila: f for f in resultado_3_capas.filas
    }
    items_por_numero: dict[int, dict] = {}
    items_sin_numero: list[dict] = []

    for item in items_textuales:
        n = item.get("numero_fila")
        if isinstance(n, int) and n > 0:
            items_por_numero[n] = item
        else:
            items_sin_numero.append(item)

    # Merge
    numeros_todos = sorted(set(items_por_numero.keys()) | set(por_numero_3capas.keys()))
    items_mergeados: list[dict] = []

    for n in numeros_todos:
        item_textual = items_por_numero.get(n)
        fila_3capas = por_numero_3capas.get(n)

        if item_textual and fila_3capas:
            # Mergear: 3-capas tiene precedencia para campos estructurales
            item = dict(item_textual)
            if fila_3capas.profesiones_aceptadas:
                item["profesiones_aceptadas"] = fila_3capas.profesiones_aceptadas
            if fila_3capas.experiencia_minima.cargos_similares_validos:
                exp = item.get("experiencia_minima") or {}
                if not isinstance(exp, dict):
                    exp = {}
                exp["cargos_similares_validos"] = (
                    fila_3capas.experiencia_minima.cargos_similares_validos
                )
                if fila_3capas.experiencia_minima.cantidad and not exp.get("cantidad"):
                    exp["cantidad"] = fila_3capas.experiencia_minima.cantidad
                    exp["unidad"] = "meses"
                item["experiencia_minima"] = exp
            if fila_3capas.tipo_obra_valido and not item.get("tipo_obra_valido"):
                item["tipo_obra_valido"] = fila_3capas.tipo_obra_valido
            item["_fuente_extraccion"] = f"merge:textual+{fila_3capas.fuente}"
            items_mergeados.append(item)
            diag["items_actualizados"] += 1

        elif fila_3capas:
            # Solo en 3-capas — convertir a dict y agregar
            items_mergeados.append({
                **fila_3capas.to_dict(),
                "_fuente_extraccion": fila_3capas.fuente,
            })
            diag["items_agregados"] += 1

        elif item_textual:
            # Solo en textual — mantener
            item = dict(item_textual)
            item["_fuente_extraccion"] = "textual"
            items_mergeados.append(item)
            diag["items_solo_textuales"] += 1

    # Items sin numero — agregar al final
    for item in items_sin_numero:
        item = dict(item)
        item["_fuente_extraccion"] = "textual_sin_numero"
        items_mergeados.append(item)

    return items_mergeados, diag
