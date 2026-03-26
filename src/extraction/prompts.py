"""
Prompts para extracción de datos de certificados de profesionales.
Contexto: propuestas técnicas de licitaciones de obras públicas en Perú.
"""

PASO2_PROMPT = """Eres un extractor de datos de propuestas técnicas peruanas de obras públicas.
El texto proviene de OCR sobre documentos escaneados y puede tener errores tipográficos menores.

Del texto OCR a continuación extrae la información del profesional propuesto.

CARGO ESPERADO: {cargo}

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

INSTRUCCIONES campo por campo:
- proyecto: nombre completo del proyecto de obra (empieza con verbos como "Mejoramiento", "Construcción", "Supervisión de la obra", etc.)
- cargo: cargo desempeñado en ese proyecto (Coordinador de Supervisión, Jefe de Supervisión, Especialista en Estructuras, etc.)
- empresa_emisora: nombre de la empresa o consorcio que EMITE la constancia (quien firma el papel)
- ruc: RUC de la empresa emisora si aparece (11 dígitos)
- cui: Código Único de Inversiones del proyecto de la constancia.
  ATENCIÓN: el CUI que aparece en la declaración jurada inicial (ANEXO 16) es el del proyecto LICITADO, NO de las experiencias pasadas.
  Solo extrae el CUI si aparece dentro de la constancia/certificado individual mismo (por ejemplo: "CUI 2345678" o "código 2345678").
  Si no aparece explícitamente en la constancia, usa null.
- fecha_inicio: fecha de inicio del servicio (formato original del documento)
- fecha_fin: fecha de fin del servicio. Si dice "a la fecha" o "a la actualidad", usa el texto "a la fecha"
- fecha_emision: fecha en que fue emitido el certificado (suele aparecer al final del documento con "Lima, DD de mes del AAAA")
- firmante: nombre completo de quien firma el certificado
- cargo_firmante: cargo de quien firma (Representante Legal, Representante Común, Gerente General, etc.)
- folio: número de folio impreso al pie de la página (generalmente 3-4 dígitos sueltos, no parte del texto)

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
      "cui": null,
      "fecha_inicio": "...",
      "fecha_fin": "...",
      "fecha_emision": "...",
      "firmante": "...",
      "cargo_firmante": "...",
      "folio": null
    }}
  ]
}}

TEXTO OCR:
{texto}"""
