
## Arquitectura 100% local y open source

Basado en lo que se sabe del proyecto, esta sería la stack recomendada:

---

### Visión general

```
┌─────────────────────────────────────────────────────┐
│                    SERVIDOR LOCAL                    │
│                                                      │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐  │
│  │  Frontend │    │  Backend │    │  IA / Modelos │  │
│  │  Next.js  │◄──►│ FastAPI  │◄──►│  Ollama +     │  │
│  │           │    │(Python)  │    │  LLaMA / Qwen │  │
│  └──────────┘    └────┬─────┘    └───────────────┘  │
│                       │                              │
│              ┌────────┼────────┐                     │
│              ▼        ▼        ▼                     │
│         ┌────────┐ ┌──────┐ ┌──────────────┐        │
│         │ PostgreSQL│ Redis │ │  Filesystem  │        │
│         │ + pgvector│(queue)│ │  (PDFs/docs) │        │
│         └────────┘ └──────┘ └──────────────┘        │
└─────────────────────────────────────────────────────┘
         ▲                           ▲
         │ scraping interno          │ archivos
    InfoObras                   usuarios via
    SUNAT                       interfaz web
```

---

### Capa por capa

**Frontend — Next.js**
Simple, sin dependencias de nube. El cliente sube el PDF desde el navegador, ve el progreso del análisis en tiempo real y descarga el Excel final. Accesible desde cualquier máquina de la red interna.

**Backend — FastAPI (Python)**
Python es la elección natural porque todas las librerías de OCR, procesamiento de PDF y LLM tienen soporte nativo. FastAPI es ligero y permite streaming de respuestas para mostrar el progreso al usuario.

**OCR — Doctr o PaddleOCR**
Ambas son open source y manejan bien documentos escaneados en español. PaddleOCR tiene mejor soporte para documentos con sellos y firmas superpuestas, que es exactamente el problema del cliente. Doctr es más fácil de integrar. Vale la pena probar ambas con los PDFs reales del cliente antes de decidir.

**LLM local — Ollama + Qwen2.5 o LLaMA 3.1**
Ollama es el estándar para servir modelos localmente. Para este caso específico — extracción estructurada de texto en español con reglas estrictas — Qwen2.5:14b o Qwen2.5:32b son mejores opciones que LLaMA porque tienen mejor desempeño en español y en tareas de extracción estructurada. Si el servidor tiene GPU con 24GB+ de VRAM, el modelo de 32b es viable; si no, el de 14b es suficiente para este caso de uso.

La temperatura se configura en 0 o muy cercana a 0 para que el modelo sea determinista y no "invente" datos.

**Base de datos — PostgreSQL + pgvector**
PostgreSQL guarda los proyectos, profesionales, experiencias y resultados. pgvector permite hacer búsquedas semánticas de proyectos similares en el futuro (útil para el módulo de InfoObras). Redis sirve como cola de tareas para los jobs de procesamiento largo (un PDF de 2300 páginas puede tardar varios minutos).

**Scraping — Playwright**
Para InfoObras y SUNAT. Playwright es más robusto que Selenium para sitios que usan JavaScript dinámico. Se ejecuta headless en el servidor. Importante: construirlo con rate limiting y manejo de errores porque InfoObras es un sitio del Estado peruano y puede ser inestable.

**Generación de Excel — openpyxl**
Para producir el Excel exactamente en el formato que el cliente ya usa, con los mismos colores, columnas y fórmulas.

---

### Hardware mínimo recomendado

| Componente | Mínimo | Recomendado |
|---|---|---|
| CPU | 8 cores | 16 cores |
| RAM | 32 GB | 64 GB |
| GPU | GTX 1080 (8GB VRAM) | RTX 3090/4090 (24GB VRAM) |
| Almacenamiento | 500 GB SSD | 2 TB NVMe |
| SO | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

Sin GPU el sistema funciona, pero el procesamiento de un PDF grande pasaría de minutos a potencialmente 30–60 minutos por documento. Con GPU el modelo corre en VRAM y la diferencia es dramática.

---

### Flujo de datos dentro del sistema

```
1. Usuario sube PDF (propuesta) + PDF (bases)
         ↓
2. OCR pipeline
   - Detectar páginas escaneadas vs. texto nativo
   - Aplicar OCR solo donde es necesario
   - Extraer mapa de folios (número de hoja por posición)
         ↓
3. Chunking inteligente
   - Dividir por profesional (detectar secciones)
   - Dividir por certificado dentro de cada profesional
   - Mantener referencia al folio original
         ↓
4. Extracción con LLM (temperatura = 0)
   - Prompt estructurado para cada chunk
   - Output en JSON con schema fijo
   - Validación del JSON antes de guardar
         ↓
5. Aplicación de reglas de negocio
   - Motor de reglas (sin LLM, puro código)
   - Generación de alertas
   - Cálculo de duraciones y antigüedad
         ↓
6. Enriquecimiento externo (workers en paralelo)
   - SUNAT: fecha creación empresa por RUC
   - InfoObras: código, estado, valorizaciones
   - SNIP: código CUI por nombre de proyecto
         ↓
7. Evaluación contra bases
   - Comparación con JSON de requisitos (Paso 1)
   - Motor de coincidencia literal de cargos
   - Generación de CUMPLE/NO CUMPLE con justificación
         ↓
8. Generación de Excel
   - openpyxl con el template del cliente
   - Colores de alerta automáticos
   - Fórmulas de conteo de años
```

---

### Lo más crítico a resolver primero

Antes de escribir una línea de código del sistema, hay que hacer dos cosas:

**Primero:** Probar el OCR con 5–10 páginas reales de los PDFs del cliente. Los PDFs escaneados de licitaciones peruanas varían mucho en calidad — algunos vienen de fotocopias de fotocopias. La elección del motor de OCR (y los parámetros de preprocesamiento de imagen) define si el sistema es viable o no.

**Segundo:** Probar el LLM en la extracción del Paso 3 con un certificado real. La extracción de las 27 columnas desde un certificado escaneado es el corazón del sistema. Si el modelo no lo hace bien con temperatura 0, hay que ajustar el prompt o considerar un modelo más grande antes de comprometerse con la arquitectura.