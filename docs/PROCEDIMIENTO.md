# PROCEDIMIENTO DE DESARROLLO

## InfoObras Analyzer — Arquitectura y Pipeline Técnico

**Fecha:** 2026-03-06  
**Versión:** 1.0

---

## 1. Arquitectura del Sistema

### Pipeline Completo

```
PDF completo (~2300 págs.)
       │
       ▼
   ┌──────────────────────┐
   │ Image Preprocessing   │  ← Denoising, deskewing,
   │                       │     binarización
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ Layout Detection      │  ← Surya / LayoutParser
   │ (detección de zonas)  │     Identifica tablas, títulos,
   │                       │     párrafos, firmas
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ OCR / Vision Model    │  ← Ruta A: PaddleOCR (texto)
   │                       │     Ruta B: Qwen2.5-VL (lectura
   │                       │     directa de imagen)
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ Segmentación          │  ← Detectar bloques de certificados
   │ automática            │     por patrones ("CERTIFICADO",
   │                       │     "CONSTANCIA", "SE CERTIFICA")
   │                       │     2300 págs. → ~45 certificados
   └────┬─────────────────┘
        │
        ▼  (paralelo)
   ┌──────────────────────┐
   │ LLM extracción       │  ← Qwen2.5 14B / DeepSeek-R1
   │ cert 1 → JSON        │     Prompt estructurado
   │ cert 2 → JSON        │     10-20 seg total
   │ cert 3 → JSON        │
   │ ...                   │
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ PostgreSQL            │  ← Datos estructurados
   │ profesionales         │
   │ experiencias          │
   │ proyectos             │
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ Motor de reglas       │  ← Python puro (if/else)
   │ (NO es IA)            │     Comparar contra bases
   │                       │     Generar alertas
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ Verificación externa │  ← Playwright (scraping)
   │ ├── Infobras         │
   │ ├── SUNAT RUC        │
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ Motor de alertas      │  ← Python puro
   │ (NO es IA)            │     9 tipos de alerta
   └────┬─────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ Excel / Dashboard     │  ← openpyxl / React
   └──────────────────────┘
```

### Tiempo de procesamiento esperado

| Etapa | Tiempo |
|---|---|
| OCR (2300 págs.) | 1 – 2 min |
| Segmentación de certificados | ~10 seg |
| Extracción LLM (paralelo) | 1 – 2 min |
| Motor de reglas + alertas | ~30 seg |
| **Total** | **3 – 5 minutos** |

vs las **12+ horas** que toma hoy manualmente.

---

## 2. Insight Clave: Segmentación de Certificados

**Este es el truco que elimina la necesidad de partir el PDF manualmente.**

El PDF de 2300 páginas NO se procesa completo. Se segmenta automáticamente en bloques de certificados:

### Paso 1: OCR de todas las páginas

```python
import fitz  # PyMuPDF
from paddleocr import PaddleOCR

ocr = PaddleOCR(lang='es')

def extract_pages(pdf_path):
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        # Convertir página a imagen
        pix = page.get_pixmap(dpi=300)
        img = pix.tobytes("png")
        
        # OCR
        result = ocr.ocr(img)
        text = "\n".join([line[1][0] for line in result[0]])
        
        pages.append({
            "page": i + 1,
            "text": text,
            "folio": extract_folio(text)  # Número en esquina
        })
    return pages
```

### Paso 2: Detectar inicio/fin de certificados

```python
CERT_PATTERNS = [
    "CERTIFICADO",
    "CONSTANCIA",
    "SE CERTIFICA QUE",
    "ACREDITA",
    "CERTIFICO QUE",
    "HACEMOS CONSTAR"
]

def segment_certificates(pages):
    certificates = []
    current_cert = None
    
    for page in pages:
        text_upper = page["text"].upper()
        
        # ¿Inicia un nuevo certificado?
        is_start = any(pattern in text_upper for pattern in CERT_PATTERNS)
        
        if is_start:
            if current_cert:
                certificates.append(current_cert)
            current_cert = {
                "id": len(certificates) + 1,
                "pages": [page],
                "start_folio": page["folio"]
            }
        elif current_cert:
            current_cert["pages"].append(page)
    
    if current_cert:
        certificates.append(current_cert)
    
    return certificates
```

