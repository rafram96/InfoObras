"""
Explorador completo de una obra en InfoObras.

Busca por CUI, consulta todos los endpoints que tienen datos,
y muestra toda la información formateada.

Uso:
    python explorar_obra.py 2157301
    python explorar_obra.py 2157301 --solo-busqueda
"""
import sys
import io
import re
import json
import time
import argparse
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

BASE_MAPA = "https://infobras.contraloria.gob.pe/infobrasweb"
BASE_WEB = "https://infobras.contraloria.gob.pe/InfobrasWeb"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_WEB}/Mapa/Index",
}

_JS_VAR_RE = re.compile(r"var\s+(\w+)\s*=\s*(\[.*?\])\s*;", re.DOTALL)
_DELAY = 1.5


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def crear_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f"{BASE_WEB}/", timeout=10)
    return s


def fecha_legible(ts_str):
    """Convierte /Date(1574485200000)/ a DD/MM/YYYY."""
    m = re.search(r"/Date\((\d+)\)/", ts_str or "")
    if not m:
        return ts_str or ""
    ts = int(m.group(1)) / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")


def extraer_vars_js(html):
    """Extrae todas las variables JS tipo array del HTML."""
    variables = {}
    for match in _JS_VAR_RE.finditer(html):
        nombre = match.group(1)
        try:
            variables[nombre] = json.loads(match.group(2))
        except json.JSONDecodeError:
            pass
    return variables


def get_html(session, endpoint, obra_id):
    """GET a un endpoint de InfoObras, retorna el HTML."""
    url = f"{BASE_WEB}/Mapa/{endpoint}"
    session.headers["Accept"] = "text/html,*/*"
    r = session.get(url, params={"ObraId": obra_id}, timeout=30)
    session.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    r.raise_for_status()
    return r.text


def buscar_por_cui(session, cui):
    """Busca obras por CUI. Retorna lista de dicts."""
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


# ──────────────────────────────────────────────────────────────────────
# Display
# ──────────────────────────────────────────────────────────────────────

MES_NOMBRE = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}
MES_NUM = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
    "NOVIEMBRE": 11, "DICIEMBRE": 12,
}


def mostrar_datos_obra(obra):
    """Muestra los datos de la búsqueda."""
    print(f"\n{'=' * 70}")
    nombre = obra.get("nombrObra", "(sin nombre)")
    # Cortar nombre largo en líneas
    if len(nombre) > 65:
        print(f"  {nombre[:65]}")
        print(f"  {nombre[65:]}")
    else:
        print(f"  {nombre}")
    print(f"{'=' * 70}")

    f_ini = fecha_legible(obra.get("fechaIniObra", ""))
    f_fin = fecha_legible(obra.get("fechaFinObra", ""))

    print(f"  CUI               : {obra.get('codUniqInv', '')}")
    print(f"  Código InfoObras  : {obra.get('codigoObra', '')}")
    print(f"  Estado            : {obra.get('estObra', '')}  |  Actualización: {obra.get('estActualizacion', '')}")
    print(f"  Tipo de obra      : {obra.get('nomTipoObra', '')}")
    print(f"  Modalidad         : {obra.get('nombrModalidad', '')}  |  Nivel: {obra.get('nombrNivel', '')}")
    print(f"  Entidad           : {obra.get('nombreEntidad', '')}")

    ejecutor = obra.get("nombreEjecutor", "")
    ruc_ej = obra.get("rucEjecutor", "")
    if ejecutor:
        print(f"  Ejecutor          : {ejecutor}  (RUC: {ruc_ej})")

    monto = obra.get("montoObraSoles")
    if monto:
        print(f"  Monto contrato    : S/ {monto:,.2f}")
    ejecutado = obra.get("montoEjecucion")
    if ejecutado:
        print(f"  Monto ejecutado   : S/ {ejecutado:,.2f}")

    print(f"  Plazo             : {obra.get('plazoObra', '')} días")
    print(f"  Fechas            : {f_ini} → {f_fin}")

    # Supervisor y residente actuales (del endpoint de búsqueda)
    sup = obra.get("nombresSupervisor", "")
    if sup:
        ruc_sup = obra.get("rucSupervisor", "")
        dni_sup = obra.get("dniSupervisor", "")
        print(f"  Supervisor actual : {sup}  (RUC: {ruc_sup} | DNI: {dni_sup})")
    res = obra.get("nombresResidente", "")
    if res:
        dni_res = obra.get("numdocResidente", "")
        print(f"  Residente actual  : {res}  (DNI: {dni_res})")

    print(f"  URL ficha         : {BASE_WEB}/Mapa/Obra?ObraId={obra.get('codigoObra', '')}")


