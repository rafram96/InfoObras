# Propuesta Técnica y Económica

## InfoObras Analyzer — Sistema de Verificación Automatizada de Propuestas Técnicas

| | |
|---|---|
| **Cliente:** | Ing. Manuel Echandía — Inmobiliaria Alpamayo |
| **Desarrollador:** | Rafael Ramos Huamaní |
| **Fecha:** | 7 de marzo de 2026 |

---

<!--
═══════════════════════════════════════════════════════════════
NOTAS DE NEGOCIACIÓN (No mostrar al cliente)
═══════════════════════════════════════════════════════════════

CONTEXTO:
APU-Spec: S/. 8,500 → "Muy caro" primero, aceptado después.
InfoObras: S/. 9,500 = solo S/. 1,000 más (12%).
Argumento: complejidad equivalente, frecuencia de uso mayor.

IMPORTANTE — YA TENEMOS EVIDENCIA REAL:
La PoC de Infobras YA está hecha (buscar.py, detalle_probe.py).
- Infobras responde con requests puro (sin Playwright, sin CAPTCHA).
- Portal completamente público, sin login.
- 6 endpoints mapeados: búsqueda, ficha, preparación, ejecución, cierre.
- lSupervisor, lResidente, lAvances, lModificacionPlazo → todo disponible.
- Tiempo por CUI: ~5-8 segundos.
- Riesgo técnico de Infobras: ELIMINADO.

Esto significa:
- No hay PoC separada (ya está hecha).
- No hay riesgo de scraping de Infobras.
- El único riesgo real que queda es el OCR.
- Semanas reales probablemente reducibles a 6.

DESGLOSE REAL:
| Componente                    | Horas | Cobro    |
|-------------------------------|-------|----------|
| OCR + Segmentación + Extrac.  | 80h   | S/.2,800 |
| Motor reglas + alertas        | 30h   | S/.1,100 |
| Integración Infobras completa | 50h   | S/.1,800 | ← ya hay código base
| SUNAT/CIP                     | 20h   | S/.  700 |
| Generación Excel              | 20h   | S/.  700 |
| Interfaz Web                  | 50h   | S/.1,800 |
| Testing + entrega             | 20h   | S/.  600 |
| TOTAL                         | 270h  | S/.9,500 |

S/. 9,500 ÷ 270h = S/. 35/h
VS histórico: SEACE S/. 37/h, APU-Spec S/. 61/h, Config Server S/. 87/h.
Bajo, pero es cliente estratégico.

LÍNEA ROJA: S/. 8,500 (igual que APU-Spec).
            No bajar de ahí.

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

En un flujo de tres minutos:

```
Subir PDF + Bases → sistema procesa todo → Excel con alertas + verificaciones
                                  ~3 minutos
```

### Concretamente:

- **Procesar el PDF completo** (~2,300 págs.) sin partirlo. Segmentación automática en ~45 certificados procesados en paralelo.
- **Extraer datos de cada profesional** automáticamente (nombre, cargo, fechas, proyecto, empresa, CIP, folio en el PDF).
- **Evaluar contra las bases** con columnas cumple/no cumple.
- **9 alertas automáticas** como código determinístico: fechas inconsistentes, periodo COVID, antigüedad, empresa posterior a experiencia, "a la fecha", cargo inválido, profesión, tipo de obra, CIP.
- **Verificar en Infobras** automáticamente: estado de obra, paralizaciones, supervisor/residente en el periodo del certificado.
- **Consultar SUNAT** para fecha de constitución de empresa.
- **Generar el Excel con tu formato**, incluyendo todas las columnas de evaluación y alertas coloreadas.
- **Propiedad total.** Todo en tu servidor local, sin suscripciones, sin nube.

---

## 2. Solución Técnica (resumen)

### El pipeline

```
PDF completo
    │
    ▼
OCR + Segmentación          ← PaddleOCR, ~45 certificados detectados
    │
    ▼ (paralelo)
Extracción con LLM          ← ÚNICO punto de IA (Qwen2.5 14B, local)
    │
    ▼
PostgreSQL                  ← Base de datos estructurada
    │
    ▼
Motor de reglas             ← Python if/else — no inventa, no omite
    │
    ▼
Verificación Infobras       ← API pública, requests, ~5-8 seg por obra
    │
    ▼
SUNAT / CIP                 ← Consultas automatizadas
    │
    ▼
Excel con alertas + Web
```

### IA vs Código

| Qué | Cómo | Por qué importa |
|---|---|---|
| Extraer datos del certificado | LLM (IA) | Texto desestructurado, formatos variables |
| Comparar fechas, cargos, tipos | Código Python | 100% exacto, nunca omite |
| Detectar 9 alertas | Código Python | Determinístico, auditable |
| Verificar en Infobras | API pública | Sin CAPTCHA, sin login, ~5-8 seg/obra |
| Verificar empresa en SUNAT | Scraping | Automatizable |
| Generar Excel | openpyxl | Template + datos |

---

## 3. Propuesta Económica

<!--
═══════════════════════════════════════════════════════════════
COMPARATIVA PARA EL CLIENTE (mostrar si lo pide):