### Resultado:

```
2300 páginas → ~45 certificados de 2-4 páginas cada uno
```

Cada certificado es perfecto para enviar al LLM.

---

## 3. Extracción con LLM

### Modelo recomendado

| Modelo | VRAM | Uso |
|---|---|---|
| **Qwen2.5 14B Q4_K_M** | 16-24 GB | 🔥 Principal — mejor para extracción JSON |
| DeepSeek-R1 Distill 14B | 20 GB | Análisis complejo / razonamiento |
| Llama 3.1 8B | 8 GB | Fallback ligero |

**¿Por qué Qwen2.5?**
- Superior en extracción estructurada (JSON limpio)
- Sigue instrucciones muy bien
- Contexto largo
- Rápido en GPU
- Temperatura ≤ 0.1 → no inventa

### Prompt de extracción

```python
EXTRACTION_PROMPT = """
Analiza el siguiente certificado de experiencia profesional y extrae 
los datos en formato JSON. Si un dato no está presente, pon null.

CERTIFICADO:
{certificate_text}

Responde SOLO con el JSON, sin explicaciones:

{{
  "nombre": "nombre completo del profesional",
  "profesion": "profesión (Ingeniero Civil, Arquitecto, etc.)",
  "cip": "número de CIP o colegiatura",
  "cargo": "cargo o función desempeñada",
  "proyecto": "nombre del proyecto u obra",
  "tipo_obra": "tipo (hospital, carretera, edificio, etc.)",
  "tipo_intervencion": "tipo (construcción, mejoramiento, ampliación, etc.)",
  "empresa": "empresa o consorcio que emite el certificado",
  "fecha_inicio": "YYYY-MM-DD",
  "fecha_fin": "YYYY-MM-DD o 'a la fecha' si así dice",
  "fecha_emision": "YYYY-MM-DD del certificado",
  "firmante": "nombre de quien firma",
  "cargo_firmante": "cargo del firmante",
  "folio": "número de folio si aparece"
}}
"""
```

### Procesamiento paralelo

```python
import asyncio
from ollama import AsyncClient

async def extract_certificate(client, cert):
    text = "\n".join([p["text"] for p in cert["pages"]])
    
    response = await client.chat(
        model="qwen2.5:14b",
        messages=[{
            "role": "user",
            "content": EXTRACTION_PROMPT.format(certificate_text=text)
        }],
        options={"temperature": 0.1}
    )
    
    return json.loads(response["message"]["content"])

async def extract_all(certificates):
    client = AsyncClient()
    tasks = [extract_certificate(client, cert) for cert in certificates]
    results = await asyncio.gather(*tasks)
    return results
```

---

## 4. Base de Datos (PostgreSQL)

