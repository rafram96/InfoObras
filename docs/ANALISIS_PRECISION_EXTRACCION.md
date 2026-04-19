# Análisis de Precisión — Pipeline de Extracción

> ⚠️ **DOCUMENTO REEMPLAZADO (18-abr-2026):** Su contenido se consolidó en [`docs/PLAN_MEJORAS_UNIFICADO.md`](./PLAN_MEJORAS_UNIFICADO.md) junto con el plan pdfplumber y los 7 fixes nuevos de la reunión con el cliente. Se deja este archivo solo como referencia histórica del análisis original.
>
> **Contexto:** El TDR falló en la prueba de hoy. Necesito mejorar la precisión de extracción antes de la demo.
> **Fecha:** 2026-04-18

---

## Resumen ejecutivo

El pipeline tiene **37 issues de precisión** identificados, la mayoría en el **extractor TDR (Paso 1)**. Los más críticos:

1. **Tablas OCR entrelazadas** — B.2 con 4+ profesionales solo extrae 1-2
2. **Dedup pierde sinónimos de cargo** — al fusionar duplicados, lista de cargos similares se pierde
3. **Filtros muy agresivos** — pages/asistentes válidos son descartados
4. **Prompt TDR con reglas contradictorias** — LLM confundido

**Ganancia estimada si se aplican los top 5 fixes: +20-30% precisión**

---

## Issues por componente (prioridad descendente)

### 🔴 CRÍTICOS — TDR Extractor (Paso 1)

#### 1. Tablas OCR entrelazadas no se extraen completas
**Archivo:** `src/tdr/config/signals.py` (PROMPT_RTM_PERSONAL)
**Síntoma:** B.2 con 4 profesionales → LLM extrae solo 1 o 2
**Causa:** El prompt dice "cargo más cercano a N meses" pero en OCR fragmentado los cargos quedan a 5+ líneas del "48 meses"
**Ejemplo real:**
```
Jefe de expediente 48 meses Coordinador 36 meses Especialista en estructuras 24 meses
Arquitecto Ingeniero Ingeniero Civil desempeñado del cargo desempeñado del cargo
```
**Fix:** Agregar al prompt: *"Si ves N instancias de 'X meses en el cargo', extrae N profesionales aunque los cargos estén mezclados. Usa proximidad POSICIONAL (cargo más cercano espacialmente a cada 'X meses'), no similitud semántica."*

#### 2. `_dedup_personal` pierde cargos similares al merge
**Archivo:** `src/tdr/extractor/pipeline.py` líneas 318, 360-375
**Síntoma:** Profesional queda con menos alternativas de cargo válido
**Causa:** En `_merge_deep`, para listas se elige la más larga en vez de unirlas
**Ejemplo:**
- Entry 1: `cargos_similares_validos: ["Jefe", "Gestor"]`
- Entry 2: `cargos_similares_validos: ["Jefe", "Coordinador"]`
- Merge: usa ["Jefe", "Gestor"] o ["Jefe", "Coordinador"] (una u otra, no ambas) → pierde "Coordinador"

**Fix:** Cambiar a `resultado[k] = list(set(base_v + v))` para unir ambas listas.

#### 3. Umbral de score muy alto filtra páginas válidas
**Archivo:** `src/tdr/extractor/scorer.py`
**Síntoma:** Páginas con RTM válido son descartadas por "baja confianza"
**Causa:** `SCORER_MIN_SCORE` típico es 3.0-4.0, pero páginas reales con OCR fragmentado scorean 2.5-3.2
**Fix:** Bajar a 2.0 específicamente para bloques `rtm_personal`.

#### 4. Compresión de tablas VL borra filas largas válidas
**Archivo:** `src/tdr/extractor/pipeline.py` línea 43 `_MAX_CELDA = 200`
**Síntoma:** Filas con descripciones largas (250-500 chars) desaparecen
**Causa:** Threshold `_MAX_CELDA=200` elimina filas donde cualquier celda supere 200 chars
**Fix:** Subir a 600, o detectar cabeceras y solo comprimir filas con "Descripción" > 200.

#### 5. Detección de tabla fragmentada con ratio muy alto
**Archivo:** `src/tdr/tables/detector.py` línea 40-44
**Síntoma:** B.2 con 12 items queda sin detectar como tabla
**Causa:** `ratio_cortas > 0.5` requiere 50%+ de líneas < 30 chars, pero OCR real tiene líneas de 40-80 chars
**Fix:** Cambiar a `len(l.strip()) < 50` (más amplio) y `ratio > 0.4`.

