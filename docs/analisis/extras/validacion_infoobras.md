# 🔍 Pipeline: Extracción de datos de obras en InfoObras

### ENTRADA
- **CIU** (Código de Identificación Única de la obra) — *dato crítico, sin esto no arranca nada*

---

### ETAPA 1 — Búsqueda de la obra
**Manual:** Ir a InfoObras, ingresar el CIU en el buscador web
**Nota:** Si hay múltiples resultados, elegir el más apropiado según contexto (especialmente la **fecha**)
**Automatizable con:** scraping web o API de InfoObras (hay mención a "Ingmétodo / consulta Gemini" como alternativa de búsqueda)

---

### ETAPA 2 — Acceso a la ficha pública
**Manual:** Hacer clic en "Ficha pública" de la obra encontrada
**Extraer (opcional):** Resumen ejecutivo, datos importantes:
  - Fecha de Contrato
  - Fecha de inicio
  - Fecha de finalización
  - Código de InfoObra
  - Código de Ínversión Único (CIU)

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
- Revisar el **cargo y persona con experiencia** (durante los meses que se hayan mencionado en el sertificado de servicios)

---

### ETAPA 5 — Extracción Extra de datos
De la sección **Datos de Ejecución**:
- Entrega de terreno, extraer: (fecha) + Acta (descargar)
- Fechas de avance de Obra 

---

### ETAPA 6 - Informes de Control
De la sección **Informes de Control**:
- Descargar la columna 'Informe' de cada fila, usar de la columna 'n° de Informe' como nombre

**Prompt a utilizar:**
```
PARA INFORMES DE CONTRALORIA

Indicar los periodos de suspensión, fecha de termino de obra, fecha de recepción.
Fecha de reactivación de la obra por covid

En todos los casos señalar la fuente, la página y copiar la referencia.
```