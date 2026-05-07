"""
Scraper de SUNAT (e-consultaruc.sunat.gob.pe) — consulta directa sin browser.

Resuelve la verificación automática de fecha de inscripción de empresas emisoras,
necesaria para ALT04 (empresa emisora constituida después del inicio de la
experiencia declarada).

El "reCAPTCHA" del portal público de SUNAT es un stub que acepta cualquier token
de 52 chars como válido — generamos uno aleatorio en cada llamada.

Sin CAPTCHA real, sin Playwright, sin Selenium. Solo `requests` + `re`.

Basado en el PoC en JS:
  C:/Users/Holbi/Documents/Freelance/variedad/prueba-externos/sunat-playwright/sunat.js

Endpoints:
  [1] GET  /cl-ti-itmrconsruc/FrameCriterioBusquedaWeb.jsp → cookies de sesión
  [2] POST /cl-ti-itmrconsruc/jcrS00Alias  → consulta (RUC | DNI | razón social)

Uso típico:
  from src.scraping.sunat import consultar_ruc
  empresa = consultar_ruc("20263373058")
  if empresa and empresa.fecha_inscripcion:
      ...
"""
from __future__ import annotations

import html as html_module
import json
import logging
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Optional

import requests

try:
    from rapidfuzz import fuzz
except ImportError:  # rapidfuzz es opcional para los tests; en prod debe instalarse
    fuzz = None  # type: ignore

logger = logging.getLogger(__name__)

HOST = "https://e-consultaruc.sunat.gob.pe"
FORM_PATH = "/cl-ti-itmrconsruc/FrameCriterioBusquedaWeb.jsp"
SEARCH_PATH = "/cl-ti-itmrconsruc/jcrS00Alias"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Etiquetas del HTML de detalle SUNAT. Cada una tiene un patrón:
#   <h4>Etiqueta:</h4>
#     ...
#   <p class="list-group-item-text">VALOR</p>
# (algunos campos usan <h4 class="list-group-item-heading"> en lugar de <p>)
_FIELDS = [
    "Número de RUC",
    "Tipo Contribuyente",
    "Nombre Comercial",
    "Fecha de Inscripción",
    "Fecha de Inicio de Actividades",
    "Estado del Contribuyente",
    "Condición del Contribuyente",
    "Domicilio Fiscal",
    "Sistema Emisión de Comprobante",
    "Actividad Comercio Exterior",
    "Sistema Contabilidad",
    "Sistema de Emisión Electrónica",
    "Emisor electrónico desde",
    "Comprobantes Electrónicos",
    "Afiliado al PLE desde",
    "Padrones",
]


# ============================================================================
# Modelo de datos
# ============================================================================

@dataclass
class EmpresaSUNAT:
    """Datos de un contribuyente SUNAT relevantes para el motor de reglas."""

    ruc: str
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    tipo_contribuyente: Optional[str] = None
    fecha_inscripcion: Optional[date] = None
    fecha_inicio_actividades: Optional[date] = None
    estado: Optional[str] = None
    condicion: Optional[str] = None
    domicilio_fiscal: Optional[str] = None
    actividades_economicas: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Serializar dates a ISO string para JSON
        if self.fecha_inscripcion:
            d["fecha_inscripcion"] = self.fecha_inscripcion.isoformat()
        if self.fecha_inicio_actividades:
            d["fecha_inicio_actividades"] = self.fecha_inicio_actividades.isoformat()
        # raw queda fuera del dump por defecto (ruidoso)
        d.pop("raw", None)
        return d


# ============================================================================
# Normalización y fuzzy match de nombres de empresa
# ============================================================================