---

### 🟠 ALTOS — TDR Prompts

#### 6. `tipo_obra_valido` con regla de null demasiado agresiva
**Archivo:** `src/tdr/config/signals.py` PROMPT_RTM_PERSONAL línea 267
**Síntoma:** Notas con sector válido quedan como null
**Causa actual:** "null si la nota dice 'en entidades públicas y/o privadas'"
**Problema:** Si la nota es "Obras de salud en entidades públicas y privadas" → LLM confundido, puede devolver null perdiendo "salud"
**Fix:** Reemplazar por: *"Extrae SOLO la palabra del sector (salud, vial, educacion...). Ignora el contexto sobre público/privado DESPUÉS de extraer el sector. Si hay múltiples sectores, lístalos todos."*

#### 7. `cargos_similares_validos` sin límite de búsqueda
**Archivo:** `src/tdr/config/signals.py` PROMPT_RTM_PERSONAL línea 263
**Síntoma:** LLM incluye texto no relacionado como cargo similar
**Causa:** Dice "aparecen antes del N meses" sin limitar la ventana de búsqueda
**Fix:** *"Busca 'X y/o Y' SOLO en la celda/fila inmediatamente anterior al patrón 'N meses' (máximo 2 líneas). Detente en cualquier puntuación que cierre la cláusula."*

#### 8. `anos_colegiado` puede ser int en vez de string
**Archivo:** `src/tdr/config/signals.py` PROMPT_RTM_PERSONAL línea 258
**Síntoma:** `_extraer_numero_de_string(anos)` devuelve None silenciosamente
**Fix:** Agregar al prompt: *"Devolver como string: '36 meses', no como entero 36."*

#### 9. `aplica_a: ambos` causa que factores se pierdan
**Archivo:** `src/tdr/config/signals.py` PROMPT_FACTORES
**Síntoma:** Factores que aplican a postor+personal son ignorados en `_cruzar_personal_con_factores`
**Causa:** Código filtra `if f.get("aplica_a") == "personal"` → salta los "ambos"
**Fix:** Prompt: *"Si un factor aplica a ambos, divídelo en DOS objetos JSON separados con aplica_a='postor' y aplica_a='personal'."*

---

### 🟠 ALTOS — Pipeline TDR (post-LLM)

#### 10. `_filtrar_asistentes` descarta asistentes válidos sin especialistas
**Archivo:** `src/tdr/extractor/pipeline.py` línea 436-437
**Síntoma:** Documentos con solo asistentes retornan lista vacía
**Causa:** Filtro demasiado agresivo si no hay especialistas en el documento
**Fix:** Eliminar este filtro o hacerlo condicional (solo cuando haya sección "personal clave" explícita).

#### 11. `_filtrar_meta_cargos` regex demasiado estricto
**Archivo:** `src/tdr/extractor/pipeline.py` línea 479
**Síntoma:** "Consultor de Ingeniería Civil" no matchea el patrón `^consultor\s+de\s+ingenier[ií]a$`
**Fix:** Cambiar a `r"^consultor\s+de\s+ingenier"` (sin `$`).

#### 12. `_cruzar_personal_con_factores` solo aplica el primer factor genérico
**Archivo:** `src/tdr/extractor/pipeline.py` línea 613-643
**Síntoma:** Si hay 5 factores genéricos, solo se aplica el primero a todos
**Causa:** `factor_gen = factores_genericos[0]`
**Fix:** Aplicar todos los factores genéricos, no solo el primero.

#### 13. `_merge_capacitacion` sobrescribe datos válidos de RTM
**Archivo:** `src/tdr/extractor/pipeline.py` línea 779
**Síntoma:** Horas de capacitación extraídas por LLM desaparecen al merge con bloque VL
**Causa:** Siempre prefiere VL aunque no tenga hours
**Fix:** `if cap_match and cap_match.get("duracion_minima_horas")` — solo sobrescribir si VL tiene hours.

#### 14. `_filtrar_registros_vacios` descarta profesionales válidos
**Archivo:** `src/tdr/extractor/pipeline.py` línea 254
**Síntoma:** Profesional con `experiencia_minima` parcialmente llena es descartado
**Causa:** Umbral 80% null cuenta recursivamente todos los campos del dict anidado
**Fix:** Solo filtrar si hay 3+ campos: `if ratio >= umbral and len(total) >= 3`.

