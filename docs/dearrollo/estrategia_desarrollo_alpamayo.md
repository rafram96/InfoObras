# Estrategia de Desarrollo: Análisis de Requerimientos y Propuesta Técnica "InfoObras Analyzer"

A partir del análisis detallado de la transcripción, he elaborado una estrategia de desarrollo técnica óptima orientada a mitigar los riesgos principales (velocidad, calidad de OCR en escaneos malos, alucinaciones de IA y scraping), asegurando robustez funcional.

---

## 1. Arquitectura del Sistema (Backend & Frontend)

Dado que el procesamiento de grandes volúmenes de documentos pesados bloquea conexiones fácilmente, se debe utilizar una arquitectura asíncrona guiada por tareas (Task-Queue Architecture).

*   **API y Orquestación:** **FastAPI (Python)**. Ideal para microservicios de IA, con excelente soporte para carga/descarga de archivos e integración nativa asíncrona y Swagger (para documentar la API).
*   **Gestor de Colas (Workers):** **Celery respaldado por Redis o RabbitMQ**. Cuando el archivo de 2000 páginas entra al sistema, la API no lo procesa al instante, solo lo encola y responde un `Task_ID` (ej: "Procesando..."). 
*   **Base de Datos:** **PostgreSQL** (para guardar los metadatos del concurso, profesionales guardados, links a InfoObras cacheados y la traza de los jobs).
*   **Frontend (Intranet Web):** **React.js, Vue.js o Next.js**. Para construir una UI ágil que haga "polling" o use WebSockets para mostrar el avance en tiempo real (barra de progreso por folios procesados), el Chatbot integrado y brinde los botones de exportación a Excel.

---

## 2. Estrategia de IA, OCR y Procesamiento (El Core)

### 2.1. El Cuello de Botella: Ingesta Masiva y OCR
Enviar un PDF escaneado de 2000 páginas como imagen a GPT-4 Vision o Gemini Pro no solo es caro, sino que tiene un límite de cuota altísimo y es la causa de que a Gemini "le dé flojera o alucine".

*   **Solución Modular Dividida:**
    1.  **División y Layout:** Un script en Python rompe el PDF en fragmentos o imágenes hoja por hoja y desecha documentos masivos de fotos sin texto (mediante un modelo ligero de clasificación de imagen o LayoutMv3).
    2.  **Motor OCR Dedicado Local:** Utilizar **DocTR (Document Text Recognition by Mindee)**, **Surya OCR** o un pipeline de **Tesseract** con pre-procesamiento de imagen en OpenCV optimizado para GPU. Esto mapea texto a coordenadas en la hoja (Trazabilidad).

### 2.2. Lógica Híbrida de IA: Menos es Más
*   **Enrutador Heurístico / LLM Pequeño:** Una vez se tiene el texto, NO se manda a un súper LLM. Un modelo local pequeño o reglas de PNL tradicionales filtran: *¿Esta página parece un certificado, un CV, parte del TDR o basura?*
*   **Extracción de Información (Generación Estructurada):** Aquí entra un modelo local potente como **Llama-3-8B-Instruct** o **Mistral-7B**. Se le envía el folio OCR específico, instándolo mediante frameworks tipo `Instructor` u `Outlines` para forzar que el Output sea **estrictamente JSON**. (Esto elimina el problema de outputs fragmentados y evita que la IA cambie formatos). 
*   **Sistema RAG para Chat (El requerimiento extra):** Se vectoriza todo el texto en una base de datos vectorial local (ej: ChromaDB o Qdrant) para que el Chatbot de consultas contextuales (pedido por Rafael) sea directo y certero.

---

## 3. Manejo Determinista de Reglas de Negocio (Adiós a Alucinaciones)

La inteligencia artificial **no debe ser usada para realizar cálculos matemáticos de fechas ni juicios finales de descalificación**. La regla de oro aquí es: *La IA lee y extrae los datos, Python hace el cálculo y emite el juicio.*

*   **Coherencia y Alertas:** Una vez la base de variables en formato JSON está extraída (ej. "Fecha emisión", "Inicio Obras"). El backend lo compara corriendo lógica estricta en Python.
    *   `if "Fecha de Emisión" < "Fecha de Fin Experiencia" = FLAG_ALERTA`
*   **Semántica Restringida para Literalidad de Cargo:** Para saber si "Supervisor de Equipamiento" cumple el TDR de "Jefe de Supervisión", se utiliza medición de similitudes (Embeddings). Si el score es dudoso (ej. entre 60% y 80%), el Excel emite un estado *AMARILLO ("Requiere revisión humana")*.

---

## 4. Estrategia de Scraping de InfoObras

El CUI (Código Único de Inversiones) será el input automático extraído y pasado a un módulo completamente asíncrono e independiente del procesamiento del PDF.
*   **Scraping API/DOM:** Construir un sistema como prueba de concepto usando la librería `requests` de Python (asumiendo llamadas API tras el rediseño) o `Playwright` (si hay protecciones frontend simples tipo Cloudflare).
*   **Tolerancia a Fallos:** Las webs del Estado fallan. Si InfoObras se cae a mitad de procesamiento de un expediente de licitación, el software no debe fallar; el output debe ser "Verificación Omitida - Sistema Contraloría Inestable" para no frenar la productividad manual de Manuel.

---

## 5. Arquitectura de Hardware (On-Premise On Demand)

Dado que se requiere extrema privacidad (On-Premise) y velocidad sobre PDFs de alto peso y OCR:

*   **GPU (Tarjeta Gráfica):** Imprescindible. Mínimo 1, preferiblemente 2 x **NVIDIA RTX 3090 / RTX 4090** (24 GB VRAM c/u). Las tarjetas gráficas manejarán la inferencia ultra-rápida del modelo Llama 3 y la aceleración del Layout Analysis y OCR de manera masiva.
*   **Procesamiento y Memoria:** Procesador de hilos múltiples (ej. AMD Ryzen 9 O Threadripper / Intel i9). Al menos 64 GB o 128 GB de RAM (DDR5) y almacenamiento en disco de estado sólido NVMe (Velocidad de Lectura/Escritura es fundamental para partir y escribir archivos de 250MB rápido).

---

## 6. Plan de Acción Recomendado (Fases)

**Fase 1: PoC de Riesgo Crítico (1-2 Semanas)**
1.  **Benchmarking OCR:** Pedir al cliente un par de archivos y comparar precisión de extracción de fechas bajo firmas en un pipeline real.
2.  **Robustecer Script de InfoObras:** Finalizar y probar la prueba de concepto del Scraper.

**Fase 2: Motor de Extracción Local (3-4 Semanas)**
1.  Servidor local de IA asíncono implementado (Ollama/vLLM o Transformers nativos).
2.  Script de extracción estructurada TDR vs Propuesta desde cero hasta formar el JSON de entidades exacto.

**Fase 3: Reglas de Análisis y Exportación (2-3 Semanas)**
1.  Cruzar de base de datos extraída y Scraper de infoobras implementando el motor de Alertas Falsas.
2.  Desarrollo de exportación Excel semaforizado (`pandas` / `openpyxl`).

**Fase 4: Desarrollo Web Frontend y Empaquetado (3 Semanas)**
1.  Implementar la Intranet Web y el chatbot de documento (RAG).
2.  Implementar links a "Folios" para la extrema trazabilidad del documento.
3.  Despliegue final en Workstation.