| Proyecto  | Precio   | Complejidad principal   | Semanas |
|-----------|----------|-------------------------|---------|
| APU-Spec  | S/. 8,500| RAG + ChromaDB          | 5       |
| InfoObras | S/. 9,500| OCR + Scraping Infobras | 7       |

Argumento: "Solo S/. 1,000 más (12%) para un sistema
que usarás 15-20 veces/año vs 4-7 de APU-Spec."
═══════════════════════════════════════════════════════════════
-->

### **INVERSIÓN TOTAL: S/. 9,500**

La propuesta se divide en dos fases con entregables verificables:

---

### Fase 1 — Demo Funcional (3 semanas): **S/. 4,200**

| Componente | Detalle |
|---|---|
| **OCR + Segmentación** | PaddleOCR con preprocesamiento de imagen. Detección automática de bloques de certificados. Procesamiento paralelo del PDF completo. |
| **Extracción con LLM** | Qwen2.5 14B local (prompts basados en tu sintaxis actual en Gemini). JSON estructurado por profesional → PostgreSQL. |
| **Motor de reglas + 9 alertas** | Comparación contra bases del concurso. Código Python puro: no inventa, no omite. |
| **Generación de Excel** | Tu formato exacto. Columnas cumple/no cumple. Alertas coloreadas (rojo/amarillo). |

**✅ DEMO al final de Fase 1:** El sistema procesa un PDF real tuyo y genera el Excel automáticamente. Tu criterio para aprobar el segundo pago.

**Elimina inmediatamente:** Las 6 corridas en Gemini, el partir manual el PDF, el copiar/pegar resultados.

---

### Fase 2 — Sistema Completo (4 semanas): **S/. 5,300**

| Componente | Detalle |
|---|---|
| **Integración Infobras** | Búsqueda por CUI, extracción de datos generales, estado de ejecución, supervisores/residentes históricos, detección de paralizaciones por mes. |
| **Verificaciones SUNAT/CIP** | Fecha de constitución de empresa. Vigencia CIP. Alerta automática si empresa fue constituida después de la experiencia. |
| **Interfaz web** | Panel accesible por red interna. Subir PDF, ver progreso, revisar resultados, descargar Excel. Multiples usuarios. |
| **Análisis de oferta económica** | Verificación matemática de fórmulas, subtotales y totales. Reporte de inconsistencias. |
| **Integración final + deploy** | Instalación en tu servidor. Testing con concurso completo real. |

**✅ ENTREGA al final de Fase 2:** Sistema completo operativo en tu servidor.

---

### Condiciones de Pago

| Hito | % | Monto | Condición |
|---|---|---|---|
| Anticipo al Inicio | 40% | **S/. 3,800** | Inicio del proyecto + entrega de PDFs para testing |
| Aprobación Demo (Fase 1) | 30% | **S/. 2,850** | Sistema genera Excel con PDF real tuyo (Semana 3) |
| Entrega Final (Fase 2) | 30% | **S/. 2,850** | Sistema completo en servidor + capacitación (Semana 7) |

---

### Comparación con APU-Spec

| Proyecto | Precio | Complejidad | Semanas | Uso estimado/año |
|---|---|---|---|---|
| APU-Spec | S/. 8,500 | RAG + ChromaDB + 130 partidas | 5 | 4–7 veces |
| **InfoObras** | **S/. 9,500** | OCR + Infobras + Motor reglas | 7 | **15–20 veces** |

**La diferencia es solo S/. 1,000 (12%)** para un sistema que usarás 3–4 veces más frecuente que APU-Spec.

---

### ROI (Conservador)

```
15 concursos/año
× 10 horas ahorradas por concurso (de 12+ a ~1-2 horas)
= 150 horas/año

150 horas × S/. 150/hora (costo de tu tiempo profesional)
= S/. 22,500/año en tiempo recuperado

Inversión: S/. 9,500
Punto de equilibrio: ~5 meses
```

Sin contar el valor de las observaciones detectadas automáticamente que hoy pueden escaparse.

---

## 4. Plan de Trabajo (7 semanas)

| Semana | Fase | Entregable |
|---|---|---|
| 1 | **OCR + Segmentación** | Pipeline OCR funcional. PDF completo → ~45 certificados detectados. |
| 2 | **Extracción + BD** | LLM extrae entidades → JSON → PostgreSQL. |
| 3 | **Reglas + Excel** | Motor de reglas. 9 alertas. Excel con tu formato. **← DEMO** |
| 4 – 5 | **Infobras** | Integración completa: búsqueda, estado, paralizaciones, supervisores, residentes. |
| 5 – 6 | **SUNAT/CIP + Web** | Verificaciones externas. Panel web completo. Oferta económica. |
| 7 | **Entrega** | Deploy en servidor. Testing completo. Capacitación. Manual. |

---

## 5. Insumos Necesarios del Cliente

