# InfoObras Scraper — Documentación Completa

> **Fecha:** 2026-03-07
> **CUI de prueba:** `2157301` — Hospital Román Egoavil Pando, Pasco (`ObraId=66057`, estado: Paralizada)
> **Estado PoC:** ✅ Completamente viable con `requests` puro — sin Playwright, sin CAPTCHA, sin login
> **Hallazgo clave:** Los supervisores/residentes están en JSON estructurado. **No se necesita OCR sobre valorizaciones.**

---

## 1. Hallazgos Críticos (Resumen Ejecutivo)

| Supuesto inicial | Realidad descubierta |
|---|---|
| "Infobras puede tener CAPTCHA o bot-protection" | ✅ Portal 100% público. `requests` puro funciona. Sin login. |
| "Necesitamos OCR sobre valorizaciones para nombres de supervisores" | ✅ `lSupervisor` y `lResidente` en JSON con nombre, apellidos, DNI y fechas exactas |
| "Detectar paralizaciones requiere análisis complejo" | ✅ `lAvances[n].Estado == 'Paralizado'` + `DiasParalizado` + `Causal` — un campo directo |
| "Scraping frágil a cambios del portal" | ✅ Los datos están en variables JS embebidas en el HTML, no en el DOM dinámico |
| "Necesitamos Playwright para renderizado JS" | ✅ No. El HTML ya contiene los arrays JSON como `var lSupervisor = [...]` |

**Consecuencia para el sistema:** La verificación cruzada de certificados vs Infobras es ~70% más simple de implementar de lo previsto. No hay OCR de valorizaciones, no hay scraping frágil de DOM dinámico.

---

## 2. Flujo Completo de Requests

```
CUI (ej: 2157301)
    │
    ▼  [1] POST /infobrasweb/Mapa/busqueda/obrasBasic
    │       → JSON → lista de obras → obtener codigoObra
    │       → también trae: supervisor actual, residente actual, RUC
    │
    ├──▶ [2] GET /InfobrasWeb/Mapa/Obra?ObraId={id}           (opcional)
    │         HTML con Resumen Ejecutivo (datos básicos de la obra)
    │         ~160 KB — datos ya disponibles en [1], uso reducido
    │
    ├──▶ [3] GET /InfobrasWeb/Mapa/DatosGenerales?ObraId={id} (omitir)
    │         HTML con capas GeoJSON — no relevante para verificación
    │
    ├──▶ [4] GET /InfobrasWeb/Mapa/DatosPreparacion?ObraId={id} (omitir)
    │         HTML con tablas vacías — datos cargados por AJAX por separado
    │         Todo su contenido útil ya está en DatosEjecucion
    │
    └──▶ [5] GET /InfobrasWeb/Mapa/DatosEjecucion?ObraId={id}  ← LA ÚNICA NECESARIA
              HTML con variables JS embebidas (~202 KB):
              lAvances, lSupervisor, lResidente, lContratista,
              lModificacionPlazo, lAdicionalDeduc, lEntregaTerreno,
              lAdelanto, lCronograma, lTransferenciaFinanciera
```

**Requests mínimos para verificación de certificado: solo [1] + [5]**
**Tiempo total:** ~5–8 segundos por obra

---

## 3. Endpoint [1]: Búsqueda por CUI

```
POST https://infobras.contraloria.gob.pe/infobrasweb/Mapa/busqueda/obrasBasic
     ?page=0&rowsPerPage=20&Parameters={...JSON URL-encoded...}
```

### Body (campo `Parameters`, URL-encoded):

```json
{
  "codSnip": "2157301",
  "codDepartamento": "",
  "codProvincia": null,
  "codDistrito": null,
  "codigoObra": "",
  "estadoRegistro": "",
  "nombrObra": "",
  "estObra": "",
  "fechaIniObraDesde": "",
  "fechaIniObraHasta": "",
  "nobrCodmodejec": "",
  "cobrCodentpub": "",
  "codtipobrnv1": "",
  "codtipobrnv2": null,
  "codNivel3": null,
  "codMarca": "",
  "modServControl": "",
  "servControl": "",
  "nombreEntidad": "",
  "getFavoritos": 0,
  "tieneMonitor": ""
}
```

