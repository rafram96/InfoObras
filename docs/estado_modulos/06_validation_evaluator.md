# Módulo: Evaluator (Paso 4)

> `src/validation/evaluator.py` — ~400 líneas — ✅ Completo

## Propósito
Evaluación RTM — 22 columnas por par (profesional, experiencia) según el manual del cliente.

## Funciones

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `evaluar_propuesta(profesionales, experiencias, requisitos_rtm, proposal_date, ...)` | ~80 | Orquestador top-level. Convierte dicts a RequisitoPersonal. Agrupa experiencias por nombre. Retorna `list[ResultadoProfesional]`. |
| `evaluar_profesional(profesional, experiencias, requisitos, proposal_date, ...)` | ~80 | Evalúa un profesional: busca RTM, itera experiencias, genera evaluaciones + alertas. |
| `evaluar_rtm(profesional, experiencia, requisito, proposal_date)` | ~120 | Genera las 22 columnas de una evaluación individual. |
| `_buscar_requisito(profesional, requisitos)` | ~60 | Busca el RequisitoPersonal que corresponde al cargo. 4 niveles de match. |
| `_normalizar_nombre(nombre)` | ~20 | Lowercase + strip para agrupar experiencias por profesional. |

## Búsqueda de requisito — 4 niveles

```
Professional.role vs RequisitoPersonal[].cargo
    │
    ├─ 1. Match exacto (normalizado) → ✅
    ├─ 2. Substring bidireccional → ✅
    ├─ 3. Sinónimos OSCE (_son_cargos_sinonimos) → ✅
    ├─ 4. Jaccard ≥40% (overlap de tokens) → ✅
    └─ 5. Ninguno → None (NO EVALUABLE)
```

## 22 columnas de evaluación

| Cols | Campo | Lógica |
|------|-------|--------|
| 1-3 | Identificación | cargo_postulado, nombre, profesion_propuesta |
| 4-5 | Profesión | requerida (RTM), cumple SI/NO (género neutro) |
| 6 | Folio | del certificado |
| 7-9 | Cargo | experiencia vs válidos (RTM), CUMPLE/NO CUMPLE |
| 10-12 | Proyecto | propuesto vs válido (RTM), SI/NO |
| 13-14 | Fecha término | fecha o "NO VALE" si None |
| 15-17 | Tipo obra | certificado vs requerido, CUMPLE/NO CUMPLE |
| 18-20 | Intervención | certificado vs requerida, CUMPLE/NO CUMPLE |
| 21 | Complejidad | derivada de cols 9+12+17+20 |
| 22 | 20 años | SI si end_date ≥ proposal_date - 20 años |

## Reglas de favorabilidad OSCE
- Si RTM es None → "NO EVALUABLE" (sin falso NO CUMPLE)
- Si un campo RTM es None (bases no especifican) → se asume cumplido
- "no importa" en intervención → CUMPLE

## experiencia_ref
Cada `EvaluacionRTM` guarda referencia a la `Experience` original para que el Excel Writer acceda a empresa, RUC, fechas, firmante, etc.

## Limitaciones
- Jaccard fallback puede misroutear a RTM incorrecto si hay varios parciales
- No hay configuración de umbrales (0.4 Jaccard hardcoded)
- Agrupación por nombre normalizado — frágil con nombres similares

## Dependencias
- `matching` (normalizar_cargo, match_profesion, match_cargo, match_tipo_obra, match_intervencion, _son_cargos_sinonimos)
- `rules` (check_alerts)
- `models` (Professional, Experience, RequisitoPersonal, EvaluacionRTM, ResultadoProfesional)
