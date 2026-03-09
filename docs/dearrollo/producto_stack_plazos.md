# Definición del Producto "InfoObras Analyzer": Alcance, Stack Tecnológico y Cronograma

Este documento define de manera concreta qué componentes conforman el sistema, las herramientas tecnológicas seleccionadas para construirlo bajo la restricción *On-Premise* e IA Local, y el tiempo estimado para su desarrollo e implementación.

---

## 1. ¿Qué se va a construir? (Estructura del Sistema)

El sistema será una plataforma web de uso interno (Intranet) compuesta por 5 módulos principales:

1.  **Módulo de Ingesta y Procesamiento de Documentos (Pipeline OCR)**
    *   **Funcionalidad:** Carga de PDFs masivos (+250MB, +2000 páginas).
    *   **Proceso:** Separación del PDF en hojas individuales, clasificación de las páginas (descarte de "hojas basura", retención de CVs, certificados y TDR) y ejecución de OCR (reconocimiento óptico de caracteres) conservando las coordenadas para trazabilidad (saber en qué folio está cada texto).

2.  **Módulo de Extracción de Datos (IA Local Estructurada)**
    *   **Funcionalidad:** Lectura del texto extraído y conversión a datos estructurados.
    *   **Proceso:** Lectura de las Bases/TDR para extraer la "Matriz de Requisitos". Lectura de la propuesta para extraer "Nombre, Fechas, Cargos, Entidad emisora y CUI" de manera JSON estricta y sin alucinaciones.

3.  **Módulo de Integración Externa (Scraping InfoObras)**
    *   **Funcionalidad:** Búsqueda automatizada en el portal de la Contraloría usando el código CUI o SNIP.
    *   **Proceso:** Extracción de la fecha real de inicio/fin de la obra y detección de periodos de paralización o suspensión.

4.  **Módulo de Validación y Alertas (Motor de Reglas de Negocio)**
    *   **Funcionalidad:** Motor de cálculo con lógica dura y determinista.
    *   **Proceso:** Cruce de requisitos (Bases vs Propuesta). Evaluación de coherencia temporal (fechas de emisión vs fines de contrato, cruce con fechas de InfoObras, fechas de creación de empresas en SUNAT). Generación de alertas (Rojo/Verde) por posibles documentos falsos o inconsistentes.

5.  **Interfaz de Usuario e Interacción (Frontend y Chatbot)**
    *   **Funcionalidad:** Pantalla web para que Manuel y su equipo operen el sistema.
    *   **Proceso:** Dashboard con estado de procesamiento (barra de progreso), visor para saltar directamente al folio analizado, botón de exportación del reporte final consolidado en Excel y un Chatbot interactivo (basado en RAG) para hacerle preguntas manuales sobre los documentos cargados.

---

## 2. ¿Con qué se va a construir? (Stack Tecnológico)

El stack técnico está diseñado para maximizar el rendimiento en el procesamiento de documentos pesados y asegurar la privacidad absoluta de los datos.

*   **Infraestructura Base y Entorno:**
    *   **Servidor Físico (Hardware):** Workstation o Servidor dedicado con **GPU NVIDIA** (Ej. mínimo 1x RTX 3090/4090 de 24GB VRAM, ideal 2). Al menos 64GB de RAM y SSD NVMe.
    *   **Sistema Operativo / Contenedores:** Linux (Ubuntu Server) con **Docker** y Docker Compose para orquestar todos los microservicios, facilitando el despliegue iterativo.

*   **Backend, API y Orquestación de Tareas:**
    *   **Lenguaje:** Python 3.11+.
    *   **Framework Web:** **FastAPI** (Altamente concurrente y veloz para manejar subidas de archivos grandes y servir la API).
    *   **Worker / Background Jobs:** **Celery** + **Redis** (o RabbitMQ). Esencial para que el sistema procese el PDF de 2,000 páginas en segundo plano sin colgar la interfaz web del usuario.
    *   **Base de Datos:** **PostgreSQL** para almacenar configuración, metadatos, cruces de información y cachear resultados de InfoObras exitosos.

