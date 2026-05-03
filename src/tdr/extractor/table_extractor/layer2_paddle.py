"""
Capa 2 — Extraccion de tablas con PaddleOCR PP-Structure V3 via motor-OCR.

Invoca el mode `table_extract` del subprocess_wrapper.py de motor-OCR
(rama feat/table-extract-pp-structure / main una vez mergeado). El motor
renderiza las paginas indicadas a 300 DPI y corre PP-Structure V3, que
detecta regiones de tabla y devuelve cada celda con coordenadas + el
HTML estructurado.

Ventajas sobre Capa 1:
- Funciona en PDFs ESCANEADOS (no requiere capa de texto vectorial)
- Respeta merged cells (rowspan/colspan)
- Cero LLM para identificar limites de fila/columna

Ventajas sobre Capa 3:
- No depende de un catalogo de cargos OSCE estatico
- Mas rapido cuando funciona (sin 17 llamadas LLM)
- Mas preciso (PP-Structure entiende layout visual)

Si motor-OCR no expone el mode `table_extract` (instalacion vieja),
esta capa retorna [] con motivo en diagnostico y el orchestrator cae
a Capa 3.
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from src.tdr.extractor.table_extractor.models import (
    FilaTDR,
    ExperienciaMinima,
    Confianza,
    TablaCruda,
)
from src.tdr.extractor.table_extractor.cell_parser import (
    parsear_profesiones,
    parsear_tiempo_meses,
    parsear_b2_celda_con_llm,
    parsear_b2_celda_regex,
    es_cabecera_b1,
    es_cabecera_b2,
)

logger = logging.getLogger(__name__)


# ── Disponibilidad del subprocess ────────────────────────────────────────────

def _esta_disponible_pp_structure() -> bool:
    """
    Verifica que motor-OCR este configurado:
      - MOTOR_OCR_WRAPPER apunta a un archivo existente
      - MOTOR_OCR_PYTHON apunta a un archivo existente

    No verifica si el wrapper soporta el mode 'table_extract' — eso lo
    detectamos por el resultado del subprocess (returncode != 0 o JSON
    sin la clave esperada).
    """
    motor_ocr_wrapper = os.getenv("MOTOR_OCR_WRAPPER", "")
    motor_ocr_python = os.getenv("MOTOR_OCR_PYTHON", "")

    if not motor_ocr_wrapper or not Path(motor_ocr_wrapper).exists():
        logger.info(
            "[layer2] MOTOR_OCR_WRAPPER no configurado o no existe: %r",
            motor_ocr_wrapper,
        )
        return False
    if not motor_ocr_python or not Path(motor_ocr_python).exists():
        logger.info(
            "[layer2] MOTOR_OCR_PYTHON no configurado o no existe: %r",
            motor_ocr_python,
        )
        return False

    return True


# ── Invocacion del subprocess ────────────────────────────────────────────────

def _invocar_table_extract(
    pdf_path: str,
    paginas: list[int],
    timeout: int = 1800,
) -> Optional[dict]:
    """
    Lanza el subprocess de motor-OCR en mode='table_extract'.

    Returns:
        dict con resultado del wrapper, o None si fallo.
        Schema (definido en motor-OCR/subprocess_wrapper.py):
        {
            "mode": "table_extract",
            "pdf_path": str,
            "paginas_solicitadas": list[int],
            "tablas": [
                {
                    "pagina": int,
                    "matriz": list[list[str]],
                    "html": str,
                    "bbox": list | None,
                    "n_filas": int,
                    "n_cols": int,
                    "score": float | None,
                },
                ...
            ],
            "tiempo_total": float,
            "n_paginas_procesadas": int,
            "errores": list[str],
        }
    """
    motor_ocr_python = Path(os.getenv("MOTOR_OCR_PYTHON", ""))
    motor_ocr_wrapper = Path(os.getenv("MOTOR_OCR_WRAPPER", ""))

    args = {
        "mode": "table_extract",
        "pdf_path": str(Path(pdf_path).absolute()),
        "paginas": sorted(set(paginas)),
    }

    args_file = results_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        ) as f:
            json.dump(args, f, ensure_ascii=False)
            args_file = f.name

        results_file = tempfile.mktemp(suffix=".json")

        log_file = Path("motor_ocr_table_extract.log")

        logger.info(
            "[layer2] Lanzando subprocess motor-OCR table_extract: %d paginas",
            len(args["paginas"]),
        )

        with open(log_file, "w", encoding="utf-8") as logf:
            result = subprocess.run(
                [str(motor_ocr_python), str(motor_ocr_wrapper), args_file, results_file],
                stdout=logf,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )

        if result.returncode != 0:
            try:
                last_lines = log_file.read_text(encoding="utf-8", errors="replace")[-2000:]
            except Exception:
                last_lines = "(no se pudo leer log)"
            logger.error(
                "[layer2] Subprocess fallo con codigo %d:\n%s",
                result.returncode, last_lines,
            )
            return None

        if not Path(results_file).exists() or os.path.getsize(results_file) == 0:
            logger.warning("[layer2] Subprocess no produjo results file")
            return None

        with open(results_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data

    except subprocess.TimeoutExpired:
        logger.error("[layer2] Subprocess timeout despues de %ds", timeout)
        return None
    except Exception as e:
        logger.exception("[layer2] Error inesperado en subprocess: %s", e)
        return None
    finally:
        for path in (args_file, results_file):
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass


# ── Procesamiento de matrices PP-Structure → FilaTDR ─────────────────────────

def _procesar_tabla_b1(tabla: TablaCruda) -> dict[int, FilaTDR]:
    """
    Misma logica que layer1_pdfplumber._procesar_tabla_b1 pero con
    confianza menor (PP-Structure puede confundir alguna celda en
    PDFs muy ruidosos).
    """
    resultado: dict[int, FilaTDR] = {}

    cabecera = tabla.cabecera()
    col_n = col_cargo = col_formacion = -1
    for i, c in enumerate(cabecera):
        c_upper = c.upper()
        if c_upper.strip() in ("N°", "N", "NRO", "NUM") or c_upper == "":
            if col_n < 0:
                col_n = i
        elif "CARGO" in c_upper or "RESPONSABILIDAD" in c_upper:
            col_cargo = i
        elif (
            "FORMACION" in c_upper or "FORMACIÓN" in c_upper
            or "ACADEMICA" in c_upper or "ACADÉMICA" in c_upper
        ):
            col_formacion = i

    if col_n < 0:
        col_n = 0
    if col_cargo < 0:
        col_cargo = 1
    if col_formacion < 0:
        col_formacion = 2

    for row in tabla.filas[1:]:
        if not row or len(row) <= max(col_n, col_cargo, col_formacion):
            continue

        n_raw = row[col_n].strip() if col_n < len(row) else ""
        if not n_raw or not n_raw.isdigit():
            continue
        numero = int(n_raw)

        cargo = row[col_cargo].strip() if col_cargo < len(row) else ""
        formacion_raw = row[col_formacion].strip() if col_formacion < len(row) else ""

        if not cargo:
            continue

        profesiones = parsear_profesiones(formacion_raw)

        if numero in resultado:
            f_prev = resultado[numero]
            if not f_prev.cargo and cargo:
                f_prev.cargo = cargo
            if not f_prev.profesiones_aceptadas and profesiones:
                f_prev.profesiones_aceptadas = profesiones
        else:
            resultado[numero] = FilaTDR(
                numero_fila=numero,
                cargo=cargo,
                profesiones_aceptadas=profesiones,
                pagina=tabla.pagina,
                confianza=Confianza.LAYER2_PADDLE,
                fuente="layer2",
                fila_texto_origen=f"B.1 row pp-structure: {row}",
            )

    return resultado


def _procesar_tabla_b2(
    tabla: TablaCruda,
    usar_llm: bool = True,
) -> dict[int, dict]:
    """
    Misma logica que layer1_pdfplumber._procesar_tabla_b2 pero con
    matrices de PP-Structure.
    """
    resultado: dict[int, dict] = {}

    cabecera = tabla.cabecera()
    col_n = col_cargo = col_tiempo = col_trabajos = -1
    for i, c in enumerate(cabecera):
        c_upper = c.upper()
        if c_upper.strip() in ("N°", "N", "NRO", "NUM") or c_upper == "":
            if col_n < 0:
                col_n = i
        elif "CARGO" in c_upper or "ROL" in c_upper:
            col_cargo = i
        elif "TIEMPO" in c_upper or "EXPERIENCIA" in c_upper:
            col_tiempo = i
        elif (
            "TRABAJOS" in c_upper or "PRESTACIONES" in c_upper
            or "ACTIVIDAD" in c_upper
        ):
            col_trabajos = i

    if col_n < 0:
        col_n = 0
    if col_cargo < 0:
        col_cargo = 1
    if col_tiempo < 0:
        col_tiempo = 2
    if col_trabajos < 0:
        col_trabajos = 3

    for row in tabla.filas[1:]:
        if not row or len(row) <= max(col_n, col_cargo, col_tiempo, col_trabajos):
            continue

        n_raw = row[col_n].strip() if col_n < len(row) else ""
        if not n_raw or not n_raw.isdigit():
            continue
        numero = int(n_raw)

        tiempo_raw = row[col_tiempo].strip() if col_tiempo < len(row) else ""
        trabajos_raw = row[col_trabajos].strip() if col_trabajos < len(row) else ""

        tiempo_meses = parsear_tiempo_meses(tiempo_raw)

        if usar_llm and trabajos_raw and len(trabajos_raw) > 50:
            datos_b2 = parsear_b2_celda_con_llm(trabajos_raw)
        else:
            datos_b2 = parsear_b2_celda_regex(trabajos_raw)

        resultado[numero] = {
            "tiempo_meses": tiempo_meses,
            "descripcion_raw": trabajos_raw,
            "cargos_similares": datos_b2.get("cargos_similares", []),
            "tipo_obra": datos_b2.get("tipo_obra"),
            "pagina": tabla.pagina,
        }

    return resultado


# ── API publica de la Capa 2 ─────────────────────────────────────────────────

def extraer_b1_b2_layer2(
    pdf_path: str,
    paginas_b1: list[int],
    paginas_b2: list[int],
    usar_llm_para_b2: bool = True,
    timeout: int = 1800,
) -> tuple[list[FilaTDR], dict]:
    """
    Extraccion Capa 2: PP-Structure V3 via subprocess al motor-OCR.

    Args:
        pdf_path: ruta absoluta al PDF
        paginas_b1: paginas con la tabla B.1
        paginas_b2: paginas con la tabla B.2
        usar_llm_para_b2: si True, invoca LLM para celdas verbosas de B.2
        timeout: timeout del subprocess en segundos (default 30 min)

    Returns:
        (filas, diagnostico)

    Si motor-OCR no esta disponible o el subprocess falla, retorna
    ([], diagnostico) con motivo. El orchestrator decidira el fallback.
    """
    diag: dict = {
        "capa": "layer2",
        "implementado": True,
        "tablas_pp_structure": 0,
        "tablas_b1_identificadas": 0,
        "tablas_b2_identificadas": 0,
        "filas_b1": 0,
        "filas_b2": 0,
        "errores": [],
    }

    if not _esta_disponible_pp_structure():
        diag["motivo_skip"] = (
            "motor-OCR no configurado (MOTOR_OCR_WRAPPER / MOTOR_OCR_PYTHON). "
            "Capa 2 saltada — orchestrator caera a Capa 3."
        )
        logger.info("[layer2] %s", diag["motivo_skip"])
        return [], diag

    if not Path(pdf_path).exists():
        diag["errores"].append(f"PDF no encontrado: {pdf_path}")
        return [], diag

    paginas_todas = sorted(set(paginas_b1 + paginas_b2))
    if not paginas_todas:
        diag["errores"].append("Sin paginas B.1 ni B.2 — nada que procesar")
        return [], diag

    # ── Lanzar subprocess ────────────────────────────────────────────────
    resultado_raw = _invocar_table_extract(
        pdf_path=pdf_path,
        paginas=paginas_todas,
        timeout=timeout,
    )

    if resultado_raw is None:
        diag["errores"].append("Subprocess motor-OCR fallo o timeout")
        return [], diag

    # Verificar que el wrapper soporta el mode (no es version vieja)
    if resultado_raw.get("mode") != "table_extract":
        diag["motivo_skip"] = (
            f"motor-OCR devolvio mode={resultado_raw.get('mode')!r} — "
            "version del wrapper no soporta 'table_extract'. "
            "Actualizar motor-OCR a >= rama feat/table-extract-pp-structure."
        )
        logger.warning("[layer2] %s", diag["motivo_skip"])
        return [], diag

    diag["tiempo_subprocess"] = resultado_raw.get("tiempo_total", 0.0)
    diag["n_paginas_procesadas"] = resultado_raw.get("n_paginas_procesadas", 0)
    if resultado_raw.get("errores"):
        diag["errores"].extend(resultado_raw["errores"])

    tablas_raw = resultado_raw.get("tablas", []) or []
    diag["tablas_pp_structure"] = len(tablas_raw)

    if not tablas_raw:
        diag["errores"].append(
            "PP-Structure no detecto tablas en las paginas pedidas"
        )
        logger.info(
            "[layer2] PP-Structure devolvio 0 tablas (paginas=%s)",
            paginas_todas,
        )
        return [], diag

    # ── Convertir matrices a TablaCruda + procesar B.1/B.2 ───────────────
    tablas: list[TablaCruda] = []
    for t in tablas_raw:
        matriz = t.get("matriz") or []
        if not matriz or len(matriz) < 2:
            continue
        # Normalizar todas las celdas como str
        filas_norm = [
            [(c if isinstance(c, str) else "").strip() for c in row]
            for row in matriz
        ]
        tablas.append(TablaCruda(
            pagina=int(t.get("pagina", 0) or 0),
            filas=filas_norm,
            fuente="paddle_structure",
        ))

    # Identificar B.1 / B.2 por cabecera
    filas_b1: dict[int, FilaTDR] = {}
    datos_b2: dict[int, dict] = {}

    for tabla in tablas:
        cabecera = tabla.cabecera()
        if es_cabecera_b1(cabecera):
            diag["tablas_b1_identificadas"] += 1
            filas_b1.update(_procesar_tabla_b1(tabla))
        elif es_cabecera_b2(cabecera):
            diag["tablas_b2_identificadas"] += 1
            datos_b2.update(_procesar_tabla_b2(tabla, usar_llm=usar_llm_para_b2))
        else:
            logger.info(
                "[layer2] Tabla pag %d con cabecera ambigua: %s — saltando",
                tabla.pagina, cabecera[:5],
            )

    diag["filas_b1"] = len(filas_b1)
    diag["filas_b2"] = len(datos_b2)

    # ── Merge B.1 + B.2 por numero_fila ──────────────────────────────────
    numeros = sorted(set(filas_b1.keys()) | set(datos_b2.keys()))
    filas_merged: list[FilaTDR] = []

    for num in numeros:
        fila = filas_b1.get(num)
        if fila is None:
            datos_b2_fila = datos_b2.get(num, {})
            fila = FilaTDR(
                numero_fila=num,
                cargo="",
                profesiones_aceptadas=[],
                pagina=datos_b2_fila.get("pagina"),
                confianza=Confianza.LAYER2_PADDLE * 0.8,
                fuente="layer2",
                fila_texto_origen="solo B.2 (pp-structure)",
            )

        if num in datos_b2:
            d = datos_b2[num]
            fila.experiencia_minima = ExperienciaMinima(
                cantidad=d.get("tiempo_meses"),
                unidad="meses",
                descripcion=d.get("descripcion_raw"),
                cargos_similares_validos=d.get("cargos_similares", []),
            )
            if d.get("tipo_obra"):
                fila.tipo_obra_valido = d["tipo_obra"]
            if d.get("pagina") and not fila.pagina:
                fila.pagina = d["pagina"]

        filas_merged.append(fila)

    diag["filas_mergeadas"] = len(filas_merged)
    logger.info(
        "[layer2] Resultado: %d filas (B.1=%d, B.2=%d, tiempo subprocess=%.1fs)",
        len(filas_merged), diag["filas_b1"], diag["filas_b2"],
        diag.get("tiempo_subprocess", 0),
    )

    return filas_merged, diag