> ⚠️ El CUI del formulario va en `codSnip`. En la respuesta, el CUI aparece como `codUniqInv`. El campo `codSnip` de la respuesta es el código SNIP (distinto).

### Respuesta JSON completa (obra 66057):

```json
{
  "codigoObra": 66057,
  "codUniqInv": "2157301",
  "codSnip": "95555",
  "nombrObra": "MEJORA DE LA CAPACIDAD RESOLUTIVA DEL HOSPITAL ROMAN EGOAVIL PANDO...",
  "estObra": "Paralizada",
  "estActualizacion": "Desactualizado",
  "nombreEntidad": "GOBIERNO REGIONAL PASCO",
  "nombreEjecutor": "CONSORCIO SAN CRISTOBAL",
  "rucEjecutor": "20605488341",
  "nombresSupervisor": "VICTOR AUGUSTO GAYOSO TARAZONA",
  "rucSupervisor": "20611072962",
  "dniSupervisor": "41371261",
  "nombresResidente": "MIGUEL ANGEL SANTIANI PUICAN",
  "numdocResidente": "06666379",
  "montoObraSoles": 125243328.87,
  "montoEjecucion": 2587292.0,
  "fechaIniObra": "/Date(1574485200000)/",
  "fechaFinObra": "/Date(1610773200000)/",
  "plazoObra": 420,
  "nomTipoObra": "Salud"
}
```

> ⚠️ Las fechas usan formato `/Date(timestamp_ms)/` → convertir con `datetime.fromtimestamp(ts/1000, tz=timezone.utc)`

**Lo que entrega directamente:** supervisor actual, residente actual, RUC ejecutor, estado obra, fechas, tipo de obra. Para la búsqueda rápida de si una obra existe y su estado, esto es suficiente.

---

## 4. Endpoint [2]: Resumen Ejecutivo (opcional)

```
GET https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/Obra?ObraId=66057
```

- **Tamaño:** ~160 KB
- **Datos adicionales vs [1]:** Estado de ejecución parseado, % avance físico con mes, monto del expediente técnico, documento de aprobación.
- **Para el sistema:** Casi toda esta información viene del endpoint [1]. Usar solo si se necesita el % de avance físico o el monto del expediente.

---

## 5. Endpoint [3]: Datos Generales — OMITIR

```
GET https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/DatosGenerales?ObraId=66057
```

- **Tamaño:** ~49 KB
- **Contenido principal:** Datos geoespaciales (capas GeoJSON, polígonos, geometrías de Infobras/INEI). No útil para verificación de certificados.
- **Datos de obra:** Duplicados de lo que ya trae [1].
- **Decisión:** No incluir en el pipeline del sistema.

---

## 6. Endpoint [4]: Datos de Preparación — OMITIR

```
GET https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/DatosPreparacion?ObraId=66057
```

- **Tamaño:** ~39 KB
- **Problema:** Las tablas existen en el HTML pero **los datos se cargan por AJAX** cuando el usuario hace click en el tab. El HTML estático contiene solo los encabezados:

| Sección | Columnas (sin datos en HTML estático) |
|---|---|
| 1. Residente | Nombre, Fecha inicio, Fecha fin, Doc. designación |
| 2. Supervisión de obra | Tipo, N° doc, Nombre/razón social, Monto contrato, Fechas |
| 3. Revisión del ET | N° informe, Fecha, Informe revisión, Conformidad |
| 4. Personal clave | Tipo, Nombre, Apellido, Inicio/fin labores |

- **Decisión:** Omitir. **Todo su contenido útil ya está en `lSupervisor` y `lResidente` del endpoint [5]**, en formato JSON limpio sin necesidad de parseo de HTML.

---

## 7. Endpoint [5]: Datos de Ejecución ← EL ÚNICO QUE SE NECESITA

```
GET https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/DatosEjecucion?ObraId=66057
```

