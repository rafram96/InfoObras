## Plan de desarrollo completo

---

### Decisiones tecnológicas primero

**LLM principal — Qwen2.5:32b**
Para extracción de texto estructurado en español con reglas estrictas. Temperatura 0. Sin visión porque el OCR se encarga de convertir las imágenes a texto primero — el LLM nunca ve imágenes directamente.

**LLM con visión — Qwen2.5-VL:7b o LLaVA**
Solo para los casos donde el OCR falla o tiene baja confianza. En lugar de marcar el campo para revisión humana inmediatamente, primero intenta con el modelo de visión sobre el crop de la página. Si sigue fallando, ahí sí va a revisión humana. Esto reduce la carga manual significativamente.

**OCR — PaddleOCR**
Mejor que Tesseract para documentos con sellos, firmas superpuestas y baja calidad de escaneo. Tiene soporte nativo para español y reporta score de confianza por campo, que es lo que necesitas para decidir si un campo va a revisión o no.

**Scraping — Playwright**
Ya validado. Headless, con manejo de reintentos y rate limiting.

**Cola de jobs — Celery + Redis**
**Base de datos — PostgreSQL**
**Export — openpyxl**
**Frontend — Next.js**
**API — FastAPI**
**Chat — Open WebUI + Ollama (misma instancia)**

---

### Módulos y subdivisión

---

#### MÓDULO 0 — Infraestructura
*Lo que sostiene todo lo demás. Se hace una vez.*

```
M0.1  Servidor: Ubuntu 22.04, Docker, drivers GPU
M0.2  Ollama + Qwen2.5:32b + Qwen2.5-VL:7b
M0.3  PostgreSQL + Redis
M0.4  Open WebUI conectado a Ollama
M0.5  Estructura base del proyecto (FastAPI + Celery)
M0.6  Filesystem organizado (uploads, jsons, outputs)
```

**Tiempo: 1 semana**

---

#### MÓDULO 1 — Ingesta y OCR
*El mayor riesgo técnico. Se valida con PDFs reales del cliente antes de continuar.*

```
M1.1  Endpoint de upload de PDFs (bases + propuesta)
M1.2  Detección de páginas: texto nativo vs. escaneado
M1.3  Pipeline PaddleOCR con score de confianza por campo
M1.4  Fallback a Qwen2.5-VL para campos con confianza baja
M1.5  Extracción y mapeo de folios (número de hoja por posición)
M1.6  Segmentación del PDF por secciones
        (profesionales / certificados / declaraciones juradas)
M1.7  Pantalla de revisión en frontend para campos no resueltos
```

**Tiempo: 3 semanas + 1 colchón = 4 semanas**
*Checkpoint: validar con 10 certificados reales antes de avanzar*

---

#### MÓDULO 2 — Extracción de Bases
*Relativamente simple. Las bases tienen estructura más predecible que los certificados.*

```
M2.1  Prompt para extraer requisitos por cargo
        (profesión, años, cargos similares, tipo de obra, complejidad)
M2.2  Validación del JSON de salida contra schema fijo
M2.3  Almacenamiento en PostgreSQL
M2.4  Endpoint GET /bases/{id} para consultar requisitos extraídos
M2.5  Vista en frontend para revisar y corregir si algo salió mal
```

**Tiempo: 1.5 semanas + 0.5 colchón = 2 semanas**

---

#### MÓDULO 3 — Extracción de Experiencias
*El corazón del sistema. Las 27 columnas del Paso 3.*

```
M3.1  Segmentación por profesional y por certificado
M3.2  Prompt principal de extracción (27 campos)
        - Nombre, DNI/CIP, proyecto, cargo, empresa emisora
        - RUC, público/privado, subcontrato
        - Fechas inicio/fin, duración calculada
        - Fecha emisión certificado, folio
        - Firmante, cargo del firmante
        - Tipo de documento
M3.3  Validación del JSON contra schema fijo
M3.4  Manejo de certificados con múltiples periodos
        (un certificado = N filas)
M3.5  Almacenamiento en PostgreSQL
M3.6  Endpoint de resultados parciales (para ver progreso)
```

**Tiempo: 3 semanas + 1 colchón = 4 semanas**
*Checkpoint: comparar output contra Excel real de Manuel*

---

#### MÓDULO 4 — Motor de Reglas y Alertas
*Python puro. Sin LLM. Lógica determinista.*

```
M4.1  RN-01: Fecha emisión < fecha fin → ALERTA
M4.2  RN-02: Empresa creada después del inicio → ALERTA
M4.3  RN-03: Firmante sin poderes → ALERTA
M4.4  RN-04: Experiencia > 20 años → ALERTA
M4.5  RN-05: Certificado dice "a la fecha" → NO VALE
M4.6  RN-06: Periodo COVID superpuesto → FLAG para revisión
M4.7  RN-07: Paralización en InfoObras durante periodo acreditado → ALERTA
M4.8  RN-08: Persona diferente en valorización InfoObras → ALERTA
M4.9  Clasificación por severidad: BLOQUEANTE / ADVERTENCIA / INFO
M4.10 Almacenamiento de alertas vinculadas a cada experiencia
```

**Tiempo: 1.5 semanas + 0.5 colchón = 2 semanas**

---

#### MÓDULO 5 — Enriquecimiento Externo
*Scraping ya validado. Es empaquetarlo bien como workers.*

