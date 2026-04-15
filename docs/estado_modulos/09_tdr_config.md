# Módulo: TDR Config (Prompts + Scoring)

> `src/tdr/config/signals.py` — ~200 líneas — ✅ Completo

## Propósito
Contiene los prompts LLM y las señales de scoring para la extracción de requisitos TDR (Paso 1).

## Prompts

### PROMPT_RTM_PERSONAL (~90 líneas)
Extrae personal clave de las bases del concurso. Cada item tiene:
- `cargo`: nombre exacto del cargo
- `profesiones_aceptadas`: títulos válidos
- `anos_colegiado`: "N meses"
- `experiencia_minima`: {cantidad, unidad, descripcion, cargos_similares_validos}
- `tipo_obra_valido`: sector (salud, educación, etc.) — **mejorado** para no copiar "en entidades públicas"
- `capacitacion`: {tema, tipo, duracion_minima_horas}

Maneja tablas OCR entrelazadas (B.1 + B.2 combinadas con columnas mezcladas).

### PROMPT_RTM_POSTOR
Extrae requisitos del postor (empresa):
- tipo_experiencia_valida, sector_valido, cita_exacta, experiencia_adicional_factores

### PROMPT_FACTORES
Extrae factores de evaluación:
- factor, aplica_a (postor/personal/ambos), cargo_personal, puntaje_maximo, metodologia

### PROMPT_CAPACITACION
Extrae requisitos de capacitación por separado (se cruza con personal después).

## Señales de scoring (SIGNALS)

El scorer usa regex patterns con pesos para detectar qué tipo de bloque es cada página:

| Categoría | Patterns | Pesos | Detecta |
|-----------|----------|-------|---------|
| rtm_postor | 9 | 1.0–3.0 | Requisitos del postor (experiencia empresa) |
| rtm_personal | 10 | 1.0–3.0 | Personal clave (cargos, profesiones, experiencia) |
| factores_evaluacion | 8 | 1.5–3.0 | Factores de puntuación |
| blacklist | 43 | 1.5–3.0 | Ruido: texto legal, SEACE, plantillas |
| capacitacion | 8 | 2.0–4.0 | Requisitos de capacitación (peso más alto) |

## Mejora reciente (2026-04-15)
`tipo_obra_valido` ahora instruye al LLM a extraer el **sector** (salud, educación, vial) en vez de copiar literalmente frases genéricas como "en entidades públicas y/o privadas".

## Dependencias
- Ninguna (módulo de configuración)