- **Tamaño:** ~202 KB
- **Técnica:** Los datos NO van por AJAX. Vienen **embebidos como arrays JS** en el HTML del response.
- **Método de extracción:** `re.search(r'var NOMBRE\s*=\s*(\[.*?\]);', html, re.DOTALL)` + `json.loads()`

### 7.1. `lAvances` — 37 registros (avances mensuales cronológicos)

**Uso principal:** Detectar paralizaciones en el periodo del certificado.

**Ejemplo completo (Oct 2022 — mes paralizado):**
```json
{
  "Codigo": 1229451,
  "Anio": "2022",
  "Mes": "OCTUBRE",
  "PorcProgramadoFisico": 50.03,
  "PorcRealFisico": 49.25,
  "ProgramadoFinanc": 57194966.60,
  "RealFinanc": 56298773.94,
  "PorcEjecFinanc": 49.25,
  "MontoEjecFinanc": 56298773.94,
  "Estado": "Paralizado",
  "TipoParalizacion": "Total",
  "FechaParalizacion": "15/10/2022",
  "DiasParalizado": 240,
  "Causal": "Falta de supervisor o inspector",
  "ComentarioFisico": "LA OBRA SE ENCUENTRA SUSPENDIDA",
  "ComentarioValorizado": "LA OBRA SE ENCUENTRA SUSPENDIDA",
  "lImgFisico": [
    {
      "Codigo": 3140953,
      "EsFisico": 1,
      "UrlImg": "00631412cce24b9eaac4f441a624c821",
      "nombreArchivo": "WhatsApp Image 2023-04-10 at 12.50.48 PM.jpeg",
      "Extension": "jpeg"
    }
  ],
  "lImgValorizacion": [
    {
      "Codigo": 3140957,
      "EsFisico": 0,
      "UrlImg": "a137035b4d5f495caf449c47bfe9791e",
      "nombreArchivo": "CamScanner 04-10-2023 12.33.pdf",
      "Extension": "pdf"
    }
  ]
}
```

**Campos clave para verificación:**

| Campo | Tipo | Descripción |
|---|---|---|
| `Anio` | string | Año del avance (ej: `"2022"`) |
| `Mes` | string | Mes en español mayúsculas (ej: `"OCTUBRE"`) |
| `Estado` | string | `"En ejecución"` / `"Paralizado"` / `"Finalizado"` |
| `TipoParalizacion` | string | `"Total"` / `"Parcial"` / `null` |
| `FechaParalizacion` | string | Fecha inicio de la paralización (`"DD/MM/YYYY"`) |
| `DiasParalizado` | int | Días acumulados paralizados en ese mes |
| `Causal` | string | Razón de paralización |
| `ComentarioFisico` | string | Comentario de campo |
| `lImgValorizacion` | array | PDFs de valorización mensual (con `UrlImg` y `nombreArchivo`) |

> **Nota:** Las fotos (`lImgFisico`) y las valorizaciones (`lImgValorizacion`) tienen URLs de imagen/documento accesibles. Si se necesitan como evidencia, se pueden descargar.

---

### 7.2. `lSupervisor` — 3 registros (histórico completo de supervisores)

**Uso principal:** Verificar si el nombre en el certificado corresponde a alguien que realmente fue supervisor/inspector en ese periodo.

**Ejemplo — Inspector Natural (primer registro):**
```json
{
  "Codigo": 267810,
  "TipoSupervisor": "Inspector",
  "TipoPersona": "Natural",
  "Ruc": null,
  "NombreEmpresa": null,
  "FechaContrato": null,
  "MontoSoles": 0.0,
  "NombreRep": "JULIO",
  "ApellidoPaterno": "BARRAZA",
  "ApellidoMaterno": "CHIRINOS",
  "FechaInicio": "20/11/2019",
  "FechaFin": "15/10/2020",
  "TipoDoc": "D.N.I",
  "NumeroDocRep": "10178205",
  "UrlRegistro": null,
  "DocumentoDesignacion": null,
  "FechaDesignacion": " "
}
```

**Todos los campos:**

