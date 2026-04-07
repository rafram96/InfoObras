# Scrapers del Sistema — Estado, Flujo y Pendientes

> **Última actualización:** 2026-04-06
> **Estado general:** Ambos scrapers están implementados y verificados. El trabajo pendiente es integración al pipeline de producción de `Alpamayo-InfoObras/src/`.

---

## 1. Contexto: dónde interviene cada scraper en el pipeline

```
PDF propuesta técnica (SEACE)
    │
    ▼
Paso 1 — Criterios RTM de bases
Paso 2 — Profesionales propuestos
    │
    ▼
Paso 3 — Base de datos de experiencias
    │   Por cada certificado extraído:
    │
    ├──▶ [SEACE Scraper]
    │       nomenclatura del proceso → buscar en SEACE
    │       → descargar PDF propuesta técnica si no está
    │       → Columna 25: Código CUI
    │
    ├──▶ [InfoObras Scraper]
    │       nombre_proyecto (del certificado) → buscar_por_nombre()
    │       Si hay ambigüedad → desambiguar o UI de confirmación manual
    │       → Columna 25: Código CUI
    │       → Columna 26: Código InfoObras
    │
    ▼
Paso 4 — Evaluación RTM
Paso 5 — Evaluación de años de experiencia
    │
    ├──▶ [InfoObras Scraper]
    │       fetch_by_cui(cui) → estado_obra, paralizaciones, supervisores, residentes
    │       verificar_certificado() → días paralización en periodo
    │       → Días a descontar del cómputo de experiencia
    │       → ALERTA si nombre supervisor/residente no coincide con InfoObras
```

---

## 2. SEACE Scraper

### 2.1. Ubicación y estado

| Ítem | Detalle |
|---|---|
| **Repositorio** | `C:\Users\Holbi\Documents\Freelance\Seace-Scrapper\` |
| **Estado** | ✅ Producción — completamente funcional |
| **Tecnología** | Python 3.11 · `requests` · `beautifulsoup4` · `lxml` · `rich` |
| **Sin** | Selenium, Playwright, CAPTCHA, login |

### 2.2. Qué hace

Pipeline de **5 niveles** que replica la navegación de un usuario en el portal JSF/PrimeFaces de SEACE:

```
Nivel 1  Búsqueda de procesos (filtros, paginación)
Nivel 2  Navegación a Ficha de Selección de cada proceso
Nivel 3  Detección y navegación a "Ver Ofertas Presentadas"
Nivel 4  Extracción de datos de cada postor (RUC, nombre, documentos)
Nivel 5  Resolución de URLs CMS (Alfresco) y descarga de PDFs
```

**Datos que extrae:**

| Dato | Nivel |
|---|---|
| Nomenclatura, entidad, valor referencial, tipo, fecha publicación | 1 |
| CUI, código SNIP | 1 |
| Opciones del proceso (Ver Bases, Ver Ofertas, etc.) | 2 |
| Lista de postores (RUC, razón social, fecha presentación) | 3 |
| Documentos por postor (oferta técnica, económica) | 4 |
| PDFs descargados (Oracle Storage + CMS Alfresco) | 5 |

### 2.3. Arquitectura de módulos

```
run.py
  └── main.py          CLI, logging, display con Rich
        ├── session_manager.py   Sesión HTTP: ViewState, cookies, rate limiting
        ├── search_engine.py     Búsqueda, paginación, ParseResult
        ├── ficha_scraper.py     Deep scan: fichas → ofertas → postores → PDFs
        └── exporter.py          CSV / JSON
              config.py          Constantes: URLs, IDs JSF, departamentos, códigos
