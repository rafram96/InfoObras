# Plan Definitivo — InfoObras Analyzer

**Proyecto:** Sistema de Verificación Automatizada de Propuestas Técnicas
**Cliente:** Ing. Manuel Echandía — Inmobiliaria Alpamayo
**Dev:** Rafael Ramos Huamaní
**Fecha:** Marzo 2026
**Servidor:** Windows 11 Pro (on-premise, 100% local)

---

## El Problema

Manuel analiza propuestas técnicas de concursos públicos para detectar inconsistencias en la experiencia profesional declarada. Hoy lo hace **manualmente con Gemini**, partiendo PDFs de ~2,300 páginas en 6 fragmentos y corriendo múltiples prompts. Le toma **medio día a un día completo** por propuesta.

```
Proceso actual:
PDF → partir manual → Gemini × 6 → copiar a Excel → Gemini → Excel → Infobras manual
```

---

## La Solución

Un pipeline automatizado que recibe el PDF completo y produce un Excel con evaluación y alertas.

```
PDF propuesta + PDF bases
        ↓
    OCR (PaddleOCR)
        ↓
    Segmentación automática
    (2300 págs → ~45 certificados)
        ↓
    LLM extracción (Qwen2.5 14B, temp=0)
    (cada certificado → JSON)
        ↓
    PostgreSQL
        ↓
    Motor de reglas (Python puro)
    (9 alertas determinísticas)
        ↓
    Verificación externa (Playwright)
    ├── InfoObras (paralizaciones)
    ├── SUNAT (fecha constitución empresa)
    └── CIP (vigencia colegiatura)
        ↓
    Excel con evaluación + alertas
```

**Tiempo esperado:** 10-20 min con GPU actual → 3-5 min con GPU futura

---

## Servidor

**Hardware actual + upgrades inmediatos:**

| Componente | Spec |
|---|---|
| CPU | Intel Core i9-14900K (24 cores / 32 threads) |
| RAM | 64GB DDR5-6000MHz (32GB actual + 32GB por agregar) |
| GPU | NVIDIA Quadro RTX 5000 16GB ← **suficiente para arrancar** |
| SSD | 3TB NVMe total (1TB WD Black + 2TB nuevo) |
| HDD | 1TB SATA (backups) |
| PSU | Cooler Master Gold 1050W |
| UPS | Por agregar |
| SO | Windows 11 Pro |

**GPU futura (~1 mes):** Se actualizará. Con RTX 3090/4090 (24GB) se podrá correr modelo 32B o paralelo OCR+LLM.

> ℹ️ Con la Quadro RTX 5000 actual, se procesan OCR y LLM **secuencialmente** (no simultáneamente) para no exceder los 16GB VRAM.

---

## Stack Tecnológico

| Capa | Tecnología | Nota |
|---|---|---|
| Backend | Python 3.11 + FastAPI | API REST + background tasks |
| LLM | Qwen2.5 14B Q4_K_M vía Ollama | Temp=0, extracción JSON |
| OCR | PaddleOCR | Tesseract como fallback |
| BD | PostgreSQL | Datos estructurados |
| Scraping | Playwright | InfoObras, SUNAT, CIP |
| Cola | Redis | Jobs en background |
| Excel | openpyxl | Formato del cliente |
| Frontend | Next.js 14 | Panel web interno (última fase) |

---

## Los 5 Pasos del Cliente → Los 7 Módulos del Sistema

El cliente hoy ejecuta 5 pasos manuales. El sistema los automatiza así:

