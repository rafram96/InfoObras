"""
Scraper de InfoObras (Contraloría General de la República).

Endpoints usados:
  [1] POST /infobrasweb/Mapa/busqueda/obrasBasic → búsqueda por CUI
  [5] GET /InfobrasWeb/Mapa/DatosEjecucion?ObraId={id} → datos de ejecución

Los datos de ejecución vienen como variables JavaScript embebidas en el HTML:
  var lAvances = [...];     → avances mensuales con estado/paralización
  var lSupervisor = [...];  → histórico de supervisores
  var lResidente = [...];   → histórico de residentes
  var lContratista = [...]; → contratista ejecutor

Sin CAPTCHA, sin Playwright — solo requests + regex.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_MAPA = "https://infobras.contraloria.gob.pe/infobrasweb"
BASE_WEB = "https://infobras.contraloria.gob.pe/InfobrasWeb"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_WEB}/Mapa/Index",
}

# Regex para extraer arrays JS embebidos en el HTML de DatosEjecucion
_JS_VAR_RE = re.compile(r"var\s+(\w+)\s*=\s*(\[.*?\])\s*;", re.DOTALL)

# Meses en español → número
_MES_NUM = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
    "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# Rate limiting: segundos entre requests
_DELAY = 2.0


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------

@dataclass
class SupervisorInfo:
    """Un supervisor/inspector registrado en InfoObras."""
    nombre: str
    apellido_paterno: str
    apellido_materno: Optional[str]
    tipo: str                          # "Inspector" / "Supervisor"
    tipo_persona: str                  # "Natural" / "Juridica"
    empresa: Optional[str]
    ruc: Optional[str]
    dni: Optional[str]
    fecha_inicio: Optional[date]
    fecha_fin: Optional[date]


@dataclass
class ResidenteInfo:
    """Un residente registrado en InfoObras."""
    nombre: str
    apellido_paterno: str
    apellido_materno: Optional[str]
    fecha_inicio: Optional[date]
    fecha_fin: Optional[date]


@dataclass
class AvanceMensual:
    """Un avance mensual de la obra."""
    anio: int
    mes: int
    estado: str                        # "En ejecución" / "Paralizado" / "Finalizado"
    tipo_paralizacion: Optional[str]   # "Total" / "Parcial" / None
    fecha_paralizacion: Optional[date]
    dias_paralizado: int
    causal: Optional[str]


@dataclass
class WorkInfo:
    """Datos completos de una obra de InfoObras."""
    cui: str
    obra_id: int
    nombre: Optional[str] = None
    estado: Optional[str] = None
    tipo_obra: Optional[str] = None
    entidad: Optional[str] = None
    ejecutor: Optional[str] = None
    ruc_ejecutor: Optional[str] = None
    monto_contrato: Optional[float] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    plazo_dias: Optional[int] = None
    supervisores: list[SupervisorInfo] = field(default_factory=list)
    residentes: list[ResidenteInfo] = field(default_factory=list)
    avances: list[AvanceMensual] = field(default_factory=list)
    suspension_periods: list[tuple[date, date]] = field(default_factory=list)
    raw_busqueda: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parseo de fechas
# ---------------------------------------------------------------------------

def _parse_fecha_ddmmyyyy(texto: Optional[str]) -> Optional[date]:
    """Parsea 'DD/MM/YYYY' a date."""
    if not texto or not texto.strip():
        return None
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _parse_timestamp_json(ts_str: Optional[str]) -> Optional[date]:
    """Parsea '/Date(1574485200000)/' a date."""
    if not ts_str:
        return None
    m = re.search(r"/Date\((\d+)\)/", ts_str)
    if not m:
        return None
    ts = int(m.group(1)) / 1000
    return datetime.utcfromtimestamp(ts).date()


# ---------------------------------------------------------------------------
# Session y requests
# ---------------------------------------------------------------------------

def _crear_session() -> requests.Session:
    """Crea una session HTTP con cookies y headers de InfoObras."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f"{BASE_WEB}/", timeout=10)
    return s


def _buscar_por_cui(session: requests.Session, cui: str) -> list[dict]:
    """
    Busca obras por CUI en InfoObras.
    Retorna lista de dicts crudos de la API.
    """
    params_json = {
        "codDepartamento": "", "codProvincia": None, "codDistrito": None,
        "codigoObra": "", "estadoRegistro": "", "nobrCodmodejec": "",
        "cobrCodentpub": "", "codtipobrnv1": "", "codtipobrnv2": None,
        "nombrObra": "", "codSnip": cui,
        "fechaIniObraDesde": "", "fechaIniObraHasta": "",
        "tieneMonitor": "", "estObra": "", "codNivel3": None,
        "codMarca": "", "modServControl": "", "servControl": "",
        "nombreEntidad": "", "getFavoritos": 0,
    }
    url = f"{BASE_MAPA}/Mapa/busqueda/obrasBasic"
    query = {
        "page": 0,
        "rowsPerPage": 20,
        "Parameters": json.dumps(params_json, separators=(",", ":")),
    }
    r = session.post(url, params=query, timeout=15)
    r.raise_for_status()
    data = r.json()
    result = data.get("Result", data)
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("data", result.get("obras", [result]))
    return []


