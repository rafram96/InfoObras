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

# Regex para localizar el INICIO de cada declaracion `var lXxx = ...`.
# El JSON real (que puede contener arrays anidados, comillas, etc.) se parsea
# despues con json.JSONDecoder.raw_decode para no depender de regex no-greedy.
_JS_VAR_START_RE = re.compile(r"var\s+(l[A-Z]\w*)\s*=\s*", re.MULTILINE)
_JSON_DECODER = json.JSONDecoder()

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
    # Campos financieros del cronograma (todos opcionales — no siempre vienen)
    avance_fisico_programado: Optional[float] = None  # %
    avance_fisico_real: Optional[float] = None        # %
    valorizado_programado: Optional[float] = None     # S/.
    valorizado_real: Optional[float] = None           # S/.
    pct_ejecucion_financiera: Optional[float] = None  # %
    monto_ejecucion_financiera: Optional[float] = None  # S/.


@dataclass
class ContratistaInfo:
    """Un contratista ejecutor registrado en InfoObras."""
    tipo_empresa: str                  # "Consorcio" / "Individual"
    ruc: Optional[str]                 # RUC con prefijo "C" si es consorcio
    nombre_empresa: str
    monto_soles: Optional[float]
    numero_contrato: Optional[str]
    fecha_contrato: Optional[date]
    fecha_fin_contrato: Optional[date]


@dataclass
class ModificacionPlazoInfo:
    """Una modificación de plazo (ampliación o suspensión)."""
    tipo: str                          # "Ampliación del plazo" / "Suspensión del plazo"
    causal: Optional[str]
    dias_aprobados: int
    fecha_aprobacion: Optional[date]
    fecha_fin: Optional[date]


@dataclass
class EntregaTerrenoInfo:
    """Registro de entrega de terreno."""
    fecha_entrega: Optional[date]
    porcentaje: Optional[float]
    tipo_entrega: Optional[str] = None     # "Total" / "Parcial"


@dataclass
class AdendaInfo:
    """Adenda al contrato (modificacion contractual formal)."""
    numero: Optional[str]
    fecha: Optional[date]
    descripcion: Optional[str] = None


@dataclass
class TransferenciaFinancieraInfo:
    """Transferencia financiera recibida por la entidad ejecutora."""
    ambito: Optional[str]
    entidad_origen: Optional[str]
    monto: Optional[float]
    documento: Optional[str] = None


@dataclass
class AdelantoInfo:
    """Garantia de adelanto (directo, materiales, etc.)."""
    tipo: Optional[str]                    # "Directo" / "Materiales" / etc.
    monto: Optional[float]
    fecha_entrega: Optional[date]
    documento_aprobacion: Optional[str] = None


@dataclass
class CronogramaInfo:
    """Cronograma vigente o actualizacion del cronograma."""
    tipo: Optional[str]                    # "Original" / "Actualizado" / "Reformulado"
    fecha_aprobacion: Optional[date]
    documento: Optional[str] = None
    nueva_fecha_termino: Optional[date] = None


@dataclass
class AdicionalDeductivoInfo:
    """Adicional, deductivo o reduccion al contrato."""
    numero: Optional[str]
    tipo: Optional[str]                    # "Adicional" / "Deductivo" / "Reduccion"
    subtipo: Optional[str]                 # subcategoria si existe
    causal: Optional[str]
    fecha_aprobacion: Optional[date]
    porcentaje: Optional[float]
    monto: Optional[float]
    documento: Optional[str] = None


@dataclass
class ControversiaInfo:
    """Controversia o proceso de solucion de controversias."""
    mecanismo: Optional[str]               # "Arbitraje" / "Junta de Resolucion" / etc.
    estado: Optional[str]
    fecha_inicio: Optional[date]
    fecha_fin: Optional[date]
    documento: Optional[str] = None


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
    # Campos de cabecera adicionales
    codigo_infobras: Optional[str] = None              # ej: "169628"
    porcentaje_avance_fisico: Optional[float] = None   # del ultimo avance real
    monto_ejecutado_acumulado: Optional[float] = None  # S/. acumulado
    # Colecciones existentes
    supervisores: list[SupervisorInfo] = field(default_factory=list)
    residentes: list[ResidenteInfo] = field(default_factory=list)
    avances: list[AvanceMensual] = field(default_factory=list)
    contratistas: list[ContratistaInfo] = field(default_factory=list)
    modificaciones_plazo: list[ModificacionPlazoInfo] = field(default_factory=list)
    entregas_terreno: list[EntregaTerrenoInfo] = field(default_factory=list)
    suspension_periods: list[tuple[date, date]] = field(default_factory=list)
    # Colecciones nuevas (refinacion 2026-04)
    adendas: list[AdendaInfo] = field(default_factory=list)
    transferencias: list[TransferenciaFinancieraInfo] = field(default_factory=list)
    adelantos: list[AdelantoInfo] = field(default_factory=list)
    cronogramas: list[CronogramaInfo] = field(default_factory=list)
    adicionales_deductivos: list[AdicionalDeductivoInfo] = field(default_factory=list)
    controversias: list[ControversiaInfo] = field(default_factory=list)
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


