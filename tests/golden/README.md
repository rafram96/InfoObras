# Golden set de evaluacion TDR

Carpeta para los JSON "verdad" anotados manualmente. Sirven de referencia
para medir que tan bien extrae el pipeline vs la expectativa real.

## Como anotar un TDR

1. Abre el PDF del TDR.
2. Copia `plantilla.json` a `{nombre_tdr}.json` (ej: `rtm_huancavelica.json`).
3. Para CADA cargo de la tabla B.1:
   - Transcribe literalmente la columna "CARGO Y/O RESPONSABILIDAD"
   - Lista las profesiones de "FORMACION ACADEMICA" (literal, "y/o" → lista)
   - En B.2 busca el mismo cargo y copia:
     - Tiempo minimo (en meses)
     - Lista de cargos similares de la columna "TRABAJOS O PRESTACIONES"
     - Tipo de obra (especialidad / subespecialidad)
4. Guarda.

## Estructura minima del JSON

```json
{
  "nombre_tdr": "TDR Huancavelica",
  "rtm_personal": [
    {
      "numero_fila": 1,
      "cargo": "GERENTE DE CONTRATO",
      "profesiones_aceptadas": ["Ingeniero Civil", "Arquitecto"],
      "experiencia_minima": {
        "cantidad": 24,
        "unidad": "meses",
        "cargos_similares_validos": [
          "Gerente de Obra",
          "Gerente de Proyecto",
          "Coordinador de Obra",
          "Gerente de Supervision",
          "Gerente de Construccion",
          "Director de Proyectos",
          "Director de Obra",
          "Gerente de Contrato de Supervision"
        ]
      },
      "tipo_obra_valido": "establecimientos de salud"
    }
  ]
}
```

Campos que no importan (no se evaluan): `anos_colegiado`, `capacitacion`,
`tiempo_adicional_factores`, `pagina`. Puedes omitirlos.

## Correr evaluacion

```bash
# Contra un JSON de resultado exportado:
python tests/evaluar_tdr.py tests/golden/rtm_huancavelica.json resultado.json

# Contra un job en BD:
python tests/evaluar_tdr.py tests/golden/rtm_huancavelica.json --job-id=a3f9b2c1

# Guardar metricas detalladas en JSON:
python tests/evaluar_tdr.py tests/golden/rtm_huancavelica.json --job-id=a3f9b2c1 \
    --salida-json=out/metricas_a3f9b2c1.json
```

## Que mide el script

Para cada cargo del golden, compara contra el output del pipeline:

- **Profesiones**: set de titulos. Mide precision/recall/F1 normalizado
  (case-insensitive, sin tildes).
- **Cargos similares**: set de puestos. Mismas metricas.
- **Tiempo meses**: match exacto.
- **Tipo obra**: match normalizado (substring).

Tambien detecta:

- **Cargos faltantes**: estan en golden pero el pipeline no los extrajo.
- **Cargos alucinados**: el pipeline extrajo un cargo que no esta en golden.

## Interpretar metricas

- **Recall = 100%** → el pipeline encontro TODO lo esperado (puede tener extras)
- **Precision = 100%** → todo lo que el pipeline extrajo es correcto (puede faltar)
- **F1** combina ambos; objetivo >= 0.90 para considerar "bueno"

Ejemplo de salida:

```
Profesiones:
  Precision=85.7%  Recall=72.3%  F1=0.785
  TP=42 FP=7 FN=16
```

Significa: de 49 profesiones que extrajo, 42 eran correctas (85.7% precision).
De 58 profesiones en el golden, encontro 42 (72.3% recall). Falta mejorar recall.
