# Plan híbrido — InfoObras backend + Claude Cowork

Arquitectura propuesta: separar el "trabajo determinístico" (que el backend
ya hace bien) del "trabajo inteligente" (que Cowork con Claude haría mejor).

## Idea base

El backend InfoObras conserva todo lo que tiene control determinístico:
OCR, segmentación, identificación de páginas relevantes, persistencia,
scraping, motor de reglas, generación de Excel y UI.

Cowork solo recibe **PDFs ya recortados** con las páginas que importan
para una extracción específica, devuelve JSON estructurado, y el backend
sigue el flujo.

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│ InfoObras Backend (on-prem, FastAPI)                    │
│                                                          │
│  1. Recibe PDF (propuesta o bases)                      │
│  2. OCR → markdown (motor-OCR / pdfplumber)             │
│  3. Identifica páginas relevantes                       │
│  4. Recorta sub-PDFs por bloque/cargo                   │
│         │                                                │
│         │  POST /trigger/extract-{tipo}                  │
│         │  payload: {sub_pdf, job_id, block_id}         │
│         ▼                                                │
│ ╔═══════════════════════════════════════════════════════╗│
│ ║ Claude Cowork                                          ║│
│ ║                                                        ║│
│ ║  - Skill `extract-profesional`                         ║│
│ ║  - Skill `extract-tdr-cargo`                           ║│
│ ║  - Claude lee el sub-PDF, extrae JSON estructurado    ║│
│ ║  - POST callback al backend                            ║│
│ ╚═══════════════════════════════════════════════════════╝│
│         │                                                │
│         │  POST /api/webhooks/cowork-callback            │
│         │  payload: {job_id, block_id, data}            │
│         ▼                                                │
│  5. Recibe callbacks, ensambla en DB                    │
│  6. Scraping (InfoObras / SUNAT padrón / colegios)      │
│  7. Validación (motor de reglas)                        │
│  8. Excel final → UI                                    │
└─────────────────────────────────────────────────────────┘
```

## Lo que se queda en backend (no cambia)

- OCR con motor-OCR + pdfplumber fast-path
- Segmentación / detección de páginas (`md_parser.py`, `pdf_reader.py`)
- Persistencia: PostgreSQL, jobs, archivos
- Scraping de InfoObras (Contraloría)
- Padrón SUNAT mensual (cuando se implemente)
- Motor de reglas determinístico (ALT01-ALT10)
- Generación Excel (5 hojas)
- UI web (Next.js)
- Auth, jobs, re-run, debug tools — todo intacto

## Lo que se mueve a Cowork

Solo las llamadas LLM que hoy hace `qwen2.5:14b` para extracción de
estructura:

- Extracción de profesionales por bloque (Pasos 2 y 3)
- Extracción de TDR por cargo (Paso 1, B.1 y B.2)

El motor-OCR sigue usando `qwen2.5vl:7b` para tablas escaneadas (eso es
infraestructura on-prem, no cambia).

## Por qué la idea de "PDF recortado" es clave

La diferencia económica y técnica:

| Approach | Costo | Latencia | Calidad |
|----------|-------|----------|---------|
| Mandar PDF completo (2300 págs) a LLM | Muy alto | Lento | Baja (mucho ruido) |
| Mandar sub-PDF de 5-12 págs por bloque | **Bajo** | **Rápido** | **Alta (contexto enfocado)** |

El backend ya identifica las páginas relevantes (esto YA funciona). Cowork
solo ve el subconjunto que importa.

Ejemplos:
- Profesional Juan Pérez está en págs 47-58 → sub-PDF de 12 págs → Cowork → JSON con sus certificados
- TDR cargo "Especialista en Estructuras" está en pág 4 (B.1) + pág 6 (B.2) → 2 págs → Cowork → JSON con profesiones y cargos similares

## Componentes técnicos a construir

### 1. En Cowork — 2 skills mínimas

```yaml
extract-profesional:
  input: sub_pdf, expected_format_version
  output:
    nombre: str
    dni: str
    profesion: str
    cip: str
    fecha_colegiacion: date
    certificados: [{empresa, ruc, cargo, fecha_inicio, fecha_fin, ...}]
  callback_url: optional

extract-tdr-cargo:
  input: pdf_b1_b2, numero_fila
  output:
    cargo: str
    profesiones_aceptadas: [str]
    experiencia_minima: {cantidad, unidad, cargos_similares_validos}
    tipo_obra_valido: str
  callback_url: optional
```

### 2. En backend — wrapper de Cowork

`src/extraction/cowork_client.py` — reemplaza `llm_extractor.py`:

```python
def extraer_profesional_via_cowork(sub_pdf_path, job_id, block_id):
    # 1. Subir PDF a Cowork (o pasar URL si tienes storage público)
    # 2. POST al trigger de Cowork
    # 3. Esperar callback en /api/webhooks/cowork-callback
    # 4. Devolver el resultado estructurado