```
M5.1  Worker SUNAT: fecha de creación de empresa por RUC
M5.2  Worker InfoObras búsqueda: código por nombre de proyecto
M5.3  Worker InfoObras detalle: fechas, estado, paralizaciones
M5.4  Worker InfoObras documentos: descargar actas y valorizaciones
M5.5  Worker InfoObras valorizaciones: extraer nombre de jefe de supervisión
M5.6  Manejo de errores, reintentos y caídas del portal
M5.7  Cache de resultados para no re-consultar lo mismo
        (mismo RUC o mismo CUI en múltiples jobs)
```

**Tiempo: 2 semanas + 1 colchón = 3 semanas**
*El colchón es por inestabilidad de portales del Estado*

---

#### MÓDULO 6 — Evaluación contra Bases
*Combina output de M2 + M3 + M4 + M5. Las 22 columnas del Paso 4.*

```
M6.1  Motor de coincidencia de cargos (literal + combinaciones y/o)
M6.2  Validación de profesión (literal, excepción por género)
M6.3  Validación de tipo de obra
M6.4  Validación de tipo de intervención
M6.5  Validación de complejidad
M6.6  Validación de antigüedad (últimos 20 años)
M6.7  Cálculo de años acumulados por profesional (Paso 5)
M6.8  Verificación contra mínimo RTM y factor de evaluación
M6.9  Generación de justificación textual por cada CUMPLE/NO CUMPLE
```

**Tiempo: 2 semanas + 1 colchón = 3 semanas**
*Checkpoint: comparar output contra hoja ANAISIS BD del Excel de Manuel*

---

#### MÓDULO 7 — Export y Reportes

```
M7.1  Generación de Excel con el formato exacto del cliente
        - Hoja: Bases (requisitos por cargo)
        - Hoja: Profesionales
        - Hoja: BD Experiencias (27 columnas + alertas)
        - Hoja: Análisis (22 criterios CUMPLE/NO CUMPLE)
M7.2  Colores de alerta automáticos (rojo/amarillo/verde)
M7.3  Referencias de folio como links internos
M7.4  Endpoint GET /jobs/{id}/export/excel
```

**Tiempo: 1 semana + 0.5 colchón = 1.5 semanas**

---

#### MÓDULO 8 — API completa y gestión de jobs

```
M8.1  Endpoints de jobs (POST, GET estado, GET resultados)
M8.2  Endpoints de revisión OCR (GET campos, PATCH correcciones)
M8.3  Endpoints de bases
M8.4  Endpoints de scraping standalone (SUNAT, InfoObras)
M8.5  Endpoints de alertas
M8.6  Autenticación básica (API key por ahora)
M8.7  Documentación automática (Swagger via FastAPI)
```

**Tiempo: 1.5 semanas + 0.5 colchón = 2 semanas**
*Nota: la mayoría de endpoints ya existen para este punto, esto es pulirlos y documentarlos*

---

#### MÓDULO 9 — Frontend

```
M9.1  Dashboard principal: lista de jobs y estados
M9.2  Pantalla de nuevo análisis: subir PDFs
M9.3  Pantalla de progreso: estado en tiempo real (polling)
M9.4  Pantalla de revisión OCR: campos de baja confianza
M9.5  Pantalla de resultados: profesionales, experiencias, alertas
M9.6  Pantalla de alertas: filtros por severidad y profesional
M9.7  Descarga de Excel
M9.8  Integración con Open WebUI (link/embed al chat)
```

**Tiempo: 3 semanas + 1 colchón = 4 semanas**

---

#### MÓDULO 10 — Integración Open WebUI

```
M10.1  Tool: consultar estado de un job
M10.2  Tool: obtener alertas de un análisis
M10.3  Tool: buscar profesional en resultados
M10.4  Tool: consultar InfoObras por nombre de proyecto
M10.5  Tool: consultar SUNAT por RUC
M10.6  Registrar tools en Open WebUI
M10.7  Prompt de sistema para el agente de licitaciones
```

**Tiempo: 1 semana + 0.5 colchón = 1.5 semanas**

---

### Resumen de tiempos

| Módulo | Descripción | Tiempo |
|---|---|---|
| M0 | Infraestructura | 1 sem |
| M1 | Ingesta y OCR | 4 sem |
| M2 | Extracción de bases | 2 sem |
| M3 | Extracción de experiencias | 4 sem |
| M4 | Motor de reglas | 2 sem |
| M5 | Enriquecimiento externo | 3 sem |
| M6 | Evaluación contra bases | 3 sem |
| M7 | Export y reportes | 1.5 sem |
| M8 | API completa | 2 sem |
| M9 | Frontend | 4 sem |
| M10 | Integración Open WebUI | 1.5 sem |
| **Total** | | **28 semanas** |

---

### Orden de ejecución real

Los módulos no son secuenciales puros — algunos se pueden paralelizar y otros tienen dependencias estrictas:

```
M0 → M1 → M2 ┐
              ├→ M3 → M4 → M5 → M6 → M7 → M8 → M9 → M10
         M8* ┘

*M8 se construye incrementalmente junto con cada módulo
 Frontend (M9) puede empezar en paralelo desde M3
```

---

### Los tres checkpoints críticos

Antes de avanzar al módulo siguiente en estos puntos, Manuel debe validar:

**Checkpoint 1 — al terminar M1:** el OCR lee correctamente los PDFs reales. Si no, todo lo demás falla.

**Checkpoint 2 — al terminar M3:** la extracción de las 27 columnas coincide con el Excel de Manuel en al menos 90% de los campos. Ese Excel es el ground truth.

**Checkpoint 3 — al terminar M6:** el CUMPLE/NO CUMPLE coincide con la hoja ANAISIS BD del Excel. Si hay discrepancias, son bugs en el motor de reglas o en los prompts.