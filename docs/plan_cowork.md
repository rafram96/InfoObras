# Plan 100% Cowork — InfoObras como skill suite en Anthropic

Escenario hipotético: ¿qué pasaría si todo InfoObras viviera dentro de
Claude Cowork, sin backend custom?

Este doc es un **análisis comparativo** vs la arquitectura actual y vs el
`plan_hibrido.md`. Sirve para decidir si vale la pena ir tan lejos o
quedarse en una solución híbrida.

## Cómo se vería

```
┌──────────────────────────────────────────────────────┐
│ Claude Cowork (todo aquí)                            │
│                                                       │
│  - Evaluador sube PDFs vía chat / drag & drop        │
│  - Skills:                                            │
│    • analyze-propuesta                                │
│    • analyze-tdr                                      │
│    • compare-propuestas                               │
│    • search-profesional                               │
│    • generate-excel                                   │
│    • check-sunat-via-padron (con MCP a un store)     │
│    • check-infoobras (con MCP a Contraloría)         │
│  - Persistencia: Cowork's built-in storage o KV       │
│  - Reglas de negocio (ALT01-ALT10): codificadas en   │
│    skill, ejecutadas por Claude paso a paso          │
│  - Output: Excel descargable directo del chat        │
└──────────────────────────────────────────────────────┘

       ▲ Solo dependencia externa: scrapers livianos
       │ que viven como MCP servers o Cloud Functions

┌──────────────────────────────────────────────────────┐
│ Servicios MCP minimales (opcional)                   │
│  - InfoObras Contraloría (no tiene API, scraping)    │
│  - Padrón SUNAT (BD propia con import mensual)       │
└──────────────────────────────────────────────────────┘
```

El backend FastAPI **desaparece**. PostgreSQL **desaparece**. La UI web
**desaparece** (la reemplaza el chat de Cowork). El motor-OCR
**desaparece** (Claude Vision via document parsing).

## Lo que se gana vs hoy

### Operación
- **Cero infraestructura que mantener**: sin servidor, sin DB, sin GPU,
  sin Ollama, sin Docker, sin Nginx
- **Sin deploy**: cualquier cambio en una skill se actualiza en Cowork
  directamente
- **Sin scaling**: Anthropic lo maneja. Si llega un cliente con 100
  TDRs/día, no hay que comprar otro server
- **Backups y disaster recovery automáticos**: Anthropic los maneja

### Calidad
- **Claude >> Qwen 14B** en extracción, razonamiento, español jurídico
- **Sin alucinaciones derivadas del cargo** ("Ingeniero de Costos") —
  Claude no comete ese tipo de error
- **Cross-row contamination casi desaparece** — Claude tiene mejor
  atención sobre tablas
- **B.2 mejora dramáticamente** — Claude maneja párrafos verbosos sin
  problema
- **Mantenimiento de prompts**: Claude responde a instrucciones más
  flexibles, menos prompt engineering frágil

### Velocidad
- **Job típico**: 4-6 min → 30-90 s (5-10× más rápido)
- **Iteración del cliente**: cambios en lógica de validación se hacen
  editando una skill, no redeployeando código
- **Onboarding**: cualquier evaluador nuevo puede empezar a usar Cowork
  sin instalación local

### UX
- **Chat conversacional natural**: "compárame estas 3 propuestas",
  "muéstrame las alertas críticas del último mes", "dime quién tiene la
  mejor experiencia en estructuras"
- **Multi-usuario nativo**: varios evaluadores pueden colaborar en el
  mismo análisis
- **Audit trail**: cada conversación queda registrada con thread
- **Skills componibles**: el cliente mismo puede crear shortcuts ad-hoc

## Lo que se pierde vs hoy

### Control
- **Sin custom OCR**: motor-OCR con PaddleOCR (optimizado para PDFs
  escaneados peruanos) se reemplaza por Claude Vision genérico. Para
  PDFs de mala calidad, podría perder calidad.
- **Sin pdfplumber fast-path**: la optimización para PDFs digitales
  (que detectaba texto nativo y saltaba OCR) ya no aplica.
- **Sin debug tools custom**: la página `/herramientas/debug-pdfplumber`
  con visor de console y LLM calls se va. Cowork tiene su propio audit
  pero menos detallado.
- **Sin re-run history**: el botón "re-correr" del historial con
  preservación de PDF se pierde (Cowork conserva conversaciones pero
  re-run no es lo mismo).

### Infraestructura técnica
- **Motor de reglas determinístico**: hoy las 10 alertas (ALT01-ALT10)
  son código Python que SIEMPRE da el mismo resultado para el mismo
  input. En Cowork, Claude ejecuta las reglas — más flexible pero menos
  determinístico. **Riesgo regulatorio**: si una empresa impugna el
  resultado, "Claude lo decidió" no es defendible como "código Python
  determinístico v1.2.3".
- **Cálculo de días efectivos** (Paso 5): hoy es código que descuenta
  COVID, paralizaciones, fechas de colegiación, etc. con precisión
  matemática. Reemplazarlo con Claude introduce riesgo de off-by-one en
  cálculos críticos.
- **Sin BD propia**: si quieres un dashboard de "todas las propuestas
  evaluadas en 2026" o reportes históricos, no hay BD propia para
  consultar — depende de lo que Cowork exponga.

### Costo recurrente
- **Cowork plan**: probablemente $50-200/mes según volumen
- **Tokens Claude**: cada PDF procesado consume tokens. Una propuesta
  de 2300 págs = ~2-3M tokens. A precios de Sonnet 4.5 con caching:
  ~$1-3 por análisis. Con 20 análisis/mes = $20-60/mes adicional.
