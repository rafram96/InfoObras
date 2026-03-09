# 🔍 Pipeline Completo: Extracción y Verificación de Experiencia en InfoObras

---

## PARTE 1 — Extracción de datos de la obra (InfoObras)

### ENTRADA
- **CIU** (Código de Identificación Única de la obra) — *dato crítico, sin esto no arranca nada*

---

### ETAPA 1 — Búsqueda de la obra
**Manual:** Ir a InfoObras, ingresar el CIU en el buscador web
**Nota:** Si hay múltiples resultados, elegir el más apropiado según contexto (especialmente la **fecha**)
**Automatizable con:** scraping web o API de InfoObras (manualmente se está haciendo pasando el nombre de la obra a Gemini y este obtiene el CIU)

---

### ETAPA 2 — Acceso a la ficha pública
**Manual:** Hacer clic en "Ficha pública" de la obra encontrada
**Extraer (opcional):** Resumen ejecutivo, datos importantes:
  - Fecha de Contrato
  - Fecha de inicio
  - Fecha de finalización
  - Código de InfoObra
  - Código de Inversión Único (CIU)

---

### ETAPA 3 — Datos de ejecución
**Manual:** Verificar fecha de inicio y fecha de entrega → **bajar el Acta**

**Sub-paso — Creación de directorio local:**
```
📁 "Oxapompa XXXXXX"   ← nombre del proyecto (Lugar + Código CIU)
    └── 📄 01. Acta Entrega   ← con el CIU en el nombre
```

---

### ETAPA 4 — Avances de obra
**Manual:** Revisar estado y fecha de cada avance → para verificar **acreditación**
- ¿Está **paralizado**?
- Formato de cada avance: `10.01 VAL {MES} {AÑO}`

**Sub-paso:** Entrar a "Ver Ficha" → descargar documento adjunto (`.doc`)
- Revisar el **cargo y persona con experiencia** (durante los meses que se hayan mencionado en el certificado de servicios)

---

### ETAPA 5 — Extracción extra de datos
De la sección **Datos de Ejecución**:
- Entrega de terreno, extraer: (fecha) + Acta (descargar)
- Fechas de avance de obra

---

### ETAPA 6 — Informes de Control
De la sección **Informes de Control**:
- Descargar la columna 'Informe' de cada fila, usar de la columna 'n° de Informe' como nombre

**Prompt a utilizar:**
```
PARA INFORMES DE CONTRALORÍA

Indicar los periodos de suspensión, fecha de término de obra, fecha de recepción.
Fecha de reactivación de la obra por covid.

En todos los casos señalar la fuente, la página y copiar la referencia.
```

---

## PARTE 2 — Verificación de experiencia del postor

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

### PASO 3 — Cruce con los datos extraídos de InfoObras

Con la información obtenida en la Parte 1, cruzar:
- Estado de la obra por mes (ejecutada / paralizada / suspendida)
- Actas de suspensión registradas (fechas exactas de inicio y fin de cada suspensión)
- Avances físicos y financieros por período

**Regla:** Si algún mes dentro del período declarado figura como **"Paralizado"** o **"Suspendido"** → descontar esos días del cómputo de experiencia.

---

### PASO 4 — Descuento de períodos de suspensión

Por cada acta de suspensión identificada que se solape con el período declarado:
- Calcular los días calendario de solapamiento
- Restar del total declarado
- Resultado = **días efectivamente computables**

> Ejemplo: 117 días declarados − 30 días de suspensión (04/10 al 02/11/2022) = **87 días efectivos**

---

### PASO 5 — Evaluación del umbral mínimo requerido

Comparar los días efectivos con el mínimo exigido en las bases del proceso. Si los días efectivos no alcanzan el mínimo → **experiencia no acreditable para ese ítem**.

---

### PASO 6 — Aplicación del principio de presunción de veracidad

El certificado se presume válido **salvo** que exista prueba en contrario. Si InfoObras contradice lo declarado, la presunción cae y aplica descalificación o reducción, conforme al TUO de la LPAG y jurisprudencia del OSCE (como la Resolución N° 1554-2026-TCP-S2).

---

## PARTE 3 — Fuentes de consulta

- **INFOBRAS** — infobras.contraloria.gob.pe
  Estado mensual, actas de suspensión (ya se tiene un scrapping parcial)

- **SEACE** — seace.osce.gob.pe
  Contrato, plazo contractual, adendas (ya se tiene un scrapping parcial para otro tema)

- **RNP** — rnp.gob.pe
  Historial de contratos del postor

---

## Automatización posible

Este pipeline se puede implementar como un scraper + motor de reglas que:
1. Recibe los datos del certificado (manual o por OCR del PDF)
2. Consulta InfoObras por nombre de obra o código CIU
3. Cruza las fechas y descuenta suspensiones automáticamente
4. Genera un reporte con días válidos vs. días declarados
