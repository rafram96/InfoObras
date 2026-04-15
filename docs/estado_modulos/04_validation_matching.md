# Módulo: Matching

> `src/validation/matching.py` — ~550 líneas — ✅ Completo

## Propósito
Normalización de texto y comparación de campos para el motor de reglas (Paso 4). También usado por el pipeline TDR para dedup de cargos.

## Funciones principales

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `normalizar_texto(texto)` | ~15 | Lowercase, sin acentos, sin stopwords (17 artículos/preposiciones). |
| `normalizar_cargo(cargo)` | ~40 | Maneja "y/o", "en la especialidad de", frases de acción, corrección OCR. Extraído de `pipeline.py`. |
| `es_genero_neutro(a, b)` | ~20 | "Ingeniero" == "Ingeniera" → reemplaza -o/-a por -@. |
| `match_profesion(propuesta, aceptadas)` | ~25 | Match gender-neutral. None/vacío → True (favorabilidad OSCE). |
| `match_cargo(cargo_exp, cargos_validos)` | ~50 | 3 niveles: exacto → substring → sinónimos OSCE. |
| `match_tipo_obra(proyecto, requerido)` | ~30 | Compara sector con diccionario de sinónimos. Retorna True/False/None. |
| `match_intervencion(cert, req)` | ~30 | "no importa" → True. Compara por clave de intervención. |
| `inferir_tipo_obra(project_name)` | ~20 | "Hospital Regional" → "salud". Busca en SINONIMOS_SECTOR. |
| `inferir_intervencion(project_name)` | ~20 | "Mejoramiento y Ampliación" → "mejoramiento". |

## Diccionarios

### SINONIMOS_SECTOR (9 sectores)
```
salud:        hospital, centro de salud, clinica, policlinico, essalud...
educacion:    colegio, institucion educativa, escuela, universidad...
vial:         carretera, puente, autopista, camino vecinal, pavimentacion...
saneamiento:  agua potable, alcantarillado, ptar, reservorio...
edificacion:  edificio, vivienda, residencial, condominio...
riego:        irrigacion, canal, bocatoma, represa...
transporte:   terminal, aeropuerto, puerto, estacion, metro...
deportivo:    estadio, coliseo, polideportivo, losa deportiva...
institucional: municipalidad, comisaria, local comunal...
```

### PALABRAS_INTERVENCION (12 tipos)
```
construccion, mejoramiento, ampliacion, rehabilitacion, remodelacion,
supervision, expediente tecnico, instalacion, creacion, sustitucion,
demolicion, mantenimiento
```

### SINONIMOS_CARGO (7 grupos)
```
BIM:          especialista bim, gestor bim, coordinador bim, lider bim...
Costos:       especialista en costos, metrados, presupuestos, valorizaciones...
Equipamiento: equipamiento, mobiliario, biomedico, medico hospitalario...
Seguridad:    seguridad, medio ambiente, salud ocupacional, ssoma...
Supervisión:  jefe supervision, supervisor obra, jefe expediente...
Eléctricas:   instalaciones electricas, electromecanico, ingeniero electrico...
TIC:          comunicaciones, tecnologias informacion, cableado estructurado...
```

## Matching de cargos — flujo

```
cargo_experiencia vs cargos_validos
    │
    ├─ 1. Normalizar ambos con normalizar_cargo()
    ├─ 2. Match exacto → ✅
    ├─ 3. Substring bidireccional → ✅
    ├─ 4. Sinónimos OSCE (_son_cargos_sinonimos) → ✅
    │      ├─ Normalización suave (sin quitar stopwords)
    │      ├─ Substring contra sinónimos del grupo
    │      └─ Fallback Jaccard ≥60% contra tokens del grupo
    └─ 5. Ninguno → ❌
```

## Limitaciones
- `normalizar_texto()` quita stopwords que pueden ser significativos ("Jefe de Obra" → "Jefe Obra")
- Jaccard poco confiable con strings < 3 tokens
- Sinónimos de cargo pueden ser permisivos — matchea cargos similares pero no idénticos
- Diccionarios son extensibles pero requieren actualización manual

## Dependencias
- Ninguna (módulo utilitario)
