# Módulo: Extraction Parser

> `src/extraction/md_parser.py` — ~210 líneas — ✅ Completo

## Propósito
Parsea los archivos `.md` generados por motor-OCR y los combina en `ProfessionalBlock[]`.

## Funciones

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `parse_page_texts(texto_path)` | ~40 | Lee `*_texto_*.md` y retorna `{num_pagina: texto}`. Divide por `## Página N` y extrae contenido entre bloques de código. |
| `_extract_numero(cargo_raw)` | ~15 | Extrae "N°1", "N°2" del nombre del cargo con regex. |
| `_clean_cargo(cargo_raw)` | ~10 | Elimina números del nombre del cargo. |
| `_parse_summary_table(content)` | ~60 | Parsea la tabla de resumen del archivo de profesionales. Soporta 2 formatos: viejo (5 cols: # \| Cargo \| Págs \| Inicio \| Fin) y nuevo (6 cols: # \| Cargo \| N° \| Págs \| Bloques \| Inicio). Auto-detecta el formato. |
| `parse_professional_blocks(prof_path, texto_path)` | ~85 | Orquestador principal. Combina `*_profesionales_*.md` + `*_texto_*.md`. Divide por `### N. Cargo`, extrae page_ranges del texto o de la tabla resumen, construye `ProfessionalBlock` con texto por bloque. |

## Formatos soportados

### Tabla vieja (5 columnas)
```
| # | Cargo | Págs | Pág. inicio | Pág. fin |
```

### Tabla nueva (6 columnas)
```
| # | Cargo | N° | Págs totales | Bloques | Pág. inicio |
```
Los bloques pueden tener múltiples rangos: `46–63 · 81–88 · 142–155`

## Edge cases manejados
- Auto-detección de formato de tabla
- Múltiples rangos de páginas por profesional (Tipo B)
- Fallback a tabla resumen si no hay rangos inline
- Exclusión de página separadora del rango de contenido

## Limitaciones
- Depende de estructura markdown consistente del motor-OCR
- Si el OCR produce output muy corrupto, puede no encontrar separadores

## Dependencias
- Ninguna (módulo base de parsing)
