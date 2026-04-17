# Revisión Sábado — Análisis Ejecutivo

> **Para la reunión de mañana** — foco del jefe: procesamiento + Excel
> **Frontend:** solo funcional (no le importa diseño)

---

## 1. Lo que funciona y se puede mostrar

### Pipeline completo (job_type=full)
Subir 2 PDFs (propuesta + bases) → ejecuta automáticamente:
1. OCR + segmentación (motor-OCR)
2. Extracción de profesionales y experiencias (LLM — Pasos 2-3)
3. Extracción de requisitos RTM de las bases (Paso 1)
4. Evaluación RTM cruzando ambos (Paso 4)
5. Genera Excel de 5 hojas descargable

**Tiempo:** ~50-60 min por concurso (165 págs propuesta + 200 págs bases)

### Herramientas individuales
- **/herramientas/extraccion** — solo propuesta → profesionales + experiencias
- **/herramientas/tdr** — solo bases → requisitos RTM
- **/herramientas/infoobras** — buscar obra por nombre con desambiguación automática

### Excel de 5 hojas
1. **Resumen** — totales, años efectivos por profesional, semáforo (✅/⚠️/❌)
2. **Base de Datos** — 27 columnas por experiencia
3. **Evaluación RTM** — 22 columnas con colores verde/amarillo/rojo
4. **Alertas** — 9 alertas con severidad
5. **Verificación InfoObras** — ⚠️ actualmente vacía (no integrada en pipeline)

### Panel (funcionalidades demo)
- **Historial** con filtro tipo + estado, columna de profesionales
- **/jobs/[id]** con progreso en tiempo real (WebSocket)
- **Logs del procesamiento** visibles en la misma página
- **Botón "Descargar Excel"** funcional
- **Botón "Evaluar RTM"** → modal que lista jobs TDR → genera Excel

---

## 2. Mejoras aplicadas HOY (antes de la demo)

| # | Mejora | Impacto visible |
|---|--------|-----------------|
| 1 | **Regla "a la fecha"** — usa fecha emisión certificado como fecha fin cuando falta | 8/41 experiencias del test ahora evalúan correctamente (era 20% mal evaluado) |
| 2 | **Cargo del firmante** — columna 19 del Excel ahora llena | Base de Datos más completa |
| 3 | **Deduplicación de experiencias** | Se eliminan las filas repetidas (vi 3 copias del Hospital Cajamarca en test anterior) |
| 4 | **Botón Descargar Excel** funcional en UI | Demo sin usar curl |
| 5 | **Visor de logs** en /jobs/[id] | El jefe ve qué está haciendo el sistema |
| 6 | **Selector de TDR** para evaluar RTM | Flujo completo sin intervención técnica |

---

## 3. Pendientes — orden de prioridad

### Crítico — antes de la demo

- [ ] **Correr un job `full` end-to-end** para asegurar que no falla (nunca se probó completo)
- [ ] **Revisar el Excel generado** hoja por hoja con datos reales
- [ ] **Verificar que logs + descarga funcionan** en el panel con datos actuales

### Importante — decisiones de producto para el jefe

| # | Decisión | Opciones |
|---|----------|----------|
| 1 | **¿Hoja "por profesional" o mantener todo junto?** | Hoy: todo en Base de Datos. Alt: una hoja por cada profesional con sus experiencias + evaluación |
| 2 | **¿Columna "Veredicto Final"?** | Hoy: 22 columnas crudas. Alt: columna APROBADO/OBSERVADO/RECHAZADO calculada |
| 3 | **Formato de fecha** | Hoy: `15/07/2020`. Manual cliente: `15/JUL/2020` |
| 4 | **¿Icono además de color en Excel?** | Hoy: solo colores. Alt: ✅⚠️❌ para impresión |
| 5 | **¿Qué hacer con obras no encontradas en InfoObras?** | UI de confirmación manual del CUI |
| 6 | **¿Re-correr Paso 4 con CUIs confirmados?** | Hoy no hay mecanismo para re-evaluar |

### Funcionalidad faltante — post-demo

| # | Pendiente | Por qué importa |
|---|-----------|-----------------|
| 1 | **Integrar InfoObras en el pipeline** | Hoja 5 del Excel queda vacía. Paralizaciones no descuentan tiempo |
| 2 | **Descarga documentos InfoObras + ZIP** | Actas, valorizaciones, informes CGR |
| 3 | **Verificación nombre en valorizaciones** (RF-07) | Cruce preciso del supervisor con documentos oficiales |
| 4 | **ALT10 — persona diferente en cargo** | Alerta cuando el nombre del certificado no matchea con InfoObras |
| 5 | **Historial persistente de profesionales/obras** | Hoy solo hay tabla `jobs`, cada análisis es isla |

