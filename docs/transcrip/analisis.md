Analizando la transcripción directamente con el prompt de análisis de requerimientos:

**RESUMEN EJECUTIVO**

Reunión técnica entre un cliente (empresa de licitaciones/concursos públicos en Perú) y un desarrollador, donde se describe un sistema semi-manual actual en Gemini para analizar propuestas técnicas de concursos públicos. El objetivo es automatizarlo completamente con un servidor propio con IA especializada.

---

## REQUERIMIENTOS FUNCIONALES

**RF-01 · Extracción de datos de profesionales desde PDFs escaneados** `ALTA`
Procesar archivos PDF de propuestas técnicas (hasta ~2300 páginas) mediante OCR y extraer datos de cada profesional: nombre, profesión, fecha de colegiatura, especialidad, cargo, empresa emisora, fecha de emisión y firma autorizada.
- Criterios: Soportar PDFs escaneados de baja legibilidad; extraer mínimo 10–11 campos por profesional; no requerir partir el archivo manualmente.

**RF-02 · Comparación de profesionales contra bases del concurso** `ALTA`
Contrastar los datos extraídos de cada profesional con los requerimientos mínimos establecidos en las bases del concurso (años de colegiatura, tipo de experiencia, cargo válido, tipo de obra, etc.) y emitir veredicto de cumplimiento.
- Criterios: Generar columnas de "cumple / no cumple" por cada criterio; comparar título profesional, cargo desempeñado y tipo de proyecto.

**RF-03 · Generación de tabla Excel estructurada de resultados** `ALTA`
Exportar los datos extraídos y evaluados a un archivo Excel con columnas predefinidas (nombre, DNI, E-SIP, nombre del proyecto, tipo obra, tipo intervención, fechas inicio/fin, fecha emisión del certificado, duración, etc.).
- Criterios: Estructura consistente en cada ejecución; compatible con el Excel de análisis del cliente.

**RF-04 · Sistema de alertas automáticas** `ALTA`
Detectar y marcar anomalías en los certificados de experiencia:
- Certificado con fecha de fin posterior a su fecha de emisión.
- Experiencia que abarca periodo COVID (paralización).
- Experiencia con más de 20–25 años de antigüedad respecto a la fecha de la propuesta.
- Empresa/consorcio firmante constituida después de la fecha de inicio de la experiencia.
- Presencia de "a la fecha" en lugar de fecha explícita de fin.
- Firmante sin poderes legales verificables.

**RF-05 · Scraping y consulta en Infobras** `ALTA`
Buscar automáticamente cada proyecto en el portal Infobras (por código de proyecto o CIP) y extraer: fecha de contrato, fecha de inicio de obra, fecha de finalización, estado (en ejecución / paralizado), avances mensuales de obra.
- Criterios: Detectar si el proyecto estuvo paralizado en el periodo declarado en el certificado; identificar si el profesional aparece como responsable en las valorizaciones de esos meses.

**RF-06 · Descarga y organización de documentos de Infobras** `MEDIA`
Bajar automáticamente actas y valorizaciones del portal Infobras, organizarlas en directorios nombrados por código de proyecto, con nomenclatura predefinida (ej. `01_acta_entrega_terreno`, `valorización_marzo_2021`).
- Criterios: Estructura de carpetas reproducible; archivos renombrados con convención acordada.

**RF-07 · Verificación de nombre del jefe/supervisor en valorizaciones** `MEDIA`
Cruzar el nombre del profesional declarado en el certificado con el nombre del responsable que aparece en las valorizaciones descargadas de Infobras en los meses correspondientes.
- Criterios: Reportar discrepancias en una columna de alerta; señalar el mes y documento donde difiere.

**RF-08 · Consulta de vigencia de CIP en CAPECO / Colegio Profesional** `MEDIA`
Verificar que el CIP del profesional esté vigente a la fecha de emisión de la propuesta.
- Criterios: Columna de alerta si CIP no vigente o no encontrado.