```sql
-- Concursos analizados
CREATE TABLE concursos (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(500),
    codigo VARCHAR(100),
    fecha_propuesta DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Profesionales extraídos
CREATE TABLE profesionales (
    id SERIAL PRIMARY KEY,
    concurso_id INTEGER REFERENCES concursos(id),
    nombre VARCHAR(300),
    profesion VARCHAR(200),
    cip VARCHAR(50),
    dni VARCHAR(20),
    fecha_colegiatura DATE
);

-- Experiencias de cada profesional
CREATE TABLE experiencias (
    id SERIAL PRIMARY KEY,
    profesional_id INTEGER REFERENCES profesionales(id),
    proyecto VARCHAR(500),
    cargo VARCHAR(300),
    empresa VARCHAR(300),
    tipo_obra VARCHAR(200),
    tipo_intervencion VARCHAR(200),
    fecha_inicio DATE,
    fecha_fin DATE,
    fecha_emision DATE,
    firmante VARCHAR(300),
    cargo_firmante VARCHAR(300),
    folio_pdf INTEGER,
    codigo_infobras VARCHAR(100)
);

-- Evaluaciones contra bases
CREATE TABLE evaluaciones (
    id SERIAL PRIMARY KEY,
    experiencia_id INTEGER REFERENCES experiencias(id),
    criterio VARCHAR(200),  -- 'cargo', 'profesion', 'tipo_obra', etc.
    cumple BOOLEAN,
    detalle TEXT
);

-- Alertas generadas
CREATE TABLE alertas (
    id SERIAL PRIMARY KEY,
    experiencia_id INTEGER REFERENCES experiencias(id),
    tipo VARCHAR(50),       -- 'ALT-01', 'ALT-02', etc.
    descripcion TEXT,
    severidad VARCHAR(20)   -- 'critica', 'alta', 'media'
);

-- Verificaciones en Infobras
CREATE TABLE verificaciones_infobras (
    id SERIAL PRIMARY KEY,
    experiencia_id INTEGER REFERENCES experiencias(id),
    estado_obra VARCHAR(100),
    fecha_inicio_real DATE,
    fecha_fin_real DATE,
    paralizado BOOLEAN,
    periodo_paralizado VARCHAR(200),
    supervisor_valorizacion VARCHAR(300),
    coincide_nombre BOOLEAN,
    url_infobras TEXT
);

-- Verificaciones de empresa
CREATE TABLE verificaciones_empresa (
    id SERIAL PRIMARY KEY,
    experiencia_id INTEGER REFERENCES experiencias(id),
    ruc VARCHAR(20),
    fecha_constitucion DATE,
    fuente_url TEXT,
    alerta BOOLEAN
);
```

---

## 5. Motor de Reglas (Código Python, sin IA)

```python
from datetime import date, timedelta
from typing import List
from dataclasses import dataclass

@dataclass
class Alerta:
    tipo: str
    descripcion: str
    severidad: str

def evaluar_experiencia(exp, bases, fecha_propuesta) -> List[Alerta]:
    alertas = []
    
    # ALT-01: Fecha fin posterior a emisión del certificado
    if exp.fecha_fin and exp.fecha_emision:
        if exp.fecha_fin > exp.fecha_emision:
            alertas.append(Alerta(
                "ALT-01",
                f"Fecha fin ({exp.fecha_fin}) posterior a emisión ({exp.fecha_emision})",
                "critica"
            ))
    
    # ALT-02: Periodo COVID
    COVID_INICIO = date(2020, 3, 16)  # configurable
    COVID_FIN = date(2021, 12, 31)    # configurable
    if exp.fecha_inicio and exp.fecha_fin:
        if exp.fecha_inicio <= COVID_FIN and exp.fecha_fin >= COVID_INICIO:
            alertas.append(Alerta(
                "ALT-02",
                f"Experiencia abarca periodo COVID ({COVID_INICIO} - {COVID_FIN})",
                "alta"
            ))
    
    # ALT-03: Experiencia > 20 años
    if exp.fecha_fin:
        antiguedad = (fecha_propuesta - exp.fecha_fin).days / 365
        if antiguedad > 20:
            alertas.append(Alerta(
                "ALT-03",
                f"Experiencia tiene {antiguedad:.0f} años de antigüedad (>20)",
                "alta"
            ))
    
    # ALT-04: Empresa constituida después del inicio
    if exp.verificacion_empresa and exp.verificacion_empresa.fecha_constitucion:
        if exp.verificacion_empresa.fecha_constitucion > exp.fecha_inicio:
            alertas.append(Alerta(
                "ALT-04",
                f"Empresa creada ({exp.verificacion_empresa.fecha_constitucion}) después del inicio ({exp.fecha_inicio})",
                "critica"
            ))
    
    # ALT-05: "A la fecha" en vez de fecha explícita
    if exp.fecha_fin_texto and "a la fecha" in exp.fecha_fin_texto.lower():
        alertas.append(Alerta(
            "ALT-05",
            "Usa 'a la fecha' en vez de fecha explícita de fin",
            "alta"
        ))
    
    # ALT-06: Cargo no válido según bases
    cargos_validos = bases.get_cargos_validos(exp.profesional.cargo_postulado)
    if exp.cargo and exp.cargo.lower() not in [c.lower() for c in cargos_validos]:
        alertas.append(Alerta(
            "ALT-06",
            f"Cargo '{exp.cargo}' no está en cargos válidos: {cargos_validos}",
            "critica"
        ))
    
    # ALT-07: Profesión no coincide
    profesion_requerida = bases.get_profesion_requerida(exp.profesional.cargo_postulado)
    if exp.profesional.profesion != profesion_requerida:
        alertas.append(Alerta(
            "ALT-07",
            f"Profesión '{exp.profesional.profesion}' ≠ requerida '{profesion_requerida}'",
            "critica"
        ))
    
    # ALT-08: Tipo de obra no coincide
    tipos_validos = bases.get_tipos_obra_validos()
    if exp.tipo_obra and exp.tipo_obra.lower() not in [t.lower() for t in tipos_validos]:
        alertas.append(Alerta(
            "ALT-08",
            f"Tipo de obra '{exp.tipo_obra}' no coincide con bases",
            "alta"
        ))
    
    # ALT-09: CIP no vigente (dato de verificación externa)
    if exp.profesional.cip_vigente == False:
        alertas.append(Alerta(
            "ALT-09",
            f"CIP {exp.profesional.cip} no vigente",
            "alta"
        ))
    
    return alertas
```