def mostrar_supervisores(datos):
    """Muestra supervisores de DatosPreparacion."""
    lista = datos.get("lSupervisor", [])
    print(f"\n  ── Supervisores/Inspectores ({len(lista)}) ──")
    if not lista:
        print(f"     (sin registro)")
        return
    for i, s in enumerate(lista, 1):
        nombre = f"{s.get('NombreRep', '')} {s.get('ApellidoPaterno', '')} {s.get('ApellidoMaterno', '')}".strip()
        tipo = s.get("TipoSupervisor", "")
        persona = s.get("TipoPersona", "")
        f_ini = s.get("FechaInicio", "")
        f_fin = s.get("FechaFin", "") or "(vigente)"
        dni = s.get("NumeroDocRep", "")
        empresa = s.get("NombreEmpresa", "")
        ruc = s.get("Ruc", "")

        print(f"  [{i}] {nombre}")
        print(f"      {tipo} | {persona} | DNI: {dni}")
        print(f"      Periodo: {f_ini} → {f_fin}")
        if empresa:
            print(f"      Empresa: {empresa} (RUC: {ruc})")


def mostrar_residentes(datos):
    """Muestra residentes de DatosPreparacion."""
    lista = datos.get("lResidente", [])
    print(f"\n  ── Residentes ({len(lista)}) ──")
    if not lista:
        print(f"     (sin registro)")
        return
    for i, r in enumerate(lista, 1):
        nombre = f"{r.get('NombreRep', '')} {r.get('ApellidoPaterno', '')} {r.get('ApellidoMaterno', '')}".strip()
        f_ini = r.get("FechaInicio", "")
        f_fin = r.get("FechaFin", "") or "(vigente)"
        cuaderno = r.get("AperturaCuadernoObra", "")
        print(f"  [{i}] {nombre}")
        print(f"      Periodo: {f_ini} → {f_fin}  |  Cuaderno obra: {cuaderno}")


def mostrar_avances(datos):
    """Muestra avances de DatosEjecucion."""
    lista = datos.get("lAvances", [])
    print(f"\n  ── Avances mensuales ({len(lista)}) ──")
    if not lista:
        print(f"     (sin registro)")
        return

    # Tabla compacta
    print(f"  {'Periodo':<16} {'Estado':<16} {'Tipo':<8} {'Días':<6} {'%Fis':<7} {'%Fin':<7} {'Docs':<5} {'Comentario'}")
    print(f"  {'─' * 16} {'─' * 16} {'─' * 8} {'─' * 6} {'─' * 7} {'─' * 7} {'─' * 5} {'─' * 30}")

    for a in lista:
        mes_str = a.get("Mes", "").upper().strip()
        mes_num = MES_NUM.get(mes_str, 0)
        mes_corto = MES_NOMBRE.get(mes_num, mes_str[:3])
        anio = a.get("Anio", "")
        estado = a.get("Estado", "")
        tipo = a.get("TipoParalizacion", "") or ""
        dias = a.get("DiasParalizado", 0)
        porc_fis = a.get("PorcRealFisico", 0)
        porc_fin = a.get("PorcEjecFinanc", 0)
        n_docs = len(a.get("lImgValorizacion", [])) + len(a.get("lImgFisico", []))
        comentario = (a.get("ComentarioFisico") or "")[:40]
        if comentario == "No se reportaron comentarios":
            comentario = ""

        # Resaltar paralizaciones
        marcador = ">>>" if "paraliz" in estado.lower() else "   "

        print(f"{marcador}{mes_corto} {anio:<12} {estado:<16} {tipo:<8} {dias:<6} {porc_fis:<7.1f} {porc_fin:<7.1f} {n_docs:<5} {comentario}")


