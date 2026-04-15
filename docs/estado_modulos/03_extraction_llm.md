# Módulo: LLM Extractor

> `src/extraction/llm_extractor.py` — ~600 líneas — ✅ Completo

## Propósito
Orquesta la extracción LLM (Pasos 2 y 3) sobre texto OCR segmentado por profesional.

## Funciones principales

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `extract_block(block)` | ~70 | Combina Paso 2 + Paso 3 para un ProfessionalBlock. Distingue Tipo A (1 bloque) vs Tipo B (2+ bloques). |
| `extract_professional_info(block)` | ~80 | Paso 2: extrae nombre, DNI, profesión, colegiatura, cargo. Retry + fallback a bloque 0. |
| `extract_experiences(block, name)` | ~100 | Paso 3: extrae todos los certificados. Fallback a ANEXO 16 si lista vacía. |

## Funciones de soporte

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `_filtrar_paginas(texto)` | ~30 | Elimina páginas irrelevantes (contratos, resoluciones, SEACE) con 160+ regex. |
| `_clasificar_paginas_tipo_a(texto)` | ~50 | Para Tipo A: clasifica en anexo16, diplomas, certificados, ruido. |
| `_validar_paso2(result)` | ~30 | Valida schema de Paso 2 (nombre obligatorio, no texto volcado). |
| `_validar_paso3(result)` | ~30 | Valida schema de Paso 3 (lista experiencias, sinónimos raíz). |
| `_normalizar_experiencia(exp)` | ~60 | Mapea 70+ sinónimos de campo → schema canónico. Parsea fechas a ISO. |
| `_parsear_fecha(texto)` | ~40 | Parsea fechas españolas: "10 de enero del 2023", "01/ENE/2018", "15/03/2020", ISO. |

## Flujo de extracción

```
ProfessionalBlock
    │
    ├─ Tipo B (3+ bloques): bloque 1 → Paso 2, bloque 2 → Paso 3
    └─ Tipo A (1 bloque):   clasificar páginas → Paso 2 + Paso 3
         │
         ▼
    filtrar páginas (quitar contratos/legal)
         │
         ▼
    LLM (Qwen 14B) → JSON
         │
         ▼
    validar schema → retry si falla
         │
         ▼
    normalizar campos (sinónimos + parseo fechas)
```

## Campos parseados por _parsear_fecha()

| Formato | Ejemplo | Soportado |
|---------|---------|-----------|
| Texto español | "10 de enero del 2023" | ✅ |
| Abreviatura | "01/ENE/2018" | ✅ |
| Numérico | "15/03/2020" | ✅ |
| ISO | "2023-01-15" | ✅ |
| "a la fecha" | — | ✅ (retorna None) |
| Manuscrito/corrupto | — | ❌ |

## Sinónimos de campo (70+)
Mapean nombres en español e inglés al schema canónico:
- `"project" → "proyecto"`, `"company" → "empresa_emisora"`
- `"signer" → "firmante"`, `"work_type" → "tipo_obra"`
- etc.

## Limitaciones
- Filtro de páginas puede ser agresivo con contenido legítimo mezclado con legal
- Fallback chain complejo — difícil de debuggear
- Parseo de fechas falla con formatos no estándar o manuscritos
- Tipo B depende de delimitadores consistentes del motor-OCR

## Dependencias
- `ollama_client`, `md_parser`, `prompts`
