# Estado del Proyecto — Alpamayo InfoObras

> **Última actualización:** 2026-04-15
> **Repositorios:** Alpamayo-InfoObras (backend) + Panel-InfoObras (frontend)
> **Servidor:** Windows 11, NVIDIA Quadro RTX 5000 16GB, PostgreSQL via Docker

---

## 1. Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────────┐
│  PANEL (Next.js 15)         localhost:3002                  │
│  ├── Dashboard                                              │
│  ├── Nuevo Análisis (pipeline completo)                     │
│  ├── Historial (filtro tipo + estado)                       │
│  ├── Herramientas individuales:                             │
│  │   ├── /herramientas/extraccion (profesionales)           │
│  │   ├── /herramientas/tdr (requisitos)                     │
│  │   └── /herramientas/infoobras (consulta obras)           │
│  └── /jobs/[id] (detalle + WebSocket progreso)              │
│                                                             │
│  Proxy: /api/* → http://localhost:8000/api/*                │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  BACKEND (FastAPI)      localhost:8000                       │
│  ├── POST /api/jobs (extraction | tdr | full)               │
│  ├── GET  /api/jobs, /api/jobs/:id                          │
│  ├── POST /api/jobs/:id/evaluate (Paso 4 + Excel)           │
│  ├── GET  /api/jobs/:id/excel (descarga)                    │
│  ├── POST /api/infoobras/search                             │
│  ├── GET  /api/infoobras/obra/:cui                          │
│  ├── WS   /ws/jobs/:id (progreso real-time)                 │
│  ├── GET  /health, /health/{module}                         │
│  └── DELETE /api/jobs/:id (con cancelación)                 │
│                                                             │
│  ThreadPoolExecutor(max_workers=1) — GPU única              │
│  PostgreSQL: tabla jobs con JSONB                           │
└─────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
    ┌──────────┐     ┌──────────────┐     ┌──────────────┐
    │ Motor-OCR│     │ Ollama       │     │ InfoObras    │
    │ (subproc)│     │ qwen2.5:14b  │     │ Contraloría  │
    │ PaddleOCR│     │ qwen2.5vl:7b │     │ (requests)   │
    │ + Qwen VL│     │ localhost:   │     │ API pública  │
    │          │     │ 11434        │     │              │
    └──────────┘     └──────────────┘     └──────────────┘
```

---

## 2. Pipeline de los 5 Pasos

### Paso 1 — Extracción de Requisitos TDR (Bases)
**Estado: ✅ Implementado y probado**

- Entrada: PDF de bases del concurso
- Proceso: pdfplumber → fallback motor-OCR → extraer_bases() con Qwen 14B
- Salida: `rtm_personal[]`, `rtm_postor[]`, `factores_evaluacion[]`
- Archivos: `src/tdr/extractor/pipeline.py`, `scorer.py`, `llm.py`, `parser.py`
- Prompts: `src/tdr/config/signals.py` (PROMPT_RTM_PERSONAL, PROMPT_RTM_POSTOR, PROMPT_FACTORES)
- Post-procesamiento: dedup de cargos, merge con capacitación, cruce con factores

### Paso 2 — Profesionales Propuestos
**Estado: ✅ Implementado y probado**

- Entrada: PDF de propuesta técnica (escaneado, 100-400 páginas)
- Proceso: motor-OCR → segmentación por profesional → LLM extracción
- Salida: `Professional(name, role, profession, tipo_colegio, registro_colegio, folio)`
- Archivos: `src/extraction/llm_extractor.py`, `md_parser.py`, `prompts.py`
- Features: filtro de páginas irrelevantes (160+ regex), retry con fallback, detección CUI sospechoso

### Paso 3 — Base de Datos de Experiencias
**Estado: ✅ Implementado y probado**

- Entrada: texto OCR segmentado por profesional
- Proceso: LLM extrae certificados con 13 campos
- Salida: `Experience(project_name, role, company, ruc, fechas, firmante, folio, tipo_obra, tipo_intervencion, tipo_acreditacion)`
- Parseo de fechas: `_parsear_fecha()` maneja formatos españoles ("10 de enero del 2023", "01/ENE/2018", "15/03/2020")
- Fechas parseadas se guardan como `_parsed` (ISO) en el JSONB
- Sinónimos de campo: 70+ mapeos (español + inglés) para normalizar respuesta del LLM

### Paso 4 — Evaluación RTM
**Estado: ✅ Implementado y probado con datos reales**

- Entrada: Professional[] + Experience[] + RequisitoPersonal[]
- Proceso: `evaluar_propuesta()` → 22 columnas por (profesional, experiencia)
- Archivos: `src/validation/evaluator.py`, `rules.py`, `matching.py`
- 22 columnas: profesión, cargo, proyecto, tipo obra, intervención, complejidad, 20 años
- 9 alertas: ALT01-ALT09 (6 automáticas, ALT04/ALT09 manuales)
- Matching: normalización de cargos, género neutro, sinónimos sectoriales, sinónimos de cargo OSCE
- Degradación elegante: sin datos externos → "NO EVALUABLE" (sin falsos positivos)
- Test: `run_paso4_test.py` con datos reales — 12 profesionales, 41 experiencias, 11/12 con match RTM

### Paso 5 — Cálculo de Años Efectivos
**Estado: ✅ Implementado**

- `calculate_effective_days()` y `calculate_effective_years()` en `rules.py`
- Descuenta COVID (16/03/2020 – 31/12/2021)
- Descuenta paralizaciones de InfoObras
- Fusión de periodos para no descontar doble
- Integrado en la hoja Resumen del Excel (columna "Años Efectivos")

---

## 3. Scrapers

### InfoObras (Contraloría)
**Estado: ✅ Implementado completo**

- Archivo: `src/scraping/infoobras.py` (~700 líneas)
- `fetch_by_cui(cui)` → WorkInfo con datos completos (2 requests, ~5-8 seg)
- `buscar_obra_por_certificado(project_name, cert_date, entidad)` → desambiguación automática
  - Extrae keywords del nombre del proyecto
  - Múltiples queries (específica → genérica)
  - Scoring: similitud nombre (Jaccard) + proximidad fecha + entidad
  - Detección de ambigüedad (diff < 5 puntos entre candidatos)
- `buscar_obras_por_nombre(nombre)` → lista cruda para UI
- `verificar_profesional_en_obra(obra, nombre, cargo, fechas)` → VerificacionProfesional
  - Cruza nombre con supervisores/residentes (Jaccard ≥0.6)
  - Verifica solapamiento de periodos
  - Detecta paralizaciones en el periodo del certificado
- Datos extraídos: supervisores, residentes, avances mensuales, paralizaciones, contratista
- API pública, sin CAPTCHA, sin login — solo `requests`

### SUNAT
**Estado: ⏭️ Verificación manual**

- SUNAT tiene CAPTCHA — no se automatiza
- ALT04 (empresa constituida después del inicio) queda como verificación manual
- El evaluador verifica en https://e-consultaruc.sunat.gob.pe

### Colegios Profesionales (CIP, CAP, CBP, etc.)
**Estado: ⏭️ Verificación manual**

- Cada colegio tiene portal diferente
- ALT09 queda como verificación manual por el evaluador

---

## 4. Reportes

### Excel Writer
**Estado: ✅ Implementado — 5 hojas**

- Archivo: `src/reporting/excel_writer.py`
- `write_report(resultados, output_path, proposal_date, filename, infoobras_data)`
- **Hoja 1 — Resumen**: totales, tabla por profesional con semáforo (verde/rojo), años efectivos
- **Hoja 2 — Base de Datos**: 27 columnas (empresa, RUC, fechas, COVID, duración, firmante, alertas, CUI)
- **Hoja 3 — Evaluación RTM**: 22 columnas con colores verde/amarillo/rojo
- **Hoja 4 — Alertas**: todas las alertas con código, severidad, descripción
- **Hoja 5 — Verificación InfoObras**: obras consultadas, supervisores, paralizaciones
- Estilos: header azul oscuro, bordes, auto-width, wrap text

---

## 5. Panel Web (Frontend)

### Stack
- Next.js 15 (App Router) + React 19 + TypeScript
- Tailwind CSS 3 + Material Design 3 (colores custom)
- Material Symbols Outlined (iconos)
- Sin state management externo (useState/useEffect)
- Proxy: Next.js rewrites `/api/*` → `http://localhost:8000/api/*`

### Páginas

| Ruta | Descripción |
|------|-------------|
| `/` | Dashboard — métricas, últimos análisis, accesos rápidos |
| `/nuevo-analisis` | Pipeline completo — 2 dropzones (propuesta + bases), opciones avanzadas |
| `/historial` | Lista de jobs — filtro por tipo + estado, columna profesionales, ConfirmModal para eliminar |
| `/herramientas/extraccion` | Upload propuesta → OCR + extracción profesionales |
| `/herramientas/tdr` | Upload bases → extracción requisitos RTM |
| `/herramientas/infoobras` | Búsqueda de obras → candidatos con score → detalle completo |
| `/jobs/[id]` | Detalle job — progreso (WebSocket + polling fallback), tabs condicionales por tipo |

### Componentes compartidos
- `PanelShell` — layout con sidebar + topnav
- `Sidebar` — NAV_MAIN + NAV_TOOLS + mobile bottom nav
- `PdfDropzone` — drag & drop PDF con feedback visual
- `ConfirmModal` — modal de confirmación reutilizable (variante danger/default)
- `TopNav` — header con título, notificaciones, avatar

### Tipos principales (types.ts)
- `JobType`: "extraction" | "tdr" | "full"
- `Job`, `JobDetail`: con `job_type`, `started_at`, `profesionales_count`
- `ExtractionResult`, `TdrResult`: resultados tipados por tipo de job
- `RequisitoPersonal`, `FactorEvaluacion`: modelos TDR

---

## 6. API Backend

### Tipos de Job

| job_type | Entrada | Proceso | Salida |
|----------|---------|---------|--------|
| `extraction` | PDF propuesta | OCR + Pasos 2-3 | Profesionales + experiencias |
| `tdr` | PDF bases | pdfplumber/OCR + Paso 1 | RTM + factores |
| `full` | PDF propuesta + PDF bases | OCR + Pasos 1-4 + Excel | Todo + Excel descargable |

### Endpoints de evaluación
- `POST /api/jobs/{id}/evaluate` — cruza extracción con TDR, genera Excel
- `GET /api/jobs/{id}/excel` — descarga Excel generado

### Endpoints InfoObras
- `POST /api/infoobras/search` — busca obras por nombre con scores
- `GET /api/infoobras/obra/{cui}` — datos completos de una obra

### WebSocket
- `ws://host:8000/ws/jobs/{id}` — envía progreso cada 2s, se cierra al terminar

### Cancelación de jobs
- DELETE marca el job en `_cancelled_jobs` set
- Los runners verifican con `_check_cancelled()` al inicio y entre fases

---

## 7. Infraestructura

### Servicios (Docker Compose)
- PostgreSQL 16-alpine en puerto 5432
- pgAdmin 4 en puerto 5050
- Backend y frontend corren directamente (no en Docker)

### Configuración (.env)
- `DATABASE_URL` — PostgreSQL connection string
- `MOTOR_OCR_PYTHON` / `MOTOR_OCR_WRAPPER` — rutas al motor-OCR
- `OLLAMA_BASE_URL` — URL de Ollama (default localhost:11434)
- `QWEN_MODEL` / `QWEN_VL_MODEL` — modelos LLM
- `CORS_ORIGINS` — orígenes permitidos para el panel
- `UPLOADS_DIR` / `OUTPUT_DIR` — directorios de trabajo

### Despliegue LAN
- Backend: `uvicorn src.api.main:app --host 0.0.0.0 --port 8000`
- Frontend: `npm run dev` (ya usa `--hostname 0.0.0.0 --port 3002`)
- Firewall: puertos 3002 y 8000 abiertos
- Acceso: `http://<IP_SERVIDOR>:3002`

---

## 8. Modelos de Datos

### Experience (Paso 3)
```
professional_name, dni, project_name, role, company, ruc,
start_date, end_date, cert_issue_date, folio, cui, infoobras_code,
signer, raw_text, source_file,
tipo_obra, tipo_intervencion, tipo_acreditacion
```

### RequisitoPersonal (Paso 1 → wrapper tipado)
```
cargo, profesiones_aceptadas, anos_colegiado,
experiencia_minima {cantidad, unidad, descripcion, cargos_similares_validos},
tipo_obra_valido, tiempo_adicional_factores, capacitacion
```

### EvaluacionRTM (Paso 4 — 22 columnas)
```
cargo_postulado, nombre, profesion_propuesta/requerida, cumple_profesion,
folio, cargo_experiencia, cargos_validos, cumple_cargo,
proyecto_propuesto/valido, cumple_proyecto,
fecha_termino, alerta_fecha_termino,
tipo_obra cert/req, cumple_tipo_obra,
intervencion cert/req, cumple_intervencion,
acredita_complejidad, dentro_20_anos,
alertas[], experiencia_ref
```

### WorkInfo (InfoObras)
```
cui, obra_id, nombre, estado, tipo_obra, entidad, ejecutor,
fecha_inicio, fecha_fin, plazo_dias,
supervisores[], residentes[], avances[], suspension_periods[]
```

---

## 9. Sistema de Alertas

| Código | Descripción | Severidad | Automática |
|--------|-------------|-----------|-----------|
| ALT01 | Fecha fin posterior a fecha emisión certificado | WARNING | ✅ |
| ALT02 | Periodo incluye COVID (16/03/2020–31/12/2021) | WARNING | ✅ |
| ALT03 | Experiencia con más de 20 años de antigüedad | WARNING | ✅ |
| ALT04 | Empresa constituida después del inicio experiencia | CRITICAL | ⏭️ Manual (SUNAT) |
| ALT05 | Sin fecha de término ("a la fecha") | CRITICAL | ✅ |
| ALT06 | Cargo no válido según bases | CRITICAL | ✅ |
| ALT07 | Profesión no coincide con requerida | CRITICAL | ✅ |
| ALT08 | Tipo de obra no coincide | CRITICAL | ✅ |
| ALT09 | Colegiatura no vigente | WARNING | ⏭️ Manual (CIP/CAP/etc.) |

---

## 10. Pendientes

### Funcionalidad — InfoObras

| # | Pendiente | Fuente | Impacto | Esfuerzo |
|---|-----------|--------|---------|----------|
| 1 | **RF-06: Descarga documentos InfoObras + ZIP** — actas de entrega, valorizaciones mensuales, informes CGR. Estructura de carpetas definida en `docs/transcrip/resumen_producto.md` | RF-06 | Alto | Medio |
| 2 | **RF-07: Verificar nombre del profesional en valorizaciones** — descargar .doc de valorizaciones del periodo del certificado y extraer nombre del responsable. Comparar con nombre declarado. | RF-07 | Alto | Alto |
| 3 | **ALT10: Persona diferente en cargo** — cuando `verificar_profesional_en_obra()` detecta que el nombre no coincide con los supervisores/residentes de InfoObras, generar alerta formal en rules.py | analisis.md | Medio | Bajo |
| 4 | **Informes de Control CGR** — endpoint de InfoObras no explorado. Contiene periodos de suspensión oficiales, fechas de reactivación COVID con fuente documental. | RF-06, validacion_sugerida.md | Medio | Medio |
| 5 | **Datos entrega de terreno** — `lEntregaTerreno` disponible en el scraper pero no se extrae ni se incluye en el Excel | validacion_infoobras.md | Bajo | Bajo |

#### Estructura ZIP definida (RF-06)
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

### Funcionalidad — Evaluación

| # | Pendiente | Impacto | Esfuerzo |
|---|-----------|---------|----------|
| 6 | **Regla "a la fecha"** — cuando end_date=None y cert_issue_date existe, usar cert_issue_date como fecha fin efectiva (actualmente solo marca ALT05 pero no ajusta el cómputo) | Medio | Bajo |
| 7 | **ALT10 — días declarados vs calculados** — comparar duración declarada en certificado con cálculo propio del sistema | Bajo | Bajo |

### Precisión

| # | Pendiente | Impacto |
|---|-----------|---------|
| 8 | Sinónimos de cargo — algunos no matchean (Electromecánico, NNNN del OCR) | Iterativo |
| 9 | Re-correr TDR con prompt mejorado de tipo_obra_valido para verificar mejora | Puntual |
| 10 | Cargo del firmante no se extrae del certificado (col 19 del Excel vacía) | Bajo |

### Deuda técnica

| # | Pendiente | Impacto |
|---|-----------|---------|
| 11 | **Tests unitarios** — 0 tests en el proyecto | Alto |
| 12 | Organizar docs .md (propuesta de estructura existe, no ejecutada) | Bajo |
| 13 | Commits pendientes en ambos repos | Inmediato |

### Descartado

- ~~RF-08 (CIP/CAP/CBP)~~ — cada colegio tiene portal diferente, verificación manual
- ~~RF-09 (SUNAT)~~ — tiene CAPTCHA, verificación manual
- ~~RF-10 (Chat IA)~~ — no priorizado por el cliente
- ~~RF-11 (Oferta económica)~~ — prioridad baja, no solicitado aún
- ~~Celery/Redis~~ — ThreadPoolExecutor funciona bien para 1 worker
- ~~LangChain/ChromaDB~~ — no se necesita
- ~~Playwright~~ — requests funciona para InfoObras

---

## 11. Archivos Clave

### Backend (Alpamayo-InfoObras/src/)
```
api/main.py                    — FastAPI, jobs, endpoints, WebSocket (~1200 líneas)
extraction/models.py           — dataclasses: Professional, Experience, EvaluacionRTM, etc.
extraction/llm_extractor.py    — orquesta LLM Pasos 2-3 (~600 líneas)
extraction/md_parser.py        — parsea archivos .md del motor-OCR
extraction/prompts.py          — PASO2_PROMPT, PASO3_PROMPT
extraction/ollama_client.py    — wrapper HTTP para Ollama
tdr/extractor/pipeline.py      — pipeline TDR Paso 1 (~1000 líneas)
tdr/config/signals.py          — prompts TDR + señales scorer
validation/evaluator.py        — evaluación RTM Paso 4 (~350 líneas)
validation/rules.py            — 9 alertas + cálculo días efectivos (~325 líneas)
validation/matching.py         — normalización + sinónimos (~450 líneas)
scraping/infoobras.py          — scraper InfoObras completo (~700 líneas)
reporting/excel_writer.py      — Excel 5 hojas (~350 líneas)
```

### Frontend (Panel-InfoObras/frontend/src/)
```
app/page.tsx                           — Dashboard
app/nuevo-analisis/page.tsx            — Pipeline completo
app/historial/page.tsx                 — Historial con filtros
app/herramientas/extraccion/page.tsx   — Herramienta profesionales
app/herramientas/tdr/page.tsx          — Herramienta TDR
app/herramientas/infoobras/page.tsx    — Consulta InfoObras
app/jobs/[id]/page.tsx                 — Detalle job (~800 líneas)
components/Sidebar.tsx                 — Navegación
components/PdfDropzone.tsx             — Upload PDF
components/ConfirmModal.tsx            — Modal confirmación
components/PanelShell.tsx              — Layout
components/TopNav.tsx                  — Header
lib/types.ts                           — Tipos TypeScript
lib/helpers.ts                         — Utilidades UI
```

### Configuración
```
.env.example         — todas las variables documentadas
docker-compose.yml   — PostgreSQL + pgAdmin
requirements.txt     — dependencias Python
CLAUDE.md            — guía del proyecto para Claude
```

### Scripts de prueba
```
run_extraction.py    — CLI para Pasos 2-3
run_tdr.py           — CLI para Paso 1
run_paso4_test.py    — test Paso 4 con datos reales + genera Excel
```
