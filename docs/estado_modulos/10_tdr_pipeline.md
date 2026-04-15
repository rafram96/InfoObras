# Módulo: TDR Pipeline

> `src/tdr/extractor/pipeline.py` — ~1000 líneas — ✅ Completo

## Propósito
Pipeline completo de extracción de requisitos TDR: texto OCR → scoring → bloques → LLM → dedup → merge → output.

## Función principal

```python
extraer_bases(full_text, nombre_archivo, pdf_path, output_dir) → dict
```

Retorna:
```python
{
    "rtm_postor": [...],
    "rtm_personal": [...],
    "factores_evaluacion": [...],
    "_bloques_detectados": [...],
    "_tablas_stats": {...}
}
```

## Funciones clave

### Preprocesamiento
| Función | Descripción |
|---------|-------------|
| `_comprimir_tabla_vl()` | Elimina filas de tabla con celdas > 200 chars (bloat de descripciones) |
| `_es_pagina_tabla_vl()` | Detecta si una página es >60% tabla markdown |
| `_subdividir_bloque()` | Divide bloques > 15K chars con overlap de 1 página |

### Extracción
| Función | Descripción |
|---------|-------------|
| `extraer_bases()` | Orquestador principal (~150 líneas). Coordina todo el pipeline. |

### Post-procesamiento
| Función | Descripción |
|---------|-------------|
| `_dedup_personal()` | Fusiona duplicados por cargo normalizado |
| `_merge_deep()` | Merge de dicts con prioridad a fuente VL sobre LLM |
| `_filtrar_asistentes()` | Elimina asistentes cuando existen especialistas |
| `_filtrar_meta_cargos()` | Elimina cargos genéricos (Consultoría, Modelador BIM) |
| `_limpiar_anos_colegiado()` | Quita sufijos OSCE del campo años colegiado |
| `_filtrar_registros_vacios()` | Elimina registros con ≥80% campos null |
| `_cruzar_personal_con_factores()` | Vincula factores de evaluación a personal por cargo |
| `_cruzar_postor_con_factores()` | Vincula factores a requisitos del postor |
| `_merge_capacitacion()` | Fusiona datos de capacitación por cargo |

### Utilidades
| Función | Descripción |
|---------|-------------|
| `_es_nulo()` | Normaliza null/None/empty |
| `_contar_campos()` | Cuenta campos no-null |
| `_extraer_numero_de_string()` | "48 meses" → 48 |
| `_similarity_cargo()` | Jaccard de tokens de cargo |
| `_extraer_especialidad()` | "Asistente de X" → "X" |
| `_guardar_debug_bloques()` | Debug output a bloques_debug.md |

## Flujo del pipeline

```
full_text (de motor-OCR o pdfplumber)
    │
    ▼
parse_full_text() → PageResult[]
    │
    ▼
score_page() por cada página → PageScore[]
    │
    ▼
[Mejora de tablas con Qwen VL si pdf_path disponible]
    │   mejorar_texto_con_tablas() → full_text mejorado
    │   re-parsear y re-scorear
    │
    ▼
group_into_blocks() → Block[] (rtm_postor, rtm_personal, factores, capacitacion)
    │
    ▼
Por cada bloque:
    ├─ _subdividir_bloque() si > 15K chars
    ├─ _comprimir_tabla_vl() para tablas grandes
    └─ extraer_bloque(texto, tipo) → dict via Ollama
    │
    ▼
Post-procesamiento:
    ├─ _dedup_personal() — fusionar duplicados
    ├─ _merge_capacitacion() — cruzar con sección capacitación
    ├─ _limpiar_anos_colegiado() — normalizar
    ├─ _filtrar_asistentes() — quitar asistentes redundantes
    ├─ _filtrar_meta_cargos() — quitar genéricos
    ├─ _cruzar_personal_con_factores() — vincular factores
    ├─ _cruzar_postor_con_factores() — vincular factores postor
    └─ _filtrar_registros_vacios() — limpiar ≥80% null
    │
    ▼
Resultado: {rtm_postor, rtm_personal, factores_evaluacion}
```

## Módulos auxiliares del TDR

| Archivo | Descripción |
|---------|-------------|
| `parser.py` | Divide full_text en páginas |
| `scorer.py` | Scoring de relevancia por página + agrupación en bloques |
| `llm.py` | Llamadas a Ollama para extracción de bloques |
| `report.py` | Genera reporte diagnóstico markdown |
| `tables/enhancer.py` | Mejora tablas con Qwen VL |
| `tables/detector.py` | Detección heurística de tablas |
| `tables/vision.py` | Procesamiento visual de tablas |
| `tables/docling_client.py` | Integración Docling (opcional) |
| `clients/motor_ocr_client.py` | Subprocess wrapper para motor-OCR |
| `config/settings.py` | Constantes (timeouts, modelos, umbrales) |

## Limitaciones
- Pipeline largo y complejo — difícil debuggear fallos intermedios
- Subdivision con overlap puede causar extracción duplicada
- _merge_deep() prioriza VL sobre LLM de forma hardcoded
- _dedup_personal() puede over-merge cargos similares pero distintos
- Depende de consistencia del scoring para clasificar bloques correctamente
- No genera reporte de errores de extracción por bloque

## Dependencias
- `signals`, `parser`, `scorer`, `llm`, `report` (internos TDR)
- `matching.normalizar_cargo` (para dedup)
- `ollama_client` (indirecto via llm.py)
