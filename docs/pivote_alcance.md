# Pivote de alcance — qué entregar al cliente

Documento de decisión. Captura la situación real y la propuesta de pivote
después de 5-6 semanas de desarrollo, considerando:

- Limitaciones del modelo open-source local (Qwen 14B) para extracción
- Imposibilidad práctica de migrar a Claude API (sin presupuesto del dev
  para pagar tokens, sin disposición del cliente a contratar API directa)
- Que el cliente ya descubrió Claude.ai por su cuenta y obtuvo resultados
  satisfactorios para análisis manual

## Estado actual del sistema

### Lo que SÍ funciona end-to-end
- Pipeline OCR con motor-OCR (PaddleOCR) y fast-path pdfplumber
- Detección automática de digital vs escaneado
- Persistencia: PostgreSQL, jobs, files, retención de PDFs, re-run
- Frontend Next.js: historial paginado, debug, jobs detail
- Scraping InfoObras Contraloría (existe en `src/scraping/`)
- Estructura del Excel de salida (5 hojas planificadas)
- Motor de reglas determinístico (ALT01-ALT10, 22 criterios RTM, cálculo
  días efectivos con descuentos COVID/colegiación/paralizaciones)

### Lo que NO funciona suficientemente bien
- **Extracción LLM con Qwen 14B**: F1 profesiones ~0.55 con variabilidad
  ±0.05 entre runs, F1 cargos similares ~0.30, field bleed en B.2,
  cross-row contamination
- Como la extracción está al inicio del pipeline, **bloquea la
  verificación** del motor de reglas, scraping, y Excel generator —
  todos esperan data estructurada de calidad

## Lo que vio el cliente (Manuel)

Subió las bases del concurso CP-02-2025 a Claude.ai con un prompt grande
y obtuvo:

- `BD_Experiencias_Paso3_CP02-2025.xlsx` (49 filas × 29 columnas)
- `Evaluacion_RTM_Paso4_CP02-2025.xlsx` (49 filas × 25 columnas)