*   **Motor de IA y Extracción de Datos:**
    *   **OCR:** **DocTR** (Mindee) o **Surya** (Optimizado para extraer texto y coordenadas bounding boxes en GPU) o Tesseract afinado.
    *   **LLM (Inteligencia Artificial Local):** **Llama-3 (8B)** o **Mistral (7B)** servido mediante **vLLM** o **Ollama**. (Modelos abiertos instalados en el propio servidor que no envían datos a internet, con coste cero por texto analizado).
    *   **Librería de Conversión a JSON:** **Instructor** u **Outlines** en Python (Obligan al LLM a devolver llaves/valores exactos y evitan la "vagancia" del modelo).
    *   **Chatbot Documental (RAG):** **LangChain** + Base de datos vectorial ligera como **ChromaDB** o **Qdrant** (para que el Chat entienda todo el contexto completo de las propuestas).

*   **Web Scraping y Automatización:**
    *   **Librerías:** **Playwright** (Si InfoObras usa renderizado pesado en Javascript o Cloudflare) o la librería `requests` + `BeautifulSoup` (si el API directo de InfoObras está accesible).

*   **Frontend (Interfaz Web):**
    *   **Framework:** **Next.js** (React) o **Vue.js + Nuxt**, idealmente con **TailwindCSS** para diseñar un panel intuitivo y moderno de uso interno.
    *   **Exportación:** Librerías nativas en python (`pandas`, `openpyxl`) o librerías TS en frontend para compilar la salida de resultados al formato MS Excel requerido.

---

## 3. Plazo de Previsión de Construcción (Cronograma)

El desarrollo del proyecto, considerando su complejidad técnica (Extracción de IA + OCR + Scraping Gubernamental), comprenderá aproximadamente entre **8 a 10 semanas (2.5 meses)** para tener una versión de producción estable y funcional, dividida en las siguientes fases (Sprints):

**Fase 1: Módulos de Riesgo Crítico y PoCs (Semanas 1 y 2)**
*   Aprobación e instalación del Hardware (GPU).
*   Prueba de concepto de Scraping a InfoObras: Asegurar la extracción del CUI superando posibles trabas de seguridad.
*   Prueba exhaustiva del motor OCR sobre PDFs (ejemplos provistos por Manuel) con sellos/firmas difusos.
*   *Entregable:* OCR funcionando en consola y script de InforObras extrayendo JSON.

**Fase 2: Motor de Ingesta, División y Extracción IA (Semanas 3 a 5)**
*   Setup de FastAPI y Celery+Redis para cargas masivas asíncronas.
*   Lógica en Python para la partición de las 2,000 páginas.
*   Despliegue del Modelo Llama-3/Mistral local vía vLLM.
*   Prompts estructurados para extracción de Entidades de Bases/TDR y de los CVs/Certificados obligando al output JSON.
*   *Entregable:* API Backend capaz de recibir un PDF, parsearlo, leerlo con IA y almacenar las variables extraídas en la Base de Datos.

**Fase 3: Motor Python de Reglas de Negocio y Reporte (Semanas 6 y 7)**
*   Programación determinista de las reglas: cálculo superposición de fechas, match semántico de cargos, evaluación "A la fecha".
*   Integración automática de las respuestas de InfoObras en el proceso de evaluación.
*   Generador automático de documento Excel con formato customizado (Rojo/Verde, alertas y trazabilidad de folio).
*   *Entregable:* Sistema Back-to-End capaz de generar el Excel de salida a partir de los PDFs ingresados.

**Fase 4: Frontend y Chatbot Web (Semanas 8 y 9)**
*   Desarrollo UI/UX de la Intranet (Dashboard de Jobs en ejecución).
*   Visor integrado del PDF para comprobar las partes rojas (folios).
*   Implementación del subsistema RAG y ventana de Chat interactivo (Requisito de Rafael).
*   *Entregable:* Interfaz lista y conectada al backend.

**Fase 5: Despliegue, Ajustes y Pase a Producción (Semana 10)**
*   Configuración de contenedores en ambiente de producción (Servidor local On-Prem).
*   Ronda de pruebas con documentos en vivo y "tuning" final de umbrales del modelo.
*   Capacitación a Manuel y equipo en el uso del dashboard.
*   *Entregable Final:* Sistema InfoObras Analyzer v1.0 100% operativo en Alpamayo.
