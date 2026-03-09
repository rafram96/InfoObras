# Proyecto InfoObras

## Objetivo
Revisión de Propuestas

## Análisis primario

- En el proceso actual se demora al menos medio día por propuesta (realmente concentrado, así que inclusive más)
- Archivos (PDF escaneados) gigantes (2300 Hojas)
- Le interesa principalmente el análisis de profesionales (en el caso de ejemplo recién iniciaron en la página 2065 aprox hasta la 2349 la información de los profesionales, el resto era 'relleno')
- Existen constancias de servicio donde está (estructurar esta información para procesar y verificar):
  - Nombre del profesional
  - Cargo del profesional
  - Nombre del proyecto
  - Periodo en que laboró
  - Empresa que emite la constancia
  - Fecha de emisión de la constacia
  - Y sello/firma de quien firma
- Se repitieron mínimamente cada paso 6 veces o posiblemente más (copiar, pegar en gemini, esperar, pegar en excel, etc), es manejable pero dividiendo el archivo en partes. Este procesa toma actualmente de 6hrs a más

## Dolores identificados
Para una tabla de pains-gains:
  - 'Pierdo tiempo partiendo los archivos'
  - 'Píerdo tiempo corriendo cada paso varias veces'

---

## Proceso ACTUAL (Para profesionales)
  - Divide el archivo en 6 partes (lo pasa a gemini)
  - Agrega las normas de OSCE 2025 (lo tiene guardado en notebookLM)


  ### PASO 1: RESUMIR CRITERIOS DE EVALUACION DE RTM PROFESIONALES
  
  **Objetivo:** Leer las BASES del concurso y consolidar un cuadro estructurado mostrando QUÉ SE SOLICITA para cada profesional
  
  **Entrada:** Solo el documento de BASES
  
  **Datos clave:** RTM = Requisitos Técnicos Mínimos. Si no se cumple, la propuesta se descalifica.
  
  **Ejemplo de extracción inicial:**
  ```yaml
  Cargo: Jefe de Supervisión
  Profesión: Ingeniero Civil
  Experiencia mínima: 8 años
  Experiencia específica: 3 supervisiones de obras hospitalarias
  ```

  **Cuadro de Profesionales - Estructura de columnas (1-6):**
  
  - **Columna 1 - Cargo y Profesión**: Precisar qué profesiones acepta cada cargo según los requisitos técnicos
  - **Columna 2 - Años de Colegiado**: Requisito mínimo de años de inscripción
  - **Columna 3 - Requisito Mínimo**: Número mínimo de años de experiencia o participaciones en supervisiones/ejecuciones. Señalar cargos similares válidos, con puntuación por cada experiencia y puntaje máximo alcanzable
  - **Columna 4 - Tipo de Obra/Proyecto**: Precisar qué tipo de experiencia cuenta como válida para el profesional
  - **Columna 5 - Tiempo Adicional**: Indicar tiempo adicional solicitado en los factores de evaluación para este profesional
  - **Columna 6 - Capacitación**: Señalar qué capacitación, de qué tipo, es solicitada en los factores de evaluación

  **Resultado estructurado:**
  ```yaml
  profesionales:
    - cargo: "Jefe de Supervisión"
      profesion: "Ing. Civil"
      anos_colegiado: 5
      experiencia_minima: "3 supervisiones hospitalarias"
      tipo_obra: "Hospitales"
      tiempo_adicional: "5 años extra"
      capacitacion: "Gestión de proyectos"
    
    - cargo: "Especialista Ambiental"
      profesion: "Ing. Ambiental"
      anos_colegiado: 3
      experiencia_minima: "2 proyectos"
      tipo_obra: "Obras públicas"
      tiempo_adicional: "3 años extra"
      capacitacion: "Gestión ambiental"
  ```
  **Importante**: Este paso es la definición de las reglas de validación