```

### 2.4. El desafío técnico: JSF + PrimeFaces

El portal usa **JavaServer Faces** con **PrimeFaces**. Cada interacción requiere:
- **ViewState dinámico** — token que cambia con cada request; sin él el servidor rechaza
- **JSESSIONID** — cookie de sesión que mantiene estado server-side
- **Payloads JSF** — IDs internos de componentes (ej: `tbBuscador:idFormBuscarProceso:j_idt188_input`)
- **PrimeFaces.submit()** — algunos clicks son form submits con 302 redirect, no AJAX

El scraper reinicializa la sesión antes de cada ficha porque el ViewState del árbol de componentes server-side se invalida al navegar.

### 2.5. Flujo de requests por nivel

**Nivel 1 — Búsqueda AJAX:**
```
POST /buscadorPublico/buscadorPublico.xhtml
Faces-Request: partial/ajax

Payload clave:
  javax.faces.source = tbBuscador:idFormBuscarProceso:btnBuscarSel
  tbBuscador:idFormBuscarProceso:anioConvocatoria_input = 2025
  tbBuscador:idFormBuscarProceso:j_idt188_input = 64   ← obra
  tbBuscador:idFormBuscarProceso:descripcionObjeto = hospital
  javax.faces.ViewState = [token dinámico]

Respuesta: XML partial-response → CDATA con tabla HTML → ParseResult
```

**Nivel 2 — Ficha de Selección:**
```
POST /buscadorPublico/buscadorPublico.xhtml  (NO AJAX, follow redirects)
→ HTTP 302 → fichaSeleccion.xhtml?id=UUID&ptoRetorno=LOCAL
```

**Nivel 3 — Página de Ofertas:**
```
POST /fichaSeleccion/fichaSeleccion.xhtml  (NO AJAX)
→ Página con tabla de postores
```

**Nivel 4 — Documentos del Postor:**
```
POST /fichaSeleccion/fichaListaPresentacionExpInteresOfertasProcedimiento.xhtml
→ Página con descargaDocGeneral() calls
```

**Nivel 5 — Resolución CMS Alfresco:**
```
# Tipo 2 (Oracle Storage): URL directa → GET descarga
# Tipo 3 (Alfresco CMS):
GET https://alfprod.seace.gob.pe/alfresco/service/osce/downloadDoc
    ?id={UUID}&doc=c{random}&guest=false
→ JSONP: { "result": "200", "downloadUrl": "/service/api/node/content/..." }
→ GET descarga desde alfprod.seace.gob.pe o prodcont2.seace.gob.pe (fallback)
```

### 2.6. Modelos de datos

```python
@dataclass
class ProcessResult:
    numero: str
    entidad: str
    fecha_publicacion: str
    nomenclatura: str          # "LP-ABR-35-2025-HRDC-1"
    objeto_contratacion: str   # "Obra"
    descripcion: str
    codigo_snip: str
    cui: str                   # ← LINK con InfoObras
    valor_referencial: str
    moneda: str
    version_seace: str
    extras: dict               # nid_proceso, nid_convocatoria, j_idt, row_index

@dataclass
class FichaResult:
    params: FichaParams
    ficha_cargada: bool
    tiene_ofertas: bool
    ofertas_navegadas: bool
    documentos: list[DocumentoOferta]
    estado_proceso: str
    etapa: str
    error: str

@dataclass
class DocumentoOferta:
    nombre: str
    url: str                   # URL ya resuelta, descargable directamente
    tipo: str                  # "tipo_3" (CMS) o "tipo_2" (Oracle)
    postor: str
    ruc_postor: str
```

### 2.7. Uso desde CLI

```bash
# Buscar obras con "hospital", deep scan + descarga
python run.py --deep --desc hospital --obras --download

# Buscar todas las obras de 2025 en Lima
python run.py --obras --anio 2025 --depto LIMA --all-pages --csv

