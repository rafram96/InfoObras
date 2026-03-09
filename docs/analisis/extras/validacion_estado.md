Entendido. Aquí está el pipeline como proceso replicable:

---

## Pipeline de Verificación de Experiencia de Postores

### PASO 1 — Extracción de datos del certificado presentado

Del documento aportado por el postor, extraer:
- Nombre del profesional
- Cargo declarado
- Nombre exacto de la obra/servicio
- Fecha de inicio y fecha de fin
- Días totales declarados
- Emisor del certificado (razón social del consorcio o empresa)

---

### PASO 2 — Cálculo propio de días

Calcular independientemente la diferencia entre fecha inicio y fecha fin. Comparar con los días declarados. Si no coincide → **observación automática**.

---

### PASO 3 — Cruce con INFOBRAS (Contraloría General de la República)

Buscar la obra por nombre o código SNIP/CUI en el portal INFOBRAS. Extraer:
- Estado de la obra por mes (ejecutada / paralizada / suspendida)
- Actas de suspensión registradas (fechas exactas de inicio y fin de cada suspensión)
- Avances físicos y financieros por período

**Regla:** Si algún mes dentro del período declarado figura como **"Paralizado"** o **"Suspendido"** en INFOBRAS → descontar esos días del cómputo de experiencia.

---

### PASO 4 — Descuento de períodos de suspensión

Por cada acta de suspensión identificada que se solape con el período declarado:
- Calcular los días calendario de solapamiento
- Restar del total declarado
- Resultado = **días efectivamente computables**

En el caso de las imágenes: 117 días declarados − 30 días de suspensión (04/10 al 02/11/2022) = **87 días efectivos**.

---

### PASO 5 — Evaluación del umbral mínimo requerido

Comparar los días efectivos con el mínimo exigido en las bases del proceso. Si los días efectivos no alcanzan el mínimo → **experiencia no acreditable para ese ítem**.

---

### PASO 6 — Aplicación del principio de presunción de veracidad

El certificado se presume válido **salvo** que exista prueba en contrario. Si INFOBRAS contradice lo declarado, la presunción cae y aplica descalificación o reducción, conforme al TUO de la LPAG y jurisprudencia del OSCE (como la Resolución N° 1554-2026-TCP-S2 citada en las imágenes).

---

### Fuentes a consultar en el paso 3

| Portal | URL | Qué obtener |
|---|---|---|
| INFOBRAS | infobras.contraloria.gob.pe | Estado mensual, actas de suspensión |
| SEACE | seace.osce.gob.pe | Contrato, plazo contractual, adendas |
| RNP | rnp.gob.pe | Historial de contratos del postor |

---

### Automatización posible

Este pipeline se puede implementar como un scraper + motor de reglas que:
1. Recibe los datos del certificado (manual o por OCR del PDF)
2. Consulta INFOBRAS por nombre de obra o código
3. Cruza las fechas y descuenta suspensiones automáticamente
4. Genera un reporte con días válidos vs. días declarados