def _extraer_datos_ejecucion(session: requests.Session, obra_id: int) -> dict[str, list]:
    """
    Descarga DatosEjecucion y extrae las variables JS embebidas.
    Retorna {nombre_variable: lista_de_dicts}.
    """
    url = f"{BASE_WEB}/Mapa/DatosEjecucion"
    session.headers["Accept"] = "text/html,*/*"
    r = session.get(url, params={"ObraId": obra_id}, timeout=30)
    session.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    r.raise_for_status()

    variables: dict[str, list] = {}
    for match in _JS_VAR_RE.finditer(r.text):
        nombre = match.group(1)
        try:
            datos = json.loads(match.group(2))
            variables[nombre] = datos
        except json.JSONDecodeError:
            logger.warning("InfoObras: no se pudo parsear var %s", nombre)

    return variables


# ---------------------------------------------------------------------------
# Procesamiento de datos crudos → modelos
# ---------------------------------------------------------------------------

def _procesar_supervisores(raw_list: list[dict]) -> list[SupervisorInfo]:
    """Convierte la lista cruda de lSupervisor a SupervisorInfo."""
    supervisores = []
    for r in raw_list:
        supervisores.append(SupervisorInfo(
            nombre=r.get("NombreRep", ""),
            apellido_paterno=r.get("ApellidoPaterno", ""),
            apellido_materno=r.get("ApellidoMaterno"),
            tipo=r.get("TipoSupervisor", ""),
            tipo_persona=r.get("TipoPersona", ""),
            empresa=r.get("NombreEmpresa"),
            ruc=r.get("Ruc"),
            dni=r.get("NumeroDocRep"),
            fecha_inicio=_parse_fecha_ddmmyyyy(r.get("FechaInicio")),
            fecha_fin=_parse_fecha_ddmmyyyy(r.get("FechaFin")),
        ))
    return supervisores


def _procesar_residentes(raw_list: list[dict]) -> list[ResidenteInfo]:
    """Convierte la lista cruda de lResidente a ResidenteInfo."""
    residentes = []
    for r in raw_list:
        residentes.append(ResidenteInfo(
            nombre=r.get("NombreRep", ""),
            apellido_paterno=r.get("ApellidoPaterno", ""),
            apellido_materno=r.get("ApellidoMaterno"),
            fecha_inicio=_parse_fecha_ddmmyyyy(r.get("FechaInicio")),
            fecha_fin=_parse_fecha_ddmmyyyy(r.get("FechaFin")),
        ))
    return residentes


def _procesar_avances(raw_list: list[dict]) -> list[AvanceMensual]:
    """Convierte la lista cruda de lAvances a AvanceMensual."""
    avances = []
    for r in raw_list:
        anio_str = r.get("Anio", "0")
        mes_str = (r.get("Mes") or "").upper().strip()
        anio = int(anio_str) if anio_str.isdigit() else 0
        mes = _MES_NUM.get(mes_str, 0)

        avances.append(AvanceMensual(
            anio=anio,
            mes=mes,
            estado=r.get("Estado", ""),
            tipo_paralizacion=r.get("TipoParalizacion"),
            fecha_paralizacion=_parse_fecha_ddmmyyyy(r.get("FechaParalizacion")),
            dias_paralizado=int(r.get("DiasParalizado", 0) or 0),
            causal=r.get("Causal"),
        ))
    return avances


