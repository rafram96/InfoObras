# Tracing y lineage documental — diseño

Documento de planeamiento. No implementado. Listo para priorizar cuando se decida.

## Por qué importa

Este sistema toma decisiones automáticas sobre licitaciones públicas. Para cada alerta o evaluación generada el cliente debe poder responder:

- ¿Por qué el sistema dijo esto?
- ¿De qué parte del PDF salió?
- ¿Qué regla se activó?
- ¿Qué confidence tenía?
- ¿Con qué versión del pipeline se procesó?

Hoy se responde mirando logs y dumps en disco. No queda en la BD ni se ve en la UI.

## Lo que ya existe (no reinventar)

Tracing operacional implementado:

| Pieza | Ubicación | Para qué sirve |
|---|---|---|
| Logs por fase | `src/api/job_logs.py` | `01_ocr.log`, `02_extraction.log`, `03_tdr.log`, `04_sunat.log`, `06_evaluation.log`, `motor_ocr.log` por job |
| Dumps de LLM | `data/llm_calls/{job_id}/*.json` | Prompt + raw_response + usage por cada llamada a Qwen 14B |
| Bundle ZIP | `bundle_job_logs()` | Descarga todo el contexto de un job (logs + result.json + llm_calls) |
| Re-run | `POST /api/jobs/:id/rerun` + `source_job_id` | Replay del mismo PDF con pipeline actual |
| Estado del job | tabla `jobs` (PostgreSQL) | id, status, result JSONB, error, progress |
| Alertas | `Alert(code, severity, description, experience)` en `validation/rules.py` | Estructura básica, sin ancla al texto fuente |

Eso cubre el plano **"¿qué pasó técnicamente en este job?"**. Suficiente para debug del backend.

## Brecha — lo que falta para auditoría documental

| Hueco | Impacto |
|---|---|
| `Experience` no guarda `source_page` / `source_md_file` / `source_text_snippet` | Imposible decirle al evaluador de dónde salió un dato extraído |
| `Alert` no guarda evidencia (texto fuente, página, regla con reasoning) | El cliente ve la alerta pero no el texto que la disparó |
| No hay `pipeline_version` por job | Si cambia un prompt o una regla, los jobs viejos no son comparables |
| No hay tablas relacionales | Imposible queries cruzadas: "todas las ALT06 de los últimos 30 jobs y su texto fuente" |
| Sin bbox en `.md` del motor-OCR | No se puede resaltar la zona del PDF original en la UI |

## Diseño por niveles

Tres incrementos, de menor a mayor compromiso. Cada uno entrega valor por sí solo.

---

### Nivel 1 — Anclas de evidencia

**Esfuerzo: 1-2 días. Sin tablas nuevas. Cambios al modelo Python + JSONB existente.**

Objetivo: cada alerta y cada experiencia llevan referencia al texto fuente.

**Cambios:**

```python
# src/extraction/models.py
@dataclass
class SourceRef:
    md_file: str          # "Lircay_profesionales_20260420_180022.md"
    page_start: int       # 17
    page_end: int         # 17 (igual si es una sola página)
    snippet: str          # primeros ~200 chars del bloque origen
    # bbox: opcional para Nivel 4 (motor-OCR)

@dataclass
class Experience:
    # ... campos existentes ...
    source: Optional[SourceRef] = None    # NUEVO

@dataclass
class Alert:
    # ... campos existentes ...
    evidence_snippet: Optional[str] = None     # NUEVO
    evidence_page: Optional[int] = None        # NUEVO
    rule_reasoning: Optional[str] = None       # NUEVO — por qué disparó
```

**Donde se popula:**

1. `extraction/llm_extractor.py` al producir `Experience` ya sabe qué bloque del `.md` lo originó (lo tiene en `ProfessionalBlock`) → puede llenar `source`.
2. `validation/rules.py::check_alerts()` ya recibe `Experience` → propaga `exp.source.page_start` a `Alert.evidence_page` y un snippet recortado a `Alert.evidence_snippet`.
3. Para `ALT04` (SUNAT) y `ALT08` (tipo de obra) → `rule_reasoning` describe la comparación que falló.

