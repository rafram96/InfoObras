A continuación presento el análisis detallado de la transcripción de la reunión para la elaboración del documento de requerimientos y propuesta.

---

## PARTE 1: INFORMACIÓN DEL CLIENTE Y CONTEXTO DE NEGOCIO

*   **Cliente:** Manuel Echanda (Evaluador/Analista de propuestas).
*   **Rol:** Se encarga de revisar propuestas técnicas y económicas para licitaciones públicas (concursos públicos), tanto las que su empresa presenta como las de la competencia para encontrar fallos y descalificarlos.
*   **Volumen de trabajo:**
    *   Archivos PDF masivos de aprox. 250 MB.
    *   Promedio de 2,000 a 2,300 páginas por propuesta.
    *   Debe analizar rangos específicos (ej. 300 páginas correspondientes a los profesionales).
*   **Herramientas actuales y limitaciones:**
    *   **Gemini (versión actual):** Útil para lógica, pero tiene límites de tokens ("se vuelve vaga", "alucina", se niega a procesar archivos muy grandes).
    *   **Proceso manual:** Manuel debe partir los PDFs en 6 o más partes manualmente para que la IA los procese.
    *   **Excel:** Construye tablas de cumplimiento manualmente o copiando outputs fragmentados de la IA.
    *   **InfoObras:** Consulta manual para verificar la veracidad de las obras.
*   **Tiempo actual:** Aproximadamente medio día (4-6 horas) dedicándose al 100% por propuesta, teniendo que repetir procesos múltiples veces.
*   **Usuarios:** Principalmente Manuel y su equipo interno. Acceso vía red interna.
*   **Urgencia:** Alta. "Lo necesito urgente", "para mañana si es posible".
*   **Competencia:** Analiza propuestas propias (control de calidad) y de competidores (para impugnar/descalificar).

---

## PARTE 2: REQUERIMIENTOS FUNCIONALES

### RF-01: Ingesta y Procesamiento de PDFs Masivos
*   **Descripción:** Capacidad de cargar archivos PDF escaneados (sin capa de texto) de más de 2000 páginas y 250MB sin necesidad de partirlos manualmente.
*   **Prioridad:** Crítica / Alta.
*   **Tecnología implícita:** OCR potente y manejo de memoria eficiente.

### RF-02: Extracción de Bases del Concurso (TDR)
*   **Descripción:** El sistema debe leer las "Bases" o "Términos de Referencia" (TDR) y extraer la matriz de requisitos para el personal clave.
*   **Inputs:** PDF de las Bases.
*   **Outputs:** Lista de requisitos (Cargo, Tiempo de experiencia, Tipo de obra, Colegiatura, etc.).

### RF-03: Extracción de Datos de Profesionales
*   **Descripción:** Extraer datos estructurados de los CVs y certificados presentados en la propuesta.
*   **Datos clave:** Nombre, Profesión, Fecha de colegiatura, Cargo desempeñado, Fechas de inicio/fin, Nombre de la obra.

### RF-04: Validación Cruzada (Propuesta vs. Bases)
*   **Descripción:** Comparar automáticamente si el profesional propuesto cumple con los requisitos extraídos en el RF-02.
*   **Reglas:**
    *   Validar coincidencia de cargo (semántica y literal).
    *   Validar tipo de obra (ej. "Hospital" es válido, "Carretera" no).
    *   Calcular tiempo de experiencia acumulada.
*   **Output:** Cuadro de Excel con columnas de "CUMPLE" / "NO CUMPLE" y motivos.

### RF-05: Sistema de Alertas de Veracidad (Reglas de Negocio)
*   **Descripción:** Detectar inconsistencias lógicas que sugieran documentación falsa o inexacta.
*   **Alertas específicas mencionadas:**
    *   *Fecha Emisión vs. Fin:* Si la fecha de emisión del certificado es anterior a la fecha de fin de la experiencia -> **ALERTA**.
    *   *Creación Empresa vs. Inicio:* Si la fecha de inicio de experiencia es anterior a la fecha de creación de la empresa emisora -> **ALERTA**.
    *   *Firmante:* Validar si quien firma es Representante Legal o tiene poderes vigentes.

