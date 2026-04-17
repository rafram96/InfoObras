"""
Explorador de datos InfoObras — ver TODO lo que hay.

Descarga los datos crudos de una obra y muestra absolutamente todo:
variables JS, campos, documentos descargables, URLs, etc.
Para después decidir qué se necesita y qué procesos ejecutar.

Uso:
    python probe_datos.py                          # CUI default: 2157301
    python probe_datos.py 2186942                  # otro CUI
    python probe_datos.py --nombre "HOSPITAL POMABAMBA"
    python probe_datos.py --obra-id 66057          # directo por ObraId
"""
import sys
import io
import os
import re
import json
import time
import logging
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Importar lógica real del src/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.scraping.infoobras import (
    _crear_session,
    _buscar_por_cui,
    _extraer_datos_ejecucion,
    _parse_timestamp_json,
    buscar_obras_por_nombre,
    BASE_WEB,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

# Delay entre requests
_DELAY = 2.0


# ──────────────────────────────────────────────────────────────────────
# Explorar endpoint de búsqueda [1]
# ──────────────────────────────────────────────────────────────────────

def explorar_busqueda(obras: list[dict]):
    """Muestra TODO lo que devuelve el endpoint de búsqueda."""
    print(f"\n{'=' * 70}")
    print(f"  ENDPOINT [1] BÚSQUEDA — {len(obras)} resultado(s)")
    print(f"{'=' * 70}")

    for i, obra in enumerate(obras[:5]):
        print(f"\n  ── Resultado {i+1} ──")
        for key in sorted(obra.keys()):
            val = obra[key]
            if val is None or val == "" or val == " ":
                continue
            # Timestamps /Date(...)/ → mostrar legible al lado
            if isinstance(val, str) and "/Date(" in val:
                fecha = _parse_timestamp_json(val)
                print(f"    {key:<28}: {val}  →  {fecha}")
            elif isinstance(val, float):
                print(f"    {key:<28}: {val:,.2f}")
            else:
                print(f"    {key:<28}: {val}")

        # URL de ficha pública
        oid = obra.get("codigoObra")
        if oid:
            print(f"    {'--- URL ficha':<28}: {BASE_WEB}/Mapa/Obra?ObraId={oid}")

    if len(obras) > 5:
        print(f"\n  ... {len(obras) - 5} resultados más no mostrados")


# ──────────────────────────────────────────────────────────────────────
# Explorar DatosEjecucion [5] — TODO lo crudo
# ──────────────────────────────────────────────────────────────────────

def explorar_datos_ejecucion(datos: dict[str, list], obra_id: int):
    """Muestra TODAS las variables JS con TODOS sus campos y documentos."""
    print(f"\n{'=' * 70}")
    print(f"  ENDPOINT [5] DATOS EJECUCIÓN — ObraId={obra_id}")
    print(f"  Variables encontradas: {len(datos)}")
    print(f"  URL: {BASE_WEB}/Mapa/DatosEjecucion?ObraId={obra_id}")
    print(f"{'=' * 70}")

    # Resumen rápido primero
    print(f"\n  ── Inventario ──")
    for var_name in sorted(datos.keys()):
        n = len(datos[var_name])
        print(f"    {var_name:<32}: {n:>3} registros")

    # Ahora cada variable en detalle
    for var_name in sorted(datos.keys()):
        registros = datos[var_name]
        print(f"\n{'─' * 70}")
        print(f"  {var_name} — {len(registros)} registros")
        print(f"{'─' * 70}")

        if not registros:
            print("    (vacío)")
            continue

        # Mostrar todos los campos del primer registro para saber la estructura
        print(f"\n  CAMPOS DISPONIBLES (del registro 1):")
        primer = registros[0]
        for key in primer.keys():
            val = primer[key]
            tipo = type(val).__name__
            if isinstance(val, list):
                print(f"    {key:<28}: list[{len(val)} items]")
            elif isinstance(val, str) and len(val) > 60:
                print(f"    {key:<28}: ({tipo}) {val[:60]}...")
            else:
                print(f"    {key:<28}: ({tipo}) {val}")

        # Mostrar todos los registros
        print(f"\n  REGISTROS:")
        for i, item in enumerate(registros):
            print(f"\n  [{i+1}]")

            for key, val in item.items():
                if isinstance(val, list):
                    # Sublistas = documentos/imágenes → mostrar en detalle
                    if val:
                        print(f"      {key} ({len(val)} docs):")
                        for j, doc in enumerate(val):
                            _mostrar_documento(doc, indent=8)
                else:
                    if val is not None and val != "" and val != " ":
                        if isinstance(val, float):
                            print(f"      {key:<28}: {val:,.2f}")
                        else:
                            print(f"      {key:<28}: {val}")


def _mostrar_documento(doc: dict, indent: int = 8):
    """Muestra un documento/imagen adjunto con toda su info."""
    espacios = " " * indent
    codigo = doc.get("Codigo", "?")
    url_img = doc.get("UrlImg", "")
    nombre = doc.get("nombreArchivo", "?")
    ext = doc.get("Extension", "?")
    es_fisico = doc.get("EsFisico", "?")

    print(f"{espacios}Codigo={codigo} | EsFisico={es_fisico} | {nombre} (.{ext})")
    print(f"{espacios}  UrlImg (UUID): {url_img}")

    # Mostrar cualquier otro campo del doc que no hayamos mostrado
    campos_conocidos = {"Codigo", "UrlImg", "nombreArchivo", "Extension", "EsFisico"}
    extras = {k: v for k, v in doc.items() if k not in campos_conocidos and v is not None}
    if extras:
        for k, v in extras.items():
            print(f"{espacios}  {k}: {v}")


# ──────────────────────────────────────────────────────────────────────
# Explorar otros endpoints (tabs) que no usamos aún
# ──────────────────────────────────────────────────────────────────────

def explorar_endpoint_extra(session, obra_id: int, tab_name: str, endpoint: str):
    """Intenta descargar un endpoint adicional y muestra qué variables JS tiene."""
    url = f"{BASE_WEB}/Mapa/{endpoint}"
    print(f"\n{'─' * 70}")
    print(f"  PROBANDO: {tab_name}")
    print(f"  GET {url}?ObraId={obra_id}")

    try:
        session.headers["Accept"] = "text/html,*/*"
        r = session.get(url, params={"ObraId": obra_id}, timeout=30)
        session.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"

        print(f"  Status: {r.status_code} | Size: {len(r.text):,} bytes")

        if r.status_code != 200:
            print(f"  Error: {r.status_code}")
            return

        # Buscar variables JS
        js_var_re = re.compile(r"var\s+(\w+)\s*=\s*(\[.*?\])\s*;", re.DOTALL)
        variables_encontradas = {}
        for match in js_var_re.finditer(r.text):
            nombre = match.group(1)
            try:
                datos = json.loads(match.group(2))
                variables_encontradas[nombre] = datos
            except json.JSONDecodeError:
                variables_encontradas[nombre] = f"[JSON inválido: {match.group(2)[:100]}...]"

        if variables_encontradas:
            print(f"  Variables JS encontradas: {len(variables_encontradas)}")
            for vn, vd in variables_encontradas.items():
                if isinstance(vd, list):
                    print(f"    {vn:<30}: {len(vd)} registros")
                    if vd:
                        print(f"      Campos: {', '.join(vd[0].keys())}")
                        # Primer registro completo
                        print(f"      [1] {json.dumps(vd[0], ensure_ascii=False)[:300]}")
                else:
                    print(f"    {vn:<30}: {vd}")
        else:
            # Sin variables JS — buscar tablas u otros datos
            tablas = re.findall(r'<table[^>]*id="([^"]*)"', r.text)
            if tablas:
                print(f"  Sin variables JS. Tablas HTML encontradas: {tablas}")
            else:
                print(f"  Sin variables JS ni tablas.")

    except Exception as e:
        print(f"  Error: {e}")


# ──────────────────────────────────────────────────────────────────────
# Probar descarga de un documento
# ──────────────────────────────────────────────────────────────────────

def probar_descarga_documento(session, datos: dict[str, list]):
    """Intenta encontrar y descargar un documento para descubrir el patrón de URL."""
    print(f"\n{'=' * 70}")
    print(f"  DOCUMENTOS DESCARGABLES — búsqueda de patrón de URL")
    print(f"{'=' * 70}")

    # Recoger todos los documentos de todas las variables
    documentos = []
    for var_name, registros in datos.items():
        for reg in registros:
            for key, val in reg.items():
                if isinstance(val, list):
                    for doc in val:
                        if isinstance(doc, dict) and ("UrlImg" in doc or "UrlRegistro" in doc):
                            documentos.append({
                                "variable": var_name,
                                "campo": key,
                                **doc,
                            })
            # También campos UrlRegistro directos (no sublista)
            url_reg = reg.get("UrlRegistro")
            if url_reg and isinstance(url_reg, str) and url_reg.strip():
                documentos.append({
                    "variable": var_name,
                    "campo": "UrlRegistro",
                    "UrlRegistro": url_reg,
                    "nombreArchivo": reg.get("nombreArchivo", url_reg),
                    "Extension": reg.get("Extension", "?"),
                    "Codigo": reg.get("Codigo", "?"),
                })

    print(f"\n  Total documentos/archivos encontrados: {len(documentos)}")

    if not documentos:
        print("  Ningún documento descargable en esta obra.")
        return

    # Agrupar por variable
    por_variable = {}
    for d in documentos:
        vn = d["variable"]
        por_variable.setdefault(vn, []).append(d)

    for vn, docs in por_variable.items():
        print(f"\n  {vn} — {len(docs)} documento(s):")
        for d in docs[:5]:
            nombre = d.get("nombreArchivo", "?")
            codigo = d.get("Codigo", "?")
            uuid = d.get("UrlImg", "")
            url_reg = d.get("UrlRegistro", "")
            ext = d.get("Extension", "?")
            campo = d.get("campo", "?")
            print(f"    [{campo}] {nombre} (.{ext})")
            if uuid:
                print(f"      UUID (UrlImg): {uuid}")
            if url_reg and url_reg != nombre:
                print(f"      UrlRegistro: {url_reg}")
            print(f"      Codigo: {codigo}")
        if len(docs) > 5:
            print(f"    ... y {len(docs) - 5} más")

    # Intentar descargar uno de cada tipo para descubrir el patrón
    # Hay 2 formatos de UrlImg:
    #   - Path: "Doc/documento20221226121445.pdf" (obra 64149)
    #   - UUID: "a137035b4d5f495caf449c47bfe9791e" (obra 66057, registro paralizado)

    # Separar docs por formato
    docs_path = [d for d in documentos if "/" in d.get("UrlImg", "")][:1]
    docs_uuid = [d for d in documentos if "/" not in d.get("UrlImg", "") and d.get("UrlImg")][:1]
    docs_a_probar = docs_path + docs_uuid

    for doc in docs_a_probar:
        url_img = doc.get("UrlImg", "")
        codigo = doc.get("Codigo", "?")
        nombre_arch = doc.get("nombreArchivo", "?")
        es_path = "/" in url_img

        print(f"\n  ── Probando: {nombre_arch} ──")
        print(f"    UrlImg: {url_img} ({'path' if es_path else 'UUID'})")
        print(f"    Codigo: {codigo}")

        # Patrones según el tipo
        patrones = []

        # DownloadFile?filename= (encontrado en el HTML como link AJAX)
        if es_path:
            patrones.append(
                (f"{BASE_WEB}/Mapa/DownloadFile?filename={url_img}",
                 "DownloadFile?filename=path")
            )
            patrones.append(
                (f"https://infobras.contraloria.gob.pe/InfObrasPublic/{url_img}",
                 "InfObrasPublic/path")
            )
            patrones.append(
                (f"https://infobras.contraloria.gob.pe/infobras/{url_img}",
                 "infobras/path")
            )
        else:
            patrones.append(
                (f"{BASE_WEB}/Mapa/DownloadFile?filename={url_img}",
                 "DownloadFile?filename=UUID")
            )
            patrones.append(
                (f"https://infobras.contraloria.gob.pe/InfObrasPublic/Archivos/{url_img}",
                 "InfObrasPublic/Archivos/UUID")
            )

        # Patrones comunes a ambos
        patrones.append(
            (f"{BASE_WEB}/Mapa/DescargarArchivo?codigo={codigo}",
             f"DescargarArchivo?codigo=Codigo")
        )
        patrones.append(
            (f"{BASE_WEB}/Mapa/DescargarArchivo?id={url_img}",
             f"DescargarArchivo?id=UrlImg")
        )

        for url_test, desc in patrones:
            try:
                print(f"\n    [{desc}]")
                print(f"      URL: {url_test}")
                r = session.get(url_test, timeout=15, allow_redirects=True)
                ct = r.headers.get("Content-Type", "?")
                cd = r.headers.get("Content-Disposition", "")
                size = len(r.content)
                print(f"      Status: {r.status_code} | Content-Type: {ct} | Size: {size:,} bytes")
                if cd:
                    print(f"      Content-Disposition: {cd}")
                if r.history:
                    print(f"      Redirects: {' → '.join(h.headers.get('Location', '?') for h in r.history)}")

                # Analizar respuesta
                if r.status_code == 200 and size > 500:
                    header = r.content[:20]
                    if header.startswith(b"%PDF"):
                        print(f"      ✓ PDF REAL — {size:,} bytes")
                    elif header[:2] == b"PK":
                        print(f"      ✓ ZIP/DOCX — {size:,} bytes")
                    elif header[:4] == b"\xff\xd8\xff\xe0" or header[:4] == b"\xff\xd8\xff\xe1":
                        print(f"      ✓ JPEG — {size:,} bytes")
                    elif header[:8] == b"\x89PNG\r\n\x1a\n":
                        print(f"      ✓ PNG — {size:,} bytes")
                    elif b"html" in header.lower() or b"<!" in header:
                        print(f"      ✗ HTML (página de error o redirect)")
                    else:
                        print(f"      ? Bytes: {header}")
                elif r.status_code == 404:
                    print(f"      ✗ 404 Not Found")
                elif r.status_code == 302:
                    print(f"      → Redirect: {r.headers.get('Location', '?')}")
            except Exception as e:
                print(f"      Error: {e}")
            time.sleep(1)


# ──────────────────────────────────────────────────────────────────────
# Diagnóstico: por qué faltan variables JS
# ──────────────────────────────────────────────────────────────────────

def diagnosticar_html(session, obra_id: int):
    """Descarga HTML crudo de DatosEjecucion y busca TODAS las declaraciones var."""
    url = f"{BASE_WEB}/Mapa/DatosEjecucion"
    print(f"\n{'=' * 70}")
    print(f"  DIAGNÓSTICO HTML — ObraId={obra_id}")
    print(f"  GET {url}?ObraId={obra_id}")
    print(f"{'=' * 70}")

    session.headers["Accept"] = "text/html,*/*"
    r = session.get(url, params={"ObraId": obra_id}, timeout=30)
    session.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    html = r.text

    print(f"\n  Status: {r.status_code} | Size: {len(html):,} bytes")

    # 1. Buscar TODAS las declaraciones "var X = "
    print(f"\n  ── Todas las declaraciones 'var' encontradas ──")
    var_decl_re = re.compile(r"var\s+(\w+)\s*=\s*")
    todas = var_decl_re.findall(html)
    for vn in todas:
        print(f"    var {vn}")

    # 2. Buscar específicamente las variables que esperamos
    esperadas = [
        "lAvances", "lSupervisor", "lResidente", "lContratista",
        "lModificacionPlazo", "lAdicionalDeduc", "lEntregaTerreno",
        "lAdelanto", "lCronograma", "lTransferenciaFinanciera",
        "lControversia", "lAdenda", "lInformeControl",
    ]
    print(f"\n  ── Variables esperadas — qué valor tienen ──")
    for vn in esperadas:
        # Buscar: var lNombre = VALOR;
        m = re.search(rf"var\s+{re.escape(vn)}\s*=\s*(.*?)\s*;", html, re.DOTALL)
        if not m:
            print(f"    {vn:<30}: NO ENCONTRADA en el HTML")
            continue
        raw = m.group(1).strip()
        if raw == "null":
            print(f"    {vn:<30}: null")
        elif raw.startswith("["):
            # Intentar parsear para ver cuántos registros
            try:
                data = json.loads(raw)
                print(f"    {vn:<30}: [{len(data)} registros]")
            except json.JSONDecodeError:
                print(f"    {vn:<30}: [JSON inválido] — primeros 100 chars: {raw[:100]}")
        else:
            print(f"    {vn:<30}: {raw[:100]}")

    # 3. El regex de producción vs lo que hay
    print(f"\n  ── Test del regex de producción ──")
    print(f"    Regex: r\"var\\s+(\\w+)\\s*=\\s*(\\[.*?\\])\\s*;\"  (re.DOTALL)")
    from src.scraping.infoobras import _JS_VAR_RE
    matches = list(_JS_VAR_RE.finditer(html))
    print(f"    Matches encontrados: {len(matches)}")
    for m in matches:
        print(f"      var {m.group(1)} = [{len(m.group(2))} chars]")

    # 4. Buscar pistas de AJAX/fetch/API en el HTML
    print(f"\n  ── URLs de AJAX/API encontradas en el HTML ──")
    ajax_patterns = [
        (r'(?:fetch|axios\.get|\.ajax|\.get|\.post)\s*\(\s*["\']([^"\']+)["\']', "JS fetch/ajax"),
        (r'url\s*:\s*["\']([^"\']*(?:Supervisor|Residente|Contratista|Plazo|Terreno|Adelanto|Cronograma)[^"\']*)["\']', "URL con keyword"),
        (r'(?:href|action|src)\s*=\s*["\']([^"\']*(?:Ejecucion|Preparacion|Supervisor|Residente)[^"\']*)["\']', "href/action"),
        (r'/(?:api|Api|API)/[^"\'<>\s]+', "API path"),
        (r'/Mapa/\w+(?:\?\w+=)', "Mapa endpoint con param"),
    ]
    encontradas = set()
    for pattern, desc in ajax_patterns:
        for m in re.finditer(pattern, html):
            url_found = m.group(0) if m.lastindex is None else m.group(1)
            if url_found not in encontradas:
                encontradas.add(url_found)
                print(f"    [{desc}] {url_found}")
    if not encontradas:
        print(f"    (ninguna encontrada)")

    # 5. Probar TODOS los endpoints /Mapa/* que puedan tener las variables faltantes
    print(f"\n  ── Probing endpoints adicionales para variables faltantes ──")
    endpoints_a_probar = [
        "Sumario",
        "DatosPreparacion",
        "DatosGenerales",
        "Obra",
        "ProcesoSeleccion",
        "LineaTiempo",
        "ControlSocial",
        "InformeControl",
        "CuadernoObraDigital",
        "EjecucionFinanciera",
        "DatosCierre",
    ]
    for ep in endpoints_a_probar:
        ep_url = f"{BASE_WEB}/Mapa/{ep}"
        try:
            time.sleep(1)
            session.headers["Accept"] = "text/html,*/*"
            r2 = session.get(ep_url, params={"ObraId": obra_id}, timeout=20)
            session.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"

            # Buscar variables que nos interesan
            vars_encontradas = {}
            for vn in esperadas:
                m2 = re.search(rf"var\s+{re.escape(vn)}\s*=\s*(.*?)\s*;", r2.text, re.DOTALL)
                if m2:
                    raw2 = m2.group(1).strip()
                    if raw2 == "null":
                        vars_encontradas[vn] = "null"
                    elif raw2.startswith("["):
                        try:
                            data2 = json.loads(raw2)
                            vars_encontradas[vn] = f"[{len(data2)} registros]"
                        except json.JSONDecodeError:
                            vars_encontradas[vn] = f"[JSON inválido]"
                    else:
                        vars_encontradas[vn] = raw2[:60]

            # También buscar TODAS las "var l" (variables de datos)
            all_l_vars = {}
            for m_all in re.finditer(r"var\s+(l\w+)\s*=\s*([\[\{].*?[\]\}])\s*;", r2.text, re.DOTALL):
                vn_all = m_all.group(1)
                try:
                    data_all = json.loads(m_all.group(2))
                    all_l_vars[vn_all] = data_all
                except json.JSONDecodeError:
                    pass

            if vars_encontradas or all_l_vars:
                print(f"\n    {ep} ({len(r2.text):,} bytes) — TIENE DATOS:")
                for vn, val in vars_encontradas.items():
                    print(f"      {vn:<30}: {val}")

                # Mostrar primer registro completo de cada variable con datos
                all_to_show = all_l_vars if all_l_vars else {}
                for vn_show, data_show in all_to_show.items():
                    if isinstance(data_show, list) and data_show:
                        print(f"\n      {vn_show} — primer registro completo:")
                        for k, v in data_show[0].items():
                            if isinstance(v, list):
                                print(f"        {k:<28}: [{len(v)} items]")
                            elif v is not None and v != "" and v != " ":
                                print(f"        {k:<28}: {v}")

                # Guardar este HTML también
                dump2 = os.path.join(os.path.dirname(__file__), f"dump_{ep.lower()}_{obra_id}.html")
                with open(dump2, "w", encoding="utf-8") as f2:
                    f2.write(r2.text)
                print(f"\n      → HTML guardado en: dump_{ep.lower()}_{obra_id}.html")
            else:
                # También buscar cualquier "var l" que no sea tooltip/trivial
                other_vars = re.findall(r"var\s+(l\w+)\s*=", r2.text)
                if other_vars:
                    print(f"    {ep} ({len(r2.text):,} bytes) — sin vars esperadas, pero tiene: {', '.join(other_vars)}")
                else:
                    print(f"    {ep} ({len(r2.text):,} bytes) — sin variables de datos")
        except Exception as e:
            print(f"    {ep} — Error: {e}")

    # 6. Guardar HTML principal para inspección manual
    dump_path = os.path.join(os.path.dirname(__file__), f"dump_ejecucion_{obra_id}.html")
    with open(dump_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  HTML DatosEjecucion guardado en: {dump_path}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Explorador de datos InfoObras")
    parser.add_argument("cui", nargs="?", default="2157301",
                        help="CUI a buscar (default: 2157301)")
    parser.add_argument("--nombre", type=str,
                        help="Buscar por nombre de obra")
    parser.add_argument("--obra-id", type=int,
                        help="Ir directo por ObraId (sin buscar)")
    parser.add_argument("--extras", action="store_true",
                        help="Probar endpoints adicionales (InformeControl, CuadernoObra, etc.)")
    parser.add_argument("--descargas", action="store_true",
                        help="Intentar descubrir patrón de URL de descarga de documentos")
    parser.add_argument("--diagnostico", action="store_true",
                        help="Diagnosticar por qué faltan variables JS en DatosEjecucion")

    args = parser.parse_args()

    session = _crear_session()
    print("Session iniciada.\n")

    obra_id = args.obra_id

    # Si no tenemos obra_id, buscar
    if not obra_id:
        if args.nombre:
            print(f"Buscando por nombre: '{args.nombre}'")
            obras = buscar_obras_por_nombre(args.nombre)
        else:
            print(f"Buscando CUI: {args.cui}")
            obras = _buscar_por_cui(session, args.cui)

        if not obras:
            print("Sin resultados.")
            return

        explorar_busqueda(obras)

        obra_id = obras[0].get("codigoObra")
        if not obra_id:
            print("\nPrimera obra sin codigoObra. No se puede continuar.")
            return

    # Modo diagnóstico
    if args.diagnostico:
        diagnosticar_html(session, obra_id)
        return

    # DatosEjecucion
    print(f"\nDescargando DatosEjecucion para ObraId={obra_id}...")
    time.sleep(_DELAY)
    datos = _extraer_datos_ejecucion(session, obra_id)

    if not datos:
        print("No se extrajeron variables JS del HTML.")
        return

    explorar_datos_ejecucion(datos, obra_id)

    # Documentos descargables
    if args.descargas:
        time.sleep(_DELAY)
        probar_descarga_documento(session, datos)

    # Endpoints adicionales
    if args.extras:
        endpoints_extra = [
            ("Informes de Control", "InformeControl"),
            ("Cuaderno de Obra Digital", "CuadernoObraDigital"),
            ("Ejecución Financiera", "EjecucionFinanciera"),
            ("Datos de Cierre", "DatosCierre"),
        ]
        for nombre_tab, endpoint in endpoints_extra:
            time.sleep(_DELAY)
            explorar_endpoint_extra(session, obra_id, nombre_tab, endpoint)


if __name__ == "__main__":
    main()
