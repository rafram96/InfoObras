"""
Extrae las variables JS embebidas en tab_datosejecucion.html
(lAvances, lContratista, lSupervisor, etc.)
"""
import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

with open("utils/infoobras/tab_datosejecucion.html", encoding="utf-8") as f:
    html = f.read()

# Las variables JS son del tipo: var lNombre = [...];  o  var lNombre = null;
# Se declaran en un bloque <script> del HTML
variables = {
    "lAvances":               "Avances de obra (con estado paralización)",
    "lContratista":           "Contratistas",
    "lAdenda":                "Adendas al contrato",
    "lSupervisor":            "Supervisores",
    "lResidente":             "Residentes",
    "lTransferenciaFinanciera": "Transferencias financieras",
    "lEntregaTerreno":        "Entregas de terreno",
    "lAdelanto":              "Garantías de adelanto",
    "lCronograma":            "Cronograma",
    "lModificacionPlazo":     "Modificaciones de plazo",
    "lAdicionalDeduc":        "Adicionales / deductivos",
    "lControversia":          "Controversias",
}

for var_name, descripcion in variables.items():
    # Buscar: var lNombre = VALUE;  (VALUE puede ser [...] o null)
    m = re.search(
        rf'var\s+{re.escape(var_name)}\s*=\s*([\[{{].*?[\]}}]|null)\s*;',
        html, re.DOTALL
    )
    if not m:
        print(f"\n  [{var_name}] ({descripcion}) — NO ENCONTRADO")
        continue

    raw = m.group(1).strip()
    if raw == "null":
        print(f"\n  [{var_name}] ({descripcion}) = null")
        continue

    try:
        data = json.loads(raw)
        print(f"\n{'='*60}")
        print(f"  {var_name} — {descripcion}")
        print(f"  Registros: {len(data)}")
        print(f"{'='*60}")
        if data:
            # Imprimir los primeros 3 registros completos
            for i, item in enumerate(data[:3]):
                print(f"\n  [{i+1}] {json.dumps(item, ensure_ascii=False, indent=4)}")
            if len(data) > 3:
                print(f"\n  ... y {len(data)-3} más")
    except json.JSONDecodeError as e:
        print(f"\n  [{var_name}] — Error JSON: {e}")
        print(f"  Primeros 200 chars: {raw[:200]}")