def mostrar_paralizaciones(datos):
    """Resumen de paralizaciones."""
    avances = datos.get("lAvances", [])
    paralizados = [a for a in avances if "paraliz" in a.get("Estado", "").lower()]
    if not paralizados:
        print(f"\n  ── Sin paralizaciones registradas ──")
        return

    total_dias = sum(a.get("DiasParalizado", 0) for a in paralizados)
    print(f"\n  ── Paralizaciones: {len(paralizados)} meses, {total_dias} días totales ──")
    for a in paralizados:
        mes = a.get("Mes", "")
        anio = a.get("Anio", "")
        dias = a.get("DiasParalizado", 0)
        tipo = a.get("TipoParalizacion", "")
        fecha = a.get("FechaParalizacion", "")
        causal = (a.get("Causal") or "")[:50]
        print(f"    {mes:<12} {anio} | {tipo:<8} | {dias:>3}d | desde {fecha:<12} | {causal}")


def mostrar_contratista(datos):
    """Muestra contratista de ProcesoSeleccion."""
    lista = datos.get("lProcesoSeleccion", [])
    print(f"\n  ── Proceso de selección / Contratista ({len(lista)}) ──")
    if not lista:
        print(f"     (sin registro)")
        return
    for i, p in enumerate(lista, 1):
        contratista = p.get("Contratista", "")
        nro = p.get("NroContrato", "")
        fecha = p.get("FechaSuscripcion", "")
        monto = p.get("MontoContratado", 0)
        estado = p.get("EstadoProceso", "")
        objeto = (p.get("Objeto") or "")[:70]

        print(f"  [{i}] {contratista}")
        print(f"      Contrato: {nro}  |  Estado: {estado}")
        if fecha:
            print(f"      Fecha suscripción: {fecha}")
        if monto:
            print(f"      Monto contratado: S/ {monto:,.2f}")
        if objeto:
            print(f"      Objeto: {objeto}...")


def mostrar_informes_control(datos):
    """Muestra informes de control de la CGR."""
    lista = datos.get("lInformeControl", [])
    print(f"\n  ── Informes de Control CGR ({len(lista)}) ──")
    if not lista:
        print(f"     (sin informes)")
        return
    for i, inf in enumerate(lista, 1):
        nro = inf.get("NroInforme", "")
        titulo = (inf.get("TituloInforme") or "")[:70]
        tipo = inf.get("TipoServicio", "")
        fecha = inf.get("FechaEmision", "")
        url_informe = inf.get("RutaInforme", "")

        print(f"  [{i}] {nro}")
        print(f"      {titulo}...")
        print(f"      Tipo: {tipo}  |  Emisión: {fecha}")
        if url_informe:
            print(f"      Descargar: {url_informe}")


