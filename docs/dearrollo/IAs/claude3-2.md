# InfoObras Analyzer — Resumen de Arquitectura

**Cliente:** Grupo Echandía (Alpamayo/Indeconsult)
**Desarrollador:** Rafael Ramos Huamaní
**Fecha:** Marzo 2026

---

## ¿Qué hace el sistema?

Automatiza la verificación de experiencia profesional en propuestas técnicas de concursos públicos.

**Entrada:** PDF propuesta (~2,300 págs) + Bases del concurso
**Salida:** Excel con evaluación + ZIP con documentos descargados + Alertas

---

## Pipeline

```
PDF propuesta
    ↓
OCR (PaddleOCR) — convierte páginas escaneadas a texto
    ↓
Segmentación — divide 2300 págs en ~45 certificados
    ↓
LLM (Qwen2.5 14B, temp=0) — extrae datos → JSON
    ↓
PostgreSQL — almacena datos estructurados
    ↓
Motor de reglas (Python puro) — genera 9 alertas
    ↓
Scraping (Playwright) — verifica en InfoObras, SUNAT, CIP
    ↓
Cálculo de días efectivos — descuenta paralizaciones
    ↓
Excel (openpyxl) — reporte con colores rojo/amarillo/verde
```

**Tiempo:** 3-30 min por PDF (vs 12+ horas manual)

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Base de datos | PostgreSQL |
| LLM | Qwen 2.5 14B vía Ollama |
| OCR | PaddleOCR (Tesseract fallback) |
| Scraping | Playwright |
| Excel | openpyxl |
| Frontend | Next.js 14 |
| Cola de tareas | Redis |
| Deploy | Ubuntu 22.04 + Docker + NVIDIA CUDA |

---

## 7 Módulos del Sistema

| # | Módulo | Qué hace |
|---|---|---|
| 1 | **OCR + Segmentación** | PDF → texto por página → detectar certificados |
| 2 | **Extracción LLM** | Certificado → JSON (nombre, cargo, fechas, empresa, obra) |
| 3 | **Scraping InfoObras** | Buscar obra por CUI → fechas reales, paralizaciones, descargar docs |
| 4 | **Cálculo de días** | Días declarados − paralizaciones − suspensiones − COVID = días efectivos |
| 5 | **Motor de reglas** | 9 alertas determinísticas (if/else en Python) |
| 6 | **Generación Excel** | 5 hojas: Resumen, Detalle, Alertas, Suspensiones, Avances |
| 7 | **API + Frontend** | Web para subir PDF, ver progreso, descargar resultados |

---

## Las 9 Alertas

| Código | Qué detecta |
|---|---|
| ALT-01 | Fecha fin posterior a la emisión del certificado |
| ALT-02 | Experiencia abarca periodo COVID |
| ALT-03 | Experiencia con más de 20 años de antigüedad |
| ALT-04 | Empresa constituida después del inicio de experiencia |
| ALT-05 | Dice "a la fecha" sin fecha explícita |
| ALT-06 | Cargo no válido según bases |
| ALT-07 | Profesión no coincide con la requerida |
| ALT-08 | Tipo de obra no coincide con bases |
| ALT-09 | CIP no vigente |

---

## Base de Datos (5 tablas principales)

```
projects → certificates → professionals
                               ↓
                           alerts
                               ↓
                        verifications (InfoObras, SUNAT, CIP)
                               ↓
                          obra_data (avances, suspensiones, descargas)
```

Tabla extra: `processing_logs` (para tracking del progreso)

---

## API (6 endpoints)

| Método | Ruta | Función |
|---|---|---|
| POST | `/api/upload` | Subir PDF |
| GET | `/api/status/{id}` | Ver progreso |
| WS | `/ws/status/{id}` | Progreso en tiempo real |
| GET | `/api/download/excel/{id}` | Descargar Excel |
| GET | `/api/download/docs/{id}` | Descargar documentos (ZIP) |
| DELETE | `/api/project/{id}` | Eliminar proyecto |

---

## Excel de Salida (5 hojas)

| Hoja | Contenido |
|---|---|
| Resumen | Totales: cumplen, no cumplen, alertas críticas |
| Detalle Profesionales | Nombre, cargo, obra, CUI, días declarados/efectivos, ¿cumple? |
| Alertas | Código, severidad, descripción por profesional |
| Suspensiones | CUI, fechas, días, motivo, fuente |
| Avances Mensuales | CUI, mes, estado, avance físico/financiero |

Colores: 🟢 Cumple · 🟡 Observación · 🔴 No cumple

---

## Cronograma (7 semanas)

| Semana | Qué se hace | Entregable |
|---|---|---|
| 1 | OCR + Segmentación + BD | PDF → 45 certificados en BD |
| 2 | Extracción LLM + Cálculo días | 45 profesionales con datos estructurados |
| 3 | Scraping InfoObras (parte 1) | Datos de obras en BD |
| 4 | Scraping InfoObras (parte 2) + SUNAT/CIP | Verificaciones completas |
| 5 | Motor de reglas + Excel | Excel completo con alertas |
| 6 | Frontend + API | Web funcional |
| 7 | Testing + Deploy + Capacitación | Sistema en producción |

---

## Riesgos Principales

| Riesgo | Qué pasa | Mitigación |
|---|---|---|
| InfoObras cambia | Scraper deja de funcionar | Cache + fallback manual |
| OCR falla en docs malos | No extrae texto | Preprocesamiento + Tesseract fallback |
| SUNAT tiene CAPTCHA | No se puede verificar empresa | Verificación manual asistida |

---

## Hardware Mínimo

- **GPU:** NVIDIA 16GB+ VRAM (RTX 3090/4090)
- **RAM:** 32-64 GB
- **CPU:** 8-16 cores
- **Disco:** SSD NVMe 500GB+
- **SO:** Ubuntu 22.04 LTS

---

## Métricas de Éxito

| Métrica | Meta |
|---|---|
| Precisión OCR | ≥ 90% |
| Certificados detectados | 100% |
| Campos extraídos correctos | ≥ 95% |
| CUIs encontrados en InfoObras | ≥ 85% |
| Cálculo de días | 100% sin errores |
| Tiempo total | < 30 min por PDF |