Estructura ~85% igual a la del Excel objetivo de Lircay (referencia
manual de Roberto). **Las justificaciones celda-por-celda incluso
superiores** al Excel manual (ej: *"SÍ – 'Ingeniero Civil' está
literalmente en la lista..."*) vs simplemente "CUMPLE".

### Lo que Claude.ai SÍ produjo
- Extracción estructurada de profesionales y certificados
- Evaluación RTM con CUMPLE/NO CUMPLE + justificación textual
- 3 alertas calculadas: COVID, experiencia anterior a titulación,
  certificado emitido antes de culminación

### Lo que Claude.ai NO produjo (porque no puede)
- Cruce con SUNAT (fecha creación empresa → ALT04)
- Cruce con InfoObras Contraloría (CUI, estado obra, suspensiones, actas)
- Cálculo de días efectivos descontando paralizaciones
- Hojas adicionales (Resumen, Verificación InfoObras, hoja TDR formal)
- Procesamiento batch
- Histórico consultable

## Decisión: pivote de alcance

**Dado que el cliente:**
- Ya tiene flujo funcional con Claude.ai para extracción
- No quiere pagar Claude API extra
- Tiene su sub de Claude.ai

**Y dado que el dev:**
- No puede sostener la migración a Claude API a su costo
- Tiene casi todo lo demás del sistema funcionando

**Pivote**: en vez de competir contra Claude.ai en extracción (donde
perdemos), entregar las **integraciones y enriquecimientos que Claude.ai
NO puede hacer**. El cliente extrae con Claude.ai, nosotros
enriquecemos.

## Suite de tools propuesta (lo que se entrega)

### Tool 1 — Verificación SUNAT vía padrón mensual

**Qué hace**: dado un RUC, devuelve fecha de inicio de actividades, estado,
condición, razón social. Cubre alerta ALT04 (empresa constituida después
del inicio de experiencia).

**Cómo**: descarga mensual del padrón SUNAT (gratuito, ~3GB), import a
PostgreSQL local, lookup instantáneo por API.

**Esfuerzo**: ~6-8 horas
- Tabla `sunat_padron` + índice
- Script de import inicial + cron mensual
- Endpoint `GET /api/sunat/{ruc}` o tool MCP
- Tests con RUCs reales

**Por qué SÍ**: es el caso más alto-valor, datos estables, gratuito,
on-prem.

### Tool 2 — Cruce automático con InfoObras Contraloría

**Qué hace**: dado el nombre de un proyecto o un CUI, devuelve estado de
la obra, fecha inicio/fin, suspensiones, actas, paralizaciones.
Información necesaria para validar las experiencias declaradas y
descontar días efectivos.

**Cómo**: scraping ya existente en `src/scraping/`, encapsulado como tool
con cache local de 7 días.

**Esfuerzo**: ~10-12 horas
- Refactor del scraping existente
- Cache de respuestas (tabla `infoobras_cache`)
- Manejo de timeouts / fallback
- Endpoint `GET /api/infoobras/buscar?nombre=` y `/api/infoobras/cui/{cui}`

**Por qué SÍ**: ya existe el código base, solo hay que envolverlo. Es
información que NO está en ningún otro lado y que el cliente necesita
verificar manualmente hoy.

### Tool 3 — Excel formatter + validador determinístico ⭐

**Qué hace**: toma como input el JSON estructurado que el cliente extrae
con Claude.ai (formato a definir, idealmente lo que ya genera Claude),
aplica las reglas determinísticas y los cruces externos, y produce el
Excel formato Lircay completo con las 5 hojas.

**Cómo**:
1. Endpoint `POST /api/analizar` recibe JSON estructurado
2. Aplica los 22 criterios RTM (CUMPLE/NO CUMPLE)
3. Calcula días efectivos descontando COVID + paralizaciones (de
   InfoObras) + colegiación + experiencia anterior a titulación
4. Cruza RUCs con SUNAT (Tool 1)
5. Cruza proyectos con InfoObras (Tool 2)
6. Genera Excel con openpyxl en formato Lircay (5 hojas)

**Esfuerzo**: ~3-4 días
- Definir schema JSON de input (alineado con lo que produce Claude.ai)
- Reuse del motor de reglas existente
- Generador de Excel con `openpyxl` siguiendo formato Lircay
- Tests con golden Lircay como referencia

**Por qué SÍ**: **es la pieza que cierra el flujo end-to-end con el
cliente**. Manuel saca JSON de Claude.ai, lo sube a tu sistema, recibe
Excel formato firmable. Reusa todo el motor de reglas que ya tienes.

## Lo que se DESCARTA del backlog original

| Item | Por qué se descarta |
|------|---------------------|
| Vigencia de colegiaturas (CIP, CAP, etc.) | Cada colegio tiene portal distinto, fragmentado, ROI bajo. Que el evaluador lo verifique manual. |
| Verificación SUNAT vía formulario directo | Tiene CAPTCHA. Padrón mensual ya cubre el caso real. |
| Reescritura del LLM local (Opción A fila-por-fila) | Sin presupuesto Claude API y Qwen toca techo, no vale el tiempo. |
| Diccionario de dominio (PROFESIONES_TIPICAS_POR_CARGO) | Solo aplica si el LLM local mejora — ya no es prioridad. |
| Migración a Gemma 4 | Lo mismo: no resuelve el problema de raíz si no se paga API. |
| `plan_hibrido.md` (Cowork + backend) | Requiere que cliente pague API o Cowork plan. No aplica. |
| `plan_cowork.md` (100% Cowork) | Idem. |
| Schedules / monitores SEACE | Buena idea pero lateral al deliverable inmediato. Para Fase 2. |

## Otras tools a considerar (NO en alcance inmediato pero anotadas)

### Comparador de propuestas competidoras
Toma N propuestas evaluadas en el sistema → genera reporte ejecutivo
comparativo (cuál tiene mejor staff, alertas críticas por postor, etc.).
Útil para concursos donde el cliente evalúa 3-5 postores. **~1-2 días.**

### Histórico consultable
Búsquedas tipo "todos los profesionales que aparecieron en propuestas de
hospitales nivel III en 2024", "todas las experiencias del profesional X
en el sistema". Aprovecha PostgreSQL. **~1-2 días.**

### Pre-evaluador go/no-go de TDRs
Dado un TDR nuevo y el perfil de la empresa (qué profesionales tienen,
qué experiencia), responde "vale la pena postular" antes de invertir las
horas del análisis completo. Requiere LLM, así que **fuera de alcance sin
Claude API**.

### Monitor SEACE
Cron diario que busca licitaciones nuevas relevantes y manda alerta.
Útil pero lateral. **Fase 2 — no entra ahora.**

### Detector de profesionales repetidos entre postores
Si el mismo profesional aparece en propuestas de 2 postores competidores,
red flag. Trivial dado el histórico. **~4-6 horas, en Fase 2.**

## Cómo presentárselo al cliente

### Mensaje propuesto

> Manuel, después de probar a fondo el sistema con la información que
> manejamos, llegamos a un punto claro:
>
> **Lo que descubriste con Claude.ai funciona muy bien para la extracción
> y la evaluación inicial.** Genera las dos hojas más importantes del
> Excel con buena calidad.
>
> **Lo que Claude.ai NO te da, y que te sigue tomando horas manuales:**
>
> 1. **Verificar cada RUC contra SUNAT** (ALT04: empresa constituida
>    después del inicio de la experiencia → toca con tarjetita en SUNAT)
> 2. **Cruzar cada proyecto contra InfoObras** (estado de obra,
>    suspensiones, actas → entrar a InfoObras uno por uno)
> 3. **Calcular días efectivos descontando** COVID + paralizaciones +
>    colegiación (manual con calculadora)
> 4. **Generar el Excel completo en formato Lircay** con las 5 hojas
>    (lo armas a mano hoja por hoja)
>
> Te propongo enfocar el sistema en esos 4 puntos: tú usas Claude.ai como
> ya lo haces, sacas un JSON estructurado, lo subes a mi sistema y
> recibes el Excel completo con todos los cruces ya hechos.
>
> Esto te ahorra ~3-4 horas de trabajo manual por análisis. El sistema
> queda funcionando como complemento de Claude.ai, no como sustituto.
>
> Esfuerzo: ~1-2 semanas. Costo: el mantenimiento mensual habitual, sin
> dependencias externas pagadas. ¿Avanzamos?

### Lo que necesitas confirmar con él en la conversación

1. **Volumen de propuestas/mes** que evalúa (para dimensionar)
2. **Formato del JSON** que Claude.ai le da hoy (para definir el schema
   de input)
3. **Si está OK con el flujo**: él copia el JSON de Claude.ai → pega/sube
   en tu sistema → recibe Excel
4. **Cuánto le toma hoy** las verificaciones SUNAT/InfoObras manuales
   (para validar el ahorro de tiempo)

## Plan de trabajo si acepta

| Semana | Entregable |
|--------|------------|
| Semana 1 | Tool 1 (SUNAT padrón) + Tool 2 (InfoObras scraping) |
| Semana 2 | Tool 3 (Excel formatter + validador determinístico) + tests |
| Semana 3 | Integración end-to-end + UI mínima de subida JSON + bug fixes |

Total: 2-3 semanas para deliverable productivo, vs el "estado de
incertidumbre" actual.

## Plan B si NO acepta

- Cierras consultoría con lo construido hasta hoy
- Le entregas:
  - Repo completo documentado (los `docs/*.md` ya armados)
  - Servidor configurado con todo lo que funciona
  - Acceso a re-correr lo que tiene en histórico
- Honorarios de cierre por lo trabajado
- Le dejas la puerta abierta: *"cuando veas que las verificaciones
  SUNAT/InfoObras te quitan tiempo, llámame y retomamos"*

## Decisión interna recomendada

**Mantener el servidor y la infra existente** (DB, OCR, scraping
existente, UI) y enfocar las próximas 2-3 semanas SOLO en las 3 tools
arriba. Cero más debates sobre LLM local, golden sets, validators
sofisticados. Esos quedan en `docs/proximas-mejoras-tdr.md` por si
algún día se retoman.

**Cuando el cliente confirme el alcance**, ejecutar las 3 tools
linearmente. Cada una entregada y testeada antes de pasar a la
siguiente. Sin ramas largas, sin VL, sin Cowork — solo lo que
demostramos que funciona.