**Esto NO necesita IA.** Son comparaciones determinísticas que nunca fallan.

---

## 6. Scraping de Infobras

### Estrategia

```python
from playwright.async_api import async_playwright

async def buscar_proyecto_infobras(codigo_infobras: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # 1. Ir a búsqueda avanzada
        await page.goto("https://infobras.contraloria.gob.pe/")
        
        # 2. Buscar por código
        await page.fill("#txtCodigo", codigo_infobras)
        await page.click("#btnBuscar")
        
        # 3. Esperar resultados
        await page.wait_for_selector(".resultado-item")
        
        # 4. Entrar a la ficha
        await page.click(".resultado-item a")
        
        # 5. Extraer datos generales
        datos = {
            "fecha_contrato": await page.text_content("#fecha-contrato"),
            "fecha_inicio": await page.text_content("#fecha-inicio"),
            "fecha_fin": await page.text_content("#fecha-fin"),
            "estado": await page.text_content("#estado"),
            "monto": await page.text_content("#monto"),
        }
        
        # 6. Ir a avance de obra
        await page.click("tab-avance-obra")
        
        # 7. Extraer avances mensuales
        avances = await extraer_avances_mensuales(page)
        
        # 8. Descargar valorizaciones
        await descargar_documentos(page, codigo_infobras)
        
        await browser.close()
        return datos, avances
```

### Manejo de riesgos del scraping

```python
# Reintentos automáticos
async def scrape_con_reintentos(func, *args, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await func(*args)
        except TimeoutError:
            await asyncio.sleep(2 ** attempt)  # Backoff exponencial
        except Exception as e:
            if "CAPTCHA" in str(e):
                return {"error": "CAPTCHA detectado", "manual": True}
            raise
    return {"error": "Max retries exceeded", "manual": True}

# Rate limiting respetuoso
RATE_LIMIT = 2  # segundos entre requests
async def rate_limited_scrape(projects):
    results = []
    for project in projects:
        result = await scrape_con_reintentos(buscar_proyecto_infobras, project)
        results.append(result)
        await asyncio.sleep(RATE_LIMIT)
    return results
```

---

## 7. Verificación Cruzada con Valorizaciones