```

### 3. Backend expuesto a internet

Hoy el backend corre en localhost del server. Para que Cowork le pueda
hacer callback necesitas:

- Nginx Proxy Manager (ya existe en el server) → expone backend con SSL
- Subdomain tipo `infoobras-api.alpamayo.pe`
- Auth en webhooks (HMAC con secret compartido)

### 4. Job correlation

El backend manda `job_id + block_id` en cada trigger. Cuando llega el
callback, lo correlaciona y guarda en DB. Si después de N segundos no
llega callback → timeout y retry o fallar.

## Latencia esperada

| Etapa | Hoy (Qwen local) | Con Cowork híbrido |
|-------|------------------|---------------------|
| Extracción 1 profesional (12 págs) | ~60 s | ~10-15 s |
| TDR completo (17 cargos × 2 calls) | 4-6 min | ~30-60 s (paralelo) |
| Propuesta completa (50-100 profesionales) | 1-2 horas | 5-10 min (paralelo) |

El paralelismo es clave: hoy Qwen procesa 1 bloque a la vez (1 GPU). Con
Cowork mandas 50 sub-PDFs en paralelo, Anthropic los procesa
concurrentemente, los resultados llegan en pocos minutos.

## Trabajo estimado

| Tarea | Esfuerzo |
|-------|----------|
| Setup Cowork (account, plan, skills básicas) | 4-6 h |
| Crear skill `extract-profesional` con Claude | 4 h |
| Crear skill `extract-tdr-cargo` con Claude | 3 h |
| Wrapper en backend (`cowork_client.py`) | 4-6 h |
| Endpoint `/api/webhooks/cowork-callback` con auth HMAC | 2-3 h |
| Exponer backend vía Nginx (subdomain + SSL) | 2-3 h |
| Job correlation + timeout/retry | 3-4 h |
| Migración del flujo actual (feature flag para A/B) | 4-6 h |
| Testing end-to-end con golden | 4-6 h |
| **Total** | **~4-5 días** |

## Riesgos / cuidados

1. **Estabilidad del callback**: si Cowork no devuelve el callback (cae,
   timeout), el job se queda colgado. Necesitas un poller secundario o
   timeout duro con marcado de error en BD.

2. **Costo Cowork**: depende del plan que elija el cliente. Hay que
   confirmar si webhooks/triggers están incluidos en el tier al que va
   a suscribirse, y volumen estimado de PDFs/mes.

3. **Backend público**: hoy es localhost. Exponerlo agrega superficie de
   ataque. HMAC en webhooks, rate limiting, IP allowlist si Cowork
   permite.

4. **Privacidad**: los PDFs siguen siendo bids gubernamentales. Aunque el
   cliente ya no exija on-prem, vale confirmar que está OK con que los
   datos pasen por Anthropic. Cowork tiene retención configurable
   (zero-retention para datos sensibles).

5. **Latencia de Cowork triggers**: no es instantáneo como una API call.
   Hay overhead de orquestación. Probar primero el RTT real con un job de
   prueba antes de comprometer la migración.

6. **Vendor lock-in**: si Cowork cambia su API, sus precios, o
   desaparece, hay que migrar. Mantener la abstracción del wrapper hace
   esa migración más fácil (cambias `cowork_client.py` por
   `claude_api_client.py` o `anthropic_messages_client.py`).

## Implicaciones para el roadmap

Si esto se materializa, varios items del backlog cambian de prioridad:

- **Opción A (extracción fila-por-fila)**: pierde urgencia. Claude
  maneja el contexto fila-por-fila implícitamente al recibir sub-PDFs
  recortados.
- **Diccionario de dominio**: sigue siendo útil pero menos crítico.
  Claude no aluciona "Ingeniero de Costos" como Qwen.
- **Evaluar Gemma 4**: pierde sentido si ya estamos con Claude. Solo
  vale la pena si Cowork no llega a aprobarse y volvemos a on-prem.
- **B.2 dedicado**: se resuelve naturalmente porque Claude maneja mejor
  los párrafos verbosos.

## Decisión y prerequisitos

**Antes de comprometerse**:

1. Confirmar con el cliente:
   - ¿OK con que PDFs (bids gubernamentales) pasen por Anthropic vía
     Cowork?
   - ¿Asume el costo del plan Cowork (variable según volumen)?
   - ¿Acepta exponer un endpoint del backend a internet?
2. Hacer un POC pequeño: 1 sub-PDF → 1 skill Cowork → 1 callback.
   Medir RTT real, costo real, calidad del JSON.
3. Solo después de validar el POC, comprometer los 4-5 días de
   migración.

**Si los 3 puntos del 1 son sí y el POC funciona**: este plan es la
ruta más rápida para llegar a "minutos por job" sin reescribir el
backend completo.

Si alguno es no: revisar `plan_cowork.md` o quedarse con la arquitectura
actual e iterar con Opción A para mejorar precision.
