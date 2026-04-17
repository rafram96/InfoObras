# Scraper InfoObras — Estado y Siguiente Fase

> **Última actualización:** 2026-04-15
> **Archivo:** `src/scraping/infoobras.py` (~1000 líneas)
> **PoC original:** `variety/infoobras/buscar.py` + `variety/infoobras/SCRAPER.md`

---

## 1. Lo que está implementado y funciona

### Búsqueda y resolución de obras

| Función | Qué hace | Probado |
|---------|----------|---------|
| `fetch_by_cui(cui)` | Busca por CUI → WorkInfo completo (2 requests, ~5-8s) | ✅ CUI 2157301, 2186942 |
| `buscar_obra_por_certificado(project_name, cert_date, entidad)` | Busca por nombre con desambiguación automática (keywords → score → selección) | ✅ Hospital Pomabamba, Hospital Ayacucho |
| `buscar_obras_por_nombre(nombre)` | Búsqueda cruda para UI de confirmación manual | ✅ |
| `verificar_profesional_en_obra(obra, nombre, cargo, fechas)` | Cruza nombre del profesional con supervisores/residentes + detecta paralizaciones en periodo | ✅ Lógica completa, no probado con datos de supervisores reales |

### Datos que se extraen

| Variable JS | Modelo | Campos extraídos |
|-------------|--------|-----------------|
| `lAvances` | `AvanceMensual` | anio, mes, estado, tipo_paralizacion, fecha_paralizacion, dias_paralizado, causal |
| `lSupervisor` | `SupervisorInfo` | nombre, apellidos, tipo (Inspector/Supervisor), empresa, RUC, DNI, fechas |
| `lResidente` | `ResidenteInfo` | nombre, apellidos, fechas |
| Endpoint [1] búsqueda | `WorkInfo.raw_busqueda` | nombresSupervisor, nombresResidente (actuales), montos, fechas, tipo obra, entidad |

### Desambiguación

Scoring con 3 criterios ponderados:
- **50%** — Similitud de nombre (Jaccard sobre tokens normalizados)
- **30%** — Proximidad de fecha_inicio a cert_date (más cercana y anterior = mejor)
- **20%** — Coincidencia de entidad

Extracción de keywords: quita stopwords genéricas ("MEJORAMIENTO", "SERVICIOS", "SALUD"), mantiene topónimos y marcadores de tipo ("HOSPITAL", "POMABAMBA").

Threshold: score ≥ 15.0 para auto-selección, log de ambigüedad si diff < 5.0 entre top 2.

### Periodos de suspensión

`_extraer_periodos_suspension()` agrupa meses consecutivos con estado "Paralizado"/"Suspendido" en un solo periodo `(date, date)`. Usa `fecha_paralizacion` exacta si existe, sino aproxima al inicio del mes.

### API endpoints

| Endpoint | Método | Qué hace |
|----------|--------|----------|
| `/api/infoobras/search` | POST | Busca obras por nombre, retorna candidatos con scores |
| `/api/infoobras/obra/{cui}` | GET | Datos completos de una obra por CUI |

### Página en el Panel

`/herramientas/infoobras` — búsqueda por nombre + fecha + entidad, tabla de candidatos con scores, vista detalle con supervisores, residentes y paralizaciones.

---

## 2. Endpoints de InfoObras usados

```
[1] POST /infobrasweb/Mapa/busqueda/obrasBasic
    → JSON con lista de obras (codigoObra, nombrObra, estObra, fechas, supervisor actual, etc.)
    → Parámetro clave: codSnip=CUI o nombrObra=nombre

[5] GET /InfobrasWeb/Mapa/DatosEjecucion?ObraId={id}
    → HTML con variables JS embebidas:
       var lAvances = [...];
       var lSupervisor = [...];
       var lResidente = [...];
       var lContratista = [...];
       var lModificacionPlazo = [...];
       var lAdicionalDeduc = [...];
       var lEntregaTerreno = [...];
       var lAdelanto = [...];
       var lCronograma = [...];
       var lTransferenciaFinanciera = [...];
```

---

## 3. Lo que NO está implementado

### 3.1 Descarga de documentos (RF-06)

Cada avance mensual (`lAvances`) tiene documentos adjuntos:

```json
{
  "lImgValorizacion": [
    {
      "Codigo": 3140957,
      "EsFisico": 0,
      "UrlImg": "a137035b4d5f495caf449c47bfe9791e",
      "nombreArchivo": "CamScanner 04-10-2023 12.33.pdf",
      "Extension": "pdf"
    }
  ],
  "lImgFisico": [
    {
      "Codigo": 3140953,
      "EsFisico": 1,
      "UrlImg": "00631412cce24b9eaac4f441a624c821",
      "nombreArchivo": "WhatsApp Image 2023-04-10.jpeg",
      "Extension": "jpeg"
    }
  ]
}
```

