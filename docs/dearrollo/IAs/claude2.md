# 🎯 ARQUITECTURA COMPLETA - InfoObras Analyzer

Perfecto, ahora tengo el contexto completo del flujo manual. Voy a diseñar la arquitectura ajustada a este proceso real.

---

## 📋 ANÁLISIS DEL FLUJO REAL

### **Proceso Manual Actual:**

```
1. ENTRADA: PDF propuesta técnica (~2,300 págs)
   └─> Contiene múltiples certificados de experiencia

2. POR CADA CERTIFICADO:
   a) Extraer datos del certificado (OCR + LLM)
   b) Obtener CUI de la obra (buscar en Gemini o InfoObras)
   c) Scraping InfoObras con CUI:
      - Ficha pública
      - Datos de ejecución (fechas, actas)
      - Avances mensuales (estado por mes)
      - Informes de Contraloría (suspensiones)
   d) Descargar documentos:
      - Acta de entrega
      - Valorizaciones mensuales
      - Informes de control
   e) Calcular días efectivos:
      - Días declarados
      - Menos días de suspensión
      - Menos días de COVID
   f) Validar contra bases del concurso

3. SALIDA:
   - Excel con evaluación
   - Carpeta con documentos descargados
   - Alertas de observaciones
```

---

## 🏗️ ARQUITECTURA DETALLADA AJUSTADA

### **Componentes del Sistema:**

