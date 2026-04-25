# Próximas mejoras al pipeline de extracción TDR

Roadmap post-merge de `feat/tdr-vl-extraction`. Captura lo que aprendimos
durante el experimento VL y qué falta atacar para subir precisión.

## Estado actual (lo que mergeó)

- Golden set anotado para TDR Huancavelica (`tests/golden/rtm_huancavelica.json`)
- Script de evaluación `tests/evaluar_tdr.py` con métricas por campo
- Fix del validador `_es_profesion_derivada_del_cargo` que descarta
  alucinaciones tipo "Ingeniero de Costos" para cargo "ESPECIALISTA EN COSTOS"
- Banner mejorado al startup (incluye USE_VL_TDR_EXTRACTION y FORCE_MOTOR_OCR)
- Infraestructura VL (`vl_extractor.py`, `vl_extract_tdr_worker.py`,
  `vl_extract_tdr_client.py`) — desactivada por default (`USE_VL_TDR_EXTRACTION=false`)

## Métricas baseline actuales

Sobre TDR Huancavelica (17 cargos), con 3 runs:

| Métrica                    | Valor estable    |
|----------------------------|------------------|
| Cargos detectados          | 17/17 ✅         |
| Tiempo meses               | 100% ✅          |
| Tipo obra                  | 100% ✅          |
| Profesiones F1             | 0.55 ± 0.05      |
| Profesiones Precision      | ~70%             |
| Profesiones Recall         | 41-55%           |
| Cargos similares F1        | 0.30 ± 0.03      |

La variabilidad ±0.05 entre runs viene del LLM (qwen2.5:14b) no determinista
incluso a `temperature=0`. Para métricas confiables hay que promediar 3-5 runs.

## Problema raíz: cross-row contamination

El LLM textual procesa todo el bloque B.1 (3-5 páginas, 17 filas) en una sola
llamada. Resultado: mezcla profesiones entre filas adyacentes.

**Ejemplos observados** en runs distintos del mismo PDF:
- Fila #9 (COMUNICACIONES) recibió `["medico", "tecnologo medico", "ingeniero
  mecatronico"]` que pertenecen a #10 EQUIPAMIENTO HOSPITALARIO
- Fila #14 (COSTOS) inventó `"Ingeniero de Costos"` derivándolo del nombre del
  cargo (esto sí ya está fix con el validador, pero ilustra el patrón)
- Filas #15, #16, #17 frecuentemente pierden las profesiones genéricas
  ("Ingeniero Civil", "Arquitecto") que sí aparecen en B.1

Esto **no se arregla con prompt engineering** sin cambiar la estrategia.

## Opción A — Extracción fila-por-fila ⭐ RECOMENDADA

### Idea

En vez de mandar todo B.1 al LLM en un solo prompt, **una llamada por fila**:

1. Detectar las 17 filas de B.1 con regex sobre el texto OCR (números N°,
   límites por header repetido, etc.)
2. Para cada fila, extraer su contenido específico (las ~3-5 líneas que la
   componen visualmente)
3. Mandar al LLM **solo esa fila** con prompt acotado: "extrae profesiones
   y cargo de esta fila. NO inventes."
4. Recolectar 17 respuestas → estructura final

### Por qué resuelve cross-row

- El LLM solo ve una fila a la vez. No tiene de dónde "robar" datos de filas
  adyacentes.
- El prompt es 95% más corto → la atención del modelo se concentra en una
  cosa.
- Cada fila tiene contexto independiente → si una falla, las otras 16 no
  arrastran el error.

### Trade-offs

| Pro                                | Contra                                   |
|------------------------------------|------------------------------------------|
| Elimina cross-row de raíz          | 17 llamadas LLM en vez de 1 → +50% latencia |
| Cada fila es debuggeable aislada   | Necesita parser robusto por fila         |
| Errores localizados, no propagan   | Más complejo de mantener                 |
| Reproducibilidad mucho mejor       | Reutiliza menos contexto compartido      |

### Estimación

