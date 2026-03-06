# Propuesta Técnica y Económica

## InfoObras Analyzer — Sistema de Verificación Automatizada de Propuestas Técnicas

| | |
|---|---|
| **Cliente:** | Ing. Manuel Echandía — Inmobiliaria Alpamayo |
| **Desarrollador:** | Rafael Ramos Huamaní |
| **Fecha:** | 6 de marzo de 2026 |

---

<!--
═══════════════════════════════════════════════════════════════
NOTAS DE NEGOCIACIÓN (No mostrar al cliente)
═══════════════════════════════════════════════════════════════

CONTEXTO:
Costo real: ~S/. 25,000 (350 horas × S/. 70/h promedio)
Precio propuesto: S/. 13,500 (subsidio ~46%)
APU-Spec cerrado en S/. 8,500 (155h, 5 semanas)
InfoObras: ~350h, 7 semanas, ~2.3x APU-Spec en horas
Precio: ~1.6x APU-Spec → proporción justa con descuento

COMPARATIVA:
| Aspecto        | APU-Spec     | InfoObras              |
| Semanas        | 5            | 7                      |
| IA real        | RAG+ChromaDB | Solo extracción JSON   |
| OCR            | No           | Sí (PaddleOCR)         |
| Scraping       | No           | Sí (3 portales)        |
| Lo difícil     | RAG+prompts  | Scraping gubernamental |

LÍNEA ROJA: S/. 10,000 mínimo absoluto sin infra.
            S/. 11,500 mínimo con infra.
═══════════════════════════════════════════════════════════════
-->

## 1. Introducción

En base a la reunión del 6 de marzo de 2026, presento la propuesta para **InfoObras Analyzer**: un sistema que automatiza el análisis de propuestas técnicas de concursos públicos.

### Lo que hace el sistema

Convierte el flujo manual actual:

```
PDF → partir en 6 → Gemini × 6 → copiar → Excel → Gemini × 6 → Infobras manual
                                    12+ horas por concurso
```

En un flujo de un solo paso:

```
Subir PDF + Bases → sistema procesa todo → Excel con alertas + verificaciones
                            3 – 5 minutos
```

### Concretamente:

- **Procesar el PDF completo** (~2,300 págs.) sin partirlo. Lo segmenta automáticamente en ~45 certificados y los procesa en paralelo.
- **Extraer datos de cada profesional** (nombre, cargo, fechas, proyecto, empresa, CIP, folio).
- **Evaluar contra las bases** con columnas cumple/no cumple.
- **9 alertas automáticas** (fechas, COVID, antigüedad, firmante, tipo de obra, etc.).
- **Verificar en Infobras** (paralizaciones, valorizaciones, supervisores).
- **Consultar SUNAT/CIP** (empresa, vigencia colegiatura).
- **Generar el Excel** con el formato que ya se maneja.
- **Propiedad total** del cliente. **100% local**, sin suscripciones.

---

## 2. Solución Técnica

### Arquitectura

| Capa | Componente | ¿Es IA? |
|---|---|---|
| 1 | OCR del PDF escaneado (PaddleOCR) | ❌ Herramienta |
| 2 | Segmentación en certificados individuales | ❌ Código |
| 3 | Extracción de datos por certificado (LLM local) | ✅ **Único punto de IA** |
| 4 | Base de datos PostgreSQL | ❌ BD estándar |
| 5 | Motor de reglas + 9 alertas (Python if/else) | ❌ Código puro |
| 6 | Scraping Infobras/SUNAT/CIP (Playwright) | ❌ Scraping web |
| 7 | Interfaz web + Excel (React + openpyxl) | ❌ Web estándar |

**La IA solo extrae datos. Todo lo demás es código determinístico** — no inventa, no omite, no falla.

### Diferencia clave vs Gemini actual

| Qué hace | Gemini hoy | InfoObras Analyzer |
|---|---|---|
| Comparar fechas | La IA (puede equivocarse) | **Código** (100% exacto) |
| Detectar alertas | La IA (puede omitir) | **Código** (nunca omite) |
| Evaluar cumplimiento | La IA (puede inventar) | **Código** (deterministico) |
| Verificar Infobras | Tú, manualmente | **Scraping automático** |

---

## 3. Propuesta Económica

<!--
═══════════════════════════════════════════════════════════════
DESGLOSE REAL (NO MOSTRAR):