| Paso manual | Módulo del sistema | Tipo |
|---|---|---|
| **Paso 1:** Resumir criterios de las bases (RTM) | **M1: Extracción de Bases** — LLM lee las bases y extrae la matriz de requisitos por cargo | IA |
| **Paso 2:** Listar profesionales propuestos | **M2: OCR + Segmentación** — OCR del PDF completo, detectar certificados por patrones | Herramienta |
| **Paso 3:** BD de experiencias (27 columnas) | **M3: Extracción LLM** — Cada certificado → JSON con los 27 campos | IA |
| **Paso 4:** Evaluación RTM (22 criterios) | **M4: Motor de Reglas** — Comparación determinística propuesta vs bases | Código |
| **Paso 5:** Evaluación de años acumulados | **M4** (mismo módulo, cálculo adicional) | Código |
| Verificación InfoObras (sugerido) | **M5: Scraping + Verificación** — Consulta portales, cruza fechas, descuenta suspensiones | Código + Scraping |
| Generar Excel | **M6: Generación de Reportes** — Excel con 5 hojas + colores | Código |
| — | **M7: Interfaz Web** — Panel para subir, ver progreso, descargar | Frontend |

---

## Las 9 Alertas

Todo código Python. Sin IA.

| # | Alerta | Lógica |
|---|---|---|
| ALT-01 | Fecha fin > fecha emisión certificado | Comparación de fechas |
| ALT-02 | Experiencia abarca periodo COVID | Rango: 16/03/2020 – 31/12/2021 |
| ALT-03 | Antigüedad > 20 años | Cálculo desde fecha de propuesta |
| ALT-04 | Empresa constituida después del inicio | Fecha SUNAT vs fecha inicio |
| ALT-05 | "A la fecha" sin fecha explícita | Búsqueda de texto |
| ALT-06 | Cargo no válido según bases | Comparación contra lista |
| ALT-07 | Profesión no coincide | Comparación directa |
| ALT-08 | Tipo de obra no coincide | Comparación contra lista |
| ALT-09 | CIP no vigente | Verificación externa |

> ℹ️ **Para profundizar:** Cada alerta tiene severidad (crítica/alta/media). Ver claude3.md sección 5.5 para la implementación detallada.

---

## Base de Datos (estructura general)

```
projects             → Un análisis completo (PDF + bases)
  └── certificates   → Cada certificado detectado (2-4 págs)
       └── professionals → Datos extraídos por LLM (27 campos)
            ├── alerts          → Resultado de las 9 reglas
            ├── verifications   → Consultas a portales externos
            └── obra_data       → Datos de InfoObras (avances, suspensiones)
```

Tabla adicional: `processing_logs` para tracking de progreso.

> ℹ️ **Para profundizar:** Ver claude3.md sección 4 para el schema SQL completo con índices, triggers y views.

---

## Excel de Salida

| Hoja | Contenido |
|---|---|
| **Resumen** | Totales: profesionales evaluados, cumplen, no cumplen, alertas |
| **Detalle** | Las 27 columnas del Paso 3 + días efectivos |
| **Análisis** | Los 22 criterios CUMPLE/NO CUMPLE del Paso 4 |
| **Alertas** | Código, severidad, descripción por profesional |
| **Suspensiones** | Datos cruzados con InfoObras |

Colores: 🟢 Cumple · 🟡 Revisar · 🔴 No cumple / Alerta

> ℹ️ **Para profundizar:** El formato exacto de las 27 columnas (Paso 3) y 22 columnas (Paso 4) está en manual.md.

---

## Cronograma (7 semanas, 1 dev)

| Sem | Fase | Qué se hace | Entregable |
|---|---|---|---|
| 1 | **PoC + OCR** | Setup servidor, PaddleOCR, segmentación | PDF → certificados detectados. **GO/NO-GO** |
| 2 | **Extracción LLM** | Ollama + Qwen2.5, prompts, JSON → BD | 45 certificados → datos en PostgreSQL |
| 3 | **Reglas + Excel** | Motor de alertas, generador Excel | Excel con evaluación. **DEMO AL CLIENTE** |
| 4 | **Scraping InfoObras (1)** | Búsqueda, ficha pública, avances | Datos de InfoObras en BD |
| 5 | **Scraping InfoObras (2) + SUNAT/CIP** | Informes, suspensiones, verificaciones | Verificaciones cruzadas completas |
| 6 | **Frontend + API** | Web: upload, progreso, descarga | Panel web funcional |
| 7 | **Testing + Deploy** | Pruebas con datos reales, capacitación | Sistema en producción |