# Sufijos legales que aparecen al final del nombre y deben quitarse para
# comparar nombres "INSTITUTO DE CONSULTORIA" vs "INSTITUTO DE CONSULTORIA S.A."
_SUFIJOS_LEGALES_RE = re.compile(
    r"\b(?:"
    r"S\.?\s?A\.?\s?C\.?|"   # S.A.C. / SAC / S A C
    r"S\.?\s?A\.?\s?A\.?|"   # S.A.A.
    r"S\.?\s?A\.?|"           # S.A. / SA
    r"E\.?\s?I\.?\s?R\.?\s?L\.?|"  # E.I.R.L.
    r"S\.?\s?R\.?\s?L\.?|"   # S.R.L.
    r"S\.?\s?C\.?\s?R\.?\s?L\.?|"  # S.C.R.L.
    r"LTDA|LIMITADA|"
    r"SOCIEDAD\s+ANONIMA(?:\s+CERRADA|\s+ABIERTA)?|"
    r"EMPRESA\s+INDIVIDUAL\s+DE\s+RESPONSABILIDAD\s+LIMITADA"
    r")\b\.?",
    re.IGNORECASE,
)


def normalizar_nombre_empresa(s: str) -> str:
    """
    Normaliza un nombre de empresa para comparación fuzzy.

    Aplica:
      1. Strip de acentos (Ñ → N, á → a, etc.)
      2. Eliminación de sufijos legales (S.A., S.A.C., E.I.R.L., etc.)
      3. Eliminación de puntuación y símbolos
      4. Colapso de whitespace
      5. UPPERCASE

    Ejemplos:
      "INSTITUTO DE CONSULTORÍA S.A.C." → "INSTITUTO DE CONSULTORIA"
      "INDECONSULT  E.I.R.L."           → "INDECONSULT"
    """
    if not s:
        return ""
    # Quitar acentos
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Quitar sufijos legales
    s = _SUFIJOS_LEGALES_RE.sub("", s)
    # Quitar puntuación que no sea letra/número/espacio
    s = re.sub(r"[^\w\s]", " ", s)
    # Colapsar whitespace y uppercase
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def score_match_empresa(declarado: str, sunat: str) -> int:
    """
    Compara dos nombres de empresa con fuzzy matching.

    Returns:
        Score 0-100. Interpretación recomendada:
          ≥ 85: match fuerte (misma empresa, posible diferencia de sufijo)
          70-84: match parcial (probablemente misma pero verificar)
          < 70: mismatch (probablemente empresas distintas o RUC declarado mal)

    Si rapidfuzz no está disponible, devuelve 100 si los strings normalizados
    son iguales y 0 si no — degradación elegante.
    """
    norm_decl = normalizar_nombre_empresa(declarado or "")
    norm_sunat = normalizar_nombre_empresa(sunat or "")
    if not norm_decl or not norm_sunat:
        return 0
    if fuzz is None:
        return 100 if norm_decl == norm_sunat else 0
    # token_sort_ratio maneja bien orden distinto y palabras extra
    return int(fuzz.token_sort_ratio(norm_decl, norm_sunat))


# ============================================================================
# Helpers privados
# ============================================================================