- **Total mensual estimado**: $100-300
- **Hoy**: $0 (todo on-prem, GPU ya pagada)

### Lock-in
- **Total dependencia de Anthropic**: si suben precios, cambian API,
  o discontinúan Cowork, hay que reescribir todo.
- **Migración inversa difícil**: salir de Cowork de vuelta a on-prem
  requiere reconstruir todo lo que se eliminó (backend, DB, motor de
  reglas, OCR custom). El plan híbrido NO tiene este lock-in.

### Privacidad / compliance
- **Datos del cliente en Anthropic**: bids gubernamentales, datos de
  profesionales (DNI, CIP, certificados). Aunque Cowork tenga
  zero-retention configurable, igual hay que validar con el cliente
  que es aceptable contractualmente.
- **Cumplimiento legal Perú**: la Ley de Protección de Datos
  Personales (Ley 29733) exige ciertos controles. On-prem los cumple
  por defecto. Cowork requiere DPA con Anthropic.

## Tabla comparativa

| Dimensión | Hoy (on-prem) | Híbrido (plan_hibrido.md) | 100% Cowork (este doc) |
|-----------|---------------|---------------------------|-------------------------|
| Velocidad | Lento (4-6 min) | Rápido (30-90 s) | Rápido (30-90 s) |
| Calidad LLM | Qwen 14B (medio) | Claude (alto) | Claude (alto) |
| Costo mensual | $0 | $50-150 | $100-300 |
| Infraestructura | Server + GPU | Server (sin GPU?) + Cowork | Solo Cowork |
| Tiempo de migración | (ya está) | 4-5 días | 2-3 semanas |
| Lock-in | Bajo | Medio (wrapper aísla) | **Alto** |
| Determinismo de reglas | **Total** (código Py) | Total (motor reglas se queda) | **Bajo** (Claude) |
| Auditabilidad | Total | Total (logs propios) | Limitada (logs Cowork) |
| Privacidad | **Total** (on-prem) | Media (PDFs van a Anthropic) | Media (todo va a Anthropic) |
| Onboarding evaluador | Instalación local | Web | Web (Cowork chat) |
| Custom OCR | **Sí** (PaddleOCR + pdfplumber) | Sí (queda en backend) | No (Claude Vision) |
| Backend a mantener | Sí | Sí (más simple) | **No** |

## Cuándo tendría sentido ir 100% Cowork

Solo si **TODOS** estos son ciertos:

1. El cliente acepta dependencia total de Anthropic (aceptación legal +
   contractual + DPA firmado)
2. El cliente no necesita auditabilidad regulatoria de las decisiones
   automáticas (ALT01-ALT10 ejecutadas por Claude vs código)
3. El cliente acepta el costo recurrente (~$100-300/mes mínimo)
4. El volumen es predecible y bajo (no nos sorprende un mes con 200
   análisis que dispare costos)
5. **No** se proyecta integrar con otros sistemas internos del cliente
   (que requerirían el backend como punto de integración)
6. El equipo de mantenimiento NO quiere infraestructura custom

## Cuándo NO tiene sentido ir 100% Cowork

- Si la auditabilidad de las reglas es legal/contractual (probable en
  contratos públicos del Estado)
- Si el cliente quiere ver/modificar cómo se calculan los días
  efectivos (Paso 5 con descuentos COVID + colegiación)
- Si el cliente no quiere quedar atado a un proveedor único de IA
- Si en el futuro habrá integración con SAP / ERP / otros sistemas del
  cliente (esos integran mejor con un backend tradicional)
- Si el cliente quiere bajar el costo a $0 cuando no hay análisis (hoy
  on-prem cuesta lo mismo idle vs en uso, Cowork cobra por uso)

## Recomendación

**El plan híbrido (`plan_hibrido.md`) es el sweet spot** para casi
todos los casos:

- Saca todo el upside de Claude (velocidad + calidad)
- Mantiene control determinístico del motor de reglas
- Mantiene la BD propia para reportes y auditoría
- Lock-in limitado (cambiar Cowork por API directa o por otro provider
  es trivial — solo cambia el wrapper)
- Privacidad parcial (sub-PDFs cortos, no propuesta entera)
- Migración corta (4-5 días vs 2-3 semanas)

**100% Cowork sería justificable solo** si el cliente prioriza por
encima de todo:
- Cero infraestructura propia
- Iteración rapidísima (cambios sin redeploy)
- Y acepta los trade-offs de lock-in y determinismo

Para una inmobiliaria evaluando contratos públicos en Perú (donde la
auditabilidad importa), **el híbrido es más defendible**.

## Si igual se quisiera ir 100% Cowork

Plan de migración estimado:

| Fase | Esfuerzo |
|------|----------|
| Diseñar las skills (10-12 skills) | 3-4 días |
| Implementar las skills con Claude | 5-7 días |
| MCP server para Contraloría InfoObras | 2-3 días |
| MCP server para Padrón SUNAT | 2 días |
| Migración de reglas ALT01-ALT10 a skill | 3-4 días |
| Generador de Excel desde skill | 1-2 días |
| Testing end-to-end con golden | 3-4 días |
| Onboarding del cliente al chat | 1-2 días |
| Decommissioning del backend actual | 1-2 días |
| **Total** | **~3 semanas** |

Más todo lo que aprendamos en el camino sobre limitaciones específicas
de Cowork que requieran workarounds.