---

  ### PASO 2: RESUMIR PROFESIONALES PROPUESTOS
  
  **Objetivo:** Hacer un cuadro consolidado de todos los profesionales presentados en el PDF de la propuesta, según su colegiación y profesión
  
  **Entrada:** Solo la sección de profesionales de la de propuesta (PDF)
  
  **Cuadro de Profesionales Presentados - Estructura de columnas (1-5):**
  
  - **Columna 1 - Nombre del Profesional**: Nombre completo del profesional presentado
  - **Columna 2 - Profesión**: Profesión según título profesional oficial
  - **Columna 3 - Fecha de Colegiación**: Fecha de inscripción en el colegio profesional
  - **Columna 4 - Especialidad Postulada**: Especialidad a la que postula según bases o términos de referencia
  - **Columna 5 - Número de Página**: Página donde se encuentra la constancia de colegiación en el PDF (Aquí hay posibles casoso donde el número del folio (impreso en la hoja) sea diferente del número de la página de PDF, se quiere el número del FOLIO)
  
  **Advertencia importante**: NO OMITIR NINGÚN PROFESIONAL CLAVE
  
  **Resultado estructurado:**
  ```yaml
  profesionales_propuestos:
    - nombre: "Juan Pérez García"
      profesion: "Ingeniero Civil"
      fecha_colegiacion: "2015-06-15"
      especialidad_postulada: "Jefe de Supervisión"
      pagina: 2078
    
    - nombre: "María López Rodríguez"
      profesion: "Ingeniera Ambiental"
      fecha_colegiacion: "2018-03-22"
      especialidad_postulada: "Especialista Ambiental"
      pagina: 2145
  ```