| Tarea                                              | Esfuerzo |
|----------------------------------------------------|----------|
| Detector de límites de fila (regex sobre OCR)      | 2-3 h    |
| Refactor del prompt B.1 a versión "una fila"       | 1-2 h    |
| Loop por fila + agregación + parser                | 2-3 h    |
| Misma idea aplicada a B.2 (más complejo)           | 4-6 h    |
| Tests con golden + iteración                       | 3-4 h    |
| **Total**                                          | **1.5-2 días** |

### Mejora esperada

- Profesiones Recall: 41-55% → 75-80%
- Profesiones F1: 0.55 → 0.75+
- Cargos similares F1: 0.30 → 0.55+
- Latencia por TDR: 3-4 min → 5-7 min (aceptable para batch)
- Variabilidad entre runs: ±0.05 → ±0.02 (más estable)

### Plan de implementación

1. **Detector de filas B.1** — `src/tdr/extractor/row_splitter.py`
   - Input: texto OCR de las páginas de B.1
   - Output: lista de 17 strings, una por fila
   - Heurística: split por números al inicio de línea (1\n, 2\n, ...)
     con validación de continuidad

2. **Nuevo prompt acotado** — `src/tdr/config/signals.py`
   - `PROMPT_RTM_PERSONAL_FILA` (vs el actual que ve todo)
   - Recibe: número de fila, texto de la fila
   - Devuelve: `{numero, cargo, profesiones[]}`
   - Reglas anti-alucinación más fuertes (sin contexto de otras filas)

3. **Orquestador** — `src/tdr/extractor/pipeline.py`
   - Si `USE_ROW_BY_ROW_EXTRACTION=true` (nuevo flag)
   - Reemplaza el bloque actual de extracción rtm_personal
   - Loop con `concurrent.futures` para paralelizar 4-6 filas a la vez
   - Mantener pipeline actual como fallback si falla

4. **Aplicar la misma estrategia a B.2**
   - Es más complejo porque las filas B.2 son párrafos largos
   - Posiblemente combinar 2-3 filas por llamada para no saturar requests

5. **Re-correr eval con golden y comparar**
   - Si F1 sube como esperamos → flag a default `true`
   - Mergear a main

## Opciones alternativas (descartadas o de menor prioridad)

### Opción B — Prompt rework con reglas estrictas

Reescribir `PROMPT_RTM_PERSONAL` con reglas más explícitas de "una fila a la
vez". Probado parcialmente — mejora marginal incierta (+0-10% recall),
4-6 horas de trabajo. **No resuelve el problema de raíz**, solo lo mitiga.

Posible reintento si Opción A no es viable por tiempo.

### Opción C — Aceptar lo que hay + revisión manual