| Componente                    | Horas | Real       | Cobro    |
|-------------------------------|-------|------------|----------|
| PoC                           | 25h   | S/. 2,500  | S/.1,000 |
| OCR + Segmentación + Extrac.  | 80h   | S/. 6,400  | S/.2,800 |
| Motor reglas + alertas + Excel| 35h   | S/. 2,800  | S/.1,500 |
| Scraping Infobras + verif.    | 90h   | S/. 7,200  | S/.3,000 |
| SUNAT/CIP                     | 25h   | S/. 2,000  | S/.  800 |
| Interfaz web + oferta econ.   | 65h   | S/. 5,200  | S/.2,400 |
| TOTAL                         | 320h  | S/.26,100  |S/.11,500 |
| Infra                         |       |            | S/.1,500 |
| GRAN TOTAL                    |       |            |S/.13,000 |

LÍNEA ROJA: S/. 10,000 sin infra.
═══════════════════════════════════════════════════════════════
-->

### Fase Previa: Prueba de Concepto (PoC)

> ⚠️ El OCR sobre documentos reales y el scraping de Infobras tienen incertidumbre. La PoC los valida antes.

| Componente | Inversión |
|---|---|
| **Prueba de Concepto:** Benchmark OCR con documentos reales del cliente. Prueba de scraping Infobras (estructura, CAPTCHA). Prototipo de segmentación de certificados + extracción LLM. Informe GO/NO-GO. | **S/. 1,000.00** |

**Si la PoC falla, el cliente solo paga la PoC.** Sin penalidad.

---

### Desglose de Inversión

| Componente | Inversión |
|---|---|
| **Pipeline OCR + Segmentación + Extracción IA:** Preprocesamiento de imagen para documentos escaneados. Motor OCR (PaddleOCR). Segmentación automática del PDF en ~45 certificados individuales. Extracción paralela con Qwen2.5 14B (prompt basado en las sintaxis del cliente). Almacenamiento en PostgreSQL. | **S/. 2,800.00** |
| **Motor de Reglas, Alertas y Excel:** 9 alertas automáticas (código Python, no IA). Evaluación contra requerimientos de las bases. Excel con formato del cliente, columnas cumple/no cumple, alertas coloreadas. | **S/. 1,500.00** |
| **Scraping Infobras + Verificación Cruzada:** Scraper del portal Infobras (búsqueda, datos generales, avances mensuales). Detección de paralizaciones. Descarga de valorizaciones. OCR sobre valorizaciones + fuzzy matching de supervisores. Organización de archivos en directorios. | **S/. 3,000.00** |
| **Verificaciones Externas (SUNAT/CIP):** Consulta SUNAT (fecha constitución empresa). Vigencia CIP. Fallback manual si hay CAPTCHA. | **S/. 800.00** |
| **Interfaz Web + Oferta Económica:** Panel web (subir PDF, ver progreso, resultados, descargar Excel). Acceso multiusuario por red interna. Verificación matemática de oferta económica. | **S/. 2,400.00** |
| **Subtotal** | **S/. 11,500.00** |

### Infraestructura: Servidor IA Local

| Concepto | Inversión |
|---|---|
| **Configuración del Servidor:** Ubuntu Server, NVIDIA CUDA, Ollama, Qwen2.5 14B, PostgreSQL, FastAPI, red interna. *Si ya tiene infra de APU-Spec, se reduce (solo agregar PostgreSQL + web server).* | **S/. 1,500.00** |

### Resumen

| Resumen | Monto |
|---|---|
| Prueba de Concepto | S/. 1,000.00 |
| Subtotal Proyecto | S/. 11,500.00 |
| Infraestructura (si aplica) | S/. 1,500.00 |
| **INVERSIÓN TOTAL** | **S/. 14,000.00** |
| **Con infra APU-Spec existente** | **S/. 13,000.00** |

<!--
═══════════════════════════════════════════════════════════════
OPCIONES DE NEGOCIACIÓN:

OPCIÓN 1 — Dos bloques:
"Bloque A — Core (S/. 6,300):
   PoC + OCR + Reglas/Alertas + Excel
   → Ya elimina las 6 corridas, genera Excel automático.
 Bloque B — Verificaciones (S/. 6,200):
   Infobras + SUNAT/CIP + Web
   → Agrega verificación automática."

OPCIÓN 2 — MVP mínimo:
"Solo Core sin web (S/. 5,300):
   PoC + OCR + Reglas + Excel
   Resultado: script de línea de comandos → Excel
   Sin Infobras, sin SUNAT, sin web."

