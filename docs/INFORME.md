# INFORME DE ANÁLISIS DE REQUERIMIENTOS

**Proyecto:** InfoObras Analyzer — Sistema de Verificación Automatizada de Propuestas Técnicas  
**Cliente:** Ing. Manuel Echandía — Inmobiliaria Alpamayo  
**Fecha:** 2026-03-06  
**Fuente:** Reunión técnica del 06/03/2026

---

## 1. RESUMEN EJECUTIVO

El cliente analiza propuestas técnicas de concursos públicos para detectar inconsistencias en la experiencia profesional declarada por competidores. Actualmente realiza este proceso **manualmente con Gemini**, partiendo PDFs de ~2,300 páginas en 6 fragmentos y corriendo múltiples prompts.

**El problema no es de IA. Es un pipeline mal diseñado:**

```
PDF → partir manual → Gemini → copiar → Excel → Gemini → Excel → Infobras manual
```

**La solución es un pipeline automatizado:**

```
PDF completo (~2300 págs.)
    │
    ▼
OCR (PaddleOCR)                         ← herramienta, no IA
    │
    ▼
Segmentación automática                  ← detectar certificados
    │                                       2300 págs. → ~45 certs
    ▼
Extracción de entidades (LLM)            ← ÚNICO punto de IA
    │                                       Qwen2.5 14B, paralelo
    ▼
PostgreSQL                                ← BD estructurada
    │
    ▼
Motor de reglas + alertas                 ← código Python (if/else)
    │
    ▼
Verificación externa                      ← scraping
    ├── Infobras (paralizaciones, valorizaciones)
    ├── SUNAT (fecha constitución empresa)
    └── Colegio Profesional (vigencia CIP)
    │
    ▼
Excel / Dashboard web
```

**Tiempo de procesamiento:** ~3-5 minutos por PDF completo (vs 12+ horas manual).

---

## 2. QUÉ ES IA Y QUÉ ES CÓDIGO

### La IA SOLO hace esto:

| Tarea | Por qué necesita IA |
|---|---|
| Extraer entidades del texto OCR (nombre, cargo, fechas, proyecto) | Texto desestructurado, formatos variables |
| Interpretar tipo de obra/intervención | Requiere comprensión semántica |

### Todo lo demás es CÓDIGO:

| Tarea | Implementación |
|---|---|
| Comparar cargo vs bases | `if cargo not in cargos_validos: alerta()` |
| Verificar fechas inconsistentes | `if fecha_fin > fecha_emision: alerta()` |
| Detectar periodo COVID | `if fecha in rango_covid: alerta()` |
| Verificar antigüedad | `if antiguedad > 20: alerta()` |
| Detectar "a la fecha" | `if "a la fecha" in texto: alerta()` |
| Generar Excel | Template + datos de la BD |
| Scraping Infobras | Playwright + parseo HTML |

---

## 3. INSIGHT CLAVE: SEGMENTACIÓN

**Este truco elimina la necesidad de partir el PDF manualmente.**

El PDF de 2300 páginas no se procesa completo. Se segmenta automáticamente:

1. OCR de todas las páginas → texto por página
2. Detectar inicio de certificados por patrones ("CERTIFICADO", "CONSTANCIA", "SE CERTIFICA")
3. Agrupar páginas en bloques de 2-4 páginas por certificado
4. Resultado: **~45 certificados** que se procesan en paralelo

Cada certificado es perfecto para el LLM (2-4 páginas, no 2300).

---

## 4. COMPONENTES DEL SISTEMA

### 4.1. Pipeline OCR + Segmentación + Extracción

- **OCR:** PaddleOCR con preprocesamiento de imagen (denoising, deskewing, binarización)
- **Segmentación:** Detección de bloques de certificados por patrones textuales
- **Extracción:** Qwen2.5 14B con prompt estructurado → JSON por profesional
- **Procesamiento paralelo:** Todos los certificados simultáneamente
- **Complejidad real:** MEDIA — OCR es herramienta existente, prompts ya funcionan, el truco es la segmentación

### 4.2. Motor de Reglas y Alertas

100% código Python. 9 alertas determinísticas:

