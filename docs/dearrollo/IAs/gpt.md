Conde, si el requisito es **100% local + open source**, el diseño cambia un poco respecto a usar APIs como GPT o Claude. La buena noticia es que **sí se puede hacer**, pero hay que elegir modelos y herramientas que funcionen bien **on-premise**.

Voy a reorganizar todo el plan considerando:

* **sin servicios cloud**
* **sin APIs externas**
* **todo ejecutándose localmente**
* **stack open source**

Te lo estructuro como un **plan de arquitectura + roadmap de desarrollo de 6–8 semanas**.

---

# 1. Objetivo del sistema (versión local)

Automatizar el análisis de propuestas técnicas de licitaciones procesando **PDFs grandes (1000–2300 páginas)** y generando un **reporte estructurado de evaluación**.

Entrada:

```
Propuesta.pdf (aquí están los certificados y demás cosas)
Bases.pdf
```

Salida:

```
Excel evaluación
Alertas
Base de datos de profesionales y experiencias
```

Todo ejecutándose **localmente en un servidor**.

---

# 2. Arquitectura general

Arquitectura diseñada para **procesar documentos grandes localmente**.

```
Frontend
   ↓
Backend API
   ↓
Document Processing Pipeline
   ↓
OCR + Layout Detection
   ↓
Local LLM Extraction
   ↓
Structured Database
   ↓
Rule Engine
   ↓
Report Generator
```

---

# 3. Stack tecnológico completo

## Backend

**Python + FastAPI**

Motivos:

* ecosistema de IA
* librerías de documentos
* integración con modelos locales

---

## Frontend

Para el MVP:

```
Streamlit
```

Ventajas:

* rapidísimo de desarrollar
* interfaz simple
* ideal para herramientas internas

Alternativa futura:

```
Next.js
```

---

## Base de datos

```
PostgreSQL
```

Tablas principales:

```
documents
pages
professionals
experiences
requirements
evaluation_results
alerts
```

---

## Almacenamiento de documentos

Carpeta estructurada:

```
data/
   proposals/
   bases/
   certificates/
   processed/
```

---

# 4. Procesamiento de documentos

Este módulo es crítico.

## Lectura de PDFs

Herramienta:

```
PyMuPDF (fitz)
```

Permite:

* leer PDFs grandes
* extraer texto
* detectar páginas sin texto
* obtener imágenes

---

# 5. OCR (100% local)

Motor recomendado:

```
PaddleOCR
```

Por qué:

* open source
* mejor precisión que Tesseract
* funciona bien con español
* detecta tablas y layout

Pipeline:

```
PDF page
↓
¿tiene texto?
↓
si no → OCR
↓
texto limpio
```

Alternativa:

```
Tesseract OCR
```

pero PaddleOCR suele ser mejor para documentos técnicos.

---

# 6. Detección de estructura del documento

Necesitamos identificar:

* CV profesionales
* certificados
* bases
* tablas

Herramienta recomendada:

```
LayoutParser
```

Usa modelos basados en:

```
Detectron2
```

Permite detectar:

* títulos
* párrafos
* tablas
* bloques

Esto mejora mucho la extracción.

---

# 7. LLM local

Aquí está la decisión más importante.

Necesitamos un modelo que funcione bien para:

* extracción de información
* comprensión de texto técnico
* español

Recomendación:

## Modelo principal

```
Llama 3 8B Instruct
```

o

```
Mistral 7B Instruct
```

Ambos:

* open source
* funcionan bien para extraction
* pueden correr localmente

---

## Motor para ejecutar LLM

Recomendación:

```
Ollama
```

Ventajas:

* simple
* rápido
* fácil de integrar con Python
* soporta Llama, Mistral, etc.

Ejemplo:

```
ollama run llama3
```

---

# 8. Embeddings (para búsqueda)

Para hacer RAG o búsquedas en documentos.

Modelo recomendado:

```
bge-small-en
```

o mejor para español:

```
bge-m3
```

Alternativa:

```
sentence-transformers
```

---

## Vector database

Para almacenar embeddings:

```
ChromaDB
```

Alternativas:

```
FAISS
Weaviate
```

Pero para MVP:

```
Chroma
```

es perfecto.

---

