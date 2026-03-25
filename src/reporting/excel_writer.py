"""
Genera el Excel final con 5 hojas usando openpyxl.
Colores: Verde = Cumple · Amarillo = Observación · Rojo = No cumple/Alerta crítica
"""
from pathlib import Path

import openpyxl
from openpyxl.styles import PatternFill

GREEN = PatternFill("solid", fgColor="00B050")
YELLOW = PatternFill("solid", fgColor="FFFF00")
RED = PatternFill("solid", fgColor="FF0000")


def write_report(data: dict, output_path: Path) -> None:
    """
    Genera el Excel de salida.
    data debe contener: professionals, experiences, alerts, rtm_results, infoobras_results
    Hojas:
      1. Resumen
      2. Base de Datos (27 columnas)
      3. Evaluación RTM (22 columnas)
      4. Alertas
      5. Verificación InfoObras
    """
    wb = openpyxl.Workbook()
    # TODO: construir cada hoja
    wb.save(output_path)