### Checkpoints críticos

- **Fin semana 1:** OCR lee correctamente los PDFs reales. Si falla → replantear.
- **Fin semana 2:** Extracción de las 27 columnas coincide ≥90% con el Excel de Manuel.
- **Fin semana 3:** DEMO — el sistema procesa un PDF real y genera el Excel.

---

## Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| InfoObras cambia o bloquea | Media | Alto | Scraping resiliente + caché + fallback manual |
| OCR falla en docs deteriorados | Media | Alto | PoC semana 1 + preprocesamiento + Tesseract fallback |
| SUNAT tiene CAPTCHA | Alta | Medio | Fallback manual. No bloquea el resto del sistema |
| GPU actual es lenta | Baja | Bajo | Funciona, solo más lento. GPU nueva en ~1 mes |

---

## Dependencias del Cliente

| Qué necesito | Cuándo |
|---|---|
| PDFs de propuestas reales (mínimo 2-3) | Semana 1 |
| Bases del concurso (PDF o Excel) | Semana 1 |
| Prompts/sintaxis que usa en Gemini | Semana 2 |
| Formato exacto del Excel de salida | Semana 3 |
| Acceso al servidor para deploy | Semana 6 |

---

## Instalación del Servidor (Día 1)

El servidor es **Windows 11 Pro**. Se necesita instalar:

### Imprescindible
- NVIDIA drivers + CUDA Toolkit + cuDNN
- Python 3.11
- Git + Git LFS
- Node.js LTS
- Docker Desktop (incluye WSL2)
- PostgreSQL 16
- Redis
- Ollama → descargar modelo `qwen2.5:14b-instruct-q4_k_m`

### Para desarrollo
- VSCode con extensiones (Python, Docker, GitLens)
- PaddleOCR + OpenCV (pip install)
- FastAPI + uvicorn (pip install)
- Playwright (pip install + browsers)
- openpyxl (pip install)

### Estructura de carpetas recomendada
```
D:\InfoObras\
├── backend\          ← Código Python (FastAPI + pipeline)
├── frontend\         ← Next.js (semana 6)
├── data\
│   ├── uploads\      ← PDFs subidos
│   ├── processed\    ← Cache OCR
│   └── downloads\    ← Resultados + docs descargados
├── models\           ← Modelos Ollama (gestionado por Ollama)
└── docs\             ← Documentación del proyecto
```

> ℹ️ **Tiempo estimado de instalación:** 3-4 horas.

---

## Qué NO incluye este plan (para después)

- [ ] Dashboard con gráficos y estadísticas
- [ ] Chat con documentos (RAG / Open WebUI)
- [ ] Análisis de oferta económica (verificación matemática)
- [ ] Multi-tenancy / gestión de usuarios con roles
- [ ] Histórico de licitaciones analizadas
- [ ] Exportación a otros formatos (PDF, Word)
- [ ] Modo SaaS (escalamiento a múltiples clientes)

---

## Referencias Detalladas

Para profundizar en cualquier aspecto:

| Tema | Archivo |
|---|---|
| Proceso manual del cliente (5 pasos, columnas exactas) | `analisis/manual.md` |
| Pipeline de verificación InfoObras | `analisis/validacion_sugerida.md` |
| Arquitectura completa con SQL, API, endpoints | `dearrollo/IAs/claude3.md` |
| Resumen de arquitectura (alto nivel) | `dearrollo/IAs/claude3-2.md` |
| Informe para el cliente | `INFORME.md` |
| Procedimiento técnico con código | `PROCEDIMIENTO.md` |