**RF-09 · Búsqueda web de fecha de constitución de empresa** `MEDIA`
Para cada empresa o consorcio que firma un certificado, buscar en internet (SUNAT / Registros Públicos) la fecha de constitución, registrarla en el Excel y emitir alerta si es posterior a la fecha de inicio de la experiencia declarada.
- Criterios: Indicar fuente (URL) de la consulta; alerta automática ante inconsistencia.

**RF-10 · Interfaz de chat con agente IA especializado** `MEDIA`
Proveer una interfaz de chat web (solución interna) conectada a un modelo de lenguaje local especializado, accesible por múltiples usuarios de la empresa vía red interna.
- Criterios: Temperatura baja (respuestas precisas, no creativas); accesible 24/7; sin dependencia de servicios externos de pago por uso.

**RF-11 · Análisis y validación de oferta económica** `BAJA`
Revisar la oferta económica de un concurso, verificar que los cálculos matemáticos sean correctos e identificar errores.
- Criterios: Emitir reporte de inconsistencias; señalar fórmulas o totales incorrectos.

---

## REQUERIMIENTOS NO FUNCIONALES

**RNF-01 · Rendimiento** — El sistema debe procesar un PDF de ~2300 páginas completo sin necesidad de partirlo en fragmentos, con tiempos de respuesta razonables.

**RNF-02 · OCR sobre documentos escaneados** — Capacidad de extraer texto de PDFs escaneados de baja resolución o legibilidad reducida, habitual en documentos peruanos.

**RNF-03 · Privacidad** — El procesamiento debe realizarse en servidor propio de la empresa; los documentos no deben enviarse a servicios en la nube de terceros.

**RNF-04 · Disponibilidad** — El servidor debe operar 24/7 sin intervención manual.

**RNF-05 · Precisión / Temperatura del modelo** — El modelo debe ceñirse estrictamente a las instrucciones sin "inventar" datos; temperatura baja configurable.

**RNF-06 · Escalabilidad interna** — La solución web debe soportar múltiples usuarios simultáneos de la empresa conectados al servidor local.

---

## RESTRICCIONES

- Los documentos fuente son mayoritariamente PDFs escaneados (no tienen capa de texto nativa), lo que hace obligatorio el OCR.
- El portal Infobras es externo y público; el scraping depende de su disponibilidad y estructura.
- Actualmente el cliente usa Gemini (API externa) con límites de contexto que obligan a fragmentar los archivos; el sistema deseado debe eliminar esa restricción.
- El servidor debe ser instalado como activo físico de la empresa.
- El presupuesto y plazo no están definidos; el cliente exige "lo antes posible".

---

## AMBIGÜEDADES

- No se especificó qué hacer cuando Infobras no tiene registro del proyecto (proyecto anterior al portal, o sin código).
- No está definido el criterio exacto para considerar un periodo como "COVID" (¿solo 2020? ¿también 2021?).
- El mecanismo para verificar poderes legales del firmante no fue detallado.
- No se aclaró si la búsqueda de fecha de constitución de empresa debe cubrir consorcios (entidades temporales sin registro único).
- El formato exacto del Excel de salida no fue entregado en la reunión (el cliente mencionó mandarlo después).

---

## RIESGOS

- El OCR sobre documentos escaneados de baja calidad puede generar extracción incorrecta de fechas y nombres, produciendo falsos positivos/negativos en las alertas.
- El portal Infobras puede cambiar su estructura HTML o requerir autenticación, rompiendo el scraping.
- Dependencia de un único desarrollador para todo el sistema (riesgo de continuidad).
- El cliente opera con urgencia pero sin fecha límite formal, lo que puede generar entregas incompletas bajo presión.
- Modelos de lenguaje locales (open source) pueden tener menor capacidad de comprensión de documentos técnicos peruanos comparado con modelos comerciales.