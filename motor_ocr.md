# Motor OCR — Arquitectura

## Qué es

Motor de OCR para expedientes de licitaciones públicas peruanas. Extrae texto de PDFs escaneados y segmenta el documento por profesional (Gerente, Jefe, Especialistas, etc.).

## Pipeline

```
PDF → Imágenes (300 DPI) → Paddle OCR (subproceso) → Qwen fallback → Segmentación → Consolidación
```

### Fase 1: OCR

1. **PDF → PNG**: Convierte cada página a imagen a 300 DPI
2. **Pasada 1 — PaddleOCR** (subproceso aislado): Procesa TODAS las páginas. Corre en subprocess para liberar VRAM al terminar.
3. **Pasada 2 — Qwen-VL** (proceso principal): Solo para páginas donde Paddle falló (confianza < 0.80 **Y** tasa descarte > 0.45). Usa Ollama local con `qwen2.5vl:7b`. Reintenta con imagen más pequeña (2048 → 1024 → 768px).

### Fase 2: Segmentación

1. **Pre-filtro** (`es_candidata_separadora`): Páginas con 1-15 líneas limpias. Lista blanca de patrones de cargo (gerente, jefe, supervisor, especialista, coordinador, residente). Lista negra de frases de descarte.
2. **Clasificación** (`evaluar_separadora`): Qwen-VL analiza la imagen (reducida al 50%) y devuelve JSON: `{es_separadora, cargo, confianza}`. Si Qwen falla → fuzzy matching contra CARGOS_BASE (53 cargos).
3. **Agrupación**: Páginas entre separadoras consecutivas forman una sección.

### Fase 3: Consolidación

Detecta documentos **Tipo B** donde el mismo profesional aparece en múltiples bloques temáticos (B.1 Calificaciones, B.2 Experiencia, B.3 Equipamiento) y los fusiona en un solo `ProfessionalSection`.

## Estructura del proyecto

```
src/
├── main.py                     # Orquestador (process_document, process_and_segment)
├── config.py                   # Configuración global
├── models/
│   ├── page_result.py          # PageResult (OCR de una página)
│   └── document_result.py      # DocumentResult (métricas del documento)
├── engines/
│   ├── paddle_engine.py        # Wrapper PaddleOCR
│   └── qwen_engine.py          # Wrapper Qwen-VL vía Ollama
├── pipeline/
│   ├── pdf_to_images.py        # PDF → PNG
│   ├── page_processor.py       # Lógica de una página
│   ├── paddle_worker.py        # Worker del subproceso Paddle
│   └── decision.py             # Criterio de fallback a Qwen
├── segmentation/
│   ├── segmenter.py            # Orquestador segmentación
│   ├── detector.py             # Clasificador de separadoras (Qwen + fuzzy)
│   ├── consolidator.py         # Fusión de bloques duplicados
│   ├── config.py               # CARGOS_BASE, PATRONES_CARGO, NORMALIZACIONES
│   ├── models/
│   │   ├── professional_section.py
│   │   └── separator_page.py
│   └── output/
│       ├── markdown_writer.py          # Reporte segmentación
│       └── consolidation_writer.py     # Reporte profesionales
└── output/
    └── markdown_writer.py      # Reportes OCR (métricas + texto)

run.py                          # Entrada producción (documento completo)
run_test.py                     # Entrada testing (rango de páginas)
```

## Modelos de datos clave

### PageResult
```
page_number, image_path, engine_used ("paddle"|"qwen"|"error"),
text, lines, line_scores,
conf_promedio, conf_mediana, conf_min, conf_max, conf_std,
det_count, rec_count, tasa_descarte,
lineas_baja_confianza, angle_detected, tiene_tabla,
tiempo_paddle, tiempo_qwen, tiempo_total
```

### ProfessionalSection
```
section_index, cargo, cargo_raw, numero (N°1, N°2...),
separator_page, pages[], total_pages, has_tables,
bloques_origen[] (para Tipo B)
```

### SeparatorPage
```
page_number, es_separadora, cargo_detectado, cargo_normalizado,
confianza_qwen ("alta"|"media"|"baja"), metodo ("qwen"|"fuzzy_fallback"|"descartada")
```

## Configuración principal

| Parámetro | Valor | Propósito |
|-----------|-------|-----------|
| `UMBRAL_CONFIANZA_PROMEDIO` | 0.80 | Fallback a Qwen si conf < esto |
| `UMBRAL_TASA_DESCARTE` | 0.45 | Fallback a Qwen si descarte > esto |
| `MAX_LINEAS_SEPARADORA` | 15 | Máx líneas para candidata a separadora |
| `FUZZY_SCORE_MINIMO` | 80 | Umbral fuzzy matching |
| `QWEN_MODEL` | qwen2.5vl:7b | Modelo Ollama |
| `PDF_DPI` | 300 | Resolución de extracción |
| `MAX_WORKERS` | 4 | Workers paralelos |

## Arquitectura de subproceso

PaddleOCR corre en **subprocess aislado** para evitar conflicto de VRAM con Qwen:

```
Main process                    Subprocess (paddle_worker.py)
    │                               │
    ├── Serializa args (JSON) ──────►  Carga PaddleOCR (~500MB VRAM)
    │                               │  Procesa todas las páginas
    │                               │  Serializa resultados (pickle)
    │◄── Lee resultados ────────────┤  Exit (VRAM liberada por OS)
    │
    ├── Pasada 2: Qwen (si necesario)
    └── Segmentación
```

## Outputs

Por cada documento se generan hasta 4 reportes markdown:
1. `{nombre}_metricas_{ts}.md` — Métricas OCR por página
2. `{nombre}_texto_{ts}.md` — Texto extraído por página
3. `{nombre}_segmentacion_{ts}.md` — Candidatas evaluadas, separadoras detectadas
4. `{nombre}_profesionales_{ts}.md` — Profesionales consolidados con rangos de páginas

## Hardware actual

- **CPU**: Intel i9
- **GPU**: Quadro RTX 5000 (16GB VRAM, 448 GB/s bandwidth)
- **Bottleneck**: Inferencia Qwen-VL (~20-30s por llamada). Bandwidth de VRAM limita tokens/s.
