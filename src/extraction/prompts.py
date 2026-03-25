"""
Prompts para extracción de datos de certificados de profesionales.
Contexto: propuestas técnicas de licitaciones de obras públicas en Perú.
"""

PASO2_SYSTEM = """Eres un extractor de datos de propuestas técnicas peruanas de obras públicas.
El texto proviene de OCR sobre documentos escaneados — puede haber errores tipográficos menores.
Responde SOLO con JSON válido, sin texto adicional."""

PASO2_PROMPT = """Del siguiente texto OCR de un expediente de licitación pública peruana,
extrae la información del profesional propuesto.

Busca:
- Su nombre completo (suele aparecer en diplomas universitarios o constancias CIP)
- DNI (documento de identidad, 8 dígitos)
- Número de CIP (registro del Colegio de Ingenieros del Perú, 4-6 dígitos)
- Fecha de incorporación al CIP (formato original del documento)
- Profesión (Ingeniero Civil, Arquitecto, etc.)
- Cargo al que postula en esta propuesta

Devuelve este JSON exacto:
{{
  "nombre": "...",
  "dni": "...",
  "cip": "...",
  "fecha_cip": "...",
  "profesion": "...",
  "cargo_postulado": "..."
}}

Si no encuentras un campo, usa null.

CARGO ESPERADO: {cargo}

TEXTO OCR:
{texto}"""


PASO3_SYSTEM = """Eres un extractor de certificados de experiencia laboral de propuestas técnicas peruanas.
El texto proviene de OCR — puede haber errores tipográficos menores.
Responde SOLO con JSON válido, sin texto adicional."""

PASO3_PROMPT = """Del siguiente texto OCR extrae TODOS los certificados o constancias de experiencia laboral.
Cada certificado dice quién prestó servicios, en qué proyecto, en qué período, y quién lo firma.

Para cada certificado encontrado, extrae:
- proyecto: nombre completo del proyecto
- cargo: cargo desempeñado (tipo de servicio)
- empresa_emisora: empresa o consorcio que emite la constancia
- ruc: RUC del emisor si aparece
- cui: Código Único de Inversiones si aparece (número de 7 dígitos aprox, puede estar como "CUI", "CUl" o "código")
- fecha_inicio: fecha de inicio del servicio (formato del documento)
- fecha_fin: fecha de fin del servicio, o "a la fecha" si no tiene fecha de término
- fecha_emision: fecha en que fue emitido el certificado
- firmante: nombre de quien firma
- cargo_firmante: cargo de quien firma
- folio: número de folio/página del documento si aparece impreso en la hoja

Devuelve este JSON exacto:
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

Si no hay certificados, devuelve {{"experiencias": []}}.

PROFESIONAL: {nombre}

TEXTO OCR:
{texto}"""