| ID | Alerta | Lógica |
|---|---|---|
| ALT-01 | Fecha fin > fecha emisión | Comparación de fechas |
| ALT-02 | Periodo COVID | Rango configurable |
| ALT-03 | Antigüedad > 20 años | Cálculo de años |
| ALT-04 | Empresa posterior a experiencia | Comparación de fechas |
| ALT-05 | "A la fecha" sin fecha explícita | Búsqueda de texto |
| ALT-06 | Cargo no válido | Búsqueda en lista |
| ALT-07 | Profesión no coincide | Comparación directa |
| ALT-08 | Tipo de obra no coincide | Búsqueda en lista |
| ALT-09 | CIP no vigente | Dato externo |

**Complejidad real:** BAJA — Son if/else bien definidos.

### 4.3. Scraping de Infobras

- Búsqueda por código de proyecto o CUI
- Extracción de datos generales (contrato, fechas, estado, monto)
- Detección de paralizaciones en el rango del certificado
- Descarga de valorizaciones y documentos
- OCR sobre valorizaciones → extraer nombre del supervisor → fuzzy matching

**Complejidad real:** ALTA — Portal gubernamental, puede cambiar, posible CAPTCHA. Es el componente más riesgoso.

### 4.4. Verificaciones Externas (SUNAT / CIP)

- SUNAT: fecha de constitución de empresa (tiene CAPTCHA conocido)
- Colegio de Ingenieros: vigencia CIP
- Fallback manual asistido si los portales bloquean

**Complejidad real:** MEDIA — Funciona o no funciona.

### 4.5. Interfaz Web

- Panel web: subir PDF → ver progreso → ver resultados → descargar Excel
- Acceso multiusuario por red interna
- Dashboard de alertas con resaltado visual

**Complejidad real:** MEDIA — Web dev estándar.

### 4.6. Análisis de Oferta Económica

- Verificación matemática de fórmulas, subtotales, totales
- **Complejidad real:** BAJA

---

## 5. RIESGOS

### Los que SÍ importan:

| # | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R-01 | **Infobras cambia o bloquea** | Media | Alto | Scraping resiliente + caché + fallback manual |
| R-02 | **OCR insuficiente en docs muy deteriorados** | Media | Alto | PoC con docs reales + preprocesamiento + PaddleOCR |
| R-03 | **SUNAT CAPTCHA** | Alta | Medio | Fallback manual asistido. No bloquea el sistema. |

### Los que parecen graves pero no lo son:

| Riesgo aparente | Por qué no es grave |
|---|---|
| "LLM no es suficiente" | El cliente ya tiene prompts funcionando. Se replican. |
| "2300 páginas es mucho" | Se segmentan en ~45 certificados. No se procesan de golpe. |
| "Las reglas son complejas" | Son if/else. El cliente ya las tiene definidas. |
| "Servidor con GPU" | Setup estándar con Ollama. |

---

## 6. STACK TECNOLÓGICO

| Componente | Tecnología |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| OCR | PaddleOCR + Tesseract (fallback) |
| LLM | Qwen2.5 14B Q4_K_M via Ollama |
| Scraping | Playwright |
| BD | PostgreSQL |
| Frontend | React / Next.js |
| Exportación | openpyxl |
| Paralelización | asyncio |
| Servidor | Ubuntu 22.04 + NVIDIA CUDA |

---

## 7. CRONOGRAMA (7 semanas, 1 dev)

| Semana | Fase | Entregable |
|---|---|---|
| 1 | PoC + OCR | Benchmark OCR, prueba Infobras, informe GO/NO-GO |
| 2 | Extracción LLM + BD | PDF completo → JSON → PostgreSQL |
| 3 | Reglas + Alertas + Excel | Excel con evaluación + alertas (**DEMO**) |
| 4-5 | Scraping Infobras | Verificación automática + descarga docs |
| 5-6 | SUNAT/CIP + Web | Verificaciones externas + interfaz web |
| 7 | Integración + Entrega | Deploy, testing, capacitación |

---

## 8. AMBIGÜEDADES PENDIENTES

| # | Ambigüedad |
|---|---|
| A-01 | ¿Qué hacer si proyecto no existe en Infobras? |
| A-02 | Rango exacto de "periodo COVID" |
| A-03 | ¿Cómo verificar poderes legales del firmante? |
| A-04 | Formato exacto del Excel de salida |

---

## 9. DEPENDENCIAS DEL CLIENTE

| Insumo | Cuándo |
|---|---|
| PDFs de propuestas (mínimo 2-3) | Semana 1 |
| Bases del concurso | Semana 1 |
| Sintaxis/prompts de Gemini | Semana 2 |
| Excel de formato de salida | Semana 3 |
| Servidor con GPU adquirido | Semana 6 |

---

*Documento generado el 2026-03-06.*