```python
from difflib import SequenceMatcher

def fuzzy_match_nombre(nombre_certificado: str, nombre_valorizacion: str) -> float:
    """Retorna score de similitud entre 0 y 1"""
    # Normalizar
    n1 = normalizar_nombre(nombre_certificado)
    n2 = normalizar_nombre(nombre_valorizacion)
    return SequenceMatcher(None, n1, n2).ratio()

def normalizar_nombre(nombre: str) -> str:
    """Normaliza nombre para comparación"""
    nombre = nombre.upper().strip()
    # Quitar tildes
    nombre = unidecode(nombre)
    # Quitar caracteres especiales
    nombre = re.sub(r'[^A-Z\s]', '', nombre)
    # Quitar espacios múltiples
    nombre = re.sub(r'\s+', ' ', nombre)
    return nombre

def verificar_supervisor_en_valorizacion(nombre_certificado, valorizacion_pdf):
    """
    OCR sobre la valorización descargada,
    buscar nombre del supervisor/jefe,
    comparar con el nombre del certificado.
    """
    # OCR de la valorización
    texto = ocr_pdf(valorizacion_pdf)
    
    # Buscar patrones de supervisor/jefe
    patrones = [
        r"(?:supervisor|jefe|residente).*?:\s*(.+)",
        r"(?:ing\.|arq\.)\s+(.+?)(?:\n|$)",
    ]
    
    nombres_encontrados = []
    for patron in patrones:
        matches = re.findall(patron, texto, re.IGNORECASE)
        nombres_encontrados.extend(matches)
    
    # Comparar con fuzzy matching
    mejor_match = 0
    mejor_nombre = None
    for nombre in nombres_encontrados:
        score = fuzzy_match_nombre(nombre_certificado, nombre)
        if score > mejor_match:
            mejor_match = score
            mejor_nombre = nombre
    
    return {
        "coincide": mejor_match > 0.8,
        "score": mejor_match,
        "nombre_encontrado": mejor_nombre,
        "nombre_esperado": nombre_certificado
    }
```

---

## 8. Generación del Excel

```python
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font

ROJO = PatternFill(start_color="FFCCCC", fill_type="solid")
AMARILLO = PatternFill(start_color="FFFFCC", fill_type="solid")
VERDE = PatternFill(start_color="CCFFCC", fill_type="solid")

def generar_excel(concurso, profesionales):
    wb = Workbook()
    
    # Hoja 1: Base de datos bruta
    ws_datos = wb.active
    ws_datos.title = "Base de Datos"
    
    headers = [
        "Profesional", "Profesión", "CIP", "DNI",
        "Cargo Postulado", "Proyecto", "Cargo en Certificado",
        "Empresa", "Tipo Obra", "Tipo Intervención",
        "Fecha Inicio", "Fecha Fin", "Duración (días)",
        "Fecha Emisión", "Firmante", "Folio PDF",
        "Código Infobras", "Fecha Constitución Empresa",
        "Fuente Constitución"
    ]
    ws_datos.append(headers)
    
    for prof in profesionales:
        for exp in prof.experiencias:
            ws_datos.append([
                prof.nombre, prof.profesion, prof.cip, prof.dni,
                prof.cargo_postulado, exp.proyecto, exp.cargo,
                exp.empresa, exp.tipo_obra, exp.tipo_intervencion,
                exp.fecha_inicio, exp.fecha_fin, exp.duracion_dias,
                exp.fecha_emision, exp.firmante, exp.folio_pdf,
                exp.codigo_infobras, exp.fecha_constitucion_empresa,
                exp.fuente_constitucion
            ])
    
    # Hoja 2: Análisis con alertas
    ws_analisis = wb.create_sheet("Análisis")
    
    headers_analisis = [
        "Profesional", "Cargo", "Proyecto",
        "Cumple Profesión", "Cumple Cargo", "Cumple Tipo Obra",
        "Cumple Intervención", "Cumple Complejidad",
        "Antigüedad OK", "Periodo COVID", "Fechas Consistentes",
        "Empresa Válida", "CIP Vigente",
        "Estado Infobras", "Paralizado", "Supervisor Coincide",
        "ALERTAS"
    ]
    ws_analisis.append(headers_analisis)
    
    for prof in profesionales:
        for exp in prof.experiencias:
            fila = [
                prof.nombre, exp.cargo, exp.proyecto,
                # Cumplimientos
                exp.cumple_profesion, exp.cumple_cargo,
                exp.cumple_tipo_obra, exp.cumple_intervencion,
                exp.cumple_complejidad, exp.cumple_antiguedad,
                # Alertas
                exp.alerta_covid, exp.fechas_consistentes,
                exp.empresa_valida, exp.cip_vigente,
                # Infobras
                exp.estado_infobras, exp.paralizado,
                exp.supervisor_coincide,
                # Resumen alertas
                "; ".join([a.descripcion for a in exp.alertas])
            ]
            
            row_idx = ws_analisis.max_row + 1
            ws_analisis.append(fila)
            
            # Colorear celdas según alertas
            if exp.alertas:
                for cell in ws_analisis[row_idx]:
                    if any(a.severidad == "critica" for a in exp.alertas):
                        cell.fill = ROJO
                    elif any(a.severidad == "alta" for a in exp.alertas):
                        cell.fill = AMARILLO
    
    wb.save(f"analisis_{concurso.codigo}.xlsx")
```