---

  ### PASO 3: BASE DE DATOS DE EXPERIENCIAS DE PROFESIONALES

  **Objetivo:** Consolidar un cuadro de todas las experiencias presentadas en el PDF de propuesta para cada profesional

  **Entrada:** Solo la sección de profesionales de la propuesta (PDF)

  **Instrucciones críticas:**
  - Usar SOLO certificados, no documentos resumen o formatos
  - Si un certificado cubre más de un período, presentar un registro por período
  - Agrupar por profesional, ordenar cronológicamente por fecha fin (más reciente a más antigua)

  **Estructura de columnas (1–27):**

  **Datos del Profesional:**
  - **Columna 1 – Nombre del Profesional:** Nombre completo del profesional
  - **Columna 2 – DNI o Número de Colegiatura:** Identificador del profesional

  **Datos del Proyecto:**
  - **Columna 3 – Nombre del proyecto:** Nombre completo según el certificado
  - **Columna 4 – Cargo en el proyecto:** Cargo desempeñado durante la experiencia
  - **Columna 5 – Empresa/Consorcio emisor:** Nombre del consorcio o empresa que emite la constancia
  - **Columna 6 – RUC del emisor:** RUC del consorcio o empresa emisora

  **Clasificación:**
  - **Columna 7 – Tipo de obra:** Indicar si la obra es Pública o Privada
  - **Columna 8 – Tipo de acreditación:** Precisar si la experiencia es acreditada por un certificado emitido por el dueño del contrato o es producto de un subcontrato

  **Fechas de Experiencia:**
  - **Columna 9 – Fecha de inicio:** Fecha de inicio de la experiencia (formato DD/MES/AÑO)
  - **Columna 10 – Fecha de fin:** Fecha de término de la experiencia (formato DD/MES/AÑO)
  - **Columna 11 – Periodo COVID:** Si la fecha de fin (col. 10) es posterior al 15/03/2020 y la fecha de inicio (col. 9) es anterior al 15/03/2020, escribir "INCLUYE PERIODO COVID". En caso contrario, dejar en blanco
  - **Columna 12:** En blanco (reservada)
  - **Columna 13:** En blanco (reservada)
  - **Columna 14 – Duración:** Duración total de la experiencia

  **Certificado:**
  - **Columna 15 – Fecha de emisión:** Fecha de emisión del certificado (formato DD/MES/AÑO)
  - **Columna 16 – Alerta emisión:** Escribir "ALERTA" si la fecha de emisión del certificado es anterior a la fecha de fin de la experiencia. En caso contrario, dejar en blanco
  - **Columna 17 – Folio:** Número de folio donde se ubica el certificado en el PDF

  **Signatario:**
  - **Columna 18 – Nombre del firmante:** Nombre de quien firma el certificado
  - **Columna 19 – Cargo del firmante:** Cargo de quien firma el certificado
  - **Columna 20 – Alerta firmante:** Escribir "ALERTA" si quien firma no es el representante legal o representante máximo del emisor. En caso contrario, dejar en blanco

  **Validación de Empresa:**
  - **Columna 21 – Fecha de creación del emisor:** Fecha de inicio de actividades de la empresa o consorcio emisor, consultada en SUNAT (https://e-consultaruc.sunat.gob.pe) mediante RUC o nombre, tomando el campo "Fecha de Inicio de Actividades"
  - **Columna 22 – Alerta antigüedad del emisor:** Escribir "ALERTA" si la fecha de la columna 21 es posterior a la fecha de inicio de la experiencia (col. 9). En caso contrario, dejar en blanco
  - **Columna 23 – Alerta experiencia antigua:** Escribir "ALERTA" si la fecha de término (col. 10) supera los 20 años desde la fecha de presentación de la propuesta. En caso contrario, dejar en blanco

  **Datos Complementarios:**
  - **Columna 24 – Tipo de documento:** Precisar si presenta constancia, certificado u otro tipo de documento
  - **Columna 25 – Código CIU:** Código CIU del proyecto (col. 3), buscado en internet por nombre del proyecto
  - **Columna 26 – Código InfoObras:** Código InfoObras del proyecto (col. 3), buscado en internet por nombre del proyecto
  - **Columna 27 – Validación cruzada emisor:** Repetir la fecha de creación del emisor (igual que col. 21) y escribir "ALERTA" si esa fecha es posterior al inicio de la experiencia (col. 9). En caso contrario, dejar en blanco

  **Resultado estructurado:**
  ```yaml
  experiencias_profesionales:
    - nombre: "Juan Pérez García"
      dni_colegiatura: "12345678"
      proyecto: "Supervisión Hospital Regional del Sur"
      cargo: "Jefe de Supervisión"
      empresa_emisora: "Consorcio Salud Sur"
      ruc_emisor: "20501234567"
      tipo_obra: "Pública"
      tipo_acreditacion: "Certificado directo"
      fecha_inicio: "01/ENE/2018"
      fecha_fin: "30/JUN/2020"
      alerta_covid: "INCLUYE PERIODO COVID"
      col_12: ""
      col_13: ""
      duracion: "24 meses" # en meses
      fecha_emision: "15/JUL/2020"
      alerta_emision: ""
      folio: 2078
      nombre_firmante: "Carlos Ríos Vega"
      cargo_firmante: "Gerente General"
      alerta_firmante: ""
      fecha_creacion_emisor: "10/MAR/2015"
      alerta_antigüedad_emisor: ""
      alerta_experiencia_antigua: ""
      tipo_documento: "Certificado"
      codigo_ciu: "2186942" #código único de inversiones (PRINCIPAL)
      codigo_infoobras: "350456" # Es un id correlativo interno (autonumérico). Suele tener 5 o 6 dígitos
      validacion_cruzada_emisor: "10/MAR/2015"
  ```
  > Hasta el paso 3 ha sido creación de una BD del personal, el paso 4 es un análisis que necesita ser enriquecido

---

  ### PASO 4: EVALUACIÓN DE EXPERIENCIAS CONTRA CRITERIOS RTM (manualmente realizado hasta aquí)

  **Objetivo:** Evaluar si las experiencias de cada profesional propuesto cumplen los criterios básicos (RTM) establecidos en las bases

  **Entrada:** Propuesta de profesionales (PDF) + Bases o Términos de Referencia (TDR-RTM)

  **Instrucciones críticas:**
  - Usar SOLO certificados, no documentos resumen o formatos
  - Si un certificado cubre más de un período, presentar un registro por período
  - Agrupar por profesional, ordenar cronológicamente por fecha fin (más reciente a más antigua)
  - No omitir ninguna experiencia

  **Estructura de columnas (1–22):**

  **Identificación:**
  - **Columna 1 – Cargo en el proyecto:** Cargo postulado según la propuesta técnica
  - **Columna 2 – Nombre del Profesional:** Nombre completo del profesional propuesto
  - **Columna 3 – Profesión propuesta:** Profesión según título profesional indicado en la propuesta técnica
  - **Columna 4 – Profesión requerida:** Profesión exigida para el cargo según las bases o TDR (sección: Experiencia del Personal Clave / Capacidad Técnica y Profesional / Requisitos de Calificación)
  - **Columna 5 – ¿Cumple profesión?:** Indicar SI o NO. La profesión debe coincidir literalmente con lo indicado en las bases; si tiene alguna palabra adicional, indicar NO. No se considera diferencia de género como causal de incumplimiento
  - **Columna 6 – Folio del certificado:** Número de folio donde se ubica el certificado en la propuesta técnica (indicado en los extremos de la hoja, no el número de página del visor PDF)

  **Cargo de la Experiencia:**
  - **Columna 7 – Cargo en la experiencia:** Cargo desempeñado según el certificado presentado en la propuesta técnica
  - **Columna 8 – Cargos válidos según bases:** Cargos aceptados para el profesional según las bases o TDR (secciones: Formación Académica / Calificaciones del Personal Clave / Capacidad Técnica y Profesional / Requisitos de Calificación)
  - **Columna 9 – ¿Cumple cargo?:** Indicar CUMPLE o NO CUMPLE. El cargo debe coincidir literalmente con lo indicado en las bases; cualquier palabra adicional o diferencia implica NO CUMPLE. No se considera diferencia de género como causal de incumplimiento

  **Tipo de Proyecto/Obra:**
  - **Columna 10 – Proyecto/experiencia propuesto:** Nombre del proyecto o experiencia presentada en la propuesta técnica
  - **Columna 11 – Proyecto/experiencia válido según bases:** Tipo de obra, proyecto o experiencia válida para el cargo según las bases o TDR (sección: Experiencia del Personal Clave / Capacidad Técnica y Profesional / Requisitos de Calificación)
  - **Columna 12 – ¿Cumple proyecto/obra?:** Indicar SI o NO. El tipo de proyecto u obra debe ser igual a lo indicado en las bases

  **Fecha de Término:**
  - **Columna 13 – Fecha de término de la experiencia:** Fecha de fin indicada en el certificado
  - **Columna 14 – Alerta fecha de término:** Si el certificado no indica fecha de término, o señala "hasta la actualidad" o similar, escribir "NO VALE". Si tiene fecha de término definida, dejar en blanco

  **Tipología de Obra:**
  - **Columna 15 – Tipo de obra del certificado:** Tipología indicada en el certificado (ejemplos: obras en general, salud, educación, etc.)
  - **Columna 16 – Tipo de obra requerido por bases:** Tipología exigida por las bases para este profesional (ejemplos: obras en general, salud, educación, etc.)
  - **Columna 17 – ¿Cumple tipo de obra?:** Si el tipo de obra de la columna 15 coincide con lo requerido en la columna 16, indicar CUMPLE. En caso contrario, indicar NO CUMPLE

  **Tipo de Intervención:**
  - **Columna 18 – Intervención del certificado:** Si las bases exigen experiencia igual o similar, precisar el tipo de intervención indicada en el certificado (ejemplos: construcción, creación, mejoramiento, etc.). Si las bases no exigen experiencia similar, escribir "El tipo de intervención no importa"
  - **Columna 19 – Intervención requerida por bases:** Si las bases exigen experiencia igual o similar, precisar el tipo de intervención exigida en las bases o TDR (ejemplos: construcción, creación, mejoramiento, etc.). Si las bases no exigen experiencia similar, escribir "El tipo de intervención no importa"
  - **Columna 20 – ¿Cumple intervención?:** Si el tipo de intervención de la columna 18 coincide con lo requerido en la columna 19, indicar CUMPLE. En caso contrario, indicar NO CUMPLE

  **Validaciones Finales:**
  - **Columna 21 – ¿Acredita nivel de complejidad?:** Indicar si la experiencia acredita el nivel de complejidad solicitado por las bases para este profesional
  - **Columna 22 – ¿Dentro de los últimos 20 años?:** Indicar si la fecha de término de la experiencia se encuentra dentro de los últimos 20 años desde la fecha de presentación de la oferta

  **Resultado estructurado:**
  ````yaml
  evaluacion_rtm:
    - cargo_postulado: "Jefe de Supervisión"
      nombre: "Juan Pérez García"
      profesion_propuesta: "Ingeniero Civil"
      profesion_requerida: "Ingeniero Civil"
      cumple_profesion: "SI"
      folio: 2078
      cargo_experiencia: "Supervisor de Obra"
      cargos_validos: "Supervisor de Obra / Residente de Obra"
      cumple_cargo: "CUMPLE"
      proyecto_propuesto: "Supervisión Hospital Regional del Sur"
      proyecto_valido: "Supervisión de obras hospitalarias"
      cumple_proyecto: "SI"
      fecha_termino: "30/JUN/2020"
      alerta_fecha_termino: ""
      tipo_obra_certificado: "Salud"
      tipo_obra_requerido: "Salud"
      cumple_tipo_obra: "CUMPLE"
      intervencion_certificado: "Construcción"
      intervencion_requerida: "Construcción"
      cumple_intervencion: "CUMPLE"
      acredita_complejidad: "SI"
      dentro_20_anios: "SI"
  ````

  El análisis quiere enriquecer con mi aporte, posible alerta nueva si el 'cip' (cualquier código que sea viable comprobar vigencia a través una api o web) es vigente

---

  ### Paso de Verificación: Verificar experiencia de los profesionales (Como lo hace el estado)
  - Ver pipeline completo de extracción y verificación en InfoObras: [validacion_sugerida.md](validacion_sugerida.md)
  - Solamente sugerencia vaga sin explicar aún: Que se evalue la evaluación económica de una oferta (si está bien o está mal, es tema matemático)

  ---
  
  ### PASO 5: EVALUACIÓN DE AÑOS DE EXPERIENCIA REQUERIDOS

  **Objetivo:** Evaluar si cada profesional propuesto cumple con el número de años de experiencia exigidos, tanto en los Requisitos Técnicos Mínimos (RTM) como en los factores de evaluación

  **Entrada:** Propuesta de profesionales (PDF) + Bases o Términos de Referencia (TDR-RTM)

  **Instrucciones críticas:**
  - Usar SOLO certificados, no documentos resumen o formatos
  - Un registro por profesional

  **Estructura de columnas (1–7):**

  - **Columna 1 – Nombre del profesional:** Nombre completo del profesional propuesto
  - **Columna 2 – Cargo al que postula:** Cargo postulado según la propuesta técnica
  - **Columna 3 – Años acumulados propuestos:** Número de años de experiencia acumulada que acredita el profesional según los certificados presentados en la propuesta técnica
  - **Columna 4 – Años requeridos por RTM:** Número mínimo de años de experiencia que debe acreditar el profesional para el cargo según los Requisitos Técnicos Mínimos de los TDR
  - **Columna 5 – ¿Cumple RTM?:** Indicar SI si el valor de la columna 3 es igual o superior al de la columna 4. En caso contrario, indicar NO CUMPLE en mayúscula
  - **Columna 6 – Años requeridos por factor de evaluación:** Número de años de experiencia acumulada exigidos en el factor de evaluación de las bases para este profesional
  - **Columna 7 – ¿Cumple factor de evaluación?:** Indicar SI si el valor de la columna 3 es igual o superior al de la columna 6. En caso contrario, indicar NO CUMPLE en mayúscula

  **Resultado estructurado:**
  ```yaml
  evaluacion_anos:
    - nombre: "Juan Pérez García"
      cargo_postulado: "Jefe de Supervisión"
      anos_acumulados_propuestos: 12
      anos_requeridos_rtm: 8
      cumple_rtm: "SI"
      anos_requeridos_factor_evaluacion: 10
      cumple_factor_evaluacion: "SI"

    - nombre: "María López Rodríguez"
      cargo_postulado: "Especialista Ambiental"
      anos_acumulados_propuestos: 4
      anos_requeridos_rtm: 5
      cumple_rtm: "NO CUMPLE"
      anos_requeridos_factor_evaluacion: 7
      cumple_factor_evaluacion: "NO CUMPLE"
  ```