**Lo que no sabemos:**
- ¿Cómo se construye la URL de descarga? `UrlImg` es un UUID, no una URL completa.
- Probable patrón: `https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/DescargarArchivo?codigo={Codigo}` o similar con el UUID.
- **Hay que probar en vivo** con un request al servidor.

**Estructura ZIP objetivo** (definida en `docs/transcrip/resumen_producto.md`):
```
/{nombre_proyecto}_{codigo_infoobras}/
├── 01_acta_entrega_terreno.pdf
├── 02_valorizacion_marzo_2021.pdf
├── 03_valorizacion_abril_2021.pdf
├── ...
└── informes_control/
    ├── informe_001.pdf
    └── informe_002.pdf
```

### 3.2 Informes de Control de la CGR

Sección separada en InfoObras. No explorada.

**Posibles ubicaciones:**
- Variable JS `lInformeControl` dentro de DatosEjecucion (no confirmado)
- Endpoint separado: `/InfobrasWeb/Mapa/InformeControl?ObraId={id}` (no confirmado)
- Tab "Informes de Control" en la ficha pública de la obra

**Qué contienen:**
- Número de informe
- Periodos de suspensión oficiales
- Fechas de reactivación COVID
- Fuente documental descargable

### 3.3 Entrega de terreno

`lEntregaTerreno` ya viene en DatosEjecucion pero no se procesa.

Estructura esperada (del PoC SCRAPER.md §7.7):
```json
{
  "FechaEntrega": "23/11/2019",
  "Porcentaje": 100,
  "UrlRegistro": "acta_entrega.pdf"
}
```

### 3.4 Verificación de nombre en valorizaciones (RF-07)

Las valorizaciones son `.doc` o `.pdf` descargables de `lImgValorizacion`.

**El flujo sería:**
1. Para cada mes del periodo del certificado → buscar el avance de ese mes
2. Descargar la valorización (`lImgValorizacion[0]`)
3. Extraer texto (pdfplumber si es PDF, python-docx si es .doc)
4. Buscar el nombre del supervisor/residente en el texto
5. Comparar con el nombre del certificado (Jaccard)
6. Si no coincide → ALT10 "persona diferente en cargo"

**Complejidad:** Alta — requiere descargar y parsear documentos externos.

### 3.5 ALT10: Persona diferente en cargo

`verificar_profesional_en_obra()` ya detecta cuando el nombre no matchea con supervisores/residentes de InfoObras. Falta:
1. Agregar `ALT10` al enum `AlertCode` en `rules.py`
2. Generar la alerta formal cuando `score_nombre < 0.6`
3. Incluirla en el Excel (hoja de Alertas)

---

## 4. Observaciones del scraping real

### Obras finalizadas
- `lSupervisor` y `lResidente` vienen **vacíos** en obras finalizadas
- Los supervisores/residentes de obras finalizadas solo están en el endpoint de búsqueda `[1]` como `nombresSupervisor`/`nombresResidente` (solo el último, no histórico)
- **Implicación:** Para obras finalizadas, la verificación de nombre solo funciona contra el supervisor/residente actual, no contra el histórico

### Rate limiting
- Delay actual: 2.0 segundos entre requests
- InfoObras no parece tener throttling agresivo pero es mejor ser conservador
- Para descarga masiva de documentos, considerar 3-4 segundos entre descargas

### Encoding
- Las respuestas HTML usan encoding Windows-1252 en algunos casos
- El parser de variables JS con `json.loads()` funciona bien porque los arrays están en UTF-8 dentro del HTML

---

## 5. Variables JS disponibles en DatosEjecucion (referencia completa)

