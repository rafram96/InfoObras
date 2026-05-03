"""
Capa 1 — Extraccion determinística con pdfplumber.extract_tables().

Para PDFs digitales con tablas con bordes detectables, pdfplumber
identifica las celdas exactamente — sin necesidad de LLM para
identificar limites de fila/columna.

El LLM solo se invoca para parsear el contenido de celdas verbosas
(B.2 TRABAJOS O PRESTACIONES). Cero cross-row contamination posible
por construccion: cada celda se procesa en aislamiento absoluto.

Funciona en:
- TDRs publicados como PDF generado de Word/LibreOffice
- TDRs con tablas con bordes claros (la mayoria post-2018)

NO funciona en:
- TDRs escaneados (no hay capa de texto → pdfplumber.extract_tables = [])
- Tablas sin bordes definidos (raro en OSCE)
"""
from __future__ import annotations
import logging
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
    es_cabecera_b1,
    es_cabecera_b2,
)

logger = logging.getLogger(__name__)


# ── Extraccion de tablas con pdfplumber ──────────────────────────────────────

def _extraer_tablas_de_paginas(
    pdf_path: str,
    paginas: list[int],
) -> list[TablaCruda]:
    """
    Devuelve TablaCruda por cada tabla detectada en las paginas dadas.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("[layer1] pdfplumber no instalado")
        return []

    tablas: list[TablaCruda] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for pag_num in paginas:
                if pag_num < 1 or pag_num > len(pdf.pages):
                    continue
                page = pdf.pages[pag_num - 1]  # 0-indexed
                # extract_tables devuelve list[list[list[str|None]]]
                # — una lista de tablas, cada tabla es matriz de celdas
                page_tables = page.extract_tables() or []
                for raw_table in page_tables:
                    if not raw_table or len(raw_table) < 2:
                        continue
                    # Normalizar: None → "", str → str.strip()
                    filas_norm = [
                        [(c or "").strip() for c in row]
                        for row in raw_table
                    ]
                    tablas.append(TablaCruda(
                        pagina=pag_num,
                        filas=filas_norm,
                        fuente="pdfplumber",
                    ))
                    logger.info(
                        "[layer1] Pag %d: tabla %dx%d detectada",
                        pag_num, len(filas_norm),
                        max(len(r) for r in filas_norm) if filas_norm else 0,
                    )
    except Exception as e:
        logger.error("[layer1] Error abriendo PDF %s: %s", pdf_path, e)
        return []

    return tablas


# ── Procesamiento de tablas B.1 → FilaTDR ────────────────────────────────────

def _procesar_tabla_b1(tabla: TablaCruda) -> dict[int, FilaTDR]:
    """
    Procesa una tabla cruda identificada como B.1 (calificacion).
    Retorna {numero_fila: FilaTDR}.

    Estructura B.1 esperada: 4 columnas:
      N° | CARGO Y/O RESPONSABILIDAD | FORMACION ACADEMICA | GRADO O TITULO
    """
    resultado: dict[int, FilaTDR] = {}

    # Detectar mapeo de columnas via cabecera
    cabecera = tabla.cabecera()
    col_n = col_cargo = col_formacion = -1
    for i, c in enumerate(cabecera):
        c_upper = c.upper()
        if c_upper.strip() in ("N°", "N", "NRO", "NUM") or c_upper == "":
            if col_n < 0:
                col_n = i
        elif "CARGO" in c_upper or "RESPONSABILIDAD" in c_upper:
            col_cargo = i
        elif "FORMACION" in c_upper or "FORMACIÓN" in c_upper or "ACADEMICA" in c_upper or "ACADÉMICA" in c_upper:
            col_formacion = i

    # Defaults conservadores si la cabecera es ambigua
    if col_n < 0:
        col_n = 0
    if col_cargo < 0:
        col_cargo = 1
    if col_formacion < 0:
        col_formacion = 2

    # Iterar filas (skip cabecera)
    for row in tabla.filas[1:]:
        if not row or len(row) <= max(col_n, col_cargo, col_formacion):
            continue

        # Numero de fila — debe ser numerico
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
            # Si la fila ya existe (puede haber duplicados por cross-page),
            # mergear datos no-vacios
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
                confianza=Confianza.LAYER1_PDFPLUMBER,
                fuente="layer1",
                fila_texto_origen=f"B.1 row: {row}",
            )

    return resultado


# ── Procesamiento de tablas B.2 → datos de experiencia ───────────────────────

def _procesar_tabla_b2(
    tabla: TablaCruda,
    usar_llm: bool = True,
) -> dict[int, dict]:
    """
    Procesa una tabla cruda B.2 (experiencia).
    Retorna {numero_fila: {tiempo_meses, descripcion, cargos_similares, tipo_obra}}.

    Estructura B.2 esperada: 4 columnas:
      N° | CARGO/ROL | TIEMPO DE EXPERIENCIA | TRABAJOS O PRESTACIONES
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
        elif "TRABAJOS" in c_upper or "PRESTACIONES" in c_upper or "ACTIVIDAD" in c_upper:
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

        # Parser de cargos similares: LLM si verbosa, regex como fallback
        if usar_llm and trabajos_raw and len(trabajos_raw) > 50:
            datos_b2 = parsear_b2_celda_con_llm(trabajos_raw)
        else:
            from src.tdr.extractor.table_extractor.cell_parser import parsear_b2_celda_regex
            datos_b2 = parsear_b2_celda_regex(trabajos_raw)

        resultado[numero] = {
            "tiempo_meses": tiempo_meses,
            "descripcion_raw": trabajos_raw,
            "cargos_similares": datos_b2.get("cargos_similares", []),
            "tipo_obra": datos_b2.get("tipo_obra"),
            "pagina": tabla.pagina,
        }

    return resultado