```
┌─────────────────────────────────────────────────────────────┐
│                  MÓDULO 1: OCR + EXTRACCIÓN                 │
├─────────────────────────────────────────────────────────────┤
│ Input:  PDF propuesta técnica (2,300 págs)                 │
│ Output: Lista de certificados extraídos                     │
│                                                             │
│ Proceso:                                                    │
│ 1. OCR con PaddleOCR (paralelo por páginas)                │
│ 2. Segmentación automática (detectar certificados)         │
│ 3. Extracción LLM por certificado:                         │
│    - Nombre profesional                                     │
│    - DNI, CIP                                               │
│    - Cargo                                                  │
│    - Nombre de obra                                         │
│    - CUI (si aparece)                                       │
│    - Fecha inicio / Fecha fin                               │
│    - Días declarados                                        │
│    - Empresa emisora                                        │
│    - Firmante                                               │
│                                                             │
│ Tecnología: PaddleOCR + Ollama (Qwen 2.5 14B)             │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              MÓDULO 2: BÚSQUEDA DE CUI                      │
├─────────────────────────────────────────────────────────────┤
│ Input:  Nombre de obra (del certificado)                   │
│ Output: CUI validado                                        │
│                                                             │
│ Proceso:                                                    │
│ 1. Si CUI ya está en certificado → usar directamente       │
│ 2. Si no hay CUI:                                           │
│    a) Buscar en InfoObras por nombre de obra               │
│    b) Si múltiples resultados → filtrar por fecha          │
│    c) LLM valida coincidencia (nombre obra vs resultado)   │
│                                                             │
│ Tecnología: Playwright + fuzzy matching + Ollama           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│          MÓDULO 3: SCRAPING INFOBRAS (CRÍTICO)              │
├─────────────────────────────────────────────────────────────┤
│ Input:  CUI de la obra                                      │
│ Output: Datos estructurados + PDFs descargados              │
│                                                             │
│ Sub-módulo 3.1: Ficha Pública                              │
│ - Fecha de contrato                                         │
│ - Fecha inicio prevista                                     │
│ - Fecha fin prevista                                        │
│ - Código InfoObra                                           │
│ - Monto contratado                                          │
│                                                             │
│ Sub-módulo 3.2: Datos de Ejecución                         │
│ - Fecha de entrega de terreno → descargar Acta             │
│ - Fecha inicio real                                         │
│ - Fecha fin real                                            │
│ - Estado actual                                             │
│                                                             │
│ Sub-módulo 3.3: Avances de Obra                            │
│ Por cada mes:                                               │
│ - Estado: Ejecutado / Paralizado / Suspendido              │
│ - Avance físico %                                           │
│ - Avance financiero %                                       │
│ - Descargar valorización (.doc) → OCR para extraer cargo   │
│                                                             │
│ Sub-módulo 3.4: Informes de Control (Contraloría)          │
│ - Descargar cada informe PDF                                │
│ - OCR + LLM para extraer:                                   │
│   * Periodos de suspensión (fechas inicio/fin)             │
│   * Motivo de suspensión                                    │
│   * Fecha de reactivación COVID                             │
│   * Fecha de término real                                   │
│   * Observaciones                                           │
│                                                             │
│ Estructura de descarga:                                     │
│ /downloads/{project_id}/documentos/                         │
│   └─ {Nombre_Obra}_{CUI}/                                   │
│      ├─ 01_Acta_Entrega_{CUI}.pdf                          │
│      ├─ 02_Val_Ene_2023.doc                                │
│      ├─ 02_Val_Feb_2023.doc                                │
│      ├─ ...                                                 │
│      └─ Informes_Control/                                   │
│         ├─ Informe_001_2023.pdf                            │
│         └─ Informe_002_2023.pdf                            │
│                                                             │
│ Tecnología: Playwright + Async download                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│       MÓDULO 4: CÁLCULO DE DÍAS EFECTIVOS                   │
├─────────────────────────────────────────────────────────────┤
│ Input:  - Fechas declaradas (certificado)                  │
│         - Avances mensuales (InfoObras)                     │
│         - Informes de suspensión                            │
│                                                             │
│ Output: Días efectivamente computables                      │
│                                                             │
│ Algoritmo:                                                  │
│                                                             │
│ 1. Días declarados = (fecha_fin - fecha_inicio) + 1        │
│                                                             │
│ 2. Identificar meses paralizados:                          │
│    For cada mes in rango(fecha_inicio, fecha_fin):         │
│        If avance[mes].estado == "Paralizado":              │
│            dias_paralizados += dias_del_mes                │
│                                                             │
│ 3. Identificar periodos de suspensión:                     │
│    For cada informe in informes_control:                   │
│        If hay_suspension:                                   │
│            fecha_inicio_susp = extraer_fecha_inicio()      │
│            fecha_fin_susp = extraer_fecha_fin()            │
│            If hay_overlap(rango_declarado, rango_susp):    │
│                dias_suspension += dias_overlap             │
│                                                             │
│ 4. Descuento COVID (si aplica):                            │
│    COVID_INICIO = 2020-03-15                               │
│    COVID_FIN = 2021-12-31                                  │
│    If hay_overlap(rango_declarado, COVID):                 │
│        dias_covid += dias_overlap                          │
│                                                             │
│ 5. RESULTADO:                                               │
│    dias_efectivos = dias_declarados                        │
│                     - dias_paralizados                      │
│                     - dias_suspension                       │
│                     - dias_covid                            │
│                                                             │
│ Tecnología: Python puro (datetime, dateutil)               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│            MÓDULO 5: MOTOR DE VALIDACIÓN                    │
├─────────────────────────────────────────────────────────────┤
│ Input:  - Datos profesional                                │
│         - Días efectivos calculados                         │
│         - Bases del concurso                                │
│                                                             │
│ Output: Evaluación + Alertas                                │
│                                                             │
│ Validaciones:                                               │
│                                                             │
│ V-01: Días efectivos vs Mínimo requerido                   │
│       If dias_efectivos < dias_minimos_bases:              │
│           → ALERTA CRÍTICA: No cumple experiencia mínima   │
│                                                             │
│ V-02: Días declarados vs Días calculados                   │
│       If dias_declarados != (fecha_fin - fecha_inicio):    │
│           → ALERTA: Discrepancia en cálculo de días        │
│                                                             │
│ V-03: Cargo declarado vs Cargo en valorizaciones           │
│       fuzzy_match(cargo_certificado, cargo_valorizacion)   │
│       If score < 80%:                                       │
│           → ALERTA: Cargo no coincide                      │
│                                                             │
│ V-04: Periodo dentro de vigencia de obra                   │
│       If fecha_inicio_cert < fecha_inicio_obra:            │
│           → ALERTA: Experiencia antes del inicio de obra   │
│       If fecha_fin_cert > fecha_fin_obra:                  │
│           → ALERTA: Experiencia después del fin de obra    │
│                                                             │
│ V-05: Verificación de suspensiones                         │
│       If hay_suspensiones_no_descontadas:                  │
│           → ALERTA: Período incluye suspensiones           │
│                                                             │
│ V-06: Presunción de veracidad (LPAG)                       │
│       If contradiccion_infobras:                           │
│           → ALERTA: InfoObras contradice certificado       │
│           → Presunción de veracidad CAE                    │
│                                                             │
│ Tecnología: Python puro (if/else)                          │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│         MÓDULO 6: VERIFICACIONES EXTERNAS                   │
├─────────────────────────────────────────────────────────────┤
│ 6.1: SUNAT (RUC empresa)                                    │
│ - Fecha de constitución                                     │
│ - If fecha_constitucion > fecha_inicio_cert:               │
│     → ALERTA: Empresa no existía en ese periodo            │
│                                                             │
│ 6.2: CIP (Colegio de Ingenieros)                           │
│ - Verificar vigencia de colegiatura                         │
│ - If CIP no vigente en periodo:                            │
│     → ALERTA: CIP no vigente                               │
│                                                             │
│ 6.3: RNP (Registro Nacional de Proveedores)                │
│ - Historial de contratos de la empresa                      │
│                                                             │
│ Tecnología: Playwright (con CAPTCHA fallback manual)       │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│            MÓDULO 7: GENERACIÓN DE EXCEL                    │
├─────────────────────────────────────────────────────────────┤
│ Estructura del Excel:                                       │
│                                                             │
│ HOJA 1: Resumen Ejecutivo                                  │
│ - Total profesionales evaluados                             │
│ - Cumplen: X                                                │
│ - No cumplen: Y                                             │
│ - Con observaciones: Z                                      │
│ - Alertas críticas: N                                       │
│                                                             │
│ HOJA 2: Detalle por Profesional                            │
│ Columnas:                                                   │
│ | # | Nombre | DNI | CIP | Cargo | Obra | CUI |            │
│ | Fecha Inicio | Fecha Fin | Días Declarados |             │
│ | Días Paralizados | Días Suspendidos | Días COVID |       │
│ | Días Efectivos | Días Mínimos | ¿Cumple? | Observaciones│
│                                                             │
│ HOJA 3: Alertas                                             │
│ | Profesional | Código Alerta | Severidad | Descripción |  │
│                                                             │
│ HOJA 4: Detalle de Suspensiones                            │
│ Por cada obra:                                              │
│ | CUI | Obra | Fecha Inicio Susp | Fecha Fin Susp |        │
│ | Días | Motivo | Fuente |                                  │
│                                                             │
│ HOJA 5: Avances Mensuales                                  │
│ | CUI | Mes | Estado | Avance Físico % | Avance Financiero %│
│                                                             │
│ Formato:                                                    │
│ - Colores:                                                  │
│   * Verde: Cumple                                           │
│   * Amarillo: Observación menor                             │
│   * Rojo: No cumple / Alerta crítica                        │
│ - Filtros activados                                         │
│ - Tablas dinámicas                                          │
│                                                             │
│ Tecnología: openpyxl + xlsxwriter                          │
└─────────────────────────────────────────────────────────────┘
```