def mostrar_documentos_avance(datos):
    """Muestra resumen de documentos descargables por mes."""
    avances = datos.get("lAvances", [])
    total_val = 0
    total_img = 0
    for a in avances:
        total_val += len(a.get("lImgValorizacion", []))
        total_img += len(a.get("lImgFisico", []))

    print(f"\n  ── Documentos adjuntos: {total_val} valorizaciones + {total_img} fotos ──")
    print(f"  Patrón de descarga: {BASE_WEB}/Mapa/DownloadFile?filename={{UrlImg}}")

    # Mostrar solo meses que tienen valorizaciones
    meses_con_docs = [a for a in avances if a.get("lImgValorizacion")]
    if meses_con_docs:
        print(f"\n  Meses con valorizaciones:")
        for a in meses_con_docs[:10]:
            mes = a.get("Mes", "")
            anio = a.get("Anio", "")
            docs = a.get("lImgValorizacion", [])
            nombres = [d.get("nombreArchivo", "?") for d in docs[:2]]
            print(f"    {mes:<12} {anio} — {len(docs)} doc(s): {', '.join(nombres)}")
        if len(meses_con_docs) > 10:
            print(f"    ... y {len(meses_con_docs) - 10} meses más")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Explorar obra completa en InfoObras por CUI")
    parser.add_argument("cui", help="Código Único de Inversión (CUI)")
    parser.add_argument("--solo-busqueda", action="store_true",
                        help="Solo mostrar resultados de búsqueda, sin consultar endpoints adicionales")
    parser.add_argument("--obra", type=int, default=0,
                        help="Índice de la obra a explorar si hay múltiples (default: 0 = primera)")
    args = parser.parse_args()

    session = crear_session()

    # 1. Búsqueda por CUI
    print(f"Buscando CUI: {args.cui} ...")
    obras = buscar_por_cui(session, args.cui)

    if not obras:
        print("Sin resultados.")
        return

    print(f"Encontradas: {len(obras)} obra(s)")

    # Mostrar todas las obras encontradas
    for i, obra in enumerate(obras):
        if len(obras) > 1:
            marca = " ◄" if i == args.obra else ""
            print(f"\n  --- Resultado {i+1}/{len(obras)}{marca} ---")
        mostrar_datos_obra(obra)

    if args.solo_busqueda:
        return

    # Seleccionar obra
    obra = obras[args.obra]
    obra_id = obra.get("codigoObra")
    if not obra_id:
        print("\nObra sin codigoObra.")
        return

    if len(obras) > 1:
        print(f"\n{'─' * 70}")
        print(f"  Explorando obra {args.obra + 1}: ObraId={obra_id}")
        print(f"  (Usar --obra N para elegir otra)")
        print(f"{'─' * 70}")

    # 2. DatosPreparacion → supervisores + residentes
    print(f"\nConsultando DatosPreparacion...")
    time.sleep(_DELAY)
    html_prep = get_html(session, "DatosPreparacion", obra_id)
    datos_prep = extraer_vars_js(html_prep)
    mostrar_supervisores(datos_prep)
    mostrar_residentes(datos_prep)

    # 3. DatosEjecucion → avances + paralizaciones
    print(f"\nConsultando DatosEjecucion...")
    time.sleep(_DELAY)
    html_ejec = get_html(session, "DatosEjecucion", obra_id)
    datos_ejec = extraer_vars_js(html_ejec)
    mostrar_avances(datos_ejec)
    mostrar_paralizaciones(datos_ejec)
    mostrar_documentos_avance(datos_ejec)

    # 4. ProcesoSeleccion → contratista
    print(f"\nConsultando ProcesoSeleccion...")
    time.sleep(_DELAY)
    html_proc = get_html(session, "ProcesoSeleccion", obra_id)
    datos_proc = extraer_vars_js(html_proc)
    mostrar_contratista(datos_proc)

    # 5. InformeControl → informes CGR
    print(f"\nConsultando InformeControl...")
    time.sleep(_DELAY)
    html_inf = get_html(session, "InformeControl", obra_id)
    datos_inf = extraer_vars_js(html_inf)
    mostrar_informes_control(datos_inf)

    # Resumen final
    n_avances = len(datos_ejec.get("lAvances", []))
    n_paral = sum(1 for a in datos_ejec.get("lAvances", []) if "paraliz" in a.get("Estado", "").lower())
    n_sup = len(datos_prep.get("lSupervisor", []))
    n_res = len(datos_prep.get("lResidente", []))
    n_inf = len(datos_inf.get("lInformeControl", []))
    n_proc = len(datos_proc.get("lProcesoSeleccion", []))

    print(f"\n{'=' * 70}")
    print(f"  RESUMEN — CUI {args.cui} — ObraId {obra_id}")
    print(f"{'=' * 70}")
    print(f"  Avances: {n_avances} meses ({n_paral} paralizados)")
    print(f"  Supervisores: {n_sup}  |  Residentes: {n_res}")
    print(f"  Procesos/Contratista: {n_proc}")
    print(f"  Informes CGR: {n_inf}")
    print(f"  Endpoints consultados: búsqueda + DatosPreparacion + DatosEjecucion + ProcesoSeleccion + InformeControl")


if __name__ == "__main__":
    main()
