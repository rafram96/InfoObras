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

## Donde conseguir mas TDRs para anotar

El golden actual solo cubre 1 TDR (Huancavelica). Para metricas robustas
y para implementar el diccionario de dominio (ver
`docs/proximas-mejoras-tdr.md`) necesitamos 3-5 TDRs distintos.

Ordenado por utilidad:

### 1. Pedir al cliente (mejor)

Inmobiliaria Alpamayo / Indeconsult tiene archivo de TDRs a los que ya
postularon. Esos reflejan exactamente la variedad real que el sistema
procesara, y el cliente puede ayudar a anotar el golden.

Pedir 3-4 TDRs ganados/perdidos del 2023-2025, idealmente de proveedores
distintos (MINSA, EsSalud, GORE, MUNI) para variedad.

### 2. SEACE oficial (publico, gratis)

Portal: https://prod1.seace.gob.pe/seacebus-uiwd-pub/

Filtros:
- Tipo de procedimiento: Concurso Publico o Adjudicacion Simplificada
- Objeto de contratacion: Servicios (la supervision es servicio, no obra)
- Descripcion del objeto: keywords como "supervision" + "hospital",
  "supervision" + "establecimiento de salud", "RTM" o "recursos
  tecnicos minimos"
- Año de convocatoria: 2024-2025

Para descargar el TDR:
1. Click en el procedimiento
2. Pestaña "Documentos del procedimiento" o "Bases integradas"
3. PDFs descargables — TDR esta dentro de "Bases" (Capitulo III o seccion B)

### 3. Aggregadores con UI mas limpia

- https://www.contrataciones.pe/ (filtros por sector salud)
- https://www.todolicitaciones.pe/ (alertas por keyword)
- https://www.perulicitaciones.com/

Igual descargan los PDFs de SEACE pero la UX es mejor para buscar.

### 4. Datos abiertos OSCE (para analisis batch)

https://contratacionesabiertas.osce.gob.pe/busqueda

Exporta procedimientos en JSON. Util si en el futuro queremos analizar
100+ TDRs automaticamente para construir el diccionario de dominio.

## Tips para anotar el siguiente golden

1. **Variedad importa mas que cantidad**: 3 TDRs de hospitales distintos
   > 5 del mismo MINSA. Idealmente:
   - 1 hospital nivel III (mas complejo, mas cargos)
   - 1 establecimiento nivel I-2 / I-3 (mas simple)
   - 1 con peculiaridades (ej: contingencia, terreno especial)

2. **Procesa primero por el pipeline** (sube PDF -> ve output) ANTES de
   anotar manualmente. Asi tienes contra que comparar y ves donde "le
   cuesta" al pipeline.

3. **Anota basado en el output**: copia las filas que el pipeline acerto y
   corrige solo lo que esta mal. Es mucho mas rapido que anotar desde cero.

4. **Naming**: usa `{nombre_descriptivo}.json` (ej: `rtm_minsa_arequipa.json`).
   Recuerda agregar la entrada al `.gitignore` whitelist:
   ```
   !tests/golden/{nombre}.json
   ```