| Campo | Descripción | Notas |
|---|---|---|
| `TipoSupervisor` | `"Inspector"` / `"Supervisor"` | Inspector = persona natural de entidad, Supervisor = empresa contratada |
| `TipoPersona` | `"Natural"` / `"Juridica"` | |
| `Ruc` | RUC de empresa supervisora | `null` si es inspector natural |
| `NombreEmpresa` | Razón social | `null` si es persona natural |
| `NombreRep` | Nombre del representante/inspector | Siempre presente |
| `ApellidoPaterno` | Apellido paterno | Siempre presente |
| `ApellidoMaterno` | Apellido materno | Puede ser `null` |
| `FechaInicio` | Inicio del periodo (`DD/MM/YYYY`) | |
| `FechaFin` | Fin del periodo (`DD/MM/YYYY`) | `null` si aún activo |
| `TipoDoc` | `"D.N.I"` / `"RUC"` | |
| `NumeroDocRep` | DNI del supervisor natural | |

**Los 3 supervisores de esta obra:**
1. JULIO BARRAZA CHIRINOS — Inspector — 20/11/2019 → 15/10/2020
2. (pendiente de extraer registro 2)
3. VICTOR AUGUSTO GAYOSO TARAZONA — Supervisor actual (viene del endpoint [1])

---

### 7.3. `lResidente` — 3 registros (histórico completo de residentes)

**Uso principal:** Verificar si el nombre en el certificado corresponde a alguien que realmente fue residente.

**Ejemplo — Primer residente:**
```json
{
  "Codigo": 230749,
  "NombreRep": "WALTER",
  "ApellidoPaterno": "TIMANA",
  "ApellidoMaterno": "MIRANDA",
  "FechaInicio": "23/11/2019",
  "FechaFin": "16/12/2019",
  "AperturaCuadernoObra": "NO",
  "DocumentoDesignacion": " ",
  "FechaDesignacion": " ",
  "UrlRegistro": null
}
```

| Campo | Descripción |
|---|---|
| `NombreRep` | Nombre de pila |
| `ApellidoPaterno` / `ApellidoMaterno` | Apellidos separados |
| `FechaInicio` / `FechaFin` | Periodo como residente (`DD/MM/YYYY`) |
| `AperturaCuadernoObra` | `"SI"` / `"NO"` |

---

### 7.4. `lContratista` — 1 registro

**Uso principal:** Obtener RUC del ejecutor para consultar SUNAT (fecha de constitución).

```json
{
  "TipoEmpresa": "Consorcio",
  "Ruc": "C0003197145",
  "NombreEmpresa": "CONSORCIO SAN CRISTOBAL",
  "MontoSoles": 114318830.30,
  "NumeroContrato": "0028-2019-G.R.PASCO/GGR",
  "FechaContrato": "13/11/2019",
  "FechaFinContrato": "07/01/2021"
}
```

> **Nota:** RUC de consorcio empieza con `C` — no es RUC válido para SUNAT. Buscar las empresas miembro por separado si se necesita verificación.

---

### 7.5. `lModificacionPlazo` — 4 registros (ampliaciones y suspensiones)

**Uso complementario:** Confirmar periodos de paralización con resoluciones oficiales.

```json
{
  "Codigo": 90343,
  "TipoModificacion": "Ampliación del plazo",
  "NumeroPLazo": 0,
  "Causal": "Plazo adicional para la ejecución de los mayores metrados...",
  "DiasAprobados": 467,
  "FechaAprob": "06/07/2020",
  "FechaFin": "28/04/2022",
  "UrlRegistro": "Ampliaciones.pdf",
  "nombreArchivo": "Ampliaciones.pdf",
  "Extension": "pdf"
}
```

| `TipoModificacion` | Descripción |
|---|---|
| `"Ampliación del plazo"` | Días adicionales aprobados |
| `"Suspensión del plazo"` | Plazo suspendido (no corre el reloj) |

---

### 7.6. `lAdicionalDeduc` — 3 registros (adicionales y deductivos)