def _parse_js_vars(html: str) -> dict[str, list]:
    """
    Parsea TODAS las declaraciones `var lXxx = [...];` del HTML.

    Usa json.JSONDecoder.raw_decode para soportar correctamente arrays
    con sub-arrays anidados (ej: `lSupervisor = [{Documentos: [...]}]`),
    cosa que un regex no-greedy no maneja bien.

    Retorna {nombre_variable: lista_de_dicts}.
    Variables `null` o no-arrays se omiten silenciosamente.
    """
    variables: dict[str, list] = {}
    nulls: list[str] = []  # vars que aparecen como `null` (existen pero vacias)
    fallidas: list[str] = []  # vars que existen pero no se pudieron parsear

    for match in _JS_VAR_START_RE.finditer(html):
        nombre = match.group(1)
        pos = match.end()
        # Saltar whitespace antes del valor
        while pos < len(html) and html[pos] in " \t\r\n":
            pos += 1
        if pos >= len(html):
            continue
        ch = html[pos]
        if ch == "n":
            if html[pos:pos + 4] == "null":
                variables[nombre] = []
                nulls.append(nombre)
            continue
        if ch != "[" and ch != "{":
            continue
        try:
            obj, _ = _JSON_DECODER.raw_decode(html, pos)
        except json.JSONDecodeError:
            fallidas.append(nombre)
            logger.warning("InfoObras: no se pudo parsear var %s en pos %d", nombre, pos)
            continue
        if isinstance(obj, list):
            variables[nombre] = obj
        elif isinstance(obj, dict):
            variables[nombre] = [obj]

    # Log diagnostico: que variables se encontraron y con cuantos registros
    if logger.isEnabledFor(logging.INFO):
        resumen = ", ".join(
            f"{n}={len(v)}" for n, v in sorted(variables.items())
        )
        logger.info("InfoObras [vars JS]: %s", resumen or "(ninguna)")
        if nulls:
            logger.info("InfoObras [vars null]: %s", ", ".join(sorted(nulls)))
        if fallidas:
            logger.warning("InfoObras [vars no parseadas]: %s", ", ".join(fallidas))

    return variables


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
    return _parse_js_vars(r.text)


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


