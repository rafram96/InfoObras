# Módulo: InfoObras Scraper

> `src/scraping/infoobras.py` — ~1000 líneas — ✅ Completo

## Propósito
Consulta el portal de InfoObras (Contraloría General de la República) para obtener datos de obras públicas: estado, supervisores, residentes, avances, paralizaciones.

## Endpoints usados

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/infobrasweb/Mapa/busqueda/obrasBasic` | POST | Búsqueda por CUI o nombre |
| `/InfobrasWeb/Mapa/DatosEjecucion?ObraId={id}` | GET | Datos de ejecución (variables JS embebidas) |

## Dataclasses

| Clase | Campos clave |
|-------|-------------|
| `SupervisorInfo` | nombre, apellidos, tipo (Inspector/Supervisor), empresa, RUC, DNI, fechas |
| `ResidenteInfo` | nombre, apellidos, fechas |
| `AvanceMensual` | año, mes, estado, tipo_paralizacion, dias_paralizado, causal |
| `WorkInfo` | cui, obra_id, nombre, estado, supervisores[], residentes[], avances[], suspension_periods[] |
| `VerificacionProfesional` | nombre_coincide, score_nombre, periodo_valido, dias_paralizado_en_periodo, alertas[] |
| `ObraCandidata` | obra_raw, score, motivos[] |

## Funciones públicas

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `fetch_by_cui(cui)` | ~80 | Búsqueda directa por CUI → WorkInfo completo (2 requests). |
| `buscar_obras_por_nombre(nombre)` | ~50 | Búsqueda por nombre → lista de dicts crudos. |
| `buscar_obra_por_certificado(project_name, cert_date, entidad)` | ~120 | Búsqueda inteligente: extrae keywords → busca → rankea → selecciona mejor. |
| `verificar_profesional_en_obra(obra, nombre, cargo, fechas)` | ~90 | Cruza nombre con supervisores/residentes. Detecta paralizaciones en periodo. |

## Funciones internas

| Función | Descripción |
|---------|-------------|
| `_crear_session()` | Session HTTP con cookies de InfoObras |
| `_buscar_por_cui(session, cui)` | POST a obrasBasic con CUI |
| `_extraer_datos_ejecucion(session, obra_id)` | GET DatosEjecucion, extrae variables JS con regex |
| `_procesar_supervisores(raw)` | Convierte JSON a SupervisorInfo[] |
| `_procesar_residentes(raw)` | Convierte JSON a ResidenteInfo[] |
| `_procesar_avances(raw)` | Convierte JSON a AvanceMensual[] |
| `_extraer_periodos_suspension(avances)` | Agrupa meses consecutivos paralizados en periodos |
| `_extraer_palabras_clave(nombre)` | Genera múltiples queries de búsqueda (específica → genérica) |
| `_score_candidata(obra, nombre, fecha, entidad)` | Scoring: 50% nombre Jaccard + 30% fecha + 20% entidad |

## Búsqueda por certificado — flujo

```
nombre_proyecto del certificado
    │
    ▼
_extraer_palabras_clave()
    → ["HOSPITAL POMABAMBA ANTONIO", "POMABAMBA ANTONIO CALDAS", ...]
    │
    ▼  (intenta cada query hasta encontrar resultados)
buscar_obras_por_nombre(query)
    │
    ▼  (rankea candidatos)
_score_candidata() por cada resultado
    │
    ▼  (selecciona mejor si score > 15)
fetch_by_cui(cui) → WorkInfo completo
```

## Verificación de profesional — flujo

```
WorkInfo + nombre_profesional + cargo_tipo + fechas
    │
    ├─ 1. Buscar en supervisores[] o residentes[]
    │      Jaccard(nombre, "NombreRep ApellidoPaterno ApellidoMaterno")
    │      ≥ 0.6 → nombre_coincide = True
    │
    ├─ 2. Verificar en datos de búsqueda (supervisor/residente actual)
    │
    ├─ 3. Verificar solapamiento de periodos
    │
    └─ 4. Detectar paralizaciones en el periodo del certificado
           → dias_paralizado_en_periodo, alertas[]
```

## Rate limiting
- 2.0 segundos entre requests HTTP
- 1.0 segundos entre reintentos de búsqueda

## Variables JS extraídas de DatosEjecucion
`lAvances`, `lSupervisor`, `lResidente`, `lContratista`, `lModificacionPlazo`, `lAdicionalDeduc`, `lEntregaTerreno`, `lAdelanto`, `lCronograma`, `lTransferenciaFinanciera`

## Limitaciones
- Supervisores/residentes vacíos para obras finalizadas (InfoObras no los retiene)
- Supervisor actual solo viene del endpoint de búsqueda, no de DatosEjecucion
- Jaccard de nombres sensible a variaciones OCR
- Scoring de candidatos con pesos fijos (50/30/20)
- Timeout de 15-30s por request

## Pendientes
- Descarga de documentos (valorizaciones, actas) → estructura ZIP
- Informes de Control CGR (endpoint no explorado)
- Datos de entrega de terreno (`lEntregaTerreno` disponible pero no se extrae)

## Dependencias
- `requests`, `json`, `re`, `datetime`