```json
{
  "NumeroAdic": 5,
  "TipoAdicional": "Adicional",
  "SubTipo": "Adicional de obra",
  "Causal": "No previstas en el expediente",
  "FechaAprob": "30/04/2021",
  "Porcentaje": 0.0231,
  "MontoSoles": 2635485.0,
  "UrlRegistro": "adicionales/documento20210621114746.pdf"
}
```

**Uso:** Contexto de la obra. No es prioritario para verificación de certificados.

---

### 7.7. Otras variables disponibles

| Variable | Registros | Contenido |
|---|---|---|
| `lEntregaTerreno` | 1 | Fecha y porcentaje de entrega del terreno |
| `lAdelanto` | 1 | Adelantos entregados (directo, materiales) |
| `lCronograma` | 3 | Cronogramas actualizados con documentos |
| `lTransferenciaFinanciera` | 1 | Entidad origen de fondos (MINSA, MEF, etc.) |
| `lControversia` | 0 | Arbitrajes y controversias |
| `lAdenda` | 0 | Adendas al contrato |

---

## 8. Endpoint [6]: Datos de Cierre — USO LIMITADO

```
GET https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/DatosCierre?ObraId=66057
```

- **Tamaño:** ~28 KB
- **Contenido:** Finalización, Recepción, Liquidación, Transferencia.
- **Para obras paralizadas:** Todos los campos vacíos — `"No existe registro"`.
- **Para obras finalizadas:** Contiene fechas de recepción, actas, liquidación.
- **Decisión:** Incluir solo como dato complementario — no es necesario para la verificación de certificados.

---

## 9. Headers Necesarios

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/Index",
}
```

> No se necesitan cookies de sesión. Solo hacer un GET inicial a `/InfobrasWeb/` para inicializar la sesión.

---

## 10. Blueprint: Verificación de Certificado vs Infobras

Función completa para verificar si un certificado es consistente con Infobras:

```python
import re, json, requests
from datetime import datetime
from difflib import SequenceMatcher

MES_NUM = {
    "ENERO":1, "FEBRERO":2, "MARZO":3, "ABRIL":4,
    "MAYO":5, "JUNIO":6, "JULIO":7, "AGOSTO":8,
    "SEPTIEMBRE":9, "OCTUBRE":10, "NOVIEMBRE":11, "DICIEMBRE":12
}

def extraer_vars_ejecucion(html: str) -> dict:
    """Extrae todos los arrays JS del HTML de DatosEjecucion."""
    vars_nombres = [
        'lAvances', 'lContratista', 'lSupervisor', 'lResidente',
        'lModificacionPlazo', 'lAdicionalDeduc', 'lEntregaTerreno',
        'lAdelanto', 'lCronograma', 'lTransferenciaFinanciera',
    ]
    resultado = {}
    for vn in vars_nombres:
        m = re.search(rf'var\s+{vn}\s*=\s*(\[.*?\]);', html, re.DOTALL)
        if m:
            try:
                resultado[vn] = json.loads(m.group(1))
            except json.JSONDecodeError:
                resultado[vn] = []
        else:
            resultado[vn] = []
    return resultado