**Cambios en frontend (Panel-InfoObras):**

- Vista de alerta: bloque "Texto original (pág. 17): _'...plazo de ejecución 120 días...'_"
- Para Nivel 1 no hay resaltado sobre el PDF — solo página + snippet.

**Persistencia:** todo sigue dentro del `result JSONB` actual. No se rompe nada.

**Valor inmediato:** cuando el cliente pregunte "¿de dónde sale esto?" lo ve en pantalla.

---

### Nivel 2 — Persistencia relacional

**Esfuerzo: 3-5 días. Tablas nuevas en PostgreSQL. No reemplaza el JSONB, lo complementa.**

Objetivo: poder hacer queries cruzadas y métricas reales sin escanear blobs.

**Esquema propuesto:**

```sql
CREATE TABLE analyses (
    id              UUID PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    pipeline_version TEXT NOT NULL,        -- "v0.4-20260516"
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT NOT NULL,
    total_pages     INTEGER,
    processing_ms   INTEGER
);

CREATE TABLE entities (
    id              UUID PRIMARY KEY,
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,         -- 'profesional', 'experience', 'rtm_requisito'
    payload         JSONB NOT NULL,        -- el objeto serializado
    confidence      REAL,
    source_md       TEXT,
    source_page     INTEGER,
    source_snippet  TEXT
);

CREATE TABLE rule_executions (
    id              UUID PRIMARY KEY,
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    rule_code       TEXT NOT NULL,         -- 'ALT06'
    result          BOOLEAN NOT NULL,
    severity        TEXT,
    reasoning       TEXT,
    input_entities  UUID[],                -- IDs de las entidades evaluadas
    executed_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE alerts (
    id              UUID PRIMARY KEY,
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    rule_execution_id UUID REFERENCES rule_executions(id),
    code            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    description     TEXT NOT NULL,
    evidence_page   INTEGER,
    evidence_snippet TEXT,
    confidence      REAL
);

CREATE INDEX idx_analyses_job ON analyses(job_id);
CREATE INDEX idx_alerts_code ON alerts(code);
CREATE INDEX idx_entities_type ON entities(type);
```

**Migración:** al cerrar un job se llaman a estas tablas **además** del `result` JSONB existente. El JSONB queda como cache del payload completo; las tablas son la fuente queryable.

**Endpoints nuevos:**

- `GET /api/analyses/{id}/lineage/alert/{alert_id}` → devuelve `alert + rule_execution + input_entities + source` en un solo JSON
- `GET /api/metrics/rules` → conteo de cada regla disparada en los últimos N jobs
- `GET /api/metrics/extraction-quality` → confidence promedio por tipo de entidad

**Valor:** dashboards de calidad, regression testing (re-correr 20 jobs viejos con pipeline nuevo y comparar diffs), exportar dataset para mejorar prompts.

---

### Nivel 3 — Event sourcing ligero

**Esfuerzo: 2-3 días sobre Nivel 2. Una sola tabla más.**

Objetivo: reconstruir cualquier análisis paso a paso. Útil para A/B testing de prompts y respuestas históricas tipo "¿por qué hace 3 meses esta alerta no salía?".

```sql
CREATE TABLE pipeline_events (
    id              BIGSERIAL PRIMARY KEY,
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    ts              TIMESTAMPTZ DEFAULT NOW(),
    event_type      TEXT NOT NULL,         -- 'OCR_PAGE_DONE', 'ENTITY_EXTRACTED', 'RULE_TRIGGERED', 'ALERT_GENERATED'
    payload         JSONB NOT NULL
);

CREATE INDEX idx_events_analysis ON pipeline_events(analysis_id, ts);
CREATE INDEX idx_events_type ON pipeline_events(event_type);
```

Solo escribir, nunca actualizar. Es un append-only log de lo que pasó.

