"""
Pipeline de extraccion TDR de 3 capas (B.1 / B.2).

Resuelve cross-row contamination eliminando la responsabilidad del LLM
para identificar limites de fila/columna. La estructura la determinan
parsers deterministicos; el LLM solo procesa contenido aislado.

Capas (de mas robusta a menos robusta, con fallback automatico):

  Capa 1: pdfplumber.extract_tables() — celdas exactas para PDFs digitales
          con bordes de tabla detectables. Cero LLM para estructura.

  Capa 2: PP-Structure de PaddleOCR — celdas aproximadas para PDFs
          escaneados via subprocess al motor-OCR. Mediana confianza.

  Capa 3: Segmentacion regex por catalogo de cargos OSCE + LLM por fila
          aislada. Fallback robusto cuando 1 y 2 fallan.

API publica:

    from src.tdr.extractor.table_extractor import extraer_tdr_3_capas

    resultado = extraer_tdr_3_capas(
        pdf_path="ruta/al/tdr.pdf",
        texto_por_pagina={1: "...", 2: "...", ...},  # OCR ya hecho
        paginas_b1=[2, 3],
        paginas_b2=[4, 5, 6],
    )
    # resultado.filas → list[FilaTDR]
    # resultado.capa_usada → "layer1" | "layer2" | "layer3"
    # resultado.diagnostico → dict con metricas
"""
from src.tdr.extractor.table_extractor.models import (
    FilaTDR,
    ResultadoExtraccion,
    Confianza,
)
from src.tdr.extractor.table_extractor.orchestrator import (
    extraer_tdr_3_capas,
)

__all__ = [
    "FilaTDR",
    "ResultadoExtraccion",
    "Confianza",
    "extraer_tdr_3_capas",
]