# ── API publica de la Capa 1 ─────────────────────────────────────────────────

def extraer_b1_b2_layer1(
    pdf_path: str,
    paginas_b1: list[int],
    paginas_b2: list[int],
    usar_llm_para_b2: bool = True,
) -> tuple[list[FilaTDR], dict]:
    """
    Extraccion Capa 1: pdfplumber.extract_tables() + parsing determinístico.

    Args:
        pdf_path: ruta absoluta al PDF del TDR
        paginas_b1: paginas que contienen la tabla B.1
        paginas_b2: paginas que contienen la tabla B.2
        usar_llm_para_b2: si True, usa LLM para parsear celdas verbosas de B.2.
                          Si False, usa regex puro (mas rapido pero menos preciso).

    Returns:
        (filas_combinadas, diagnostico)
        - filas_combinadas: list[FilaTDR] con datos de B.1+B.2 mergeados por numero
        - diagnostico: dict con metricas de la extraccion
    """
    diag: dict = {
        "capa": "layer1",
        "tablas_b1_detectadas": 0,
        "tablas_b2_detectadas": 0,
        "filas_b1": 0,
        "filas_b2": 0,
        "filas_mergeadas": 0,
        "errores": [],
    }

    if not Path(pdf_path).exists():
        diag["errores"].append(f"PDF no encontrado: {pdf_path}")
        return [], diag

    # Extraer todas las tablas crudas de las paginas B.1 + B.2
    paginas_todas = sorted(set(paginas_b1 + paginas_b2))
    tablas = _extraer_tablas_de_paginas(pdf_path, paginas_todas)
    diag["tablas_total"] = len(tablas)

    if not tablas:
        diag["errores"].append("pdfplumber no detecto tablas (PDF escaneado o sin bordes)")
        return [], diag

    # Identificar cuales son B.1 y cuales B.2 por su cabecera
    filas_b1: dict[int, FilaTDR] = {}
    datos_b2: dict[int, dict] = {}

    for tabla in tablas:
        cabecera = tabla.cabecera()
        if es_cabecera_b1(cabecera):
            diag["tablas_b1_detectadas"] += 1
            filas_b1.update(_procesar_tabla_b1(tabla))
        elif es_cabecera_b2(cabecera):
            diag["tablas_b2_detectadas"] += 1
            datos_b2.update(_procesar_tabla_b2(tabla, usar_llm=usar_llm_para_b2))
        else:
            # Cabecera ambigua — intentar inferir por contenido de las celdas
            # (ej: si todas las filas tienen un numero en col 0 y el resto es texto,
            # podria ser B.1 o B.2 sin cabecera clara)
            logger.info(
                "[layer1] Tabla pag %d con cabecera ambigua: %s — saltando",
                tabla.pagina, cabecera[:5],
            )

    diag["filas_b1"] = len(filas_b1)
    diag["filas_b2"] = len(datos_b2)

    # Merge B.1 + B.2 por numero_fila
    numeros = sorted(set(filas_b1.keys()) | set(datos_b2.keys()))
    filas_merged: list[FilaTDR] = []

    for num in numeros:
        fila = filas_b1.get(num)
        if fila is None:
            # Fila aparece solo en B.2 — crear shell con cargo de B.2
            # (no ideal pero recuperable)
            datos_b2_fila = datos_b2.get(num, {})
            fila = FilaTDR(
                numero_fila=num,
                cargo="",  # se llenara despues si aparece en B.1 de otra pagina
                profesiones_aceptadas=[],
                pagina=datos_b2_fila.get("pagina"),
                confianza=Confianza.LAYER1_PDFPLUMBER * 0.8,  # menor confianza
                fuente="layer1",
                fila_texto_origen="solo B.2",
            )

        # Mergear datos de B.2
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
        "[layer1] Resultado: %d filas (B.1=%d, B.2=%d, merge=%d)",
        len(filas_merged), diag["filas_b1"], diag["filas_b2"], diag["filas_mergeadas"],
    )

    return filas_merged, diag