| Insumo | Para qué | Cuándo |
|---|---|---|
| PDFs de propuestas (mínimo 2-3 concursos) | Testing OCR y extracción | Inicio |
| Bases del concurso (TdR) | Configurar motor de reglas | Inicio |
| Sintaxis/prompts actuales de Gemini | Calibrar LLM de extracción | Semana 2 |
| Excel de formato actual | Replicar columnas exactas | Semana 2 |
| Servidor con GPU disponible | Deploy en Fase 2 | Semana 6 |
| Definición de rango "periodo COVID" | Configurar alerta ALT-02 | Semana 3 |

---

## 6. Servidor Recomendado

| Componente | Mínimo |
|---|---|
| GPU | NVIDIA RTX 4090 (24 GB VRAM) |
| RAM | 64 GB |
| SSD | 2 TB NVMe |
| SO | Ubuntu Server 22.04 |

*Hardware a cargo del cliente. Si ya cuenta con el servidor instalado para APU-Spec, no hay costo adicional de infraestructura.*

---

## 7. Garantía y Soporte

Incluido en la inversión:

- **90 días de soporte** para corrección de errores post-entrega.
- **3 iteraciones de calibración:** Ajuste de reglas, alertas, formato Excel, umbrales de confianza OCR.
- **Capacitación (2 horas)** con un concurso real.
- **Manual de usuario.**
- **Asistencia remota** para incidencias dentro del periodo de garantía.

Las iteraciones no incluyen funcionalidades fuera del alcance definido.

---

## 8. Exclusiones

- ❌ Hardware del servidor (adquisición por el cliente)
- ❌ Licencias de software comercial (si el OCR de documentos muy deteriorados requiere motor de pago — se definirá en Semana 1 con tus PDFs reales)
- ❌ Funcionalidades fuera de este documento
- ❌ Cambios de portales externos (SUNAT, CIP) post-garantía
- ❌ Viáticos fuera de Lima

---

## 9. Limitaciones y Riesgos Conocidos

| Riesgo | Estado | Mitigación |
|---|---|---|
| **OCR en documentos deteriorados** | ⚠️ A validar en Semana 1 con tus PDFs | Preprocesamiento de imagen + PaddleOCR. Si es insuficiente en casos extremos, se marca con baja confianza para revisión manual. |
| **Portal Infobras** | ✅ Validado | API pública funcional, sin CAPTCHA, sin login. Datos estructurados disponibles (supervisores, paralizaciones, avances). |
| **SUNAT con CAPTCHA** | ⚠️ Posible | Fallback manual asistido: formulario en la interfaz web para ingresar dato manualmente. No bloquea el sistema. |

<!--
═══════════════════════════════════════════════════════════════
OPCIONES DE NEGOCIACIÓN SI PRESIONA PRECIO:

OPCIÓN A: MVP sin web (S/. 8,500 = mismo que APU-Spec)
"Si quieres el mismo precio que APU-Spec:
 Te entrego el sistema completo de análisis (OCR + Reglas + Infobras + Excel)
 pero sin interfaz web — script CLI que corre desde terminal.
 Interface web la agregamos después como upgrade (+S/. 1,500)."

OPCIÓN B: Dos etapas separadas
"Fase A ahora: S/. 4,200 (demo funcional — elimina ya el trabajo con Gemini)
 Fase B después: S/. 5,300 (Infobras + Web)
 Lo decides después de ver la demo."

ARGUMENTO CLAVE SI DICE "ES CARO":
"Manuel, solo para el módulo de Infobras:
 ¿Cuánto tiempo te toma revisar manualmente cada proyecto en Infobras?
 ¿15-20 minutos por proyecto?
 Con 20 proyectos por concurso y 15 concursos al año: 
 = 75-100 horas solo en Infobras.
 El sistema las hace en segundos."

ARGUMENTO INFOBRAS VALIDADO (usar esto):
"Ya probé el acceso a la API de Infobras.
 El portal es completamente público, sin CAPTCHA.
 Toda la información que necesitas (supervisores, paralizaciones, avances)
 está disponible en formato JSON estructurado.
 El módulo ya tiene las bases técnicas resueltas."
═══════════════════════════════════════════════════════════════
-->

---

## Cierre

**InfoObras Analyzer** convierte 12+ horas de análisis manual en ~3 minutos de procesamiento automático. Las reglas de evaluación son código — no hay riesgo de que la IA invente o se olvide de un caso. Infobras ya fue validado: toda la información necesaria es pública y accesible.

La Fase 1 actúa como demo funcional: pagas el segundo tramo **solo si validas con tus propios documentos** que el sistema funciona correctamente.

Quedo a disposición para coordinar el inicio.

<!--
═══════════════════════════════════════════════════════════════
SCRIPT DE CIERRE:

"Manuel, comparando con APU-Spec:
 ✓ Mismo nivel de inversión (S/. 9,500 vs S/. 8,500 — 12% más)
 ✓ Sistema que usarás 3-4x más frecuente que APU-Spec
 ✓ Infobras ya validado: API pública, sin bloqueos
 ✓ Demo en semana 3: ves el Excel generado antes de pagar el 60% restante
 ✓ 90 días garantía + 3 calibraciones

 ¿Avanzamos con S/. 3,800 de anticipo
 y en 3 semanas tienes la demo?"
═══════════════════════════════════════════════════════════════
-->
