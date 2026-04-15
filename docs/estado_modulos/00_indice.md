# Estado de Módulos — Índice

> **Actualizado:** 2026-04-15
> **Total módulos:** 10 | **~4,500 líneas** | **85+ funciones**

| # | Módulo | Archivo | Líneas | Estado | Funciones |
|---|--------|---------|--------|--------|-----------|
| 1 | [Extracción: Parser](01_extraction_parser.md) | `src/extraction/md_parser.py` | ~210 | ✅ Completo | 5 |
| 2 | [Extracción: Ollama Client](02_extraction_ollama.md) | `src/extraction/ollama_client.py` | ~60 | ✅ Completo | 1 |
| 3 | [Extracción: LLM Extractor](03_extraction_llm.md) | `src/extraction/llm_extractor.py` | ~600 | ✅ Completo | 9 |
| 4 | [Validación: Matching](04_validation_matching.md) | `src/validation/matching.py` | ~550 | ✅ Completo | 9 + 3 diccionarios |
| 5 | [Validación: Rules](05_validation_rules.md) | `src/validation/rules.py` | ~400 | ✅ Completo | 6 + 9 alertas |
| 6 | [Validación: Evaluator](06_validation_evaluator.md) | `src/validation/evaluator.py` | ~400 | ✅ Completo | 5 |
| 7 | [Scraping: InfoObras](07_scraping_infoobras.md) | `src/scraping/infoobras.py` | ~1000 | ✅ Completo | 10 públicas + 9 helpers |
| 8 | [Reportes: Excel Writer](08_reporting_excel.md) | `src/reporting/excel_writer.py` | ~600 | ✅ Completo | 6 + 6 helpers |
| 9 | [TDR: Configuración](09_tdr_config.md) | `src/tdr/config/signals.py` | ~200 | ✅ Completo | 4 prompts + 5 categorías scoring |
| 10 | [TDR: Pipeline](10_tdr_pipeline.md) | `src/tdr/extractor/pipeline.py` | ~1000 | ✅ Completo | 20+ funciones |

## Flujo de dependencias

```
prompts.py ──→ llm_extractor.py ──→ md_parser.py
                    │                     │
                    ▼                     ▼
              ollama_client.py    parse_page_texts()
                                  parse_professional_blocks()
                    │
                    ▼
              matching.py ←── evaluator.py ←── rules.py
                    │               │
                    ▼               ▼
              infoobras.py    excel_writer.py
```

## Limitaciones transversales

1. **Parseo de fechas** — funciona con formatos comunes pero falla con formatos no estándar o manuscritos
2. **Similitud Jaccard** — poco confiable con strings cortos (<3 tokens)
3. **COVID** — el descuento puede ser impreciso si múltiples experiencias solapan con el mismo periodo
4. **Tablas VL** — umbral del 60% puede misclasificar contenido mixto
5. **Verificaciones manuales** — ALT04 (SUNAT) y ALT09 (colegios) requieren intervención del evaluador
