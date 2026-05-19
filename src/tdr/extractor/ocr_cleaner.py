"""
Pre-limpieza del texto OCR antes de pasarlo al LLM o al 3-layer extractor.

Motor-OCR (PaddleOCR + Qwen-VL) a veces produce salida con:
- Palabras pegadas por espacios perdidos: "deConstruccion" en vez de "de Construccion"
- "y/o" pegado a palabras adyacentes: "obray/o" en vez de "obra y/o"
- Smart quotes Unicode que rompen JSON: " " ' ' en vez de " ' '
- Whitespace y saltos de linea excesivos
- Caracteres de control invisibles que confunden al LLM

Este modulo aplica reglas genericas que NO dependen del contenido especifico
del PDF. Funciona para cualquier TDR OSCE.

NO toca:
- Errores de OCR semanticos (METRADOS -> METRÁGOS): eso lo arregla la
  Fase C (fuzzy match al lexico canonico).
- La estructura de tablas (que es responsabilidad del 3-layer).
- Texto que parece intencional aunque sea raro (numeros, simbolos validos).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# ============================================================================
# Reglas individuales (expuestas para testing per-regla)
# ============================================================================

def _separar_camel_pegado(texto: str) -> str:
    """
    'deConstruccion' -> 'de Construccion'
    'GerenteDeContrato' -> 'Gerente De Contrato' (caso menos comun)

    Solo aplica cuando una minuscula es seguida directamente por mayuscula,
    patron tipico de OCR que pego dos palabras al perder un espacio.

    No toca acronimos en mayusculas continuas (CIP, OSCE, B.1 no cambian).
    """
    return re.sub(
        r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])",
        r"\1 \2",
        texto,
    )


def _separar_y_o_pegado(texto: str) -> str:
    """
    'obray/o' -> 'obra y/o'
    'jefey/o' -> 'jefe y/o'
    'y/oSupervisor' -> 'y/o Supervisor'

    El conector 'y/o' es muy comun en TDRs OSCE para listar cargos
    alternativos y a veces el OCR lo pega a la palabra adyacente.
    """
    # palabra + "y/o" + palabra
    texto = re.sub(r"([a-záéíóúñA-ZÁÉÍÓÚÑ])y/o([a-záéíóúñA-ZÁÉÍÓÚÑ])", r"\1 y/o \2", texto)
    # solo lado izquierdo (espacio antes pero no despues)
    texto = re.sub(r"([a-záéíóúñA-ZÁÉÍÓÚÑ])y/o\s", r"\1 y/o ", texto)
    # solo lado derecho (espacio despues pero no antes)
    texto = re.sub(r"\sy/o([a-záéíóúñA-ZÁÉÍÓÚÑ])", r" y/o \1", texto)
    return texto


def _normalizar_comillas_unicode(texto: str) -> str:
    """
    Smart quotes -> ASCII equivalents.
    Evita que rompan el JSON que devuelve el LLM o que el LLM las copie
    de forma inconsistente.
    """
    reemplazos = {
        "“": '"', "”": '"',  # smart double quotes
        "‘": "'", "’": "'",  # smart single quotes
        "«": '"', "»": '"',  # guillemets
        "–": "-", "—": "-",  # en/em dash
        " ": " ",                 # non-breaking space
        "​": "",                  # zero-width space
        "﻿": "",                  # BOM
    }
    for k, v in reemplazos.items():
        texto = texto.replace(k, v)
    return texto


def _colapsar_whitespace(texto: str) -> str:
    """
    Multiple espacios/tabs -> un espacio. Multiples saltos de linea -> max 2.
    NO toca contenido relevante, solo limpia ruido visual.
    """
    # Espacios y tabs multiples
    texto = re.sub(r"[ \t]+", " ", texto)
    # Saltos de linea: max 2 consecutivos (preserva separacion entre parrafos)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    # Espacios al final de cada linea
    texto = re.sub(r" +\n", "\n", texto)
    return texto


def _separar_numero_y_unidad_pegados(texto: str) -> str:
    """
    '36meses' -> '36 meses', '24Meses' -> '24 Meses'
    Patron comun en tablas OSCE donde el numero de meses queda pegado.
    """
    return re.sub(
        r"(\d+)(meses|MESES|Meses|años|años|AÑOS)",
        r"\1 \2",
        texto,
    )


def _separar_parentesis_pegados(texto: str) -> str:
    """
    'subespecialidad(salud)' -> 'subespecialidad (salud)'
    Mejora legibilidad para el LLM sin cambiar contenido.
    """
    # palabra + paréntesis-abre
    texto = re.sub(r"([a-záéíóúñA-ZÁÉÍÓÚÑ])\(", r"\1 (", texto)
    # paréntesis-cierra + palabra
    texto = re.sub(r"\)([a-záéíóúñA-ZÁÉÍÓÚÑ])", r") \1", texto)
    return texto


# ============================================================================
# API publica
# ============================================================================

def limpiar_md_ocr(texto: str, *, log_cambios: bool = True) -> str:
    """
    Aplica todas las reglas de pre-limpieza en orden.

    Args:
        texto: texto OCR crudo (full_text del PDF o contenido de .md)
        log_cambios: si True, registra cuantos chars cambiaron por regla

    Returns:
        Texto limpio. Garantiza que el contenido semantico NO cambia,
        solo se normaliza el formato.
    """
    if not texto:
        return texto

    largo_inicial = len(texto)

    pasos = [
        ("comillas_unicode",   _normalizar_comillas_unicode),
        ("camel_pegado",       _separar_camel_pegado),
        ("y_o_pegado",         _separar_y_o_pegado),
        ("numero_unidad",      _separar_numero_y_unidad_pegados),
        ("parentesis_pegados", _separar_parentesis_pegados),
        # whitespace al final para limpiar espacios introducidos por las reglas
        ("whitespace",         _colapsar_whitespace),
    ]

    cambios_por_paso = {}
    for nombre, fn in pasos:
        antes = texto
        texto = fn(texto)
        cambios = sum(1 for a, b in zip(antes, texto) if a != b)
        # Si la longitud cambio significativamente, contarlo tambien
        diff_largo = abs(len(texto) - len(antes))
        cambios_por_paso[nombre] = cambios + diff_largo

    if log_cambios:
        total_cambios = sum(cambios_por_paso.values())
        if total_cambios > 0:
            resumen = ", ".join(
                f"{k}={v}" for k, v in cambios_por_paso.items() if v > 0
            )
            logger.info(
                "[ocr-cleaner] %d -> %d chars, cambios: %s",
                largo_inicial, len(texto), resumen,
            )

    return texto


def es_texto_sospechoso(texto: str) -> tuple[bool, list[str]]:
    """
    Heuristica que detecta si el texto OCR tiene problemas que el cleaner
    NO puede arreglar (ej: paginas rotadas, OCR completamente fallido).

    Returns:
        (es_sospechoso, razones)
    """
    razones = []
    if not texto or len(texto.strip()) < 100:
        razones.append("texto muy corto (<100 chars)")

    # Demasiados caracteres no-imprimibles
    no_print = sum(1 for c in texto if not c.isprintable() and c not in "\n\t")
    if no_print > len(texto) * 0.05:
        razones.append(f"{no_print} caracteres no imprimibles (>5%)")

    # Pocas palabras del vocabulario español típico (heuristica gruesa)
    palabras_freq = ("de", "la", "el", "y", "que", "en", "los", "las", "del")
    cuenta_freq = sum(texto.lower().count(f" {p} ") for p in palabras_freq)
    if cuenta_freq < 10:
        razones.append(f"pocas palabras frecuentes ({cuenta_freq}); OCR posiblemente roto")

    return bool(razones), razones