def _fake_captcha_token(length: int = 52) -> str:
    """
    Genera un token aleatorio de la longitud que SUNAT espera.

    El campo `token` del POST se valida contra un stub que acepta cualquier
    string del largo correcto, así que cualquier valor random sirve.
    """
    # token_hex(26) → 52 chars hex
    return secrets.token_hex(length // 2)[:length]


def _parse_fecha_sunat(value: Optional[str]) -> Optional[date]:
    """Parsea fechas SUNAT en formato '15.06.2010' o '15/06/2010' o '15-06-2010'."""
    if not value:
        return None
    value = value.strip()
    if not value or value == "-":
        return None
    for sep in (".", "/", "-"):
        if sep in value:
            try:
                return datetime.strptime(value, f"%d{sep}%m{sep}%Y").date()
            except ValueError:
                continue
    return None


def _strip_tags(s: str) -> str:
    """Quita HTML tags y colapsa whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def _parse_detalle(html: str) -> dict[str, Any]:
    """Extrae los campos del HTML de detalle SUNAT."""
    decoded = html_module.unescape(html)
    out: dict[str, Any] = {}

    for label in _FIELDS:
        pattern = (
            re.escape(label)
            + r":<\/h4>[\s\S]{0,300}?"
            + r"<(?:p|h4)[^>]*list-group-item-(?:text|heading)[^>]*>"
            + r"([\s\S]*?)<\/(?:p|h4)>"
        )
        m = re.search(pattern, decoded)
        if m:
            out[label] = _strip_tags(m.group(1))

    # Actividades económicas (pueden ser varias líneas en una tabla)
    act_block = re.search(
        r"Actividad\(es\) Económica\(s\):<\/h4>[\s\S]*?<table[\s\S]*?<\/table>",
        decoded,
    )
    if act_block:
        actividades = [
            _strip_tags(m.group(1))
            for m in re.finditer(r"<td[^>]*>([\s\S]*?)<\/td>", act_block.group(0))
        ]
        out["Actividades Económicas"] = [a for a in actividades if a]

    return out


def _parse_lista(html: str) -> list[dict[str, str]]:
    """Extrae items cuando la búsqueda devuelve múltiples resultados (razón social)."""
    decoded = html_module.unescape(html)
    items: list[dict[str, str]] = []

    pattern = re.compile(
        r"RUC:\s*<\/h4>[\s\S]*?<h4[^>]*>(\d{11})<\/h4>"
        r"[\s\S]*?<h4[^>]*>([^<]+)<\/h4>"
        r"[\s\S]*?Ubicaci[oó]n[^<]*:[^<]*<\/h4>[\s\S]*?<h4[^>]*>([^<]+)<\/h4>"
        r"[\s\S]*?Estado[^<]*:[^<]*<\/h4>[\s\S]*?<h4[^>]*>([^<]+)<\/h4>"
    )
    for m in pattern.finditer(decoded):
        items.append({
            "ruc": m.group(1).strip(),
            "razon_social": _strip_tags(m.group(2)),
            "ubicacion": _strip_tags(m.group(3)),
            "estado": _strip_tags(m.group(4)),
        })

    if not items:
        # Fallback: pattern más simple (solo RUC + razón social)
        for m in re.finditer(r"RUC:\s*(\d{11})[\s\S]*?<h4[^>]*>([^<]+)<\/h4>", decoded):
            items.append({
                "ruc": m.group(1).strip(),
                "razon_social": _strip_tags(m.group(2)),
            })

    return items


def _detectar_encoding(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "iso-8859-1" in ct or "latin1" in ct or "windows-1252" in ct:
        return "latin-1"
    return "utf-8"


# ============================================================================
# API pública
# ============================================================================

def consultar_ruc(
    ruc: str,
    *,
    timeout: float = 15.0,
    session: Optional[requests.Session] = None,
) -> Optional[EmpresaSUNAT]:
    """
    Consulta SUNAT por RUC (11 dígitos) y devuelve los datos del contribuyente.

    Devuelve `None` si:
      - SUNAT no responde 200
      - El RUC no existe
      - El HTML no es parseable

    El llamador es responsable de cachear el resultado por RUC (los datos SUNAT
    cambian muy poco — TTL razonable: 30 días).

    Args:
        ruc: número de RUC (11 dígitos)
        timeout: timeout HTTP por request, en segundos
        session: opcional, para reusar cookies/keep-alive entre llamadas

    Raises:
        ValueError: si el RUC no es 11 dígitos
    """
    if not re.match(r"^\d{11}$", ruc):
        raise ValueError(f"RUC debe ser 11 digitos: {ruc!r}")

    own_session = session is None
    if session is None:
        session = requests.Session()
    if "User-Agent" not in session.headers:
        session.headers["User-Agent"] = USER_AGENT

    try:
        # Bootstrap: GET para obtener cookies de sesión
        try:
            r_form = session.get(HOST + FORM_PATH, timeout=timeout)
            r_form.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("SUNAT bootstrap fallo para RUC %s: %s", ruc, exc)
            return None

        # POST con el RUC
        body = {
            "accion": "consPorRuc",
            "razSoc": "",
            "nroRuc": ruc,
            "nrodoc": "",
            "search1": ruc,
            "search2": "",
            "search3": "",
            "tipdoc": "1",
            "rbtnTipo": "1",
            "codigo": "",
            "contexto": "ti-it",
            "modo": "1",
            "token": _fake_captcha_token(),
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": HOST + FORM_PATH,
            "Origin": HOST,
        }
        try:
            r_search = session.post(
                HOST + SEARCH_PATH, data=body, headers=headers, timeout=timeout
            )
            r_search.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("SUNAT search fallo para RUC %s: %s", ruc, exc)
            return None

        r_search.encoding = _detectar_encoding(r_search.headers.get("Content-Type", ""))
        html = r_search.text
    finally:
        if own_session:
            session.close()

    # ¿Vino lista o detalle? La búsqueda por RUC siempre devuelve detalle,
    # pero defendemos por si SUNAT cambia.
    if "Relación de contribuyentes" in html or "Relaci&oacute;n de contribuyentes" in html:
        logger.info("SUNAT devolvio lista para RUC %s (inesperado)", ruc)
        return None

    raw = _parse_detalle(html)
    if not raw or not raw.get("Número de RUC"):
        logger.info("SUNAT no devolvio detalle parseable para RUC %s", ruc)
        return None

    # El campo "Número de RUC" viene como "12345 - RAZON SOCIAL"
    nro_ruc_full = raw.get("Número de RUC", "")
    razon_social = None
    if " - " in nro_ruc_full:
        razon_social = nro_ruc_full.split(" - ", 1)[1].strip()

    return EmpresaSUNAT(
        ruc=ruc,
        razon_social=razon_social,
        nombre_comercial=raw.get("Nombre Comercial") or None,
        tipo_contribuyente=raw.get("Tipo Contribuyente"),
        fecha_inscripcion=_parse_fecha_sunat(raw.get("Fecha de Inscripción")),
        fecha_inicio_actividades=_parse_fecha_sunat(raw.get("Fecha de Inicio de Actividades")),
        estado=raw.get("Estado del Contribuyente"),
        condicion=raw.get("Condición del Contribuyente"),
        domicilio_fiscal=raw.get("Domicilio Fiscal"),
        actividades_economicas=raw.get("Actividades Económicas", []),
        raw=raw,
    )


def buscar_por_razon_social(
    razon_social: str,
    *,
    timeout: float = 15.0,
    session: Optional[requests.Session] = None,
) -> list[dict[str, str]]:
    """
    Busca contribuyentes por razón social (puede devolver múltiples).

    Útil cuando la propuesta tiene el nombre de la empresa pero no el RUC, o
    para validar que un RUC declarado realmente coincida con el nombre.

    Devuelve lista de dicts con `ruc`, `razon_social`, `ubicacion`, `estado`.
    """
    own_session = session is None
    if session is None:
        session = requests.Session()
    if "User-Agent" not in session.headers:
        session.headers["User-Agent"] = USER_AGENT

    try:
        try:
            r_form = session.get(HOST + FORM_PATH, timeout=timeout)
            r_form.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("SUNAT bootstrap fallo: %s", exc)
            return []

        body = {
            "accion": "consPorRazonSoc",
            "razSoc": razon_social,
            "nroRuc": "",
            "nrodoc": "",
            "search1": "",
            "search2": "",
            "search3": razon_social,
            "tipdoc": "1",
            "rbtnTipo": "3",
            "codigo": "",
            "contexto": "ti-it",
            "modo": "1",
            "token": _fake_captcha_token(),
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": HOST + FORM_PATH,
            "Origin": HOST,
        }
        try:
            r_search = session.post(
                HOST + SEARCH_PATH, data=body, headers=headers, timeout=timeout
            )
            r_search.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("SUNAT busqueda razon social fallo: %s", exc)
            return []

        r_search.encoding = _detectar_encoding(r_search.headers.get("Content-Type", ""))
        html = r_search.text
    finally:
        if own_session:
            session.close()

    return _parse_lista(html)


# ============================================================================
# CLI util — `python -m src.scraping.sunat <RUC>`
# ============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) != 2:
        print("Uso: python -m src.scraping.sunat <RUC|razon social>", file=sys.stderr)
        sys.exit(1)

    arg = sys.argv[1]
    if re.match(r"^\d{11}$", arg):
        empresa = consultar_ruc(arg)
        if not empresa:
            print(json.dumps({"error": "RUC no encontrado o error al consultar"}))
            sys.exit(2)
        print(json.dumps(empresa.to_dict(), ensure_ascii=False, indent=2, default=str))
    else:
        items = buscar_por_razon_social(arg)
        print(json.dumps({"resultados": items}, ensure_ascii=False, indent=2))