**Cuándo activarlo:** no hoy. Cuando empieces a iterar sobre prompts/reglas y necesites comparar comportamiento histórico.

---

### Nivel 4 (extensión) — bbox para overlay visual

**Esfuerzo: 1-2 días en motor-OCR + 1 día en frontend. Requiere cambio aditivo coordinado.**

**Hallazgo:** el `.md` que produce motor-OCR hoy es **page-level** (`## Página N`). No hay bbox por línea ni por bloque. PaddleOCR internamente tiene `dt_polys` pero `PageResult` (motor-OCR/src/models/page_result.py) no los conserva.

Para resaltar la zona origen sobre el PDF en la UI:

1. **En motor-OCR (aditivo, permitido):**
   - Extender `PageResult` con `blocks: List[Block]` donde cada `Block` lleva `text`, `bbox`, `confidence`.
   - Extender los writers (`segmentation/output/consolidation_writer.py` y `engines/pdfplumber/markdown_writer.py`) para emitir un `*_blocks_*.json` (o anexar bbox a `*_texto_*.md` con sintaxis nueva, p.ej. `<!-- bbox: x1,y1,x2,y2 -->`).
   - Es change de contrato: hay que sincronizar con `Alpamayo/src/extraction/md_parser.py`.

2. **En Alpamayo:**
   - `md_parser.py` lee bbox y lo propaga a `ProfessionalBlock`.
   - `Experience.source.bbox` se llena.

3. **En frontend:**
   - Visor PDF (pdfjs) con overlay del rectángulo cuando se hace click en la alerta.

**Por qué dejarlo para después:** rompe el contrato motor-OCR ↔ Alpamayo (CLAUDE.md lo lista como "no romper sin sincronizar"). El valor incremental sobre Nivel 1 (página + snippet) es modesto para auditoría — el evaluador puede abrir la página en cualquier visor.

## Comparativa de niveles

| Nivel | Esfuerzo | Tablas BD | Toca motor-OCR | Beneficio principal |
|---|---|---|---|---|
| 1 | 1-2 días | 0 | No | Cada alerta muestra texto fuente y página |
| 2 | 3-5 días | 5 | No | Queries cruzadas, dashboards, métricas |
| 3 | +2-3 días | 1 más | No | Reconstrucción histórica paso a paso |
| 4 | +2-3 días | 0 | Sí (aditivo) | Overlay visual sobre el PDF |

## Decisiones pendientes

1. **¿Persistir las entidades del Paso 1 (TDR) también?** Sí, recomendado — son inputs de las reglas y deben quedar trazables.
2. **¿Cómo versionar el pipeline?** Propuesta: variable `PIPELINE_VERSION` en `.env`, se incrementa manualmente cuando cambian prompts o reglas. Se loguea en cada `analyses.pipeline_version`.
3. **¿Confidence en las reglas determinísticas?** No aplica (cumple/no cumple es binario). Sí aplica en extracción LLM (token logprob no se obtiene de Ollama; alternativa: heurística por completitud del campo).
4. **¿Migración de jobs viejos?** Opcional. Los `result JSONB` existentes pueden quedar como están; solo los jobs nuevos pueblan las tablas. Si se quiere backfill, hay un script único que parsea JSONB → tablas.
5. **¿Bbox ahora o nunca?** Recomendado **nunca** hasta que el cliente lo pida explícitamente. Página + snippet cubre el 90% del caso de uso.

## Lo que NO se va a hacer

- OpenTelemetry / Jaeger / Zipkin: este no es un sistema distribuido.
- Eventos en Kafka o cola externa: PostgreSQL + tabla append-only basta para el volumen esperado.
- Tracing distribuido entre motor-OCR y Alpamayo: el subprocess wrapper ya devuelve todo lo necesario en su JSON de respuesta.

## Próximo paso

Cuando se priorice esta línea: empezar por **Nivel 1**. Es la mejora con mejor ratio valor/esfuerzo y no compromete decisiones de los niveles siguientes.
