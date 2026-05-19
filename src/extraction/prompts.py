"""
Prompts para extracción de datos de certificados de profesionales.
Contexto: propuestas técnicas de licitaciones de obras públicas en Perú.
"""

PASO2_PROMPT = """Eres un extractor de datos de propuestas técnicas peruanas de obras públicas.
El texto proviene de OCR sobre documentos escaneados y puede tener errores tipográficos menores.

Del texto OCR a continuación extrae la información del profesional propuesto.

CARGO ESPERADO: {cargo}

REGLAS DURAS — VIOLAR CUALQUIERA DE ESTAS ES ERROR GRAVE:
1. "nombre" NUNCA puede estar vacío. Si no encuentras nombre claro, transcribe el texto más cercano a "identificado con DNI" o "el suscrito".
2. La "profesion" debe ser TÍTULO COMPLETO ("Ingeniero Civil", "Arquitecto"), nunca categoría vaga sola ("Ingeniero" sin especialidad). Si solo encuentras "Ingeniero", déjalo como "Ingeniero" pero marca implícitamente que es incompleto.
3. Si detectas errores de OCR obvios (letras pegadas como "deCampo", palabras truncadas como "Responsale"), LIMPIA antes de devolver. El OCR es ruidoso; tu trabajo incluye repararlo cuando el error es evidente.
4. Si el "registro_colegio" parece tener más de 7 dígitos, probablemente NO es un registro de colegio (los CIP/CAP tienen 4-6 dígitos) — devuelve null en ese caso.

INSTRUCCIONES:
- nombre: nombre completo de la persona. Búscalo en la declaración jurada (empieza con "Yo [NOMBRE] identificado...") o en los certificados ("Certificamos que el Ing./Arq. [NOMBRE]..."). Máximo 80 caracteres.
- dni: número de DNI de 8 dígitos
- tipo_colegio: sigla del colegio profesional al que pertenece. Ejemplos: "CIP" (Colegio de Ingenieros del Perú), "CAP" (Colegio de Arquitectos del Perú), "CBP" (Colegio de Biólogos), "CMP" (Colegio Médico). Búscalo en el diploma del colegio. Si no aparece, usa null.
- registro_colegio: número de registro en el colegio profesional (4 a 6 dígitos). Aparece como "CIP N° XXXX", "CAP N° XXXX", "Reg. N° XXXX", etc. NO confundir con el DNI. Si no aparece, usa null.
- fecha_registro: fecha de incorporación al colegio profesional tal como aparece en el documento. Si no aparece, usa null.
- profesion: título profesional (Ingeniero Civil, Arquitecto, Ingeniero Sanitario, etc.)
- cargo_postulado: cargo al que postula en esta propuesta (usa el CARGO ESPERADO como referencia)

REGLA CRÍTICA: Devuelve ÚNICAMENTE este JSON, sin texto antes ni después.
No uses el contenido de las páginas como claves del JSON.
Si no encuentras un campo, usa null.

{{
  "nombre": "...",
  "dni": "...",
  "tipo_colegio": "...",
  "registro_colegio": "...",
  "fecha_registro": "...",
  "profesion": "...",
  "cargo_postulado": "..."
}}

TEXTO OCR:
{texto}"""


PASO3_PROMPT = """Eres un extractor de certificados de experiencia laboral de propuestas técnicas peruanas.
El texto proviene de OCR sobre documentos escaneados y puede tener errores tipográficos menores.

Del texto OCR a continuación extrae TODOS los certificados o constancias de experiencia laboral del profesional.
Los certificados son documentos emitidos por empresas o consorcios que acreditan que el profesional trabajó en un proyecto.

PROFESIONAL: {nombre}

REGLAS DURAS — VIOLAR CUALQUIERA DE ESTAS ES ERROR GRAVE:
1. Para CADA certificado, el campo "proyecto" NUNCA puede estar vacío. Si no detectas un nombre de proyecto claro, transcribe el texto que sigue al verbo de inicio ("Mejoramiento de...", "Construcción de...", "Supervisión de la obra...").
2. NUNCA dos experiencias distintas del mismo profesional pueden tener TODOS los campos idénticos (proyecto + fechas + empresa). Si te pasa, es duplicado por error de copia — re-lee el texto, son experiencias DIFERENTES.
3. Las fechas deben mantener el formato del documento original ("15/03/2020", "Lima, 25 de junio del 2021"). NO inventes fechas ni las "normalices" a un formato distinto del texto.
4. El "ruc" debe tener exactamente 11 dígitos. Si encuentras un número de 8 dígitos, eso es DNI, NO RUC — devuelve null en ruc.
5. Extrae TODAS las experiencias del texto, no resumas ni omitas. Si el texto contiene 8 certificados, devuelve 8 entradas, no 4 ni 5.

INSTRUCCIONES campo por campo:
- proyecto: nombre completo del proyecto de obra (empieza con verbos como "Mejoramiento", "Construcción", "Supervisión de la obra", etc.)
- cargo: cargo desempeñado en ese proyecto (Coordinador de Supervisión, Jefe de Supervisión, Especialista en Estructuras, etc.)
- empresa_emisora: nombre de la empresa o consorcio que EMITE la constancia (quien firma el papel)
- ruc: RUC de la empresa emisora si aparece (11 dígitos)
- fecha_inicio: fecha de inicio del servicio (formato original del documento)
- fecha_fin: fecha de fin del servicio. Si dice "a la fecha" o "a la actualidad", usa el texto "a la fecha"
- fecha_emision: fecha en que fue emitido el certificado (suele aparecer al final del documento con "Lima, DD de mes del AAAA")
- firmante: nombre completo de quien firma el certificado
- cargo_firmante: cargo de quien firma (Representante Legal, Representante Común, Gerente General, etc.)
- folio: número de folio impreso al pie de la página (generalmente 3-4 dígitos sueltos, no parte del texto)
- tipo_obra: sector de la obra según el proyecto. Valores posibles: "salud", "educacion", "vial", "saneamiento", "edificacion", "riego", "transporte", "deportivo", "institucional", "otro". Si no puedes determinar el sector, usa null
- tipo_intervencion: tipo de intervención según el nombre del proyecto. Valores posibles: "construccion", "mejoramiento", "ampliacion", "rehabilitacion", "supervision", "expediente tecnico", "mantenimiento", "instalacion", "creacion", "otro". Si no puedes determinar, usa null
- tipo_acreditacion: tipo de documento presentado. Valores posibles: "certificado", "constancia", "contrato", "resolucion", "otro". Si no puedes determinar, usa null

REGLA CRÍTICA: Devuelve ÚNICAMENTE este JSON, sin texto antes ni después.
Usa exactamente estos nombres de campo. No inventes otros nombres.
Si no hay certificados en el texto, devuelve la estructura con lista vacía.

{{
  "experiencias": [
    {{
      "proyecto": "...",
      "cargo": "...",
      "empresa_emisora": "...",
      "ruc": null,
      "fecha_inicio": "...",
      "fecha_fin": "...",
      "fecha_emision": "...",
      "firmante": "...",
      "cargo_firmante": "...",
      "folio": null,
      "tipo_obra": null,
      "tipo_intervencion": null,
      "tipo_acreditacion": null
    }}
  ]
}}

TEXTO OCR:
{texto}"""