OPCIÓN 3 — Todo pero pagado en fases:
"Fase A: S/. 6,300 (semanas 1-3) → demo funcional
 Fase B: S/. 6,200 (semanas 4-7) → sistema completo
 Si la Fase A no te convence, paramos ahí."

SI DICE "ES CARO":
"Manuel, hoy pierdes 12+ horas por concurso.
 Con 15 concursos al año: 180 horas × S/. 200/h = S/. 36,000.
 Este sistema se paga en 6 meses."
═══════════════════════════════════════════════════════════════
-->

### Condiciones de Pago

| Hito | % | Monto | Condición |
|---|---|---|---|
| Anticipo al Inicio | 40% | S/. 5,600.00 | Firma + entrega de docs de muestra |
| Demo Funcional | 30% | S/. 4,200.00 | Sistema procesa PDF real → Excel con alertas (Semana 3) |
| Entrega Final | 30% | S/. 4,200.00 | Sistema completo + Infobras + web + capacitación (Semana 7) |

*Montos sobre inversión de S/. 14,000. Se ajustan proporcionalmente si aplican descuentos.*

---

## 4. Plan de Trabajo (7 Semanas)

| Semana | Fase | Entregable |
|---|---|---|
| 1 | **PoC + OCR** | Benchmark OCR. Prueba Infobras. GO/NO-GO. |
| 2 | **Extracción + BD** | PDF completo → segmentación → JSON → PostgreSQL |
| 3 | **Reglas + Excel** | Motor de reglas. 9 alertas. Excel del cliente. **← DEMO** |
| 4 – 5 | **Infobras** | Scraping, paralizaciones, valorizaciones, verificación cruzada |
| 5 – 6 | **Externos + Web** | SUNAT/CIP. Interfaz web. Oferta económica. |
| 7 | **Entrega** | Deploy servidor. Testing. Capacitación. Manual. |

---

## 5. ROI

| Concepto | Manual | Con sistema |
|---|---|---|
| Tiempo por concurso | 12+ horas | ~1 hora |
| Costo por concurso | S/. 2,000 – 3,000 | S/. 200 – 400 |
| Concursos/año | 15-20 | 15-20 |
| **Costo anual** | **S/. 30,000 – 60,000** | **S/. 3,000 – 8,000** |
| **Ahorro anual** | | **S/. 27,000 – 52,000** |

Punto de equilibrio: **menos de 6 meses**.

---

## 6. Servidor Recomendado

| Componente | Mínimo |
|---|---|
| GPU | NVIDIA RTX 4090 (24 GB VRAM) |
| RAM | 64 GB |
| SSD | 2 TB NVMe |
| CPU | Ryzen 9 / i9 |
| SO | Ubuntu Server 22.04 |

*Hardware a cargo del cliente.*

---

## 7. Garantía y Soporte

Incluido:

- **90 días de soporte** para corrección de errores.
- **3 iteraciones de ajuste** (reglas, alertas, formato Excel, scraper si Infobras cambia).
- **Capacitación** (2 horas) con concurso real.
- **Manual de usuario**.
- **Asistencia remota**.

No incluye funcionalidades nuevas fuera del alcance.

---

## 8. Exclusiones

- ❌ Hardware del servidor
- ❌ Licencias de OCR comercial (si la PoC lo determina necesario)
- ❌ Cambios en portales externos después de garantía
- ❌ Funcionalidades fuera de este documento
- ❌ Viáticos fuera de Lima

---

## Cierre

InfoObras Analyzer convierte **12+ horas de trabajo manual** en **3-5 minutos de procesamiento automático**. Las reglas son código; la IA solo extrae datos. La PoC protege la inversión.

Quedo a disposición para coordinar el inicio.

<!--
═══════════════════════════════════════════════════════════════
SCRIPT DE CIERRE:

"Manuel, resumiendo:
 ✓ 3-5 minutos vs 12+ horas
 ✓ Sin partir PDFs, sin Gemini
 ✓ Las reglas son CÓDIGO — no se inventa, no se omite
 ✓ Infobras automático
 ✓ SUNAT y CIP automático
 ✓ TU Excel con TUS alertas
 ✓ La PoC protege tu inversión: S/. 1,000 si no funciona
 ✓ 90 días garantía + 3 calibraciones

 ¿Avanzamos completo (S/. 14,000)
 o empezamos con Core (S/. 6,300 → demo en semana 3)
 y sumamos Infobras después?"
═══════════════════════════════════════════════════════════════
-->