# 9. Motor de reglas (evaluación)

Este componente **no usa IA**.

Es lógica programada.

Ejemplo:

```
if experiencia_años < requisito:
    resultado = "NO CUMPLE"
```

Ejemplo de regla:

```
if experiencia > 20 años:
    alerta = "Experiencia fuera del rango permitido"
```

Este motor genera:

```
evaluaciones
alertas
```

---

# 10. Generación de reportes

Herramienta:

```
Pandas
```

y exportación con:

```
openpyxl
```

Resultado:

```
Excel automático
```

Con hojas como:

* profesionales
* experiencias
* evaluación
* alertas

---

# 11. Módulos del sistema

Ahora el sistema completo dividido en módulos.

---

# Módulo 1 — Ingesta de documentos

Funciones:

* subir PDFs
* registrar documentos
* guardar en sistema

Output:

```
document_id
tipo_documento
```

Tiempo:

```
3 días
```

---

# Módulo 2 — Procesamiento de PDF

Funciones:

* dividir páginas
* extraer texto
* aplicar OCR cuando sea necesario

Herramientas:

```
PyMuPDF
PaddleOCR
```

Output:

```
page_text
page_number
```

Tiempo:

```
5 días
```

---

# Módulo 3 — Segmentación de contenido

Identificar secciones del documento.

Tipos:

```
CV
Certificados
Bases
Propuesta técnica
```

Método:

```
LLM classification
```

Tiempo:

```
4 días
```

---

# Módulo 4 — Extracción de profesionales

Detectar todos los profesionales.

Datos:

```
nombre
profesion
cargo
especialidad
```

Herramienta:

```
Llama 3 / Mistral
```

Tiempo:

```
4 días
```

---

# Módulo 5 — Extracción de experiencias

Extraer experiencias desde certificados.

Campos:

```
proyecto
cargo
empresa
inicio
fin
duracion
```

Tiempo:

```
7 días
```

---

# Módulo 6 — Análisis de bases

Extraer requisitos:

```
cargo
años experiencia
profesion
capacitaciones
```

Tiempo:

```
5 días
```

---

# Módulo 7 — Base de datos estructurada

Guardar:

```
profesionales
experiencias
requisitos
```

Tiempo:

```
3 días
```

---

# Módulo 8 — Motor de evaluación

Comparar:

```
experiencias vs requisitos
```

Generar:

```
cumple
no cumple
alertas
```

Tiempo:

```
4 días
```

---

# Módulo 9 — Generador de reportes

Crear Excel final.

Tiempo:

```
3 días
```

---

# 12. Cronograma total (con colchón)

```
Semana 1
Arquitectura + ingestión documentos

Semana 2
Procesamiento PDF + OCR

Semana 3
Segmentación de documentos

Semana 4
Extractor de profesionales

Semana 5
Extractor de experiencias

Semana 6
Análisis de bases

Semana 7
Motor de evaluación

Semana 8
Reportes + testing
```

Incluye **~25–30% de colchón de tiempo**.

---

# 13. Requisitos de hardware

Para correr todo local:

Mínimo recomendable:

```
CPU: 16 cores
RAM: 32 GB
GPU: 16 GB VRAM (ideal)
```

Con GPU puedes correr:

```
Llama 3 8B
```

muy rápido.

Sin GPU también funciona pero más lento.

---

# 14. Resultado final

El flujo sería:

```
Usuario sube propuesta
↓
Sistema procesa PDF
↓
OCR + extracción texto
↓
LLM extrae profesionales
↓
LLM extrae experiencias
↓
Base de datos estructurada
↓
Motor de reglas evalúa
↓
Sistema genera Excel
```

Tiempo esperado:

```
10 – 20 minutos por propuesta
```

---

💡 Conde, algo muy importante para el éxito del proyecto:

El **factor que más tiempo consume en estos sistemas no es la IA**, es:

```
limpieza y estructuración de documentos
```

Por eso el pipeline de **OCR + layout + segmentación** es clave.

---

Si quieres, en el siguiente paso puedo mostrarte algo **muy útil para este proyecto**:

👉 **La arquitectura exacta de carpetas y repositorio del código** para que el sistema sea mantenible y no se vuelva caótico a la semana 3.
