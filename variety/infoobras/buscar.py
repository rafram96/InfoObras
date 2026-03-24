"""
InfoObras Scraper — PoC
Busca una obra por CUI y extrae su ficha publica.

Uso:
    python buscar.py 2157301
"""
import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from datetime import datetime, timezone
import requests

BASE_MAPA = "https://infobras.contraloria.gob.pe/infobrasweb"
BASE_WEB  = "https://infobras.contraloria.gob.pe/InfobrasWeb"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_WEB}/Mapa/Index",
}


def crear_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f"{BASE_WEB}/", timeout=10)
    return s


def buscar_por_cui(session, cui: str) -> list[dict]:
    """Busca obras por CUI. Devuelve lista de dicts raw de la API."""
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
    # Estructura: {Parameters, Code, Description, ErrorDescription, Result}
    result = data.get("Result", data)
    # Result puede ser una lista directa o un dict con .data
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("data", result.get("obras", [result]))
    return []


def parsear_timestamp(ts_str: str) -> str:
    """Convierte /Date(1574485200000)/ a fecha legible."""
    m = re.search(r'/Date\((\d+)\)/', ts_str or "")
    if not m:
        return ts_str or ""
    ts = int(m.group(1)) / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")


def get_ficha_html(session, obra_id: int) -> str:
    """Descarga el HTML de la ficha publica de una obra."""
    session.headers["Accept"] = "text/html,*/*"
    r = session.get(f"{BASE_WEB}/Mapa/Obra", params={"ObraId": obra_id}, timeout=15)
    session.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    r.raise_for_status()
    return r.text


def parsear_ficha(html: str) -> dict:
    """Extrae datos clave del HTML de la ficha publica."""

    def txt(pattern):
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if not m:
            return ""
        raw = re.sub(r'<[^>]+>', ' ', m.group(1))
        return re.sub(r'\s+', ' ', raw).strip()

    # Quitar scripts/styles para limpiar
    clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)

    # Estado (viene en un badge o span especifico)
    estado = txt(r'Estado de ejecuci[oó]n.*?<[^>]+class=["\'][^"\']*badge[^"\']*["\'][^>]*>(.*?)</[^>]+>')
    if not estado:
        # Fallback: siguiente texto despues del label
        estado = txt(r'Estado de ejecuci[oó]n\s*</[^>]+>\s*(?:<[^>]+>\s*)*([\w\s]+?)\s*(?:</|\n)')

    # Monto
    monto = txt(r'Monto de inversi[oó]n.*?>(S/\s*[\d,\.]+)')

    # Avance
    avance = txt(r'%\s*Avance f[ií]sico.*?>([\d\.]+\s*%[^<]{0,30})')

    # Expediente tecnico
    resol = txt(r'Documento de aprobaci[oó]n.*?<td[^>]*>(.*?)</td>')
    monto_exp = txt(r'Monto aprobado.*?>(S/[\d,\.]+)')

    return {
        "estado":            estado,
        "monto_inversion":   monto,
        "avance_fisico":     avance,
        "resolucion_aprobacion": resol,
        "monto_expediente":  monto_exp,
    }


def mostrar_obra(raw: dict, ficha: dict):
    """Imprime los datos de una obra de forma legible."""
    print("\n" + "=" * 60)
    print(f"  {raw.get('nombrObra', '(sin nombre)')}")
    print("=" * 60)
    print(f"  CUI             : {raw.get('codUniqInv', '')}")
    print(f"  Cod. INFOBRAS   : {raw.get('codigoObra', '')}")
    print(f"  Estado          : {raw.get('estObra', '')} | Actualizacion: {raw.get('estActualizacion', '')}")
    print(f"  Tipo de obra    : {raw.get('nomTipoObra', '')}")
    print(f"  Entidad         : {raw.get('nombreEntidad', '')}")
    print(f"  Ejecutor        : {raw.get('nombreEjecutor', '')}")
    ruc_ej = raw.get('rucEjecutor', '')
    if ruc_ej:
        print(f"  RUC ejecutor    : {ruc_ej}")
    sup = raw.get('nombresSupervisor', '')
    ruc_sup = raw.get('rucSupervisor', '')
    dni_sup = raw.get('dniSupervisor', '')
    if sup:
        print(f"  Supervisor      : {sup} (RUC: {ruc_sup} | DNI: {dni_sup})")
    res = raw.get('nombresResidente', '')
    dni_res = raw.get('numdocResidente', '')
    if res:
        print(f"  Residente       : {res} (DNI: {dni_res})")
    monto = raw.get('montoObraSoles')
    if monto:
        print(f"  Monto contrato  : S/ {monto:,.2f}")
    ejecutado = raw.get('montoEjecucion')
    if ejecutado:
        print(f"  Monto ejecutado : S/ {ejecutado:,.2f}")
    f_ini = parsear_timestamp(raw.get('fechaIniObra', ''))
    f_fin = parsear_timestamp(raw.get('fechaFinObra', ''))
    plazo = raw.get('plazoObra', '')
    print(f"  Fechas          : {f_ini} → {f_fin} ({plazo} dias)")
    print(f"  --- Ficha publica ---")
    for k, v in ficha.items():
        if v:
            print(f"  {k:<22}: {v}")
    url = f"{BASE_WEB}/Mapa/Obra?ObraId={raw.get('codigoObra', '')}"
    print(f"\n  URL ficha       : {url}")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cui = sys.argv[1] if len(sys.argv) > 1 else "2157301"
    print(f"Buscando CUI: {cui} ...")

    session = crear_session()
    obras = buscar_por_cui(session, cui)

    if not obras:
        print("Sin resultados.")
        sys.exit(0)

    print(f"Encontradas: {len(obras)} obra(s)")

    for obra_raw in obras:
        obra_id = obra_raw.get("codigoObra")
        if not obra_id:
            continue
        print(f"\nDescargando ficha ObraId={obra_id}...")
        html = get_ficha_html(session, obra_id)
        ficha = parsear_ficha(html)
        mostrar_obra(obra_raw, ficha)