---

## 9. Stack Tecnológico Final

```
Backend:        Python 3.11+ / FastAPI
OCR:            PaddleOCR (principal) + Tesseract (fallback)
VLM:            Qwen2.5-VL 7B (lectura directa de documentos, opcional)
Layout:         Surya (detección de estructura del documento)
LLM:            Qwen2.5 14B Q4_K_M (extracción) via Ollama
                DeepSeek-R1 14B (análisis complejo, opcional)
Embeddings:     bge-large (si se necesita búsqueda semántica)
Scraping:       Playwright (Infobras, sitios dinámicos)
BD:             PostgreSQL (datos) + pgvector (si se necesita)
Frontend:       React / Next.js (dashboard web)
Exportación:    openpyxl (Excel)
Paralelización: asyncio (LLM, scraping)
Servidor OS:    Ubuntu Server 22.04 LTS + NVIDIA CUDA
```

---

## 10. Arquitectura Document AI (Procesamiento Inteligente de Documentos)

En la práctica profesional, **no se usa solo un LLM para leer documentos**. Se usa una **arquitectura híbrida** llamada **Document AI** o **Intelligent Document Processing (IDP)**.

La idea es combinar:

1. **OCR real (computer vision)** → extrae el texto exacto.
2. **Modelo de visión + lenguaje (VLM)** → entiende el documento (layout, tablas, secciones).
3. **LLM** → razona sobre el contenido y extrae entidades.
4. **RAG / embeddings** → consulta el contenido después.

### Niveles de procesamiento de documentos

#### Nivel 1: OCR Clásico (solo texto)

Solo extrae caracteres. No entiende estructura.

| Motor | Ventaja | Limitación |
|---|---|---|
| **Tesseract** | Gratis, maduro | Peor en baja calidad |
| **PaddleOCR** | Superior en docs difíciles | Más pesado |
| **EasyOCR** | Fácil de usar | Menos preciso |

#### Nivel 2: OCR + LLM (lo que usan casi todos hoy)

Pipeline típico y probado:

```
PDF / Imagen
      ↓
OCR (PaddleOCR / Tesseract)
      ↓
Texto estructurado
      ↓
LLM (Qwen2.5 / Llama / Mistral)
      ↓
JSON / análisis
```