def _extraer_periodos_suspension(avances: list[AvanceMensual]) -> list[tuple[date, date]]:
    """
    Extrae periodos continuos de paralización/suspensión desde los avances.

    Agrupa meses consecutivos con estado "Paralizado" en un solo periodo.
    """
    periodos: list[tuple[date, date]] = []
    inicio_actual: Optional[date] = None
    fin_actual: Optional[date] = None

    for av in sorted(avances, key=lambda a: (a.anio, a.mes)):
        if "paraliz" in av.estado.lower() or "suspend" in av.estado.lower():
            # Inicio del mes
            if av.anio and av.mes:
                mes_inicio = date(av.anio, av.mes, 1)
                # Fin del mes (aprox)
                if av.mes == 12:
                    mes_fin = date(av.anio, 12, 31)
                else:
                    mes_fin = date(av.anio, av.mes + 1, 1)

                # Si hay fecha exacta de paralización, usarla como inicio
                if av.fecha_paralizacion:
                    mes_inicio = av.fecha_paralizacion

                if inicio_actual is None:
                    inicio_actual = mes_inicio
                    fin_actual = mes_fin
                else:
                    # ¿Es continuación del periodo actual?
                    if mes_inicio <= fin_actual or (mes_inicio - fin_actual).days <= 31:
                        fin_actual = max(fin_actual, mes_fin)
                    else:
                        periodos.append((inicio_actual, fin_actual))
                        inicio_actual = mes_inicio
                        fin_actual = mes_fin
        else:
            # Mes activo → cerrar periodo si hay uno abierto
            if inicio_actual is not None:
                periodos.append((inicio_actual, fin_actual))
                inicio_actual = None
                fin_actual = None

    # Cerrar último periodo si quedó abierto
    if inicio_actual is not None:
        periodos.append((inicio_actual, fin_actual))

    return periodos


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def fetch_by_cui(cui: str) -> Optional[WorkInfo]:
    """
    Consulta InfoObras por CUI y retorna datos completos de la obra.

    Ejecuta 2 requests:
      1. Búsqueda por CUI → obtiene obra_id + datos básicos
      2. DatosEjecucion → avances, supervisores, residentes, paralizaciones

    Retorna None si no se encuentra la obra.
    """
    try:
        session = _crear_session()

        # [1] Buscar por CUI
        logger.info("InfoObras: buscando CUI %s", cui)
        obras = _buscar_por_cui(session, cui)

        if not obras:
            logger.info("InfoObras: CUI %s no encontrado", cui)
            return None

        # Tomar la primera obra (si hay múltiples, es desambiguación futura)
        obra_raw = obras[0]
        obra_id = obra_raw.get("codigoObra")
        if not obra_id:
            logger.warning("InfoObras: obra sin codigoObra para CUI %s", cui)
            return None

        logger.info(
            "InfoObras: CUI %s → ObraId %s — %s",
            cui, obra_id, obra_raw.get("nombrObra", "")[:60],
        )

        time.sleep(_DELAY)

        # [5] Datos de ejecución
        logger.info("InfoObras: descargando DatosEjecucion para ObraId %s", obra_id)
        datos = _extraer_datos_ejecucion(session, obra_id)

        # Procesar datos
        supervisores = _procesar_supervisores(datos.get("lSupervisor", []))
        residentes = _procesar_residentes(datos.get("lResidente", []))
        avances = _procesar_avances(datos.get("lAvances", []))
        suspension_periods = _extraer_periodos_suspension(avances)

        logger.info(
            "InfoObras: ObraId %s — %d avances, %d supervisores, %d residentes, %d periodos suspensión",
            obra_id, len(avances), len(supervisores), len(residentes), len(suspension_periods),
        )

        return WorkInfo(
            cui=cui,
            obra_id=obra_id,
            nombre=obra_raw.get("nombrObra"),
            estado=obra_raw.get("estObra"),
            tipo_obra=obra_raw.get("nomTipoObra"),
            entidad=obra_raw.get("nombreEntidad"),
            ejecutor=obra_raw.get("nombreEjecutor"),
            ruc_ejecutor=obra_raw.get("rucEjecutor"),
            monto_contrato=obra_raw.get("montoObraSoles"),
            fecha_inicio=_parse_timestamp_json(obra_raw.get("fechaIniObra")),
            fecha_fin=_parse_timestamp_json(obra_raw.get("fechaFinObra")),
            plazo_dias=obra_raw.get("plazoObra"),
            supervisores=supervisores,
            residentes=residentes,
            avances=avances,
            suspension_periods=suspension_periods,
            raw_busqueda=obra_raw,
        )

    except requests.RequestException as e:
        logger.error("InfoObras: error de red para CUI %s: %s", cui, e)
        return None
    except Exception as e:
        logger.exception("InfoObras: error inesperado para CUI %s", cui)
        return None


def buscar_obras_por_nombre(nombre: str) -> list[dict]:
    """
    Busca obras por nombre en InfoObras.
    Retorna lista de dicts crudos para desambiguación.
    """
    try:
        session = _crear_session()
        params_json = {
            "codDepartamento": "", "codProvincia": None, "codDistrito": None,
            "codigoObra": "", "estadoRegistro": "", "nobrCodmodejec": "",
            "cobrCodentpub": "", "codtipobrnv1": "", "codtipobrnv2": None,
            "nombrObra": nombre, "codSnip": "",
            "fechaIniObraDesde": "", "fechaIniObraHasta": "",
            "tieneMonitor": "", "estObra": "", "codNivel3": None,
            "codMarca": "", "modServControl": "", "servControl": "",
            "nombreEntidad": "", "getFavoritos": 0,
        }
        url = f"{BASE_MAPA}/Mapa/busqueda/obrasBasic"
        query = {
            "page": 0,
            "rowsPerPage": 20,
            "Parameters": json.dumps(params_json, separators=(",", ":")),
        }
        r = session.post(url, params=query, timeout=15)
        r.raise_for_status()
        data = r.json()
        result = data.get("Result", data)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("data", result.get("obras", []))
        return []
    except Exception as e:
        logger.error("InfoObras: error buscando por nombre '%s': %s", nombre, e)
        return []