### Deuda técnica — no urgente

- 0 tests unitarios
- Cancelación de jobs no mata el subprocess
- Sin modelo persistente de datos
- Prompts frágiles sin versionado

---

## 4. Riesgos conocidos para la demo

### Riesgo alto
- **Pipeline full nunca probado end-to-end.** Si falla en vivo, no hay plan B inmediato.
- **Hoja 5 vacía** — el jefe va a preguntar "¿y la verificación de InfoObras?". Respuesta: está conectado por módulos pero no integrado en el flujo automático aún.

### Riesgo medio
- Algunos profesionales pueden aparecer sin nombre si el LLM falla. No hay manejo elegante en el Excel.
- Páginas con OCR error se cuentan pero no se explican cuáles fueron.
- Sinónimos de cargo aún incompletos (Especialista Electromecánico, OCR corrupto "NNNN").

### Riesgo bajo
- El matching TDR tiene falsos positivos (viste "en entidades públicas y/o privadas" como tipo_obra). El prompt se mejoró pero necesita re-correr TDR.

---

## 5. Qué mostrar en la demo (orden sugerido)

### 1. Overview (2 min)
- Abrir panel en LAN (IP del servidor:3002)
- Mostrar Historial con los jobs existentes
- Explicar los 3 tipos de job: extracción, TDR, full

### 2. Pipeline completo en vivo (~50 min — en background)
- Ir a `/nuevo-analisis`
- Subir Propuesta.pdf + Bases.pdf → lanzar `job_type=full`
- **Mientras procesa**, abrir el job detalle
- Mostrar WebSocket: progreso en tiempo real
- Mostrar visor de logs: cada fase se ve
- Continuar con otros puntos mientras procesa

### 3. Mostrar Excel de un job ya terminado (mientras el nuevo procesa)
- Abrir Excel generado (usar `6c1f0fe9` o `44bfcf36`)
- Hoja por hoja:
  - Resumen: 12 profesionales, años efectivos, alertas críticas
  - Base de Datos: 27 columnas llenas
  - Evaluación RTM: semáforo verde/rojo
  - Alertas: 46 alertas detectadas

### 4. Demostrar herramientas individuales (5 min)
- `/herramientas/tdr` → subir solo bases → ver requisitos extraídos
- `/herramientas/infoobras` → buscar "Hospital Pomabamba" → ver desambiguación
- `/herramientas/extraccion` → subir solo propuesta → luego evaluar contra TDR

### 5. Discutir pendientes (10 min)
- Decisiones de producto (sección 3)
- InfoObras: qué tan urgente es la integración automática
- Tiempo estimado para siguientes features

---

## 6. Lo que NO se hace (por decisión previa)

- ~~Scraper SUNAT~~ → manual (CAPTCHA)
- ~~Scrapers colegios profesionales~~ → manual (múltiples portales)
- ~~Chat IA~~ → no priorizado
- ~~Análisis oferta económica~~ → baja prioridad
- ~~Celery/Redis~~ → ThreadPool funciona para 1 GPU
- ~~Frontend pulido~~ → explícitamente no valorado

---

## 7. Números clave para mencionar

| Métrica | Valor |
|---------|-------|
| Tiempo manual del cliente (antes) | 4-6 horas |
| Tiempo automatizado (ahora) | ~50-60 min |
| Experiencias evaluadas en el test | 41 de 12 profesionales |
| Alertas generadas en el test | 46 (antes 79, ahora bajó por mejoras) |
| Profesionales con match RTM | 11/12 (era 8/12 al inicio) |
| Líneas de código backend | ~5000 |
| Líneas de código frontend | ~2500 |

---

## 8. Preguntas frecuentes anticipadas

**P: ¿Qué pasa si la obra no está en InfoObras?**
R: Actualmente el scraper retorna None y no afecta la evaluación. Se puede agregar UI de confirmación manual del CUI.

**P: ¿Por qué la hoja 5 de InfoObras está vacía?**
R: Los módulos están implementados y probados individualmente. Falta conectarlos al pipeline completo — está como siguiente tarea.

**P: ¿Puedo procesar múltiples propuestas a la vez?**
R: No. Una GPU, un job a la vez. Los siguientes quedan en cola automáticamente.

**P: ¿Se puede re-evaluar un job con correcciones manuales?**
R: Hoy no. Hay que volver a subir. Pendiente para siguiente fase.

**P: ¿Cómo se prueba que los resultados son correctos?**
R: Corre el script `run_paso4_test.py` contra jobs existentes. No hay tests automatizados aún (deuda técnica).

**P: ¿Los prompts se pueden ajustar?**
R: Sí, están en `src/extraction/prompts.py` y `src/tdr/config/signals.py`. Cambios requieren re-correr jobs, no hay cache invalidación.