# Test de conexión
python run.py --test
```

### 2.8. Rate limiting

- 2–4 segundos entre requests normales
- 3 segundos entre páginas de resultados
- Cada deep scan de 3 fichas: ~40–60 segundos

---

## 3. InfoObras Scraper

### 3.1. Ubicación y estado

| Ítem | Detalle |
|---|---|
| **PoC** | `Alpamayo-InfoObras/variety/infoobras/` |
| **Producción** | `Alpamayo-InfoObras/src/scraping/infoobras.py` — ⚠️ stub vacío |
| **Estado PoC** | ✅ Completamente funcional y documentado |
| **Tecnología** | Python · `requests` puro |
| **Sin** | Selenium, Playwright, CAPTCHA, login |
| **CUI de prueba** | `2157301` — Hospital Román Egoavil Pando, Pasco (`ObraId=66057`) |

### 3.2. Flujo de requests

```
nombre_proyecto o CUI
    │
    ▼  [1] POST /infobrasweb/Mapa/busqueda/obrasBasic
    │       → lista de obras → elegir por desambiguación → codigoObra + CUI
    │
    └──▶ [2] GET /InfobrasWeb/Mapa/DatosEjecucion?ObraId={id}   ← EL ÚNICO NECESARIO
              HTML ~202KB — datos embebidos como arrays JS:
              lAvances, lSupervisor, lResidente, lContratista,
              lModificacionPlazo, lAdicionalDeduc, lEntregaTerreno,
              lAdelanto, lCronograma, lTransferenciaFinanciera
```

**Requests mínimos: solo [1] + [2]. Tiempo estimado: 5–8 seg por obra.**

### 3.3. Endpoints adicionales (opcionales / no explorados)

| Endpoint | Contenido | Prioridad |
|---|---|---|
| `GET /InfobrasWeb/Mapa/Obra?ObraId=X` | Resumen ejecutivo — % avance físico, monto expediente | Opcional |
| `GET /InfobrasWeb/Mapa/InformeControl?ObraId=X` | Informes de control CGR | Media |
| `GET /InfobrasWeb/Mapa/CuadernoObraDigital?ObraId=X` | Cuaderno de obra digital | Media |
| `GET /InfobrasWeb/Mapa/EjecucionFinanciera?ObraId=X` | Monto ejecutado real (SIAF) | Baja |
| `GET /InfobrasWeb/Mapa/DatosCierre?ObraId=X` | Recepción, liquidación, transferencia | Solo obras finalizadas |

### 3.4. Endpoints descartados

| Endpoint | Razón |
|---|---|
| `GET /InfobrasWeb/Mapa/DatosGenerales?ObraId=X` | Solo GeoJSON — datos duplicados |
| `GET /InfobrasWeb/Mapa/DatosPreparacion?ObraId=X` | Tablas vacías (AJAX). Todo su contenido ya está en DatosEjecucion |

### 3.5. Endpoint [1]: Búsqueda

```
POST https://infobras.contraloria.gob.pe/infobrasweb/Mapa/busqueda/obrasBasic
     ?page=0&rowsPerPage=20&Parameters={JSON URL-encoded}
