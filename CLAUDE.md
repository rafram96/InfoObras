# Alpamayo-InfoObras

## Qué es este proyecto
Sistema de evaluación automatizada de propuestas técnicas para licitaciones de obras públicas en Perú.
Lee certificados de profesionales (ya procesados por OCR en otro repo) y los evalúa contra los requisitos del TDR.

El problema que resuelve: el análisis manual de una propuesta toma 6-12 horas. Este sistema lo reduce a 20-40 minutos incluyendo verificación cruzada con InfoObras.

## Arquitectura
- **motor-OCR** (repo separado, NO tocar): caja negra. Entra PDF escaneado, salen archivos `.md` en `ocr_output/`. Corre en el servidor del cliente.
- **Este repo**: consume esos `.md` y hace extracción, validación, scraping y reportes.

## Repos y entornos

### motor-OCR
- Repo: `C:\Users\Holbi\Documents\Freelance\proyectos\motor-OCR`
- Servidor del cliente: `D:\proyectos\motor-OCR`
- Python 3.11, PaddleOCR, GPU NVIDIA Quadro RTX 5000 16GB
- Output en: `D:\proyectos\infoobras\ocr_output\{nombre_pdf}\`
- Actualmente los outputs lo tengo en la carpeta data de este proyecto
- **No tocar — funciona y tiene dependencias muy frágiles**

### Este repo (Alpamayo-InfoObras)
- Repo local: `C:\Users\Holbi\Documents\Freelance\Alpamayo-InfoObras`
- Servidor del cliente: por definir
- Python 3.12, sin dependencias de ML
- Solamente se corre cosas Python aquí, nada de LLM's que eso se prueba en el servidor

## Servidor del cliente
- OS: Windows 11 Pro
- CPU: Intel Core i9-14900K (24 cores)
- RAM: 64GB DDR5
- GPU: NVIDIA Quadro RTX 5000 16GB VRAM (usada por motor-OCR)
- SSD: 3TB NVMe
- Servicios corriendo: Docker, n8n, OpenWebUI, Nginx Proxy Manager, Ollama
- Modelos en Ollama: `qwen2.5vl:7b` (segmentación), `qwen2.5:14b` (extracción)
- Todo on-premise, sin cloud, sin APIs externas de pago

## Flujo completo del sistema
```
PDF escaneado (2300+ págs)
    ↓
[motor-OCR] OCR + segmentación por profesional
    ↓
ocr_output/{pdf}/*_profesionales_*.md
    ↓
[este repo] extracción → validación → scraping → Excel
    ↓
Reporte Excel con alertas + documentos de InfoObras
```

## Output del motor-OCR
Por cada PDF procesado genera en `ocr_output/{nombre_pdf}/`:
- `*_metricas_*.md` — calidad OCR por página
- `*_texto_*.md` — texto extraído página a página
- `*_segmentacion_*.md` — bloques crudos de segmentación (debug)
- `*_profesionales_*.md` — secciones consolidadas por profesional ← **input de este repo**

Cada `ProfessionalSection` contiene: cargo, número (N°1/N°2/etc), páginas del bloque, método de detección.

## Estructura
```
ocr_output/                  ← input (generado por motor-OCR, NO tocar)
src/
  extraction/                ← parsea .md → datos estructurados (Paso 2 y 3)
  validation/                ← motor de reglas determinístico (Pasos 4 y 5)
  scraping/                  ← InfoObras, SUNAT, CIP
  reporting/                 ← genera Excel final (5 hojas)
utils/                       ← herramientas auxiliares y PoCs
docs/                        ← documentación del proyecto
data/                        ← datos procesados (NO subir al repo)
```

## Stack
- Python 3.12
- Dependencias principales: `openai`, `openpyxl`, `requests`, `playwright`
- LLM para extracción: `qwen2.5:14b` vía Ollama local (temperatura 0)
- SIN PaddleOCR ni dependencias pesadas de ML

## Los 5 pasos del proceso (contexto del negocio)

### Paso 1 — Criterios RTM de las bases
Extrae de las bases del concurso qué se requiere por cargo: profesión, años colegiado, experiencia mínima, tipo de obra, cargos válidos.

### Paso 2 — Profesionales propuestos
Lista todos los profesionales del PDF: nombre, profesión, CIP, fecha colegiación, folio.

### Paso 3 — Base de datos de experiencias (27 columnas)
Por cada certificado: nombre, DNI, proyecto, cargo, empresa, RUC, fechas, folio, CUI, código InfoObras, firmante, etc.

### Paso 4 — Evaluación RTM (22 criterios)
Motor de reglas determinístico: cumple/no cumple por profesión, cargo, tipo de obra, intervención, complejidad.

### Paso 5 — Evaluación de años de experiencia
Suma días efectivos descontando paralizaciones, suspensiones y COVID (16/03/2020–31/12/2021).

## Las 9 alertas del motor de reglas
- ALT01: Fecha fin > fecha emisión certificado
- ALT02: Periodo COVID (16/03/2020–31/12/2021)
- ALT03: Experiencia > 20 años desde fecha de propuesta
- ALT04: Empresa emisora constituida después del inicio de experiencia
- ALT05: Certificado sin fecha de término ("a la fecha")
- ALT06: Cargo no válido según bases
- ALT07: Profesión no coincide con la requerida
- ALT08: Tipo de obra no coincide
- ALT09 (propuesta): CIP no vigente

## Scraping
- **InfoObras** (Contraloría): búsqueda por CUI → estado de obra, avances mensuales, suspensiones, actas. Funciona con `requests` + parsing, sin CAPTCHA ni Playwright.
- **SUNAT**: fecha de inicio de actividades por RUC.
- **CIP**: verificación de vigencia del número de colegiatura.

## Excel de salida (5 hojas)
1. Resumen — totales, alertas críticas
2. Base de Datos (Paso 3) — 27 columnas
3. Evaluación RTM (Paso 4) — 22 columnas, CUMPLE/NO CUMPLE
4. Alertas — código, severidad, descripción por profesional
5. Verificación InfoObras — CUI, estado, suspensiones, días descontados

Colores: Verde = Cumple · Amarillo = Observación · Rojo = No cumple/Alerta crítica

## Cliente
- Inmobiliaria Alpamayo / Indeconsult
- Contacto: Ing. Manuel Echandía
- Uso: evaluación de propuestas técnicas en concursos públicos de supervisión de obras hospitalarias

## Convenciones
- Idioma del código: espanol (variables, funciones, clases)
- Idioma de comentarios y docs: español
- Idioma de commits: español
- Formato de commits: descripción cortisima (usar formato Feat, Fix, Debug, etc)

## Comandos útiles
```bash
# Activar entorno virtual
source venv/Scripts/activate    # Windows/Git Bash

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar tests
pytest

# Scraper InfoObras (PoC)
python utils/infoobras/buscar.py
```

## Qué NO hacer
- No instalar PaddleOCR ni dependencias de ML aquí
- No modificar archivos en `ocr_output/` — son generados por motor-OCR
- No subir PDFs ni datos del cliente al repositorio
- No tocar el repo motor-OCR — funciona y sus dependencias son frágiles
- No usar APIs cloud para procesamiento — todo debe correr on-premise