Existen proyectos open-source que usan **LLM para corregir errores de OCR**, mejorando precisión ([llm_aided_ocr](https://github.com/Dicklesworthstone/llm_aided_ocr)).

**Este es el nivel que implementamos como base.**

#### Nivel 3: Vision LLM — VLM (lo más moderno)

Estos modelos **leen directamente la imagen del documento** sin necesidad de OCR separado. Se llaman **VLM (Vision Language Models)**.

| Modelo | Capacidad | VRAM |
|---|---|---|
| **Qwen2.5-VL 7B** | 🔥 Muy bueno leyendo documentos, tablas, formularios | 10-14 GB |
| **MiniCPM-V** | Ligero, ideal para GPU pequeña | 6-8 GB |
| **InternVL** | Fuerte con tablas y datos estructurados | 16+ GB |
| **Florence-2** | Visión general, detección de objetos | 4-8 GB |
| **DocOwl** | Especializado en documentos técnicos | 8-12 GB |

Estos modelos **entienden layout, tablas y formularios** — pueden interpretar un certificado escaneado viendo la imagen directamente, sin pasar por OCR.

Referencia: [Best LLM for OCR](https://www.thedigitalrelay.com/best-llm-for-ocr-that-works-fast-free-in-2025/)

#### Nivel 4: OCR-Free (experimental)

Modelos que **no usan OCR en absoluto**, leen directamente la imagen:

| Modelo | Estado |
|---|---|
| **Donut** | Funcional pero limitado |
| **DocOwl** | Más maduro |
| **TextMonkey** | Research, muy nuevo ([paper](https://arxiv.org/abs/2403.04473)) |

Aún son más experimentales. No recomendados para producción todavía.

### Pipeline Híbrido Profesional (nivel empresa)

```
PDF
 ↓
Image preprocessing (Pillow / OpenCV)
 ↓
Layout detection (Surya)
 ↓
OCR (PaddleOCR)  +  Vision Model (Qwen2.5-VL, opcional)
 ↓
Chunking por certificado
 ↓
LLM extraction (Qwen2.5 14B)
 ↓
PostgreSQL
 ↓
Motor de reglas (código)
 ↓
Excel / Dashboard
```

Referencia: [Hybrid OCR Pipeline Architecture](https://zread.ai/ahnafnafee/local-llm-pdf-ocr/6-architecture-overview-hybrid-ocr-pipeline)

### Estrategia para InfoObras Analyzer

| Fase | Enfoque | Por qué |
|---|---|---|
| **PoC (Semana 1)** | Nivel 2: PaddleOCR + LLM | Más simple, probado, rápido de implementar |
| **Si OCR falla en docs difíciles** | Nivel 3: Agregar Qwen2.5-VL | VLM lee directamente la imagen donde OCR falla |
| **Producción** | Híbrido: PaddleOCR + VLM (fallback) + LLM | Lo mejor de ambos mundos |

**En la PoC se evalúa si PaddleOCR es suficiente.** Si no lo es, se agrega Qwen2.5-VL como segundo paso para documentos problemáticos. El LLM siempre se usa para la extracción de entidades al final.

### Stack ideal para este proyecto

```
OCR:            PaddleOCR (texto)
Vision Model:   Qwen2.5-VL 7B (lectura directa si OCR falla)
Layout:         Surya (detección de estructura)
LLM:            Qwen2.5 14B (extracción de entidades → JSON)
RAG:            pgvector (si se necesita búsqueda posterior)
```

Con esto se puede hacer:
- Lectura de PDFs escaneados de calidad variable
- Extracción de datos estructurados
- Comprensión de tablas y formularios
- Chat con documentos
- Análisis de inconsistencias

---

## 11. Fases de Desarrollo

### Fase 1: PoC + OCR Pipeline (Semana 1)

**Objetivo:** Validar que OCR y segmentación funcionan con docs reales.

| Tarea | Días |
|---|---|
| Configurar PaddleOCR con preprocesamiento | 1 |
| Probar con PDFs reales del cliente (mínimo 3 calidades) | 1 |
| Implementar segmentación automática de certificados | 1 |
| Probar scraping básico de Infobras (búsqueda + datos generales) | 1 |
| Informe GO/NO-GO | 0.5 |
| **Total** | **4.5 días** |

**Entregable:** Informe de viabilidad + prototipo que segmenta un PDF real en certificados.

---

### Fase 2: Extracción LLM + Base de Datos (Semana 2)

**Objetivo:** Pipeline completo de PDF → JSON → PostgreSQL.

| Tarea | Días |
|---|---|
| Configurar Ollama + Qwen2.5 14B | 0.5 |
| Implementar prompt de extracción | 1 |
| Procesamiento paralelo de certificados | 1 |
| Esquema PostgreSQL + inserción de datos | 1 |
| Testing con PDF completo (~2300 págs.) | 1.5 |
| **Total** | **5 días** |

**Entregable:** Sistema que procesa PDF completo → datos en PostgreSQL.

---

### Fase 3: Motor de Reglas + Alertas + Excel (Semana 3)

**Objetivo:** Evaluación automática + generación del Excel del cliente.

| Tarea | Días |
|---|---|
| Extracción de requerimientos de las bases (un solo paso LLM) | 1 |
| Motor de reglas (9 alertas, código Python) | 2 |
| Generador de Excel con formato del cliente | 1 |
| Testing con concurso real completo | 1 |
| **Total** | **5 días** |

**Entregable:** Excel generado automáticamente con evaluación + alertas coloreadas.

**⚡ DEMO para el cliente en Semana 3:** El sistema procesa un PDF real y genera el Excel. Segundo hito de pago.

---

### Fase 4: Scraping Infobras (Semana 4-5)

**Objetivo:** Verificación automática en Infobras.

| Tarea | Días |
|---|---|
| Scraper de búsqueda y datos generales | 2 |
| Extracción de avances mensuales + detección paralizaciones | 2 |
| Descarga de valorizaciones y documentos | 1 |
| OCR sobre valorizaciones + extracción nombre supervisor | 2 |
| Fuzzy matching de nombres + reporte discrepancias | 1 |
| Organización de archivos descargados | 0.5 |
| Rate limiting + reintentos + manejo de errores | 1 |
| Testing con proyectos reales | 1.5 |
| **Total** | **10 días** |

**Entregable:** El Excel ahora incluye columnas de verificación Infobras.

---

### Fase 5: Verificaciones Externas + SUNAT/CIP (Semana 5-6)

**Objetivo:** Consultas automatizadas a portales externos.

| Tarea | Días |
|---|---|
| Scraper SUNAT (fecha constitución empresa) | 2 |
| Scraper Colegio Profesional (vigencia CIP) | 1.5 |
| Integración de alertas externas al Excel | 1 |
| Fallback manual para portales con CAPTCHA | 0.5 |
| Testing | 1 |
| **Total** | **6 días** |

**Entregable:** Excel con verificaciones externas integradas.

---

### Fase 6: Interfaz Web (Semana 6-7)

**Objetivo:** Panel web para que múltiples usuarios usen el sistema.

| Tarea | Días |
|---|---|
| API FastAPI (endpoints de carga, procesamiento, resultados) | 2 |
| Frontend React (subir PDF, ver progreso, tabla de resultados) | 3 |
| Descargar Excel desde la web | 0.5 |
| Módulo de oferta económica (verificación matemática) | 1.5 |
| Testing + ajustes | 1 |
| **Total** | **8 días** |

**Entregable:** Panel web funcional accesible por red interna.

---

### Fase 7: Integración + Entrega (Semana 7)

| Tarea | Días |
|---|---|
| Deploy en servidor del cliente | 1 |
| Testing end-to-end con concurso real | 1.5 |
| Calibración final (umbrales, reglas) | 0.5 |
| Capacitación (2 horas) | 0.5 |
| Manual de usuario | 0.5 |
| **Total** | **4 días** |

**Entregable:** Sistema instalado + capacitación + manual.

---

### Resumen del Cronograma

```
Semana  1    2    3    4    5    6    7
        ├────┤                              Fase 1: PoC + OCR
             ├────┤                         Fase 2: Extracción + BD
                  ├────┤                    Fase 3: Reglas + Excel ← DEMO
                       ├─────────┤          Fase 4: Infobras
                            ├────────┤      Fase 5: SUNAT/CIP
                                 ├────────┤ Fase 6: Web
                                      ├──┤ Fase 7: Entrega
```

**Total: 6 – 7 semanas** (con margen: 8 semanas si Infobras es más complejo de lo esperado).

---

## 12. Riesgo Principal y Mitigación

### El riesgo real: OCR + documentos desordenados

Los PDFs escaneados pueden producir:

```
SUPERVISOR DE C0NSTRUCCI0N    ← O confundida con 0
INGENIER0 CIVIL               ← O confundida con 0
INGENIERO ClVIL               ← I confundida con l
```

**Mitigación:**

1. **Preprocesamiento de imagen** antes del OCR (denoising, deskewing, binarización)
2. **PaddleOCR** es significativamente mejor que Tesseract para estos casos
3. **El LLM tolera errores de OCR** — puede interpretar "INGENIER0 CIVIL" como "Ingeniero Civil" porque entiende contexto
4. **Campo de confianza** — el sistema marca con baja confianza cuando el OCR no es claro

### El segundo riesgo: Infobras

Si Infobras implementa CAPTCHA o cambia estructura → el módulo falla.

**Mitigación:** Modo manual asistido. El sistema prepara los datos (código, nombre del proyecto), el usuario hace la verificación manualmente, y carga el resultado. No se pierde la inversión en los otros módulos.

---

*Documento técnico generado el 2026-03-06.*