```

**Cuerpo del campo `Parameters`:**
```json
{
  "nombrObra":         "HOSPITAL ROMAN EGOAVIL",
  "codSnip":           "",
  "codDepartamento":   "",
  "codProvincia":      null,
  "codDistrito":       null,
  "codigoObra":        "",
  "estadoRegistro":    "",
  "estObra":           "",
  "fechaIniObraDesde": "",
  "fechaIniObraHasta": "",
  "nobrCodmodejec":    "",
  "cobrCodentpub":     "",
  "codtipobrnv1":      "",
  "codtipobrnv2":      null,
  "codNivel3":         null,
  "codMarca":          "",
  "modServControl":    "",
  "servControl":       "",
  "nombreEntidad":     "",
  "getFavoritos":      0,
  "tieneMonitor":      ""
}
```

> Para búsqueda por CUI: poner el CUI en `codSnip`, dejar `nombrObra` vacío.
> ⚠️ `codSnip` del **request** recibe el CUI. En la **respuesta**, el CUI aparece como `codUniqInv` y el SNIP como `codSnip`.

**Respuesta JSON por obra:**
```json
{
  "codigoObra":        66057,
  "codUniqInv":        "2157301",
  "codSnip":           "95555",
  "nombrObra":         "MEJORA DE LA CAPACIDAD RESOLUTIVA DEL HOSPITAL ROMAN EGOAVIL PANDO...",
  "estObra":           "Paralizada",
  "estActualizacion":  "Desactualizado",
  "nombreEntidad":     "GOBIERNO REGIONAL PASCO",
  "nombreEjecutor":    "CONSORCIO SAN CRISTOBAL",
  "rucEjecutor":       "20605488341",
  "nombresSupervisor": "VICTOR AUGUSTO GAYOSO TARAZONA",
  "rucSupervisor":     "20611072962",
  "dniSupervisor":     "41371261",
  "nombresResidente":  "MIGUEL ANGEL SANTIANI PUICAN",
  "numdocResidente":   "06666379",
  "montoObraSoles":    125243328.87,
  "montoEjecucion":    2587292.0,
  "fechaIniObra":      "/Date(1574485200000)/",
  "fechaFinObra":      "/Date(1610773200000)/",
  "plazoObra":         420,
  "nomTipoObra":       "Salud"
}
```

> Fechas usan `/Date(timestamp_ms)/` → `datetime.fromtimestamp(ts/1000, tz=timezone.utc)`

### 3.6. Endpoint [2]: Datos de Ejecución

Los datos **no vienen por AJAX** — están embebidos como arrays JS en el HTML.

**Técnica de extracción:**
```python
m = re.search(rf'var\s+{nombre_var}\s*=\s*(\[.*?\]);', html, re.DOTALL)
data = json.loads(m.group(1))
```

**Variables disponibles:**

| Variable | Registros (obra 66057) | Uso en pipeline |
|---|---|---|
| `lAvances` | 37 | **Principal** — paralizaciones por mes (Paso 5) |
| `lSupervisor` | 3 | **Principal** — verificar nombre supervisor/inspector |
| `lResidente` | 3 | **Principal** — verificar nombre residente |
| `lContratista` | 1 | RUC ejecutor para SUNAT |
| `lModificacionPlazo` | 4 | Confirmar suspensiones con resoluciones |
| `lAdicionalDeduc` | 3 | Contexto |
| `lEntregaTerreno` | 1 | Contexto |
| `lAdelanto` | 1 | Contexto |
| `lCronograma` | 3 | Contexto |
| `lTransferenciaFinanciera` | 1 | Origen de fondos |
| `lControversia` | 0 | Arbitrajes |
| `lAdenda` | 0 | Adendas |

**`lAvances` — campos clave (Paso 5):**
```json
{
  "Anio":              "2022",
  "Mes":               "OCTUBRE",
  "Estado":            "Paralizado",
  "TipoParalizacion":  "Total",
  "FechaParalizacion": "15/10/2022",
  "DiasParalizado":    240,
  "Causal":            "Falta de supervisor o inspector"
}
```

**`lSupervisor` — campos clave:**
```json
{
  "TipoSupervisor":  "Inspector",
  "TipoPersona":     "Natural",
  "NombreRep":       "JULIO",
  "ApellidoPaterno": "BARRAZA",
  "ApellidoMaterno": "CHIRINOS",
  "FechaInicio":     "20/11/2019",
  "FechaFin":        "15/10/2020",
  "TipoDoc":         "D.N.I",
  "NumeroDocRep":    "10178205",
  "Ruc":             null,
  "NombreEmpresa":   null
}
```

**`lResidente` — campos clave:**
```json
{
  "NombreRep":       "WALTER",
  "ApellidoPaterno": "TIMANA",
  "ApellidoMaterno": "MIRANDA",
  "FechaInicio":     "23/11/2019",
  "FechaFin":        "16/12/2019"
}
```

**`lContratista`:**
```json
{
  "TipoEmpresa":      "Consorcio",
  "Ruc":              "C0003197145",
  "NombreEmpresa":    "CONSORCIO SAN CRISTOBAL",
  "MontoSoles":       114318830.30,
  "NumeroContrato":   "0028-2019-G.R.PASCO/GGR",
  "FechaContrato":    "13/11/2019",
  "FechaFinContrato": "07/01/2021"
}
```
> RUC de consorcio empieza con `C` — no válido para SUNAT. Buscar empresas miembro por separado si se necesita verificar.

### 3.7. Headers necesarios

```python
HEADERS = {
    "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":           "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer":          "https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/Index",
}
```

No se necesitan cookies de sesión. Solo un GET inicial a `/InfobrasWeb/` antes de la primera búsqueda.

### 3.8. Lógica de desambiguación

Cuando `buscar_por_nombre()` devuelve múltiples obras, el sistema elige la más coherente con los datos del certificado.

**Criterio principal:** la obra cuya `fechaIniObra` sea la más cercana y anterior a la fecha de emisión del certificado. Ejemplo: dos resultados con inicio en 2010 y 2019, certificado emitido en 2020 → se elige la de 2019.

**Criterios secundarios** (si el principal no resuelve):
1. Coincidencia de `nomTipoObra` con el tipo de obra inferido del certificado
2. Coincidencia de `nombreEntidad` con el emisor del certificado
3. Score de similitud del nombre de obra vs. nombre del proyecto en el certificado (Jaccard sobre tokens)

**Si la ambigüedad persiste:** la obra queda en cola para confirmación manual en la UI.

### 3.9. Rate limiting

| Situación | Pausa |
|---|---|
| Entre endpoint [1] y [2] de la misma obra | 0.5 seg |
| Entre obras distintas | 1–2 seg |
| Batch grande (> 50 obras) | 2–3 seg |
| Reintento tras error 5xx | 5 seg (backoff exponencial) |

---

## 4. Estado actual del código

### SEACE (`Seace-Scrapper/`)

| Módulo | Estado |
|---|---|
| `session_manager.py` | ✅ Funcional — ViewState, cookies, rate limiting |
| `search_engine.py` | ✅ Funcional — búsqueda, paginación, parseo |
| `ficha_scraper.py` | ✅ Funcional — deep scan 5 niveles, Alfresco CMS |
| `exporter.py` | ✅ Funcional — CSV/JSON |
| `main.py` | ✅ Funcional — CLI completa con Rich |

### InfoObras (`variety/infoobras/`)

| Archivo | Estado |
|---|---|
| `buscar.py` | ✅ PoC funcional — búsqueda por CUI, ficha HTML, parseo |
| `detalle_probe.py` | ✅ PoC funcional — extracción arrays JS de DatosEjecucion |
| `SCRAPER.md` | ✅ Documentación completa del PoC |

### Producción (`src/scraping/infoobras.py`)

```python
@dataclass
class WorkInfo:
    cui: str
    name: Optional[str]
    status: Optional[str]
    suspension_periods: list[tuple[date, date]] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