#### 15. Agrupación de páginas VL fusiona tablas distintas
**Archivo:** `src/tdr/tables/enhancer.py` línea 277-295
**Síntoma:** B.1 (pp. 136-139) + B.2 (pp. 140-143) agrupadas en un batch de 8 páginas → Qwen VL solo ve B.1
**Fix:** Detectar cambios de tabla dentro del grupo y dividir.

---

### 🟡 MEDIOS — Extracción Profesionales (Pasos 2-3)

#### 16. PASO3_PROMPT — "a la fecha" no coincide con código
**Archivo:** `src/extraction/prompts.py` línea 54
**Síntoma:** LLM devuelve `fecha_fin: "a la fecha"` como texto, luego `_parsear_fecha` falla silenciosamente
**Causa:** Prompt dice "usa el texto 'a la fecha'", pero código luego intenta parsear como fecha
**Fix:** Prompt: *"Si dice 'a la fecha', devuelve null (NO devolver el texto 'a la fecha')."*

#### 17. `_filtrar_paginas` regex demasiado amplio
**Archivo:** `src/extraction/llm_extractor.py` línea 26-43
**Síntoma:** Páginas con "CLÁUSULA del certificado" son descartadas (son válidas)
**Causa:** `CLÁUSULA` matchea cualquier mención
**Fix:** `r"CLÁUSULA\s*\d+\s*[.:-]"` (requiere número y puntuación).

#### 18. PASO2_PROMPT — CUI confundido con DNI
**Archivo:** `src/extraction/prompts.py` línea 17
**Síntoma:** LLM mete código CUI (8 dígitos) en el campo DNI
**Fix:** Agregar: *"Si encuentras un número de 8 dígitos etiquetado como 'CUI' o 'Código de Obra', NO lo uses como DNI. DNI aparece en documentos de identidad ('carnet', 'DNI'), CUI en documentos de proyecto."*

#### 19. `_normalizar_experiencia` no maneja fechas solo con años
**Archivo:** `src/extraction/llm_extractor.py` línea 475-483
**Síntoma:** "año 2017 al año 2020" se queda como texto crudo
**Fix:** Agregar fallback con regex para años: `r"(\d{4})\s*al\s*(\d{4})"` → `"01/01/YYYY"`.

#### 20. `_deduplicar_experiencias` colapsa por truncado de empresa
**Archivo:** `src/extraction/llm_extractor.py` línea 514-530
**Síntoma:** "Consorcio ABC S.A." y "Consorcio ABC" se deduplican (son diferentes)
**Fix:** Normalizar antes de hashear: `proyecto = normalizar_texto(proyecto[:50])`.

#### 21. Retry de Paso 2 no preserva intento exitoso parcial
**Archivo:** `src/extraction/llm_extractor.py` línea 621-651
**Síntoma:** Si dos intentos fallan, se devuelve el primer resultado fallido
**Fix:** Tercer fallback: combinar bloques 0+1 como texto unificado si es Tipo B.

---

### 🟡 MEDIOS — Matching (Paso 4)

#### 22. SINONIMOS_SECTOR — sectores faltantes
**Archivo:** `src/validation/matching.py` líneas 16-58
**Faltantes:** "energia" (hidroeléctrica, transmisión), "telecomunicaciones", "residuos", "patrimonio_cultural"
**Fix:** Agregar 4 grupos con sus sinónimos.

#### 23. SINONIMOS_CARGO — especialidades faltantes
**Archivo:** `src/validation/matching.py` líneas 241-279
**Faltantes:**
- "Especialista en Estructuras" (crítico - muy común)
- "Especialista en Topografía" / "Topógrafo"
- "Especialista en Acabados"
- "Ingeniero de Sistemas" / "Informático"

#### 24. `_buscar_requisito` retorna PRIMERO, no MEJOR match
**Archivo:** `src/validation/evaluator.py` línea 60-73
**Síntoma:** Si hay dos entradas del mismo cargo (básico vs avanzado), solo matchea la primera
**Fix:** Retornar el requisito con MAYOR `experiencia_minima.cantidad` (umbral más estricto).

#### 25. `match_cargo` substring sin threshold
**Archivo:** `src/validation/matching.py` línea 351
**Síntoma:** Match demasiado permisivo (cualquier substring)
**Fix:** `if norm_exp == norm_val or len(norm_exp) > len(norm_val) * 0.8 and norm_val in norm_exp`