### RF-06: Integración y Scraping de InfoObras
*   **Descripción:** El sistema debe buscar el código CUI o SNIP del proyecto en el portal "InfoObras" de la Contraloría.
*   **Funcionalidad:**
    *   Extraer fecha real de inicio y fin de obra según Contraloría.
    *   Identificar periodos de paralización o suspensión de obra.
    *   Descargar el "Acta de entrega de terreno" si está disponible.
*   **Validación:** Comparar fechas del certificado vs. fechas reales de ejecución/paralización en InfoObras. Si el certificado dice que trabajó en un mes que la obra estaba paralizada -> **ALERTA**.

### RF-07: Generación de Reportes
*   **Output:** Exportar un Excel consolidado (formato proporcionado por el cliente) con todas las validaciones, alertas y links a las fuentes de verificación.

---

## PARTE 3: REQUERIMIENTOS NO FUNCIONALES

*   **Infraestructura:** Servidor local (On-Premise). El cliente quiere que el hardware sea un activo de la empresa.
*   **Privacidad:** Alta. Los datos no deben salir a nubes públicas inseguras (o minimizarse). Uso de modelos locales preferible.
*   **Disponibilidad:** El servidor debe poder estar encendido 24/7 procesando colas de trabajo.
*   **Usabilidad:**
    *   Interfaz Web accesible desde la red interna de la empresa.
    *   Inclusión de un "Agente de Chat" (tipo chatbot) para hacer consultas específicas sobre los documentos cargados (solicitado por Rafael).
*   **Rendimiento:** Debe superar la velocidad actual (reducir las 4-6 horas de trabajo manual).
*   **Trazabilidad:** El sistema debe indicar en qué página (folio) encontró la información (ej. "Ver folio 2070").

---

## PARTE 4: REGLAS DE NEGOCIO CRÍTICAS

1.  **Regla de Coherencia Temporal (Certificados):**
    *   *Condición:* Fecha Emisión Certificado < Fecha Fin Experiencia Declarada.
    *   *Acción:* Marcar como documento inválido/falso.
2.  **Regla de Existencia Legal (Empresa):**
    *   *Condición:* Fecha Inicio Experiencia < Fecha Fundación Empresa (según SUNAT/RUC).
    *   *Acción:* Marcar como información falsa.
3.  **Regla de Paralizaciones (COVID/Otros):**
    *   *Condición:* Si el periodo de experiencia reclamado se superpone con un periodo declarado como "Suspensión de plazo" o "Paralización" en InfoObras.
    *   *Acción:* Descontar ese tiempo o invalidar la experiencia si se reclama continuidad absoluta.
4.  **Regla de Literalidad del Cargo:**
    *   *Condición:* Si las Bases piden "Jefe de Supervisión" y el certificado dice "Supervisor de Equipamiento".
    *   *Acción:* Evaluar si es equivalente o marcar NO CUMPLE (requiere IA semántica pero estricta).
5.  **Regla de "A la fecha":**
    *   *Condición:* Si un certificado dice que laboró "hasta la fecha" pero fue emitido hace meses.
    *   *Acción:* La experiencia solo es válida hasta la fecha de emisión del documento, no hasta el día de la presentación de la propuesta.

---

## PARTE 5: FLUJO DE TRABAJO COMPLETO

1.  **Carga:** El usuario sube el PDF de las Bases y el PDF de la Propuesta Técnica (masivo).
2.  **Análisis de Bases:** El sistema extrae los requisitos del perfil profesional.
3.  **Procesamiento de Propuesta:**
    *   OCR del documento completo.
    *   Identificación de secciones (Profesionales, Certificados, Declaraciones Juradas).
4.  **Extracción de Entidades:** El sistema extrae fechas, cargos, nombres de empresas, códigos CUI/SNIP.
5.  **Verificación Externa (Automática):**
    *   El sistema usa el CUI para consultar InfoObras.
    *   El sistema busca fecha de creación de empresas (posiblemente vía RUC/SUNAT scraping).