def fetch_by_cui(cui: str) -> Optional[WorkInfo]:
    raise NotImplementedError   # ← todo el PoC pendiente de trasladar
```

---

## 5. Lo que falta implementar

### 5.1. `WorkInfo` — modelo insuficiente

Campos que necesita añadir para satisfacer el pipeline:

| Campo | Fuente | Uso |
|---|---|---|
| `obra_id` | `codigoObra` del endpoint [1] | Clave para endpoint [2] |
| `tipo_obra` | `nomTipoObra` | Paso 4 col. 15 |
| `entidad` | `nombreEntidad` | Contexto / desambiguación |
| `ejecutor` / `ruc_ejecutor` | `nombreEjecutor` / `rucEjecutor` | SUNAT (ALT04) |
| `supervisor_actual` / `ruc_supervisor` | `nombresSupervisor` / `rucSupervisor` | Verificación rápida |
| `residente_actual` | `nombresResidente` | Verificación rápida |
| `monto_contrato` | `montoObraSoles` | Contexto |
| `fecha_inicio` / `fecha_fin` | `fechaIniObra` / `fechaFinObra` | Desambiguación |
| `supervisores` | `lSupervisor` de [2] | Verificación de nombre |
| `residentes` | `lResidente` de [2] | Verificación de nombre |
| `avances` | `lAvances` de [2] | Paso 5 — paralizaciones |
| `modificaciones_plazo` | `lModificacionPlazo` de [2] | Paso 5 — suspensiones |

### 5.2. Funciones faltantes en `src/scraping/infoobras.py`

| Función | Descripción | Prioridad |
|---|---|---|
| `crear_session()` | GET inicial + headers | Alta |
| `buscar_por_cui(session, cui)` | POST endpoint [1] con `codSnip=cui` | Alta |
| `buscar_por_nombre(session, nombre)` | POST endpoint [1] con `nombrObra=nombre` | Alta |
| `elegir_obra(resultados, fecha_cert, ...)` | Desambiguación | Alta |
| `extraer_datos_ejecucion(session, obra_id)` | GET endpoint [2] + extracción arrays JS | Alta |
| `fetch_by_cui(cui)` | Función pública principal — une [1] + [2] | Alta |
| `verificar_certificado(...)` | Verifica nombre + detecta paralizaciones | Alta |
| `_parsear_timestamp(ts_str)` | `/Date(ms)/` → `datetime.date` | Alta |
| `_fuzzy_nombre(n1, n2)` | Jaccard sobre tokens | Alta |
| `_periodos_solapan(ini1, fin1, ini2, fin2)` | Overlap entre rangos de fechas | Alta |

### 5.3. Pendientes de investigación del PoC InfoObras

| # | Tarea | Impacto |
|---|---|---|
| P-01 | Mapear todos los valores posibles de `Estado` y `TipoParalizacion` en `lAvances` | Alto |
| P-02 | Parsear los 3 supervisores completos de `lSupervisor` — confirmar casos borde (`FechaFin: null`, empresa jurídica) | Alto |
| P-03 | Probar con obra **finalizada** — ver `DatosCierre` real | Alto |
| P-04 | Probar búsqueda por `nombrObra` con nombres parciales/degradados por OCR | Alto |
| P-05 | Probar `/Mapa/InformeControl` — alertas de Contraloría | Medio |
| P-06 | Probar `/Mapa/CuadernoObraDigital` | Medio |

### 5.4. Integración SEACE → InfoObras

El SEACE scraper (`Seace-Scrapper/`) es un proyecto independiente. Para el pipeline de `Alpamayo-InfoObras` se necesita:

- Wrapper o importación de `SearchEngine` / `FichaScraper` para buscar por CUI/nomenclatura
- Decisión de arquitectura: ¿copiar módulos o referenciar como dependencia?
- Mapeo `ProcessResult.cui` ↔ `WorkInfo.cui` como clave de cruce entre ambos sistemas

---

## 6. Blueprint: `verificar_certificado_infobras()`

Función lista para trasladar a `src/scraping/infoobras.py`:

```python
MES_NUM = {
    "ENERO":1, "FEBRERO":2, "MARZO":3, "ABRIL":4,
    "MAYO":5, "JUNIO":6, "JULIO":7, "AGOSTO":8,
    "SEPTIEMBRE":9, "OCTUBRE":10, "NOVIEMBRE":11, "DICIEMBRE":12
}