def parsear_fecha(s: str):
    """Convierte 'DD/MM/YYYY' a datetime.date. Retorna None si falla."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


def periodos_solapan(inicio1, fin1, inicio2, fin2) -> bool:
    """True si los dos periodos de tiempo se solapan."""
    if not all([inicio1, fin1, inicio2, fin2]):
        return False
    return inicio1 <= fin2 and fin1 >= inicio2


def fuzzy_nombre(n1: str, n2: str) -> float:
    """Score de similitud de nombre entre 0 y 1."""
    from unidecode import unidecode
    def norm(s):
        s = unidecode(s).upper().strip()
        return re.sub(r'[^A-Z\s]', '', s)
    return SequenceMatcher(None, norm(n1), norm(n2)).ratio()


def verificar_certificado_infobras(
    session: requests.Session,
    cui: str,
    nombre_profesional: str,
    cargo: str,            # 'supervisor', 'inspector', 'residente'
    fecha_inicio_cert,     # datetime.date
    fecha_fin_cert,        # datetime.date
    base_web="https://infobras.contraloria.gob.pe/InfobrasWeb"
) -> dict:
    """
    Verifica un certificado contra los datos reales de Infobras.
    
    Retorna dict con:
      - obra_encontrada: bool
      - estado_obra: str
      - nombre_coincide: bool
      - score_nombre: float (0-1)
      - nombre_encontrado: str
      - periodo_valido: bool  (el profesional estuvo en el cargo en ese periodo)
      - paralizaciones: list  (meses paralizados que solapan con el certificado)
      - dias_paralizado_en_periodo: int
      - supervisores: list   (histórico completo)
      - residentes: list     (histórico completo)
      - alertas: list[str]
    """
    alertas = []

    # [1] Buscar obra por CUI
    obras = buscar_por_cui(session, cui)
    if not obras:
        return {"obra_encontrada": False, "alertas": ["Obra no encontrada en Infobras"]}

    obra = obras[0]
    obra_id = obra['codigoObra']
    estado_obra = obra.get('estObra', '')

    # [5] Datos de Ejecución
    r = session.get(f"{base_web}/Mapa/DatosEjecucion",
                    params={"ObraId": obra_id}, timeout=20)
    datos = extraer_vars_ejecucion(r.text)

    supervisores = datos.get('lSupervisor', [])
    residentes   = datos.get('lResidente', [])
    avances      = datos.get('lAvances', [])

    # --- Verificar nombre en histórico de cargo ---
    candidatos = supervisores if cargo in ('supervisor', 'inspector') else residentes

    mejor_score = 0.0
    mejor_match = None
    periodo_valido = False

    for persona in candidatos:
        nombre_inf = f"{persona.get('NombreRep','')} {persona.get('ApellidoPaterno','')} {persona.get('ApellidoMaterno','')}"
        score = fuzzy_nombre(nombre_profesional, nombre_inf)
        f_ini = parsear_fecha(persona.get('FechaInicio', ''))
        f_fin = parsear_fecha(persona.get('FechaFin', '')) or fecha_fin_cert

        if score > mejor_score:
            mejor_score = score
            mejor_match = nombre_inf.strip()
            if score > 0.75:
                periodo_valido = periodos_solapan(
                    fecha_inicio_cert, fecha_fin_cert, f_ini, f_fin
                )

    if mejor_score < 0.75:
        alertas.append(f"Nombre '{nombre_profesional}' no coincide con ningún {cargo} en Infobras (score máx: {mejor_score:.2f})")
    elif not periodo_valido:
        alertas.append(f"'{nombre_profesional}' aparece en Infobras como {cargo} pero en periodo diferente al del certificado")

    # --- Detectar paralizaciones en el periodo del certificado ---
    paralizaciones_en_periodo = []
    dias_paralizado = 0

    for avance in avances:
        if avance.get('Estado') != 'Paralizado':
            continue
        try:
            mes_num = MES_NUM.get(avance.get('Mes', '').upper(), 0)
            anio    = int(avance.get('Anio', 0))
            if mes_num == 0 or anio == 0:
                continue
            # Aproximar inicio/fin del mes
            from datetime import date
            ini_mes = date(anio, mes_num, 1)
            fin_mes = date(anio, mes_num, 28)  # conservador
            if periodos_solapan(fecha_inicio_cert, fecha_fin_cert, ini_mes, fin_mes):
                paralizaciones_en_periodo.append({
                    "periodo": f"{avance['Mes']} {avance['Anio']}",
                    "tipo": avance.get('TipoParalizacion'),
                    "dias": avance.get('DiasParalizado', 0),
                    "causal": avance.get('Causal'),
                })
                dias_paralizado += avance.get('DiasParalizado', 0)
        except (ValueError, TypeError):
            continue

    if paralizaciones_en_periodo:
        alertas.append(
            f"Obra paralizada {len(paralizaciones_en_periodo)} mes(es) durante el periodo del certificado "
            f"({dias_paralizado} días acumulados)"
        )

    return {
        "obra_encontrada": True,
        "obra_id": obra_id,
        "estado_obra": estado_obra,
        "nombre_coincide": mejor_score >= 0.75,
        "score_nombre": round(mejor_score, 3),
        "nombre_encontrado": mejor_match,
        "periodo_valido": periodo_valido,
        "paralizaciones": paralizaciones_en_periodo,
        "dias_paralizado_en_periodo": dias_paralizado,
        "supervisores": supervisores,
        "residentes": residentes,
        "alertas": alertas,
    }
```

---

## 11. Decisión: Qué Tabs Usar y Cuáles Omitir

| Tab (Endpoint) | ¿Usar? | Razón |
|---|---|---|
| **[1] Búsqueda por CUI** | ✅ Siempre | Da codigoObra, estado, supervisor actual, residente actual |
| **[2] Resumen Ejecutivo** | ⚠️ Opcional | Solo si se necesita % avance físico o monto expediente |
| **[3] Datos Generales** | ❌ Omitir | Solo datos geoespaciales y datos duplicados del [1] |
| **[4] Datos de Preparación** | ❌ Omitir | Tablas vacías (AJAX). Todo su contenido ya está en [5] |
| **[5] Datos de Ejecución** | ✅ Siempre | Toda la información: supervisores, residentes, paralizaciones |
| **[6] Datos de Cierre** | ⚠️ Opcional | Solo para obras finalizadas. Vacío en obras paralizadas. |

---

## 12. Otros Endpoints Disponibles (No Explorados)

| Endpoint | Tab visible | Prioridad |
|---|---|---|
| `/Mapa/EjecucionFinanciera?ObraId=X` | Ejecución financiera (SIAF) | Media — útil para monto ejecutado real |
| `/Mapa/InformeControl?ObraId=X` | Informes de control (Contraloría) | Alta — detecta alertas previas de CGR |
| `/Mapa/LineaTiempo?ObraId=X` | Línea de tiempo | Baja — timeout en prueba, reintentar |
| `/Mapa/ProcesoSeleccion?ObraId=X` | Procesos de selección | Media — datos de licitación |
| `/Mapa/CuadernoObraDigital?ObraId=X` | Cuaderno de obra digital | Alta — podría tener firmas y anotaciones |
| `/Mapa/ControlSocial?ObraId=X` | Control social | Baja |

---

## 13. Archivos del PoC

| Archivo | Descripción | Estado |
|---|---|---|
| `buscar.py` | Script principal: busca por CUI, descarga ficha, parsea y muestra | ✅ Funcional |
| `detalle_probe.py` | Scripts exploratorios de endpoints | Descartable |
| `tab_datosejecucion.html` | HTML de DatosEjecucion (ObraId=66057, 202KB) | Referencia |
| `tab_datospreparacion.html` | HTML de DatosPreparacion (vacío por AJAX) | Descartable |
| `tab_datosgenerales.html` | HTML de DatosGenerales (solo GeoJSON) | Descartable |
| `tab_datoscierre.html` | HTML de DatosCierre (vacío — obra paralizada) | Referencia |

---

## 14. Pendientes

| # | Tarea | Prioridad |
|---|---|---|
| P-01 | Extraer `lAvances` completo para mapear todos los meses y tipos de paralización | Alta |
| P-02 | Parsear los 3 supervisores completos de `lSupervisor` (solo se documentó el primero) | Alta |
| P-03 | Probar con obra FINALIZADA para ver datos reales de DatosCierre | Alta |
| P-04 | Probar `/Mapa/EjecucionFinanciera` (datos SIAF) | Media |
| P-05 | Probar `/Mapa/InformeControl` (informes CGR — muy valioso) | Media |
| P-06 | Probar `/Mapa/LineaTiempo` con timeout mayor | Baja |
| P-07 | Probar `/Mapa/CuadernoObraDigital` | Media |
| P-08 | Integrar `verificar_certificado_infobras()` al pipeline principal | Alta |

---

*Documentado el 2026-03-07 — PoC completado. Riesgo técnico de Infobras: ELIMINADO.*