| Variable | Registros típicos | Procesada | Descripción |
|----------|-------------------|-----------|-------------|
| `lAvances` | 20-40 | ✅ | Avances mensuales con estado, paralizaciones, documentos |
| `lSupervisor` | 0-5 | ✅ | Histórico de supervisores/inspectores |
| `lResidente` | 0-5 | ✅ | Histórico de residentes |
| `lContratista` | 1-3 | ❌ No procesada | Contratista ejecutor (RUC, nombre empresa, contrato) |
| `lModificacionPlazo` | 0-10 | ❌ No procesada | Ampliaciones y suspensiones de plazo con resoluciones |
| `lAdicionalDeduc` | 0-5 | ❌ No procesada | Adicionales y deductivos de obra |
| `lEntregaTerreno` | 0-2 | ❌ No procesada | Fecha y acta de entrega de terreno |
| `lAdelanto` | 0-2 | ❌ No procesada | Adelantos entregados |
| `lCronograma` | 0-5 | ❌ No procesada | Cronogramas actualizados |
| `lTransferenciaFinanciera` | 0-3 | ❌ No procesada | Entidad origen de fondos |
| `lControversia` | 0 (raro) | ❌ No procesada | Arbitrajes y controversias |
| `lAdenda` | 0 (raro) | ❌ No procesada | Adendas al contrato |

### De las no procesadas, las útiles son:

- **`lContratista`** — tiene el RUC del ejecutor para consulta cruzada
- **`lModificacionPlazo`** — tiene resoluciones de suspensión con fechas exactas y documentos descargables (más preciso que inferir de `lAvances`)
- **`lEntregaTerreno`** — fecha inicio real + acta

---

## 6. Pasos para continuar el desarrollo

### Paso 1: Explorar URLs de descarga (30 min)
```python
# Correr en el servidor con una obra que tenga documentos
from src.scraping.infoobras import _crear_session, _extraer_datos_ejecucion
s = _crear_session()
datos = _extraer_datos_ejecucion(s, 87978)  # Hospital Pomabamba

# Ver documentos disponibles
for av in datos.get('lAvances', [])[:3]:
    for doc in av.get('lImgValorizacion', []):
        print(f"Codigo={doc['Codigo']} UUID={doc['UrlImg']} Nombre={doc['nombreArchivo']}")

# Intentar descargar uno
# Probar: GET /InfobrasWeb/Mapa/DescargarArchivo?codigo={Codigo}
# O: GET con el UUID como path
import requests
r = s.get(f"https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/DescargarArchivo?codigo={doc['Codigo']}")
print(f"Status: {r.status_code}, Content-Type: {r.headers.get('Content-Type')}, Size: {len(r.content)}")
```

### Paso 2: Explorar Informes de Control (30 min)
```python
# Ver si hay una variable JS para informes
import re
r = s.get("https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/DatosEjecucion", params={"ObraId": 87978})
# Buscar cualquier variable que no hayamos visto
for m in re.finditer(r'var\s+(\w+)\s*=', r.text):
    print(m.group(1))

# También probar el tab de Informes de Control
r2 = s.get("https://infobras.contraloria.gob.pe/InfobrasWeb/Mapa/InformeControl", params={"ObraId": 87978})
print(f"InformeControl: status={r2.status_code}, size={len(r2.text)}")
```

### Paso 3: Procesar lEntregaTerreno (15 min)
Ya viene en los datos — solo agregar al modelo `WorkInfo` y al procesamiento.

### Paso 4: Implementar descarga + ZIP (2-4 horas)
Una vez que se conozca el patrón de URL:
1. Función `descargar_documentos_obra(obra: WorkInfo, output_dir: Path)`
2. Crear estructura de carpetas según RF-06
3. Descargar valorizaciones del periodo del certificado
4. Descargar acta de entrega si existe
5. Zipear todo

### Paso 5: Extraer nombre de valorizaciones (2-4 horas)
1. Descargar .doc/.pdf de valorización
2. Extraer texto (pdfplumber o python-docx)
3. Buscar nombre del supervisor/residente
4. Comparar con Jaccard contra nombre del certificado
5. Agregar ALT10 si no coincide

### Paso 6: Procesar lModificacionPlazo (1 hora)
Más preciso que inferir suspensiones de lAvances — tiene fechas exactas de inicio/fin de suspensión con resoluciones oficiales.

---

## 7. Archivos relacionados

| Archivo | Qué contiene |
|---------|-------------|
| `src/scraping/infoobras.py` | Implementación actual (~1000 líneas) |
| `variety/infoobras/buscar.py` | PoC original (referencia) |
| `variety/infoobras/SCRAPER.md` | Documentación completa del PoC con estructuras JSON de todos los endpoints |
| `docs/transcrip/2026-03-06_resumen_producto.md` | Estructura ZIP definida por el cliente (sección 5) |
| `docs/analisis/validacion_sugerida.md` | Pipeline completo de verificación (Etapas 3-6) |
| `docs/analisis/extras/validacion_infoobras.md` | Proceso manual del cliente en InfoObras |
| `docs/arquitectura/plan_verificacion.md` | Plan de verificación con 6 fases |