def verificar_certificado_infobras(
    session,
    cui: str,
    nombre_profesional: str,
    cargo: str,               # 'supervisor', 'inspector', 'residente'
    fecha_inicio_cert: date,
    fecha_fin_cert: date,
) -> dict:
    """
    Retorna:
      obra_encontrada, estado_obra,
      nombre_coincide, score_nombre, nombre_encontrado,
      periodo_valido, paralizaciones, dias_paralizado_en_periodo,
      supervisores, residentes, alertas
    """
    obras = buscar_por_cui(session, cui)
    if not obras:
        return {"obra_encontrada": False, "alertas": ["Obra no encontrada en InfoObras"]}

    obra = obras[0]
    obra_id = obra["codigoObra"]
    estado_obra = obra.get("estObra", "")

    datos = extraer_datos_ejecucion(session, obra_id)
    supervisores = datos.get("lSupervisor", [])
    residentes   = datos.get("lResidente", [])
    avances      = datos.get("lAvances", [])

    candidatos = supervisores if cargo in ("supervisor", "inspector") else residentes
    mejor_score, mejor_match, periodo_valido = 0.0, None, False

    for persona in candidatos:
        nombre_inf = f"{persona.get('NombreRep','')} {persona.get('ApellidoPaterno','')} {persona.get('ApellidoMaterno','')}"
        score = _fuzzy_nombre(nombre_profesional, nombre_inf)
        if score > mejor_score:
            mejor_score = score
            mejor_match = nombre_inf.strip()
            if score > 0.75:
                f_ini = _parsear_fecha(persona.get("FechaInicio", ""))
                f_fin = _parsear_fecha(persona.get("FechaFin", "")) or fecha_fin_cert
                periodo_valido = _periodos_solapan(fecha_inicio_cert, fecha_fin_cert, f_ini, f_fin)

    alertas = []
    if mejor_score < 0.75:
        alertas.append(f"Nombre '{nombre_profesional}' no coincide con ningún {cargo} en InfoObras (score: {mejor_score:.2f})")
    elif not periodo_valido:
        alertas.append(f"'{nombre_profesional}' aparece como {cargo} pero en periodo diferente al del certificado")

    paralizaciones_en_periodo = []
    dias_paralizado = 0

    for avance in avances:
        if avance.get("Estado") != "Paralizado":
            continue
        mes_num = MES_NUM.get(avance.get("Mes", "").upper(), 0)
        anio = int(avance.get("Anio", 0))
        if not mes_num or not anio:
            continue
        ini_mes = date(anio, mes_num, 1)
        fin_mes = date(anio, mes_num, 28)
        if _periodos_solapan(fecha_inicio_cert, fecha_fin_cert, ini_mes, fin_mes):
            paralizaciones_en_periodo.append({
                "periodo": f"{avance['Mes']} {avance['Anio']}",
                "tipo":    avance.get("TipoParalizacion"),
                "dias":    avance.get("DiasParalizado", 0),
                "causal":  avance.get("Causal"),
            })
            dias_paralizado += avance.get("DiasParalizado", 0)

    if paralizaciones_en_periodo:
        alertas.append(
            f"Obra paralizada {len(paralizaciones_en_periodo)} mes(es) durante el periodo del certificado "
            f"({dias_paralizado} días acumulados)"
        )

    return {
        "obra_encontrada":            True,
        "obra_id":                    obra_id,
        "estado_obra":                estado_obra,
        "nombre_coincide":            mejor_score >= 0.75,
        "score_nombre":               round(mejor_score, 3),
        "nombre_encontrado":          mejor_match,
        "periodo_valido":             periodo_valido,
        "paralizaciones":             paralizaciones_en_periodo,
        "dias_paralizado_en_periodo": dias_paralizado,
        "supervisores":               supervisores,
        "residentes":                 residentes,
        "alertas":                    alertas,
    }
```

---

*Documentado 2026-04-06 — Riesgo técnico de ambos scrapers: ELIMINADO. Pendiente: integración a `src/` de Alpamayo-InfoObras.*