6.  **Cruce de Información:** Se ejecutan las reglas de negocio (Part 4) comparando Propuesta vs. Bases vs. InfoObras.
7.  **Reporte:** Se genera el Excel con semaforización (Rojo/Verde) y alertas de texto.

---

## PARTE 6: INFRAESTRUCTURA Y SERVIDOR

*   **Hardware:** Servidor físico dedicado (Workstation/Server).
*   **Componente Crítico:** GPU potente (tarjeta gráfica) para correr modelos de IA locales y realizar OCR rápido.
*   **Software:**
    *   Modelo de IA Local (ej. Llama 3, Mistral) para privacidad y costo cero por token.
    *   Motor de OCR (ej. Tesseract optimizado o soluciones comerciales on-premise).
    *   Web Server para la interfaz interna.
*   **Red:** Intranet (acceso local).

---

## PARTE 7: ACUERDOS Y PENDIENTES

*   **Pendientes del Desarrollador (Rafael):**
    *   Cotizar el hardware (servidor) urgentemente.
    *   Elaborar la propuesta técnica del desarrollo del software.
    *   Evaluar viabilidad técnica del scraping a InfoObras (evasión de captchas, etc.).
*   **Pendientes del Cliente (Manuel):**
    *   Enviar sintaxis/prompts que usa actualmente en Gemini (Enviado por WhatsApp durante la reunión).
    *   Enviar modelo de Excel de salida esperado (Enviado).
    *   Enviar archivos de ejemplo (PDFs de propuestas, reportes de InfoObras) (Enviado parte, pendiente completar).

---

## PARTE 8: SEÑALES IMPLÍCITAS Y OBSERVACIONES

*   **Dolor Real:** El cliente siente ansiedad por la posibilidad de que se le pasen detalles que podrían descalificar a un competidor o asegurar su propia propuesta. Busca "tranquilidad" y "velocidad".
*   **Riesgo Técnico - OCR:** La calidad de los documentos escaneados (sellos borrosos, firmas manuscritas) será el mayor desafío técnico. El OCR debe ser de muy alta calidad.
*   **Riesgo Técnico - InfoObras:** El scraping de portales del estado suele ser inestable (cambios de diseño, caídas del portal). Se debe advertir al cliente que este módulo puede requerir mantenimiento constante.
*   **Expectativa de IA:** El cliente espera que la IA razone como un humano experto ("Este cargo es raro, investígalo"). Se debe calibrar la "temperatura" del modelo para que sea estricto en validaciones pero capaz de entender sinónimos de cargos.

---

## PARTE 9: GLOSARIO DE TÉRMINOS DEL NEGOCIO

*   **TDR (Términos de Referencia):** Documento que detalla los requisitos técnicos que debe cumplir el proveedor.
*   **Bases:** Reglas del juego del concurso público.
*   **InfoObras:** Portal web de la Contraloría General de la República donde se registra el avance físico y financiero de las obras públicas.
*   **CUI (Código Único de Inversiones):** Código identificador de un proyecto de inversión pública.
*   **SNIP:** Antiguo sistema de identificación de proyectos (similar al CUI).
*   **Folio:** Número de página en el expediente (crucial para referencias legales).
*   **Colegiatura:** Número de registro en el Colegio Profesional (Ingenieros, Arquitectos).
*   **Valorización:** Documento que cuantifica el avance físico de la obra en un periodo para su pago.
*   **Entregables:** Productos o informes presentados durante la consultoría/obra.
*   **Acta de Entrega de Terreno:** Documento que marca el inicio oficial de la ejecución de una obra.

---

### Preguntas de seguimiento sugeridas para la propuesta:

1.  ¿Se requiere autenticación de usuarios con roles diferenciados (admin vs. analista)?
2.  ¿Qué nivel de error es tolerable en el OCR dado que los documentos son escaneos de baja calidad?
3.  ¿Se necesita guardar un histórico de todas las licitaciones analizadas para consultas futuras (Base de Datos Histórica)?
4.  ¿El sistema debe sugerir impugnaciones basándose en la ley de contrataciones o solo mostrar los hechos?