Cliente recibe el Excel con las 4-5 filas conflictivas (típicamente #9,
#10, #14, #15, #16, #17) marcadas en amarillo para revisión humana.

**Realidad**: el cliente quiere 100% automático. Esta opción es solo si A no
fuera viable y el cliente flexibilizara el requisito. **No preferida**.

### Extracción visual estructurada con VL (rama feat/tdr-vl-extraction)

Probada y descartada por ahora:
- B.2 con qwen2.5vl:7b devolvió 0 filas (saturación de imágenes / tokens)
- B.1 dio 12/17 filas parciales
- Mejora real medida: +0.031 F1 en profesiones a costa de +3-4 min
- **No paga el tradeoff**

Reactivable si:
- Aparece un VL más potente (qwen3-vl, claude-vision, etc.)
- Splitting por imagen-página resuelve la saturación
- Cliente acepta latencia mayor

## B.2 — extracción de cargos similares necesita rework dedicado

**Estado actual**: peor parte del pipeline. F1 ~0.30, recall ~26%. Es donde
el sistema más se queda corto en cargos_similares_validos. Independiente de
Opción A (aunque se beneficia), B.2 tiene complicaciones propias.

### Por qué B.2 es harder que B.1

| Aspecto                          | B.1                                | B.2                                  |
|----------------------------------|------------------------------------|--------------------------------------|
| Estructura por celda             | corta (1-3 líneas)                 | párrafo verboso (15-25 líneas)       |
| Datos por extraer                | 1 (lista de profesiones)           | 4 (cargos, tiempo, tipo obra, descripción) |
| Patrón típico                    | "X y/o Y y/o Z"                    | "[prefijo1] y/o [prefijo2] en/de: [sufijo1] y/o [sufijo2]" |
| Cardinalidad de combinaciones    | 2-5 cargos                         | 6 prefijos × 5 sufijos = 30 combinaciones implicitas |
| Info estructurada en lista       | sí (nombres puros)                 | no (lista mezclada con prosa: "en la supervisión y/o ejecución") |
| Footnotes confunden el LLM       | rara vez                           | frecuente (76, 77, 78, etc.)         |

### Problemas específicos observados

1. **Prefijo-sufijo mal expandido**: el LLM no expande "Ingeniero y/o supervisor
   en/de: Eléctrico y/o Electricista" a "Ingeniero Eléctrico, Ingeniero
   Electricista, Supervisor Eléctrico, Supervisor Electricista". Se queda con
   los prefijos sueltos o con los sufijos sueltos.

2. **Termina la lista demasiado pronto**: el LLM corta la enumeración cuando
   ve "o la combinación de estos" pero a veces también corta antes con frases
   como "y/o" mal interpretadas.

3. **Mezcla cargos con tipo de obra**: extrae "edificaciones y afines" como
   cargo cuando es la especialidad. El validador `_es_profesion_real` ayuda
   pero no captura todos los casos.

4. **Recall conservador**: extrae 3-5 cargos por fila cuando el TDR enumera
   6-12. Pierde variantes intermedias.

5. **Cross-row en B.2**: igual que en B.1, la fila #10 a veces hereda cargos
   de #9 o #11 cuando se procesa todo junto.

6. **Field bleed (B.2 → tiempo)**: el contenido del campo "TRABAJOS O
   PRESTACIONES" se concatena con "TIEMPO DE EXPERIENCIA" cuando el LLM no
   distingue bien los límites de columna. La frase "en la supervisión y/o
   ejecución de obras en la especialidad..." termina en el campo tiempo
   en lugar de quedarse solo en cargos_similares.

### Ejemplo concreto observado — fila #5 (Huancavelica)

(Solo campos B.2. El extractor de B.1 — `profesiones_aceptadas` — funciona
suficientemente bien y se considera fuera del alcance de este rework.)

PDF de B.2 dice:

| Columna             | Valor literal                                                                                                                                                                                                                                |
|---------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| TIEMPO              | "Experiencia mínima de (36) meses"                                                                                                                                                                                                            |
| TRABAJOS / PRESTACIONES | "Especialista en estructuras y/o jefe de estructuras y/o Ingeniero Estructural y/o Especialista en diseño estructural y/o Especialista en Estructuras y edificaciones y/o la combinación de estos, en la supervisión y/o ejecución de obras en la especialidad 'edificaciones y afines' y la subespecialidad 'establecimientos de salud'." |

Pipeline produjo:

| Campo               | Valor obtenido                                                                                                       | Diagnóstico        |
|---------------------|----------------------------------------------------------------------------------------------------------------------|--------------------|
| tiempo_meses        | `"36 meses — Experiencia mínima de (36) meses en la supervisión y/o ejecución de obras en la"`                        | **Field bleed**: pegó parte del campo "TRABAJOS O PRESTACIONES" al tiempo. Debería ser solo `36`. |
| tipo_obra_valido    | `"establecimientos de salud"`                                                                                        | ✅ correcto        |
| cargos_similares    | `["Especialista en estructuras", "Jefe de estructuras"]`                                                             | **Recall bajo**: solo 2 de 5 cargos. Faltan "Ingeniero Estructural", "Especialista en diseño estructural", "Especialista en Estructuras y edificaciones". |

Esta fila concentra los 2 problemas más visibles de B.2: field bleed adyacente
(tiempo ↔ trabajos) y recall conservador en la enumeración de cargos. El
rework debe estabilizar ambas en simultáneo.

### Approaches a evaluar (cuando se aborde)

**Approach 1: Extracción fila-por-fila (parte de Opción A)**

Una llamada LLM por fila B.2. El párrafo individual es más manejable. Mejora
esperada: recall 26% → 50-60%. Latencia +30-60s por TDR.

**Approach 2: Pre-procesamiento con regex antes del LLM**

Detectar el patrón `[prefijo] en/de: [sufijos]` con regex, expandir las
combinaciones programáticamente, mandar al LLM solo para validación final.
Mejora esperada: recall 26% → 70-80% **si la regex es robusta**. Riesgo:
regex frágil con TDRs que no siguen el patrón estándar.

**Approach 3: Diccionario de domain como guía**

Cargos típicos por cargo principal en construcción hospitalaria (ej:
ESPECIALISTA EN ESTRUCTURAS típicamente acepta "Especialista en Estructuras",
"Jefe de Estructuras", "Ingeniero Estructural"). Usado como few-shot examples
en el prompt + validador post-extracción. Ver sección "Diccionario de dominio"
abajo.

**Approach 4: Enfoque híbrido — recomendado**

Combinar los 3 anteriores:
1. Extracción fila-por-fila (Approach 1) para aislar contexto
2. Pre-procesamiento regex (Approach 2) cuando detectes el patrón estándar
3. Diccionario (Approach 3) como red de seguridad — flag las filas donde
   el pipeline no extrajo cargos típicos esperados del cargo principal

### Estimación

| Tarea                                                      | Esfuerzo |
|------------------------------------------------------------|----------|
| Splitter de filas B.2 (más complejo que B.1 por verbosidad)| 3-4 h    |
| Prompt fila-por-fila acotado para B.2                      | 2-3 h    |
| Pre-procesador regex de patrón prefijo-sufijo              | 4-6 h    |
| Validador con diccionario de dominio                       | 2-3 h    |
| Tests + iteración con golden multi-TDR                     | 4-5 h    |
| **Total**                                                  | **2-3 días** |

### Mejora esperada

- Cargos similares F1: 0.30 → 0.65-0.75
- Recall: 26% → 70%+
- Estabilidad entre runs: ±0.03 → ±0.01

### Cuándo abordarlo

**Después** de Opción A para B.1 (más simple, gana experiencia en row-by-row).
**Antes** de cerrar el deadline si el cliente reporta que cargos_similares es
insuficiente para su flujo de matching contra CVs.

## Diccionario de dominio (construcción hospitalaria)

### Idea

Como TODOS los TDRs del cliente son construcción hospitalaria (inmobiliaria
Alpamayo / hospitales del MINSA), hay un set finito de profesiones y cargos
que se repiten. Construir un diccionario hardcoded `PROFESIONES_TIPICAS_POR_CARGO`
y `CARGOS_TIPICOS_POR_ROL` que pueda usarse en 3 modos:

```python
# src/tdr/config/dominio_construccion_hospitalaria.py
PROFESIONES_TIPICAS_POR_CARGO = {
    "GERENTE DE CONTRATO": ["Ingeniero Civil", "Arquitecto"],
    "JEFE DE SUPERVISION": ["Ingeniero Civil", "Arquitecto"],
    "ESPECIALISTA EN ESTRUCTURAS": ["Ingeniero Civil", "Ingeniero Estructural"],
    "ESPECIALISTA EN INSTALACIONES SANITARIAS": ["Ingeniero Sanitario", "Ingeniero Civil"],
    "ESPECIALISTA EN EQUIPAMIENTO HOSPITALARIO": [
        "Tecnólogo Médico", "Médico", "Ingeniero Mecatrónico",
        "Ingeniero Electrónico", "Ingeniero Mecánico Eléctrico"
    ],
    # ... resto
}
```

### Cómo NO usarlo

- **No** como override que mete profesiones por encima del PDF. Si un TDR
  específico restringe (ej: solo "Arquitecto" para BIM, sin Ing Civil), y el
  diccionario añade "Ing Civil", terminamos validando candidatos que NO
  deberían pasar — peor que faltar uno.
- **No** como solución única antes de tener 3-5 TDRs anotados. Con solo
  Huancavelica, sobreajustamos al caso particular.

### Cómo SÍ usarlo (3 modos combinables)

**1. Few-shot examples en el prompt LLM** (modo principal)
   - Inyectar el diccionario como contexto en `PROMPT_RTM_PERSONAL` /
     `PROMPT_RTM_PERSONAL_FILA`.
   - Ejemplo: "Los TDRs OSCE de construcción hospitalaria suelen aceptar:
     ESPECIALISTA EN ESTRUCTURAS → Ingeniero Civil, Ingeniero Estructural.
     ESPECIALISTA EN INSTALACIONES SANITARIAS → Ingeniero Sanitario, Ingeniero
     Civil. PERO extrae solo lo que diga la tabla B.1 de ESTE PDF."
   - Sesga al LLM hacia lo razonable sin quitarle fidelidad al PDF.

**2. Validador post-extracción que flaggea** (no añade)
   - Si pipeline extrae profesiones para `ESPECIALISTA EN ESTRUCTURAS` y NO
     incluye ninguna del set típico (`Ingeniero Civil`, `Ingeniero Estructural`),
     marcar `_needs_review=true` con razón "no matchea profesiones esperadas
     del dominio".
   - El cliente decide en UI: aceptar o corregir manualmente.
   - Cero riesgo de overfit — solo es señal, no acción.

**3. Fallback solo si extracción está vacía**
   - Si pipeline devolvió `profesiones_aceptadas: []` para un cargo conocido,
     usar el diccionario como respaldo + marcar `_vino_de_diccionario=true`
     para auditoría.
   - Cubre el peor caso (extracción totalmente fallida) sin contaminar casos
     normales.

### Prerequisitos antes de implementar

- **Anotar 2-3 TDRs adicionales** (no solo Huancavelica). Lo que se repite en
  TODOS va al diccionario. Lo que varía, NO. Sin esa muestra, el diccionario
  refleja Huancavelica, no el dominio.
- **Validar con el cliente** que las profesiones del diccionario sí son
  universalmente aceptadas en sus TDRs hospitalarios.

### Estimación

| Tarea                                                | Esfuerzo |
|------------------------------------------------------|----------|
| Anotar 2-3 TDRs adicionales (cliente)                | -        |
| Construir diccionario inicial vía análisis de TDRs   | 2-3 h    |
| Integrar como few-shot en prompt + validar           | 2-3 h    |
| Validador post-extracción + flag UI                  | 3-4 h    |
| Fallback de listas vacías                            | 1 h      |
| **Total** (después de tener TDRs anotados)           | **1 día** |

### Mejora esperada (combinado con Opción A)

- Reduce falsos negativos en filas problemáticas (#14, #15, #16) que tienen
  profesiones genéricas no enumeradas explícitamente en el PDF
- Estabiliza recall entre runs (variabilidad LLM compensada por diccionario)
- Da al cliente una "red de seguridad" auditable — sabe cuándo el sistema
  rellenó vs cuándo extrajo del PDF

## Verificaciones externas automatizables (SUNAT, colegios)

**Prioridad**: BAJA / extra. No bloquea el deadline, mejora cobertura de
alertas ALT04 (SUNAT) y ALT09 (colegios) que hoy se hacen manuales.

CLAUDE.md actualmente dice "SUNAT verificación manual — tiene CAPTCHA, no
se automatiza". Eso es cierto para el formulario directo, pero hay caminos
viables que no había explorado.

### SUNAT — vía padrón mensual descargable ⭐

SUNAT publica un padrón gratuito con TODOS los RUCs activos (~10M). Incluye
el dato que necesita ALT04: **fecha de inicio de actividades**.

URL: `https://www2.sunat.gob.pe/padron_reducido_ruc.zip`

**Por qué funciona para nuestro caso:**
- ALT04 dispara cuando "empresa constituida después del inicio de
  experiencia". La fecha de inscripción del RUC NO cambia → datos de hasta
  un mes de antigüedad son aceptables.
- Por TDR analizado se verifican 5-20 RUCs (los que firman certificados).
  Lookup local instantáneo, en batch, sin captcha, sin API externa.

**Implementación**:

1. Descarga inicial del padrón
2. Schema `sunat_padron` en PostgreSQL con índice `ruc UNIQUE`
3. Script de import (Python + psycopg2 bulk insert)
4. Endpoint `GET /api/sunat/{ruc}` con lookup local
5. Integrar en `src/validation/` para disparar ALT04 automáticamente
6. Cron mensual (Windows Task Scheduler) que re-importa

**Estimación**: 3-4 h.

**Trade-offs vs alternativas**:

| Opción                              | Costo     | Real-time | On-premise | Recomendada |
|-------------------------------------|-----------|-----------|------------|-------------|
| Padrón mensual                      | $0        | No (≤30d) | Sí         | ⭐           |
| API tercera (ruc.com.pe)            | ~$1/1000  | Sí        | No         | Fallback    |
| Scraping con CAPTCHA solver         | ~$1-3/1000 + frágil | Sí | Sí       | No          |

### Colegios profesionales — investigar caso por caso

CLAUDE.md dice "cada colegio tiene portal distinto, no se automatiza".
Es cierto, pero algunos colegios sí publican padrón:

- **CIP** (Colegio de Ingenieros del Perú): tiene búsqueda pública por
  número de colegiatura. Investigar si hay endpoint sin captcha.
- **CAP** (Colegio de Arquitectos): similar.
- **CMP** (Colegio Médico): tiene padrón web público.
- **CTMP** (Colegio de Tecnólogos Médicos): probablemente similar.

**Estrategia recomendada cuando se aborde**:
- Por cada colegio, evaluar si tiene endpoint público sin captcha
- Si sí → scraping ligero (BeautifulSoup) con cache local de 7 días
- Si no → marcar manual y mostrar link directo en UI

**Estimación**: 1-2h por colegio (4-5 colegios principales = ~6-10h total).

### Cuándo abordarlo

- **No bloquea el deadline**. Hoy las alertas ALT04 y ALT09 se generan como
  "verificación manual" en el Excel y el evaluador las revisa.
- Buen candidato para **post-MVP**, cuando el cliente esté usando el sistema
  y diga "esto sí valdría automatizarlo".
- SUNAT primero (mayor volumen, datos estables, padrón gratuito → quick win).
  Colegios después (más fragmentado, ROI menor).

## Otras mejoras menores (backlog)

1. **Profesiones combinadas** — el LLM ocasionalmente concatena dos profesiones
   en un solo string (ej: "Ingeniero Civil y Arquitecto"). Add post-procesador
   que detecta " y/o " interno y splittea.

2. **Normalización de cargos similares** — pipeline produce variantes ("Jefe de
   Estructuras" vs "Jefe en Estructuras"). Normalizador antes del eval/output.

3. **Anotar más golden sets** — Huancavelica solo tiene 1 anotado. Para
   métricas robustas necesitamos 3-5 TDRs distintos. Prerequisito del
   diccionario de dominio (sección anterior). Ver `tests/golden/README.md`
   sección "Donde conseguir mas TDRs para anotar" para fuentes (cliente
   primero, SEACE como respaldo) + tips de anotación.

4. **Correr eval automáticamente en CI** — cuando se pushea a main, correr
   eval contra el golden y fallar si F1 baja >0.05 vs baseline.

5. **Visualización de cross-row contamination en UI** — marcar visualmente en
   `/jobs/[id]` qué profesiones parecen "fuera de lugar" (típicamente las que
   no matchean profesiones esperadas según el cargo). Esto se beneficia
   directamente del validador del diccionario de dominio (modo 2).

## Decisión y próximo paso

**Plan inmediato**: ir con **Opción A** (extracción fila-por-fila).

**Prerequisito antes de empezar**:
- Confirmar con el cliente que +2 minutos de latencia por TDR es aceptable
- Tener golden set de al menos 1 TDR adicional (no Huancavelica) para evitar
  overfitting al PDF de prueba

**Cuando arrancar**: cuando el cliente valide que la calidad actual no es
suficiente, o cuando proactivamente queramos subir la barra antes del
deadline.