#### 26. `evaluar_rtm` no maneja None de match_cargo
**Archivo:** `src/validation/evaluator.py` línea 157
**Síntoma:** Si match es ambiguo (None), se trata como False → "NO CUMPLE"
**Fix:** Tres-way: `True → CUMPLE`, `False → NO CUMPLE`, `None → NO EVALUABLE`

#### 27. `_buscar_requisito` umbral Jaccard 40% demasiado bajo
**Archivo:** `src/validation/evaluator.py` línea 90
**Síntoma:** Matches falsos positivos en cargos con tokens comunes
**Fix:** Subir a 60% o requerir match exacto de palabra clave (ej: "estructuras" debe aparecer en ambos).

---

## Priorización para implementar

### Bloque A — Fixes rápidos de alto impacto (2-3 horas total)

Estos 5 fixes deberían restaurar ~20% de precisión:

| # | Issue | Tiempo | Impacto |
|---|-------|--------|---------|
| 2 | `_dedup_personal` union de listas | 10 min | +5-8% |
| 3 | Bajar `SCORER_MIN_SCORE` a 2.0 | 5 min | +8-12% |
| 4 | Subir `_MAX_CELDA` a 600 | 2 min | +4-7% |
| 5 | Ajustar detector de tabla fragmentada | 10 min | +3-5% |
| 10 | Eliminar `_filtrar_asistentes` agresivo | 10 min | +2-3% |

### Bloque B — Mejoras de prompts (3-4 horas)

Re-escribir prompts críticos:

| # | Issue | Tiempo |
|---|-------|--------|
| 1 | Nueva regla para tablas entrelazadas en PROMPT_RTM_PERSONAL | 30 min |
| 6 | Simplificar regla `tipo_obra_valido` | 15 min |
| 7 | Limitar ventana de búsqueda `cargos_similares_validos` | 15 min |
| 16 | "a la fecha" → null en PASO3 | 5 min |
| 18 | Distinguir CUI vs DNI en PASO2 | 10 min |

**Después de cada cambio de prompt**, hay que re-correr TDR para verificar.

### Bloque C — Mejoras de matching (1-2 horas)

| # | Issue | Tiempo |
|---|-------|--------|
| 22 | Agregar 4 sectores faltantes | 15 min |
| 23 | Agregar 4 grupos de cargos faltantes | 20 min |
| 24 | `_buscar_requisito` retorna MEJOR match | 15 min |
| 26 | Manejar None en `match_cargo` | 10 min |

### Bloque D — Correcciones menores (1-2 horas)

Issues 11-15, 17, 19-21, 25, 27 — cada uno 10-20 minutos.

---

## Root cause del fallo de hoy

El TDR falló probablemente por la combinación de:

1. **Tablas B.2 entrelazadas** → solo 1-2 profesionales de 10+ extraídos
2. **Dedup perdió sinónimos** → matching posterior falla
3. **Páginas válidas filtradas por score bajo** → RTM incompleto
4. **`_filtrar_asistentes` descartó roles legítimos** → roster incompleto
5. **`tipo_obra_valido` quedó con "en entidades públicas"** → evaluador falla

---

## Siguiente paso recomendado

**Opción 1 — Ataque incremental:**
- Aplicar Bloque A (30 min)
- Correr TDR de prueba
- Medir delta
- Decidir próximo bloque

**Opción 2 — Ataque completo:**
- Aplicar Bloques A + B + C (7-8 horas)
- Una sola corrida de TDR al final
- Comparar contra el Excel manual del cliente

**Opción 3 — Solo lo crítico para el sábado:**
- Bloques A + top 3 de B (issues 1, 6, 7)
- 4 horas total
- Suficiente para no ser humillante en la demo

---

## Lo que NO podemos arreglar con prompt/código

- OCR de mala calidad en el PDF original (problema de motor-OCR)
- Bases con formato atípico (no-OSCE)
- Tablas con más de 4 niveles de anidación

Para estos casos, mantener el fallback de "NO EVALUABLE" + flag de revisión manual.

---

## Preguntas para decidir

1. ¿Qué bloque priorizamos para el sábado?
2. ¿Tenemos tiempo para re-correr TDR 2-3 veces y medir delta?
3. ¿El cliente tiene un Excel "correcto" contra el que podamos comparar?
4. ¿Vale la pena arreglar el prompt (requiere re-correr) o mejor los fixes de código puro (no requieren re-correr)?