def _to_float(v) -> Optional[float]:
    """Convierte a float aceptando None, '', strings con coma, etc."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _procesar_avances(raw_list: list[dict]) -> list[AvanceMensual]:
    """Convierte la lista cruda de lAvances a AvanceMensual."""
    if raw_list and logger.isEnabledFor(logging.INFO):
        logger.info(
            "InfoObras [lAvances][1] keys: %s",
            sorted(raw_list[0].keys()),
        )
    avances = []
    for r in raw_list:
        anio_raw = r.get("Anio", "0")
        anio_str = str(anio_raw)
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
            avance_fisico_programado=_to_float(
                r.get("AvanceFisicoProgramado") or r.get("AvProg") or r.get("PctAvFisicoProg")
            ),
            avance_fisico_real=_to_float(
                r.get("AvanceFisicoReal") or r.get("AvReal") or r.get("PctAvFisicoReal")
            ),
            valorizado_programado=_to_float(
                r.get("ValorizadoProgramado") or r.get("MontoProg") or r.get("ValProgramado")
            ),
            valorizado_real=_to_float(
                r.get("ValorizadoReal") or r.get("MontoReal") or r.get("ValReal")
            ),
            pct_ejecucion_financiera=_to_float(
                r.get("PorcentajeEjecucionFinanciera") or r.get("PctEjeFinanciera")
            ),
            monto_ejecucion_financiera=_to_float(
                r.get("MontoEjecucionFinanciera") or r.get("MontoEjeFinanciera")
            ),
        ))
    return avances


def _procesar_contratistas(raw_list: list[dict]) -> list[ContratistaInfo]:
    """Convierte la lista cruda de lContratista a ContratistaInfo."""
    if raw_list and logger.isEnabledFor(logging.INFO):
        logger.info(
            "InfoObras [lContratista][1] keys: %s",
            sorted(raw_list[0].keys()),
        )
    contratistas = []
    for r in raw_list:
        contratistas.append(ContratistaInfo(
            tipo_empresa=r.get("TipoEmpresa", ""),
            ruc=r.get("Ruc"),
            nombre_empresa=r.get("NombreEmpresa", ""),
            monto_soles=r.get("MontoSoles"),
            numero_contrato=r.get("NumeroContrato"),
            fecha_contrato=_parse_fecha_ddmmyyyy(r.get("FechaContrato")),
            fecha_fin_contrato=_parse_fecha_ddmmyyyy(r.get("FechaFinContrato")),
        ))
    return contratistas


def _sintetizar_contratista_de_busqueda(obra_raw: dict) -> Optional[ContratistaInfo]:
    """
    Cuando lContratista viene vacio pero el endpoint de busqueda si tiene
    los datos del ejecutor, sintetiza un registro para que la UI no
    muestre 'Contratistas: 0' incorrectamente.
    """
    nombre = obra_raw.get("nombreEjecutor") or obra_raw.get("ejecutor")
    if not nombre:
        return None
    return ContratistaInfo(
        tipo_empresa="",
        ruc=obra_raw.get("rucEjecutor") or obra_raw.get("ruc"),
        nombre_empresa=str(nombre).strip(),
        monto_soles=obra_raw.get("montoObraSoles"),
        numero_contrato=None,
        fecha_contrato=_parse_timestamp_json(obra_raw.get("fechaIniObra")),
        fecha_fin_contrato=_parse_timestamp_json(obra_raw.get("fechaFinObra")),
    )


def _procesar_modificaciones_plazo(raw_list: list[dict]) -> list[ModificacionPlazoInfo]:
    """Convierte la lista cruda de lModificacionPlazo a ModificacionPlazoInfo."""
    modificaciones = []
    for r in raw_list:
        modificaciones.append(ModificacionPlazoInfo(
            tipo=r.get("TipoModificacion", ""),
            causal=r.get("Causal"),
            dias_aprobados=int(r.get("DiasAprobados", 0) or 0),
            fecha_aprobacion=_parse_fecha_ddmmyyyy(r.get("FechaAprob")),
            fecha_fin=_parse_fecha_ddmmyyyy(r.get("FechaFin")),
        ))
    return modificaciones


def _procesar_entregas_terreno(raw_list: list[dict]) -> list[EntregaTerrenoInfo]:
    """Convierte la lista cruda de lEntregaTerreno a EntregaTerrenoInfo."""
    entregas = []
    for r in raw_list:
        entregas.append(EntregaTerrenoInfo(
            fecha_entrega=_parse_fecha_ddmmyyyy(r.get("FechaEntrega")),
            porcentaje=_to_float(r.get("Porcentaje")),
            tipo_entrega=r.get("TipoEntrega") or r.get("Tipo"),
        ))
    return entregas


def _procesar_adendas(raw_list: list[dict]) -> list[AdendaInfo]:
    """Convierte la lista cruda de lAdenda a AdendaInfo."""
    adendas = []
    for r in raw_list:
        adendas.append(AdendaInfo(
            numero=str(r.get("NumeroAdenda") or r.get("Numero") or "").strip() or None,
            fecha=_parse_fecha_ddmmyyyy(r.get("FechaAdenda") or r.get("Fecha")),
            descripcion=r.get("Descripcion") or r.get("Detalle"),
        ))
    return adendas


def _procesar_transferencias(raw_list: list[dict]) -> list[TransferenciaFinancieraInfo]:
    """Convierte la lista cruda de lTransferenciaFinanciera."""
    transferencias = []
    for r in raw_list:
        transferencias.append(TransferenciaFinancieraInfo(
            ambito=r.get("Ambito") or r.get("ambito"),
            entidad_origen=(
                r.get("EntidadOrigen") or r.get("UnidadEjecutora")
                or r.get("NombreEntidad")
            ),
            monto=_to_float(r.get("MontoTransferencia") or r.get("Monto")),
            documento=r.get("DocumentoTransferencia") or r.get("Documento"),
        ))
    return transferencias


def _procesar_adelantos(raw_list: list[dict]) -> list[AdelantoInfo]:
    """Convierte la lista cruda de lAdelanto a AdelantoInfo (garantias de adelanto)."""
    adelantos = []
    for r in raw_list:
        adelantos.append(AdelantoInfo(
            tipo=r.get("TipoGarantia") or r.get("TipoAdelanto") or r.get("Tipo"),
            monto=_to_float(
                r.get("MontoGarantia") or r.get("MontoAdelanto") or r.get("Monto")
            ),
            fecha_entrega=_parse_fecha_ddmmyyyy(
                r.get("FechaEntrega") or r.get("FechaDesembolso")
            ),
            documento_aprobacion=(
                r.get("DocumentoAprobacion") or r.get("Documento")
            ),
        ))
    return adelantos


def _procesar_cronogramas(raw_list: list[dict]) -> list[CronogramaInfo]:
    """Convierte la lista cruda de lCronograma a CronogramaInfo."""
    cronogramas = []
    for r in raw_list:
        cronogramas.append(CronogramaInfo(
            tipo=r.get("TipoCronograma") or r.get("Tipo"),
            fecha_aprobacion=_parse_fecha_ddmmyyyy(
                r.get("FechaAprobacion") or r.get("FechaAprob")
            ),
            documento=r.get("DocumentoAprobacion") or r.get("Documento"),
            nueva_fecha_termino=_parse_fecha_ddmmyyyy(
                r.get("NuevaFechaTermino") or r.get("FechaTermino")
            ),
        ))
    return cronogramas


def _procesar_adicionales_deductivos(raw_list: list[dict]) -> list[AdicionalDeductivoInfo]:
    """Convierte la lista cruda de lAdicionalDeduc."""
    items = []
    for r in raw_list:
        items.append(AdicionalDeductivoInfo(
            numero=str(
                r.get("NumeroAdicional") or r.get("Numero") or ""
            ).strip() or None,
            tipo=r.get("Tipo") or r.get("TipoAdicional"),
            subtipo=r.get("Subtipo") or r.get("SubTipo"),
            causal=r.get("Causal"),
            fecha_aprobacion=_parse_fecha_ddmmyyyy(
                r.get("FechaAprobacion") or r.get("FechaAprob")
            ),
            porcentaje=_to_float(r.get("Porcentaje") or r.get("PctAprobado")),
            monto=_to_float(r.get("MontoAprobado") or r.get("Monto")),
            documento=r.get("DocumentoAprobacion") or r.get("Documento"),
        ))
    return items


def _procesar_controversias(raw_list: list[dict]) -> list[ControversiaInfo]:
    """Convierte la lista cruda de lControversia a ControversiaInfo."""
    controversias = []
    for r in raw_list:
        controversias.append(ControversiaInfo(
            mecanismo=(
                r.get("MecanismoSolucion") or r.get("Mecanismo")
                or r.get("TipoControversia")
            ),
            estado=r.get("Estado") or r.get("EstadoControversia"),
            fecha_inicio=_parse_fecha_ddmmyyyy(
                r.get("FechaInicio") or r.get("FechaInicioProceso")
            ),
            fecha_fin=_parse_fecha_ddmmyyyy(
                r.get("FechaFin") or r.get("FechaFinProceso")
            ),
            documento=r.get("DocumentoSustento") or r.get("Documento"),
        ))
    return controversias


def _derivar_avance_actual(
    avances: list[AvanceMensual],
) -> tuple[Optional[float], Optional[float]]:
    """
    Toma el avance mas reciente con datos fisicos/financieros y devuelve
    (porcentaje_avance_fisico_real, monto_ejecutado_acumulado).

    Asume que la lista viene ordenada de mas reciente a mas antiguo
    (que es como InfoObras la entrega).
    """
    pct = None
    monto = None
    for av in avances:
        if pct is None and av.avance_fisico_real is not None:
            pct = av.avance_fisico_real
        if monto is None and av.monto_ejecucion_financiera is not None:
            monto = av.monto_ejecucion_financiera
        if pct is not None and monto is not None:
            break
    return pct, monto


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
        contratistas = _procesar_contratistas(datos.get("lContratista", []))
        # Fallback: si el array embebido viene vacio pero el endpoint de
        # busqueda trae nombreEjecutor + rucEjecutor, sintetizar 1 entrada.
        if not contratistas:
            sint = _sintetizar_contratista_de_busqueda(obra_raw)
            if sint:
                contratistas = [sint]
                logger.info(
                    "InfoObras: lContratista vacio, sintetizado desde busqueda: %s",
                    sint.nombre_empresa,
                )
        modificaciones_plazo = _procesar_modificaciones_plazo(datos.get("lModificacionPlazo", []))
        entregas_terreno = _procesar_entregas_terreno(datos.get("lEntregaTerreno", []))
        adendas = _procesar_adendas(datos.get("lAdenda", []))
        transferencias = _procesar_transferencias(datos.get("lTransferenciaFinanciera", []))
        adelantos = _procesar_adelantos(datos.get("lAdelanto", []))
        cronogramas = _procesar_cronogramas(datos.get("lCronograma", []))
        adicionales_deductivos = _procesar_adicionales_deductivos(datos.get("lAdicionalDeduc", []))
        controversias = _procesar_controversias(datos.get("lControversia", []))
        suspension_periods = _extraer_periodos_suspension(avances)

        # Cabecera derivada del avance mas reciente con avance fisico real
        avance_pct_real, monto_ejecutado = _derivar_avance_actual(avances)

        logger.info(
            "InfoObras: ObraId %s — %d avances (%.2f%% real), %d sup, %d res, "
            "%d cont, %d modPlazo, %d terreno, %d adendas, %d transf, "
            "%d adelantos, %d cron, %d adic/deduc, %d contr, %d susp",
            obra_id, len(avances), avance_pct_real or 0.0,
            len(supervisores), len(residentes), len(contratistas),
            len(modificaciones_plazo), len(entregas_terreno), len(adendas),
            len(transferencias), len(adelantos), len(cronogramas),
            len(adicionales_deductivos), len(controversias), len(suspension_periods),
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
            codigo_infobras=str(
                obra_raw.get("codigoInfobras")
                or obra_raw.get("codInfobras")
                or obra_raw.get("CodigoInfobras")
                or ""
            ).strip() or None,
            porcentaje_avance_fisico=avance_pct_real,
            monto_ejecutado_acumulado=monto_ejecutado,
            supervisores=supervisores,
            residentes=residentes,
            avances=avances,
            contratistas=contratistas,
            modificaciones_plazo=modificaciones_plazo,
            entregas_terreno=entregas_terreno,
            suspension_periods=suspension_periods,
            adendas=adendas,
            transferencias=transferencias,
            adelantos=adelantos,
            cronogramas=cronogramas,
            adicionales_deductivos=adicionales_deductivos,
            controversias=controversias,
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


# ---------------------------------------------------------------------------
# Verificación de profesional en obra
# ---------------------------------------------------------------------------

@dataclass
class VerificacionProfesional:
    """Resultado de verificar un profesional contra InfoObras."""
    obra_encontrada: bool = False
    nombre_coincide: bool = False
    score_nombre: float = 0.0
    nombre_encontrado: Optional[str] = None
    periodo_valido: bool = False
    paralizaciones_en_periodo: list[dict] = field(default_factory=list)
    dias_paralizado_en_periodo: int = 0
    alertas: list[str] = field(default_factory=list)


def verificar_profesional_en_obra(
    obra: WorkInfo,
    nombre_profesional: str,
    cargo_tipo: str,
    fecha_inicio_cert: Optional[date] = None,
    fecha_fin_cert: Optional[date] = None,
) -> VerificacionProfesional:
    """
    Verifica si un profesional aparece en InfoObras para la obra dada.

    Args:
        obra: WorkInfo con datos de la obra (supervisores, residentes, avances)
        nombre_profesional: nombre del profesional según el certificado
        cargo_tipo: "supervisor" o "residente"
        fecha_inicio_cert: inicio del periodo según certificado
        fecha_fin_cert: fin del periodo según certificado

    Returns:
        VerificacionProfesional con resultado del cruce
    """
    result = VerificacionProfesional(obra_encontrada=True)

    # 1. Verificar nombre en histórico del cargo
    candidatos = obra.supervisores if cargo_tipo in ("supervisor", "inspector") else obra.residentes

    mejor_score = 0.0
    mejor_nombre = None

    for persona in candidatos:
        if isinstance(persona, SupervisorInfo):
            nombre_inf = f"{persona.nombre} {persona.apellido_paterno} {persona.apellido_materno or ''}".strip()
            p_inicio = persona.fecha_inicio
            p_fin = persona.fecha_fin
        else:
            nombre_inf = f"{persona.nombre} {persona.apellido_paterno} {persona.apellido_materno or ''}".strip()
            p_inicio = persona.fecha_inicio
            p_fin = persona.fecha_fin

        score = _jaccard(nombre_profesional, nombre_inf)

        if score > mejor_score:
            mejor_score = score
            mejor_nombre = nombre_inf

            # Verificar periodo si el nombre matchea bien
            if score >= 0.6 and fecha_inicio_cert and fecha_fin_cert and p_inicio:
                p_fin_eff = p_fin or fecha_fin_cert  # si no tiene fin, asumir vigente
                if fecha_inicio_cert <= p_fin_eff and (fecha_fin_cert >= p_inicio):
                    result.periodo_valido = True

    # También verificar en datos de búsqueda (supervisor/residente actual)
    sup_actual = obra.raw_busqueda.get("nombresSupervisor", "")
    res_actual = obra.raw_busqueda.get("nombresResidente", "")
    nombre_api = sup_actual if cargo_tipo in ("supervisor", "inspector") else res_actual
    if nombre_api:
        score_api = _jaccard(nombre_profesional, nombre_api)
        if score_api > mejor_score:
            mejor_score = score_api
            mejor_nombre = nombre_api

    result.score_nombre = round(mejor_score, 3)
    result.nombre_encontrado = mejor_nombre
    result.nombre_coincide = mejor_score >= 0.6

    if mejor_score < 0.6:
        result.alertas.append(
            f"Nombre '{nombre_profesional}' no coincide con ningún {cargo_tipo} "
            f"en InfoObras (score máx: {mejor_score:.2f})"
        )
    elif not result.periodo_valido and fecha_inicio_cert:
        result.alertas.append(
            f"'{nombre_profesional}' aparece en InfoObras pero en periodo diferente al del certificado"
        )

    # 2. Detectar paralizaciones en el periodo del certificado
    if fecha_inicio_cert and fecha_fin_cert:
        for av in obra.avances:
            if "paraliz" not in av.estado.lower() and "suspend" not in av.estado.lower():
                continue
            if av.anio and av.mes:
                try:
                    ini_mes = date(av.anio, av.mes, 1)
                    fin_mes = date(av.anio, av.mes + 1, 1) if av.mes < 12 else date(av.anio, 12, 31)
                    # Verificar solapamiento
                    if fecha_inicio_cert <= fin_mes and fecha_fin_cert >= ini_mes:
                        result.paralizaciones_en_periodo.append({
                            "periodo": f"{av.estado} — {av.mes}/{av.anio}",
                            "tipo": av.tipo_paralizacion,
                            "dias": av.dias_paralizado,
                            "causal": av.causal,
                        })
                        result.dias_paralizado_en_periodo += av.dias_paralizado
                except (ValueError, TypeError):
                    continue

    if result.paralizaciones_en_periodo:
        result.alertas.append(
            f"Obra paralizada {len(result.paralizaciones_en_periodo)} mes(es) "
            f"durante el periodo del certificado ({result.dias_paralizado_en_periodo} días)"
        )

    return result


# ---------------------------------------------------------------------------
# Similitud de nombres (Jaccard sobre tokens)
# ---------------------------------------------------------------------------

def _normalizar_tokens(texto: str) -> set[str]:
    """Normaliza texto a set de tokens para comparación Jaccard."""
    import unicodedata
    t = unicodedata.normalize("NFD", texto.upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^A-Z0-9\s]", "", t)
    return set(t.split())


def _jaccard(a: str, b: str) -> float:
    """Similitud Jaccard entre dos textos (0.0 a 1.0)."""
    t1 = _normalizar_tokens(a)
    t2 = _normalizar_tokens(b)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


# ---------------------------------------------------------------------------
# Desambiguación: elegir la obra correcta de múltiples resultados
# ---------------------------------------------------------------------------

@dataclass
class ObraCandidata:
    """Resultado de búsqueda con score de relevancia."""
    obra_raw: dict
    obra_id: int
    nombre: str
    cui: str
    estado: str
    fecha_inicio: Optional[date]
    entidad: str
    score: float = 0.0
    motivos: list[str] = field(default_factory=list)


def _extraer_palabras_clave(nombre_proyecto: str) -> list[str]:
    """
    Extrae múltiples variantes de búsqueda para un proyecto.

    Retorna lista de queries ordenadas de más específica a más genérica.
    La API de InfoObras busca por substring en el nombre de la obra,
    así que hay que enviar frases que estén contenidas en el nombre real.

    "MEJORAMIENTO Y AMPLIACIÓN DE LOS SERVICIOS DE SALUD DEL HOSPITAL
     DE APOYO DE POMABAMBA ANTONIO CALDAS DOMÍNGUEZ..."
    → ["HOSPITAL APOYO POMABAMBA", "POMABAMBA", "HOSPITAL POMABAMBA"]
    """
    import unicodedata
    t = unicodedata.normalize("NFD", nombre_proyecto.upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^A-Z0-9\s]", " ", t)

    # Palabras muy genéricas que aparecen en casi todas las obras
    stopwords_busqueda = {
        "MEJORAMIENTO", "AMPLIACION", "CONSTRUCCION", "CREACION",
        "REHABILITACION", "REMODELACION", "INSTALACION", "RECUPERACION",
        "DE", "DEL", "LA", "LAS", "LOS", "EL", "EN", "AL", "CON",
        "PARA", "POR", "A", "UN", "UNA", "Y", "O", "E",
        "SERVICIOS", "SALUD", "OBRA", "PROYECTO", "EJECUCION",
        "SUPERVISION", "CONSULTORIA", "SERVICIO",
        "CAPACIDAD", "RESOLUTIVA", "PRESTACION", "ACCESO",
    }

    # Palabras que indican lugar/tipo (útiles para búsqueda)
    marcadores_tipo = {
        "HOSPITAL", "CENTRO", "ESTABLECIMIENTO", "POSTA", "CLINICA",
        "COLEGIO", "ESCUELA", "UNIVERSIDAD", "CARRETERA", "PUENTE",
        "ESTADIO", "COLISEO", "PALACIO", "MUNICIPALIDAD",
    }

    tokens = t.split()
    # Separar: marcadores de tipo vs topónimos/nombres propios
    keywords = [w for w in tokens if w not in stopwords_busqueda and len(w) > 2]

    queries: list[str] = []

    # Query 1: Tipo + topónimo(s) — lo más específico
    # Ej: "HOSPITAL POMABAMBA" o "HOSPITAL APOYO POMABAMBA"
    tipos = [w for w in keywords if w in marcadores_tipo]
    toponimos = [w for w in keywords if w not in marcadores_tipo and w not in {"APOYO", "NIVEL", "ATENCION", "SEGUNDO", "REGIONAL"}]

    if tipos and toponimos:
        # Tipo + primeros 2 topónimos
        q = " ".join(tipos[:1] + toponimos[:2])
        queries.append(q)

    # Query 2: Solo topónimos (nombre propio del lugar)
    if toponimos:
        queries.append(" ".join(toponimos[:3]))

    # Query 3: Todas las keywords (más amplio)
    if keywords:
        q_full = " ".join(keywords[:5])
        if q_full not in queries:
            queries.append(q_full)

    # Query 4: Tipo + primer topónimo (mínimo)
    if tipos and toponimos and len(toponimos) > 0:
        q_min = f"{tipos[0]} {toponimos[0]}"
        if q_min not in queries:
            queries.append(q_min)

    return queries


def _score_candidata(
    obra: dict,
    nombre_proyecto: str,
    fecha_cert: Optional[date] = None,
    entidad: Optional[str] = None,
) -> ObraCandidata:
    """
    Calcula un score de relevancia para una obra candidata.

    Criterios (en orden de peso):
    1. Similitud de nombre (Jaccard) → 0-50 puntos
    2. Proximidad de fecha inicio → 0-30 puntos
    3. Coincidencia de entidad → 0-20 puntos
    """
    nombre_obra = obra.get("nombrObra", "")
    cui = obra.get("codUniqInv", "")
    obra_id = obra.get("codigoObra", 0)
    estado = obra.get("estObra", "")
    entidad_obra = obra.get("nombreEntidad", "")
    fecha_inicio = _parse_timestamp_json(obra.get("fechaIniObra"))

    score = 0.0
    motivos = []

    # 1. Similitud de nombre (peso: 50%)
    sim_nombre = _jaccard(nombre_proyecto, nombre_obra)
    score_nombre = sim_nombre * 50
    score += score_nombre
    motivos.append(f"nombre={sim_nombre:.2f}")

    # 2. Proximidad de fecha (peso: 30%)
    # La obra cuya fecha_inicio sea más cercana y ANTERIOR a la fecha del certificado
    if fecha_cert and fecha_inicio:
        diff_dias = (fecha_cert - fecha_inicio).days
        if 0 <= diff_dias <= 365 * 10:
            # Fecha inicio es anterior al certificado (correcto)
            # Más cercana = más puntos (máx 30 si diff < 1 año)
            score_fecha = max(0, 30 - (diff_dias / 365) * 3)
            score += score_fecha
            motivos.append(f"fecha_diff={diff_dias}d (+{score_fecha:.0f})")
        elif diff_dias < 0:
            # Obra empezó DESPUÉS del certificado → penalizar
            motivos.append(f"fecha_posterior (-10)")
            score -= 10
        else:
            # Más de 10 años de diferencia → poco probable
            motivos.append(f"fecha_lejana={diff_dias}d")

    # 3. Coincidencia de entidad (peso: 20%)
    if entidad and entidad_obra:
        sim_entidad = _jaccard(entidad, entidad_obra)
        score_entidad = sim_entidad * 20
        score += score_entidad
        if sim_entidad > 0.3:
            motivos.append(f"entidad={sim_entidad:.2f}")

    return ObraCandidata(
        obra_raw=obra,
        obra_id=obra_id,
        nombre=nombre_obra,
        cui=cui,
        estado=estado,
        fecha_inicio=fecha_inicio,
        entidad=entidad_obra,
        score=score,
        motivos=motivos,
    )


def buscar_obra_por_certificado(
    project_name: str,
    cert_date: Optional[date] = None,
    entidad: Optional[str] = None,
    min_score: float = 15.0,
) -> Optional[WorkInfo]:
    """
    Busca una obra en InfoObras a partir del nombre del proyecto en un certificado.

    Estrategia:
    1. Extraer palabras clave del nombre del proyecto
    2. Buscar en InfoObras por nombre
    3. Rankear resultados por similitud + proximidad de fecha + entidad
    4. Si el mejor candidato supera min_score → fetch datos completos
    5. Si no → retorna None (para confirmación manual en UI)

    Args:
        project_name: nombre del proyecto según el certificado
        cert_date: fecha de emisión del certificado (para desambiguación)
        entidad: nombre de la entidad contratante (para desambiguación)
        min_score: score mínimo para aceptar un candidato (default 15.0)

    Returns:
        WorkInfo con datos completos si se encontró un match sólido, None si no.
    """
    if not project_name or len(project_name.strip()) < 10:
        logger.warning("InfoObras: nombre de proyecto muy corto para buscar: '%s'", project_name)
        return None

    # 1. Extraer variantes de búsqueda (de más específica a más genérica)
    queries = _extraer_palabras_clave(project_name)
    if not queries:
        logger.warning("InfoObras: no se extrajeron palabras clave de '%s'", project_name[:60])
        return None

    # 2. Buscar con cada query hasta encontrar resultados
    resultados: list[dict] = []
    query_usada = ""
    for q in queries:
        logger.info("InfoObras: buscando '%s' (de '%s')", q, project_name[:60])
        resultados = buscar_obras_por_nombre(q)
        if resultados:
            query_usada = q
            break
        time.sleep(1.0)  # rate limiting entre reintentos

    if not resultados:
        logger.info("InfoObras: sin resultados para '%s' (probé %d queries)", project_name[:60], len(queries))
        return None

    logger.info("InfoObras: %d resultados con query '%s'", len(resultados), query_usada)

    # 3. Rankear candidatos
    candidatos = [
        _score_candidata(obra, project_name, cert_date, entidad)
        for obra in resultados
    ]
    candidatos.sort(key=lambda c: c.score, reverse=True)

    # Log top 3
    for i, c in enumerate(candidatos[:3]):
        logger.info(
            "InfoObras: candidato %d — score=%.1f — %s [%s]",
            i + 1, c.score, c.nombre[:60], ", ".join(c.motivos),
        )

    mejor = candidatos[0]

    # 4. Verificar score mínimo
    if mejor.score < min_score:
        logger.info(
            "InfoObras: mejor candidato score=%.1f < %.1f mínimo — requiere confirmación manual",
            mejor.score, min_score,
        )
        return None

    # 5. Verificar que no haya ambigüedad (segundo candidato muy cercano)
    if len(candidatos) > 1:
        segundo = candidatos[1]
        if segundo.score > 0 and (mejor.score - segundo.score) < 5.0:
            logger.info(
                "InfoObras: ambigüedad — score1=%.1f vs score2=%.1f (diff=%.1f) — requiere confirmación",
                mejor.score, segundo.score, mejor.score - segundo.score,
            )
            # Aún así retornamos el mejor, pero se podría marcar como ambiguo
            pass

    # 6. Fetch datos completos
    logger.info(
        "InfoObras: seleccionado CUI=%s (score=%.1f) — descargando datos completos",
        mejor.cui, mejor.score,
    )

    if mejor.cui:
        return fetch_by_cui(mejor.cui)
    else:
        # Sin CUI pero con obra_id — fetch directo por obra_id
        try:
            session = _crear_session()
            time.sleep(_DELAY)
            datos = _extraer_datos_ejecucion(session, mejor.obra_id)
            supervisores = _procesar_supervisores(datos.get("lSupervisor", []))
            residentes = _procesar_residentes(datos.get("lResidente", []))
            avances = _procesar_avances(datos.get("lAvances", []))
            contratistas = _procesar_contratistas(datos.get("lContratista", []))
            modificaciones_plazo = _procesar_modificaciones_plazo(datos.get("lModificacionPlazo", []))
            entregas_terreno = _procesar_entregas_terreno(datos.get("lEntregaTerreno", []))
            adendas = _procesar_adendas(datos.get("lAdenda", []))
            transferencias = _procesar_transferencias(datos.get("lTransferenciaFinanciera", []))
            adelantos = _procesar_adelantos(datos.get("lAdelanto", []))
            cronogramas = _procesar_cronogramas(datos.get("lCronograma", []))
            adicionales_deductivos = _procesar_adicionales_deductivos(datos.get("lAdicionalDeduc", []))
            controversias = _procesar_controversias(datos.get("lControversia", []))
            suspension_periods = _extraer_periodos_suspension(avances)
            avance_pct_real, monto_ejecutado = _derivar_avance_actual(avances)

            return WorkInfo(
                cui=mejor.cui or "",
                obra_id=mejor.obra_id,
                nombre=mejor.nombre,
                estado=mejor.estado,
                entidad=mejor.entidad,
                fecha_inicio=mejor.fecha_inicio,
                porcentaje_avance_fisico=avance_pct_real,
                monto_ejecutado_acumulado=monto_ejecutado,
                supervisores=supervisores,
                residentes=residentes,
                avances=avances,
                contratistas=contratistas,
                modificaciones_plazo=modificaciones_plazo,
                entregas_terreno=entregas_terreno,
                suspension_periods=suspension_periods,
                adendas=adendas,
                transferencias=transferencias,
                adelantos=adelantos,
                cronogramas=cronogramas,
                adicionales_deductivos=adicionales_deductivos,
                controversias=controversias,
                raw_busqueda=mejor.obra_raw,
            )
        except Exception as e:
            logger.error("InfoObras: error descargando datos de ObraId %s: %s", mejor.obra_id, e)
            return None
