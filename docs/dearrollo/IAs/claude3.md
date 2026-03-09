# ARQUITECTURA Y PLANEAMIENTO TÉCNICO
## InfoObras Analyzer - Sistema de Verificación Automatizada

**Cliente:** Grupo Echandía (Alpamayo/Indeconsult)  
**Desarrollador:** Rafael Ramos Huamaní  
**Fecha:** Marzo 2026  
**Versión:** 1.0

---

## 📋 ÍNDICE

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Arquitectura del Sistema](#2-arquitectura-del-sistema)
3. [Stack Tecnológico](#3-stack-tecnológico)
4. [Esquemas de Base de Datos](#4-esquemas-de-base-de-datos)
5. [Módulos del Sistema](#5-módulos-del-sistema)
6. [Pipeline de Procesamiento](#6-pipeline-de-procesamiento)
7. [APIs y Endpoints](#7-apis-y-endpoints)
8. [Estructura de Archivos](#8-estructura-de-archivos)
9. [Plan de Desarrollo 7 Semanas](#9-plan-de-desarrollo-7-semanas)
10. [Criterios de Validación](#10-criterios-de-validación)
11. [Riesgos y Mitigación](#11-riesgos-y-mitigación)

---

## 1. RESUMEN EJECUTIVO

### 1.1 Objetivo del Sistema

Automatizar la verificación de experiencia profesional en propuestas técnicas de concursos públicos mediante:

- Extracción OCR de certificados (PDF ~2,300 páginas)
- Scraping de portales estatales (Infobras, SUNAT, CIP)
- Cálculo automático de días efectivos
- Detección de suspensiones y paralizaciones
- Generación de Excel con evaluación completa
- Descarga organizada de documentos probatorios

### 1.2 Alcance Funcional

**Entradas:**
- PDF propuesta técnica (~2,300 páginas, ~45 certificados)
- Archivo bases del concurso (Excel/PDF)

**Procesamiento:**
- OCR con PaddleOCR
- Segmentación automática en certificados
- Extracción LLM de datos estructurados
- Scraping Infobras (ficha, avances, informes)
- Scraping SUNAT (constitución empresa)
- Scraping CIP (vigencia colegiatura)
- Cálculo de días efectivos con descuentos
- Motor de reglas con 9 alertas

**Salidas:**
- Excel con evaluación detallada
- ZIP con documentos descargados organizados
- Reporte de alertas por severidad

### 1.3 Características Técnicas Clave

- **100% local:** Sin APIs externas, sin cloud
- **Cliente-Servidor:** Servidor procesa, cliente descarga
- **Multi-usuario:** Acceso web desde cualquier PC
- **Procesamiento paralelo:** 45 certificados simultáneos
- **Trazabilidad completa:** Origen de cada dato verificable
- **Arquitectura modular:** 7 módulos independientes

---

## 2. ARQUITECTURA DEL SISTEMA

### 2.1 Diagrama de Alto Nivel

```
┌─────────────────────────────────────────────────────────────┐
│                    USUARIO (Navegador)                       │
│  - Sube PDF + Bases                                         │
│  - Monitorea progreso                                        │
│  - Descarga Excel + ZIP documentos                           │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/WebSocket
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              SERVIDOR (Ubuntu 22.04)                         │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            FRONTEND (Next.js 14)                     │  │
│  │  Puerto: 3000                                        │  │
│  │  - Upload interface                                   │  │
│  │  - Progress dashboard (real-time)                    │  │
│  │  - Results visualization                             │  │
│  │  - Download buttons                                   │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │ REST API                            │
│                       ▼                                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           BACKEND (FastAPI)                          │  │
│  │  Puerto: 8000                                        │  │
│  │                                                      │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐    │  │
│  │  │ OCR Engine │  │ LLM Client │  │ Rules Eng. │    │  │
│  │  │ PaddleOCR  │  │ Ollama     │  │ Python     │    │  │
│  │  └────────────┘  └────────────┘  └────────────┘    │  │
│  │                                                      │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐    │  │
│  │  │ Scrapers   │  │ Calculator │  │ Excel Gen  │    │  │
│  │  │ Playwright │  │ Datetime   │  │ openpyxl   │    │  │
│  │  └────────────┘  └────────────┘  └────────────┘    │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                     │
│  ┌────────────────────┴─────────────────────────────────┐  │
│  │                                                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │  │
│  │  │ PostgreSQL   │  │ Ollama       │  │ Redis     │  │  │
│  │  │ Port: 5432   │  │ Port: 11434  │  │ Port:6379 │  │  │
│  │  │              │  │              │  │           │  │  │
│  │  │ - projects   │  │ - Qwen 14B   │  │ - Queue   │  │  │
│  │  │ - certs      │  │ - Embed      │  │ - Cache   │  │  │
│  │  │ - profs      │  │              │  │           │  │  │
│  │  │ - alerts     │  │              │  │           │  │  │
│  │  │ - verif      │  │              │  │           │  │  │
│  │  └──────────────┘  └──────────────┘  └───────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           FILE SYSTEM                                 │  │
│  │  /srv/infobras/data/                                  │  │
│  │    ├─ uploads/          # PDFs subidos               │  │
│  │    ├─ processed/        # OCR cache                  │  │
│  │    └─ downloads/        # Resultados                 │  │
│  │       └─ {project_id}/                               │  │
│  │          ├─ resultado.xlsx                           │  │
│  │          └─ documentos/                              │  │
│  │             ├─ {Obra}_{CUI}/                         │  │
│  │             │  ├─ 01_Acta_Entrega.pdf                │  │
│  │             │  ├─ 02_Val_Ene_2023.doc                │  │
│  │             │  └─ Informes_Control/                  │  │
│  │             │     └─ Informe_001.pdf                 │  │
│  │             └─ SUNAT/                                │  │
│  │                └─ RUC_*.pdf                          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                         │
                         │ HTTPS (Scraping)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              PORTALES EXTERNOS                               │
│  - infobras.contraloria.gob.pe                              │
│  - e-consultaruc.sunat.gob.pe                               │
│  - cap.org.pe (Colegio de Ingenieros)                       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Flujo de Datos

```
1. UPLOAD
   Usuario → Frontend → Backend → File System

2. PROCESSING (Background Task)
   a) OCR: PDF → PaddleOCR → Text per page
   b) Segmentation: Pages → Certificates (45)
   c) Extraction: Certificate → LLM → JSON
   d) Database: JSON → PostgreSQL
   e) Scraping: 
      - CUI → Infobras → Downloads
      - RUC → SUNAT → Data
      - CIP → CIP → Data
   f) Calculation: Dates + Suspensions → Effective days
   g) Rules: Professional data → Alerts
   h) Excel: All data → XLSX
   i) ZIP: All downloads → ZIP

3. DOWNLOAD
   Backend → File Response → Browser → User's Downloads folder
```

---

## 3. STACK TECNOLÓGICO

### 3.1 Backend

```yaml
Framework: FastAPI 0.109.0
Language: Python 3.11+
ASGI Server: Uvicorn

Dependencies:
  # Core
  - fastapi: 0.109.0
  - uvicorn[standard]: 0.27.0
  - pydantic: 2.5.3
  - python-dotenv: 1.0.0
  
  # Database
  - psycopg2-binary: 2.9.9
  - sqlalchemy: 2.0.25
  - alembic: 1.13.1
  
  # OCR
  - paddleocr: 2.7.0
  - paddlepaddle: 2.6.0
  - opencv-python: 4.9.0
  - Pillow: 10.2.0
  - pdf2image: 1.17.0
  - pytesseract: 0.3.10  # Fallback
  
  # LLM
  - ollama: 0.1.6
  - httpx: 0.26.0
  
  # Scraping
  - playwright: 1.41.1
  - beautifulsoup4: 4.12.3
  - lxml: 5.1.0
  
  # Excel
  - openpyxl: 3.1.2
  - xlsxwriter: 3.1.9
  
  # Utils
  - python-dateutil: 2.8.2
  - dateparser: 1.2.0
  - rapidfuzz: 3.6.1
  - python-multipart: 0.0.6
  - aiofiles: 23.2.1
  
  # Cache/Queue
  - redis: 5.0.1
  - celery: 5.3.4  # Para tasks async
  
  # Logging
  - loguru: 0.7.2
```

### 3.2 Frontend

```json
{
  "framework": "Next.js 14.1.0",
  "language": "TypeScript 5.3.3",
  
  "dependencies": {
    "next": "14.1.0",
    "react": "18.2.0",
    "react-dom": "18.2.0",
    
    "axios": "1.6.5",
    "swr": "2.2.4",
    
    "tailwindcss": "3.4.1",
    "@shadcn/ui": "latest",
    
    "lucide-react": "0.312.0",
    "recharts": "2.10.3",
    "react-dropzone": "14.2.3",
    "date-fns": "3.2.0",
    "zustand": "4.4.7"
  }
}
```

### 3.3 Infraestructura

```yaml
Base OS: Ubuntu Server 22.04 LTS

Services:
  - PostgreSQL: 16
  - Redis: 7.2
  - Ollama: Latest
  - Nginx: 1.24 (reverse proxy)

LLM Model:
  - Qwen 2.5 14B Instruct Q4_K_M
  - nomic-embed-text (embeddings)

GPU Requirements:
  - VRAM: 16GB mínimo
  - CUDA: 12.1+
  - Driver: 550.x+
```

---

## 4. ESQUEMAS DE BASE DE DATOS

### 4.1 Diagrama ER

```
┌─────────────────┐
│    projects     │
├─────────────────┤
│ id (PK)         │
│ name            │
│ pdf_path        │
│ bases_path      │
│ status          │
│ total_pages     │
│ total_certs     │
│ user_id         │
│ uploaded_at     │
│ completed_at    │
└────────┬────────┘
         │
         │ 1:N
         │
         ▼
┌─────────────────┐
│  certificates   │
├─────────────────┤
│ id (PK)         │
│ project_id (FK) │
│ page_start      │
│ page_end        │
│ ocr_text        │
│ ocr_confidence  │
│ processed_at    │
└────────┬────────┘
         │
         │ 1:1
         │
         ▼
┌─────────────────┐       ┌─────────────────┐
│  professionals  │       │     alerts      │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │◄──┐   │ id (PK)         │
│ cert_id (FK)    │   │   │ prof_id (FK)    │
│ full_name       │   │   │ alert_code      │
│ dni             │   │   │ severity        │
│ cip             │   │   │ title           │
│ position        │   │   │ description     │
│ company_name    │   │   │ details (JSON)  │
│ company_ruc     │   │   │ created_at      │
│ start_date      │   └───┤                 │
│ end_date        │       └─────────────────┘
│ emission_date   │
│ obra_name       │       ┌─────────────────┐
│ obra_cui        │       │  verifications  │
│ obra_type       │       ├─────────────────┤
│ folio           │       │ id (PK)         │
│                 │       │ prof_id (FK)    │
│ dias_declarados │       │ source          │
│ dias_paralizados│       │ query_data      │
│ dias_suspension │       │ result (JSON)   │
│ dias_covid      │◄──────┤ status          │
│ dias_efectivos  │       │ verified_at     │
│                 │       │ error_msg       │
│ complies        │       └─────────────────┘
│ observations    │
│ raw_extraction  │       ┌─────────────────┐
│ created_at      │       │   obra_data     │
└─────────────────┘       ├─────────────────┤
                          │ id (PK)         │
                          │ prof_id (FK)    │
                          │ cui             │
                          │ fecha_contrato  │
                          │ fecha_inicio    │
                          │ fecha_fin       │
                          │ estado          │
                          │ monto           │
                          │ avances (JSON)  │
                          │ suspensiones    │
                          │   (JSON)        │
                          │ downloads       │
                          │   (JSON)        │
                          │ created_at      │
                          └─────────────────┘
```

### 4.2 SQL Schema Completo

```sql
-- =====================================================
-- SCHEMA: InfoObras Analyzer Database
-- Version: 1.0
-- =====================================================

-- Extension para UUIDs (opcional)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- TABLE: projects
-- =====================================================
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    
    -- Identificación
    name VARCHAR(255) NOT NULL,
    project_code VARCHAR(100),
    
    -- Archivos
    pdf_filename VARCHAR(500) NOT NULL,
    pdf_path TEXT NOT NULL,
    pdf_size_mb DECIMAL(10,2),
    bases_filename VARCHAR(500),
    bases_path TEXT,
    
    -- Metadata PDF
    total_pages INTEGER,
    total_certificates INTEGER,
    
    -- Estado
    status VARCHAR(50) DEFAULT 'uploaded',
    -- Valores: uploaded, processing, completed, failed
    
    -- Usuario (opcional)
    user_id VARCHAR(100),
    user_email VARCHAR(255),
    
    -- Timestamps
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Metadata
    metadata JSONB,
    
    -- Auditoría
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT valid_status CHECK (status IN (
        'uploaded', 'processing', 'completed', 'failed'
    ))
);

-- Índices
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_user ON projects(user_id);
CREATE INDEX idx_projects_created ON projects(created_at DESC);

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- TABLE: certificates
-- =====================================================
CREATE TABLE certificates (
    id SERIAL PRIMARY KEY,
    
    -- Relación
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    -- Ubicación en PDF
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    certificate_number INTEGER, -- Secuencial dentro del proyecto
    
    -- OCR
    ocr_text TEXT,
    ocr_confidence DECIMAL(5,2), -- 0-100
    ocr_language VARCHAR(10) DEFAULT 'es',
    raw_ocr_json JSONB,
    
    -- Procesamiento
    extraction_status VARCHAR(50) DEFAULT 'pending',
    -- Valores: pending, processing, completed, failed
    extraction_error TEXT,
    processed_at TIMESTAMP,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT valid_pages CHECK (page_end >= page_start),
    CONSTRAINT valid_extraction_status CHECK (extraction_status IN (
        'pending', 'processing', 'completed', 'failed'
    ))
);

-- Índices
CREATE INDEX idx_certificates_project ON certificates(project_id);
CREATE INDEX idx_certificates_status ON certificates(extraction_status);

-- =====================================================
-- TABLE: professionals
-- =====================================================
CREATE TABLE professionals (
    id SERIAL PRIMARY KEY,
    
    -- Relación
    certificate_id INTEGER NOT NULL REFERENCES certificates(id) ON DELETE CASCADE,
    
    -- Datos personales
    full_name VARCHAR(255),
    dni VARCHAR(20),
    cip VARCHAR(50),
    profession VARCHAR(255),
    
    -- Cargo
    position VARCHAR(255),
    position_normalized VARCHAR(255), -- Normalizado para comparación
    
    -- Empresa
    company_name VARCHAR(255),
    company_ruc VARCHAR(20),
    
    -- Fechas
    start_date DATE,
    end_date DATE,
    emission_date DATE,
    has_indefinite_end BOOLEAN DEFAULT FALSE,
    
    -- Obra/Proyecto
    obra_name TEXT,
    obra_cui VARCHAR(50),
    obra_type VARCHAR(255),
    obra_location VARCHAR(255),
    obra_entity VARCHAR(255),
    
    -- Certificado
    folio VARCHAR(100),
    certificate_number VARCHAR(100),
    issuer_name VARCHAR(255),
    issuer_position VARCHAR(255),
    
    -- Cálculo de días
    dias_declarados INTEGER, -- Según certificado
    dias_paralizados INTEGER DEFAULT 0, -- Según avances Infobras
    dias_suspension INTEGER DEFAULT 0, -- Según informes Contraloría
    dias_covid INTEGER DEFAULT 0, -- Overlap con periodo COVID
    dias_efectivos INTEGER, -- Computables reales
    
    -- Evaluación
    complies BOOLEAN,
    dias_minimos_requeridos INTEGER, -- Según bases
    observations TEXT,
    
    -- Raw data
    raw_extraction JSONB, -- JSON completo del LLM
    
    -- Auditoría
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices
CREATE INDEX idx_professionals_certificate ON professionals(certificate_id);
CREATE INDEX idx_professionals_dni ON professionals(dni);
CREATE INDEX idx_professionals_cip ON professionals(cip);
CREATE INDEX idx_professionals_ruc ON professionals(company_ruc);
CREATE INDEX idx_professionals_cui ON professionals(obra_cui);
CREATE INDEX idx_professionals_complies ON professionals(complies);

-- Trigger updated_at
CREATE TRIGGER update_professionals_updated_at
    BEFORE UPDATE ON professionals
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- TABLE: alerts
-- =====================================================
CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    
    -- Relación
    professional_id INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
    
    -- Alerta
    alert_code VARCHAR(20) NOT NULL, -- ALT-01, ALT-02, CALC-01, etc.
    severity VARCHAR(20) DEFAULT 'medium',
    -- Valores: low, medium, high, critical
    
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    details JSONB, -- Datos adicionales específicos de la alerta
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT valid_severity CHECK (severity IN (
        'low', 'medium', 'high', 'critical'
    ))
);

-- Índices
CREATE INDEX idx_alerts_professional ON alerts(professional_id);
CREATE INDEX idx_alerts_code ON alerts(alert_code);
CREATE INDEX idx_alerts_severity ON alerts(severity);

-- =====================================================
-- TABLE: verifications
-- =====================================================
CREATE TABLE verifications (
    id SERIAL PRIMARY KEY,
    
    -- Relación
    professional_id INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
    
    -- Verificación
    source VARCHAR(50) NOT NULL,
    -- Valores: infobras, sunat, cip, rnp
    
    query_data JSONB, -- Datos de la consulta (CUI, RUC, CIP, etc.)
    result JSONB, -- Resultado completo
    
    -- Estado
    status VARCHAR(50) DEFAULT 'pending',
    -- Valores: pending, processing, success, failed
    
    verified_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT valid_source CHECK (source IN (
        'infobras', 'sunat', 'cip', 'rnp'
    )),
    CONSTRAINT valid_status CHECK (status IN (
        'pending', 'processing', 'success', 'failed'
    ))
);

-- Índices
CREATE INDEX idx_verifications_professional ON verifications(professional_id);
CREATE INDEX idx_verifications_source ON verifications(source);
CREATE INDEX idx_verifications_status ON verifications(status);

-- =====================================================
-- TABLE: obra_data
-- =====================================================
CREATE TABLE obra_data (
    id SERIAL PRIMARY KEY,
    
    -- Relación
    professional_id INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
    
    -- Identificación
    cui VARCHAR(50) NOT NULL,
    codigo_infobra VARCHAR(100),
    
    -- Ficha pública
    fecha_contrato DATE,
    fecha_inicio_prevista DATE,
    fecha_fin_prevista DATE,
    fecha_inicio_real DATE,
    fecha_fin_real DATE,
    estado VARCHAR(100),
    monto_contratado DECIMAL(15,2),
    
    -- Avances mensuales (array de objetos)
    avances JSONB,
    -- Estructura: [
    --   {
    --     "mes": "2023-01-01",
    --     "mes_texto": "10.01 VAL ENE 2023",
    --     "estado": "Ejecutado",
    --     "avance_fisico": 15.5,
    --     "avance_financiero": 12.3
    --   },
    --   ...
    -- ]
    
    -- Suspensiones (array de objetos)
    suspensiones JSONB,
    -- Estructura: [
    --   {
    --     "fecha_inicio": "2023-03-15",
    --     "fecha_fin": "2023-04-30",
    --     "dias": 46,
    --     "motivo": "Paralización COVID",
    --     "fuente": "Informe 001-2023"
    --   },
    --   ...
    -- ]
    
    -- Documentos descargados
    downloads JSONB,
    -- Estructura: {
    --   "acta_entrega": "/path/to/file.pdf",
    --   "valorizaciones": ["/path/to/val1.doc", ...],
    --   "informes": ["/path/to/inf1.pdf", ...]
    -- }
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices
CREATE INDEX idx_obra_data_professional ON obra_data(professional_id);
CREATE INDEX idx_obra_data_cui ON obra_data(cui);

-- Trigger updated_at
CREATE TRIGGER update_obra_data_updated_at
    BEFORE UPDATE ON obra_data
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- TABLE: processing_logs
-- =====================================================
CREATE TABLE processing_logs (
    id SERIAL PRIMARY KEY,
    
    -- Relación
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    professional_id INTEGER REFERENCES professionals(id) ON DELETE CASCADE,
    
    -- Log
    stage VARCHAR(100) NOT NULL,
    -- Valores: upload, ocr, segmentation, extraction, 
    --          scraping_infobras, scraping_sunat, scraping_cip,
    --          calculation, rules, excel, zip
    
    status VARCHAR(50) NOT NULL,
    -- Valores: started, completed, failed
    
    message TEXT,
    details JSONB,
    
    -- Performance
    duration_seconds DECIMAL(10,3),
    
    -- Timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT valid_log_status CHECK (status IN (
        'started', 'completed', 'failed'
    ))
);

-- Índices
CREATE INDEX idx_logs_project ON processing_logs(project_id);
CREATE INDEX idx_logs_professional ON processing_logs(professional_id);
CREATE INDEX idx_logs_stage ON processing_logs(stage);
CREATE INDEX idx_logs_created ON processing_logs(created_at DESC);

-- =====================================================
-- VIEWS: Resúmenes útiles
-- =====================================================

-- Vista: Resumen de proyecto
CREATE OR REPLACE VIEW v_project_summary AS
SELECT 
    p.id,
    p.name,
    p.status,
    p.total_certificates,
    COUNT(DISTINCT pr.id) as total_professionals,
    COUNT(DISTINCT CASE WHEN pr.complies = true THEN pr.id END) as professionals_compliant,
    COUNT(DISTINCT CASE WHEN pr.complies = false THEN pr.id END) as professionals_non_compliant,
    COUNT(DISTINCT a.id) as total_alerts,
    COUNT(DISTINCT CASE WHEN a.severity = 'critical' THEN a.id END) as critical_alerts,
    p.uploaded_at,
    p.completed_at
FROM projects p
LEFT JOIN certificates c ON c.project_id = p.id
LEFT JOIN professionals pr ON pr.certificate_id = c.id
LEFT JOIN alerts a ON a.professional_id = pr.id
GROUP BY p.id;

-- Vista: Profesionales con alertas
CREATE OR REPLACE VIEW v_professionals_with_alerts AS
SELECT 
    pr.id as professional_id,
    pr.full_name,
    pr.dni,
    pr.cip,
    pr.position,
    pr.obra_name,
    pr.obra_cui,
    pr.dias_efectivos,
    pr.dias_minimos_requeridos,
    pr.complies,
    COUNT(a.id) as alert_count,
    JSON_AGG(
        JSON_BUILD_OBJECT(
            'code', a.alert_code,
            'severity', a.severity,
            'title', a.title
        )
    ) as alerts
FROM professionals pr
LEFT JOIN alerts a ON a.professional_id = pr.id
GROUP BY pr.id;

-- =====================================================
-- FUNCIONES ÚTILES
-- =====================================================

-- Función: Calcular progreso de proyecto
CREATE OR REPLACE FUNCTION get_project_progress(p_project_id INTEGER)
RETURNS JSON AS $$
DECLARE
    v_total_certs INTEGER;
    v_processed_certs INTEGER;
    v_progress DECIMAL(5,2);
    v_current_stage VARCHAR(100);
BEGIN
    -- Contar certificados
    SELECT total_certificates INTO v_total_certs
    FROM projects
    WHERE id = p_project_id;
    
    -- Contar certificados procesados
    SELECT COUNT(*) INTO v_processed_certs
    FROM certificates
    WHERE project_id = p_project_id
    AND extraction_status = 'completed';
    
    -- Calcular progreso
    IF v_total_certs > 0 THEN
        v_progress := (v_processed_certs::DECIMAL / v_total_certs) * 100;
    ELSE
        v_progress := 0;
    END IF;
    
    -- Determinar etapa actual
    SELECT stage INTO v_current_stage
    FROM processing_logs
    WHERE project_id = p_project_id
    AND status = 'started'
    ORDER BY created_at DESC
    LIMIT 1;
    
    -- Retornar JSON
    RETURN JSON_BUILD_OBJECT(
        'total_certificates', v_total_certs,
        'processed_certificates', v_processed_certs,
        'progress_percent', v_progress,
        'current_stage', v_current_stage
    );
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- DATOS INICIALES / CONFIGURACIÓN
-- =====================================================

-- Tabla de configuración (opcional)
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Configuraciones por defecto
INSERT INTO system_config (key, value, description) VALUES
('covid_start_date', '2020-03-15', 'Inicio del periodo de paralización COVID-19'),
('covid_end_date', '2021-12-31', 'Fin del periodo de paralización COVID-19'),
('max_antiquity_years', '20', 'Antigüedad máxima aceptable de experiencia'),
('ollama_model', 'qwen2.5:14b-instruct-q4_k_m', 'Modelo LLM para extracción'),
('ocr_confidence_threshold', '70', 'Confianza mínima OCR (0-100)')
ON CONFLICT (key) DO NOTHING;

-- =====================================================
-- COMENTARIOS PARA DOCUMENTACIÓN
-- =====================================================

COMMENT ON TABLE projects IS 'Proyectos de análisis de propuestas técnicas';
COMMENT ON TABLE certificates IS 'Certificados individuales extraídos del PDF';
COMMENT ON TABLE professionals IS 'Profesionales con experiencia declarada';
COMMENT ON TABLE alerts IS 'Alertas de validación por profesional';
COMMENT ON TABLE verifications IS 'Verificaciones en portales externos';
COMMENT ON TABLE obra_data IS 'Datos de obras obtenidos de Infobras';
COMMENT ON TABLE processing_logs IS 'Log detallado del procesamiento';

COMMENT ON COLUMN professionals.dias_declarados IS 'Días según certificado';
COMMENT ON COLUMN professionals.dias_paralizados IS 'Días en meses paralizados';
COMMENT ON COLUMN professionals.dias_suspension IS 'Días en suspensiones formales';
COMMENT ON COLUMN professionals.dias_covid IS 'Días en periodo COVID';
COMMENT ON COLUMN professionals.dias_efectivos IS 'Días computables finales';
```

---

## 5. MÓDULOS DEL SISTEMA

### 5.1 Módulo 1: OCR + Segmentación

**Ubicación:** `backend/app/core/ocr/`

**Archivos:**
- `paddle_ocr.py` - Motor OCR con PaddleOCR
- `preprocessor.py` - Preprocesamiento de imágenes
- `segmentation.py` - Detección de certificados

**Funciones principales:**

```python
# paddle_ocr.py
class PaddleOCREngine:
    async def process_pdf(pdf_path: str) -> List[Tuple[int, str]]
    def preprocess_image(image) -> np.ndarray
    def deskew(image) -> np.ndarray
    def extract_text(ocr_result) -> str

# segmentation.py
class CertificateSegmenter:
    def segment(pages_with_text) -> List[dict]
    def is_certificate_start(text: str) -> bool
```

**Salida:**
```json
[
  {
    "page_start": 1,
    "page_end": 3,
    "text": "CERTIFICADO\n\nSE CERTIFICA QUE...",
    "confidence": 92.5
  },
  ...
]
```

### 5.2 Módulo 2: Extracción LLM

**Ubicación:** `backend/app/core/extraction/`

**Archivos:**
- `llm_client.py` - Cliente Ollama
- `prompts.py` - Templates de prompts
- `parser.py` - Parseo de respuestas

**Funciones principales:**

```python
class OllamaClient:
    async def extract_professional(cert_text: str) -> Dict
    async def extract_batch(certificates: List[str]) -> List[Dict]
    def build_extraction_prompt(text: str) -> str
    def parse_json_response(raw_text: str) -> Dict
```

**Prompt template:**
```
Extrae del siguiente certificado de experiencia:

- full_name: Nombre completo del profesional
- dni: Número de DNI
- cip: Número de colegiatura (CIP)
- position: Cargo desempeñado
- company_name: Nombre de la empresa
- company_ruc: RUC de la empresa
- start_date: Fecha de inicio (YYYY-MM-DD)
- end_date: Fecha de fin (YYYY-MM-DD o null si "a la fecha")
- obra_name: Nombre del proyecto/obra
- obra_cui: Código CUI del proyecto
- folio: Número de folio
- issuer_name: Nombre del firmante

Responde SOLO con JSON, sin explicaciones.

TEXTO:
{text}

JSON:
```

**Salida:**
```json
{
  "full_name": "Juan Pérez García",
  "dni": "12345678",
  "cip": "123456",
  "position": "Residente de Obra",
  "company_name": "Constructora XYZ S.A.C.",
  "company_ruc": "20123456789",
  "start_date": "2022-01-15",
  "end_date": "2023-06-30",
  "obra_name": "Mejoramiento Hospital Regional",
  "obra_cui": "2283129",
  "folio": "001-2023",
  "issuer_name": "Ing. María López"
}
```

### 5.3 Módulo 3: Scraping Infobras

**Ubicación:** `backend/app/core/scrapers/`

**Archivos:**
- `base.py` - Clase base para scrapers
- `infobras.py` - Scraper completo Infobras
- `sunat.py` - Scraper SUNAT
- `cip.py` - Scraper CIP

**Funciones principales (Infobras):**

```python
class InfoObrasCompleteScraper:
    async def scrape_complete_obra(cui, obra_name, fecha_inicio, fecha_fin) -> Dict
    
    # Sub-scrapers
    async def search_by_cui(page, cui)
    async def extract_ficha_publica(page) -> Dict
    async def extract_datos_ejecucion(page, obra_dir, cui) -> Dict
    async def extract_avances_mensuales(page, obra_dir, cui, fecha_inicio, fecha_fin) -> Dict
    async def extract_informes_control(page, obra_dir, cui) -> Dict
    
    # Helpers
    async def extract_informe_data(pdf_path) -> Dict
    def extract_suspensiones_from_informes(informes) -> List[Dict]
```

**Salida ejemplo:**
```json
{
  "cui": "2283129",
  "obra_name": "Mejoramiento Hospital Regional",
  "ficha_publica": {
    "fecha_contrato": "2022-01-10",
    "fecha_inicio": "2022-02-01",
    "fecha_fin": "2024-12-31",
    "monto_contratado": 15000000.00
  },
  "avances_mensuales": [
    {
      "mes": "2022-02-01",
      "mes_texto": "10.01 VAL FEB 2022",
      "estado": "Ejecutado",
      "avance_fisico": 5.2,
      "avance_financiero": 3.8
    },
    {
      "mes": "2022-03-01",
      "mes_texto": "10.02 VAL MAR 2022",
      "estado": "Paralizado",
      "avance_fisico": 5.2,
      "avance_financiero": 3.8
    }
  ],
  "informes_control": [
    {
      "numero": "001-2022",
      "fecha": "2022-04-15",
      "tiene_suspension": true,
      "fecha_inicio_suspension": "2022-03-01",
      "fecha_fin_suspension": "2022-03-31",
      "motivo_suspension": "Falta de materiales"
    }
  ],
  "downloads": {
    "acta_entrega": "/srv/infobras/data/downloads/15/documentos/Hospital_2283129/01_Acta_Entrega_2283129.pdf",
    "valorizaciones": [
      "/srv/.../02_Val_Feb_2022_2283129.doc",
      "/srv/.../02_Val_Mar_2022_2283129.doc"
    ],
    "informes": [
      "/srv/.../Informes_Control/Informe_001-2022_2283129.pdf"
    ]
  },
  "dias_computables": 487,
  "suspensiones": [
    {
      "fecha_inicio": "2022-03-01",
      "fecha_fin": "2022-03-31",
      "dias": 31,
      "motivo": "Falta de materiales",
      "fuente": "Informe 001-2022"
    }
  ],
  "alertas": [
    {
      "codigo": "CALC-02",
      "severidad": "high",
      "titulo": "Suspensiones formales detectadas",
      "descripcion": "1 suspensión documentada (31 días)"
    }
  ]
}
```

### 5.4 Módulo 4: Cálculo de Días Efectivos

**Ubicación:** `backend/app/core/calculation/`

**Archivos:**
- `calculator.py` - Motor de cálculo

**Función principal:**

```python
def calculate_dias_efectivos(
    fecha_inicio: datetime,
    fecha_fin: datetime,
    avances: List[Dict],
    suspensiones: List[Dict]
) -> Dict:
    """
    Calcula días efectivamente computables
    
    Returns:
        {
            'dias_declarados': int,
            'dias_paralizados': int,
            'dias_suspension': int,
            'dias_covid': int,
            'dias_efectivos': int,
            'meses_paralizados': [...],
            'suspensiones_aplicadas': [...],
            'alertas': [...]
        }
    """
```

**Algoritmo:**

```
1. dias_declarados = (fecha_fin - fecha_inicio).days + 1

2. Para cada mes en avances:
     Si estado == "Paralizado" o "Suspendido":
         dias_paralizados += dias_del_mes_en_rango

3. Para cada suspensión en informes:
     overlap = calcular_overlap(suspensión, rango_declarado)
     dias_suspension += overlap

4. COVID_PERIODO = (2020-03-15, 2021-12-31)
   overlap_covid = calcular_overlap(COVID_PERIODO, rango_declarado)
   dias_covid = overlap_covid

5. dias_efectivos = dias_declarados 
                    - dias_paralizados 
                    - dias_suspension 
                    - dias_covid
```

### 5.5 Módulo 5: Motor de Reglas

**Ubicación:** `backend/app/core/rules/`

**Archivos:**
- `engine.py` - Motor principal
- `validators.py` - Validadores específicos
- `alerts.py` - Generador de alertas

**Reglas implementadas:**

```python
class RulesEngine:
    def evaluate(professional: Dict, bases: Dict) -> List[Alert]
    
    # Reglas
    def check_end_after_emission() -> Alert  # ALT-01
    def check_covid_period() -> Alert        # ALT-02
    def check_antiquity() -> Alert           # ALT-03
    def check_company_date() -> Alert        # ALT-04
    def check_indefinite_end() -> Alert      # ALT-05
    def check_valid_position() -> Alert      # ALT-06
    def check_profession_match() -> Alert    # ALT-07
    def check_obra_type() -> Alert           # ALT-08
    def check_cip_vigente() -> Alert         # ALT-09
```

**Alertas generadas:**

| Código | Título | Severidad | Condición |
|--------|--------|-----------|-----------|
| ALT-01 | Fecha fin > emisión | high | `end_date > emission_date` |
| ALT-02 | Periodo COVID | medium | Overlap con 2020-03-15 a 2021-12-31 |
| ALT-03 | Antigüedad > 20 años | medium | `start_date < (now - 20 years)` |
| ALT-04 | Empresa posterior | high | `company_founded > start_date` |
| ALT-05 | Fecha indefinida | high | `has_indefinite_end AND !end_date` |
| ALT-06 | Cargo no válido | high | Cargo no en lista bases |
| ALT-07 | Profesión no coincide | critical | Profesión != requerida |
| ALT-08 | Tipo obra no coincide | high | Tipo obra != requerido |
| ALT-09 | CIP no vigente | high | CIP no vigente en periodo |
| CALC-01 | Meses paralizados | medium | Detectados meses paralizados |
| CALC-02 | Suspensiones | high | Suspensiones en informes |
| CALC-03 | Periodo COVID | medium | Overlap COVID detectado |

### 5.6 Módulo 6: Generación Excel

**Ubicación:** `backend/app/core/export/`

**Archivos:**
- `excel_generator.py` - Generador principal
- `templates.py` - Plantillas de hojas

**Estructura del Excel:**

```
InfoObras_Proyecto_15.xlsx
├─ Hoja 1: RESUMEN
│  - Total profesionales
│  - Cumplen / No cumplen
│  - Alertas críticas
│  - Gráficos resumen
│
├─ Hoja 2: DETALLE_PROFESIONALES
│  Columnas:
│  | # | Nombre | DNI | CIP | Cargo | Obra | CUI |
│  | Fecha Inicio | Fecha Fin | Días Declarados |
│  | Días Paralizados | Días Suspendidos | Días COVID |
│  | Días Efectivos | Días Mínimos | ¿Cumple? | Observaciones |
│
├─ Hoja 3: ALERTAS
│  | Profesional | Código | Severidad | Descripción | Detalles |
│
├─ Hoja 4: SUSPENSIONES
│  | CUI | Obra | Fecha Inicio | Fecha Fin | Días | Motivo | Fuente |
│
└─ Hoja 5: AVANCES_MENSUALES
   | CUI | Mes | Estado | Avance Físico % | Avance Financiero % |
```

**Formato visual:**
- Colores condicionales:
  - Verde: Cumple
  - Amarillo: Observación menor
  - Rojo: No cumple / Alerta crítica
- Filtros automáticos en todas las tablas
- Ancho de columnas ajustado
- Formato moneda para montos
- Formato fecha DD/MM/YYYY

### 5.7 Módulo 7: API REST

**Ubicación:** `backend/app/api/`

**Endpoints principales:**

```python
# Upload
POST /api/upload
    - Multipart: pdf, bases (opcional)
    - Response: {project_id, status}

# Status
GET /api/status/{project_id}
    - Response: {
        status: 'processing' | 'completed' | 'failed',
        progress: 0-100,
        stage: 'ocr' | 'extraction' | ...,
        message: str
      }

# Download Excel
GET /api/download/excel/{project_id}
    - Response: FileResponse (Excel)

# Download Docs
GET /api/download/docs/{project_id}
    - Response: StreamingResponse (ZIP)

# Download All
GET /api/download/all/{project_id}
    - Response: StreamingResponse (ZIP con Excel + docs)

# Delete
DELETE /api/project/{project_id}
    - Response: {message: 'deleted'}
```

---

## 6. PIPELINE DE PROCESAMIENTO

### 6.1 Flujo Completo

```python
# backend/app/core/pipeline.py

class ProcessingPipeline:
    """
    Pipeline completo de procesamiento
    """
    
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.db = get_db_session()
        
    async def run(self):
        """
        Ejecuta pipeline completo
        """
        try:
            # 1. Cargar proyecto
            project = self.db.query(Project).get(self.project_id)
            pdf_path = project.pdf_path
            
            # 2. OCR + Segmentación
            log_stage(self.project_id, 'ocr', 'started')
            certificates = await self.ocr_and_segment(pdf_path)
            log_stage(self.project_id, 'ocr', 'completed')
            
            # 3. Extracción LLM (paralelo)
            log_stage(self.project_id, 'extraction', 'started')
            professionals = await self.extract_all(certificates)
            log_stage(self.project_id, 'extraction', 'completed')
            
            # 4. Buscar CUI si falta
            log_stage(self.project_id, 'cui_search', 'started')
            await self.find_missing_cuis(professionals)
            log_stage(self.project_id, 'cui_search', 'completed')
            
            # 5. Scraping Infobras (paralelo)
            log_stage(self.project_id, 'scraping_infobras', 'started')
            await self.scrape_infobras_batch(professionals)
            log_stage(self.project_id, 'scraping_infobras', 'completed')
            
            # 6. Cálculo días efectivos
            log_stage(self.project_id, 'calculation', 'started')
            await self.calculate_effective_days(professionals)
            log_stage(self.project_id, 'calculation', 'completed')
            
            # 7. Motor de reglas
            log_stage(self.project_id, 'rules', 'started')
            alerts = await self.apply_rules(professionals)
            log_stage(self.project_id, 'rules', 'completed')
            
            # 8. Verificaciones externas
            log_stage(self.project_id, 'external_verifications', 'started')
            await self.verify_external(professionals)
            log_stage(self.project_id, 'external_verifications', 'completed')
            
            # 9. Generar Excel
            log_stage(self.project_id, 'excel', 'started')
            excel_path = await self.generate_excel()
            log_stage(self.project_id, 'excel', 'completed')
            
            # 10. Crear ZIP
            log_stage(self.project_id, 'zip', 'started')
            zip_path = await self.create_zip()
            log_stage(self.project_id, 'zip', 'completed')
            
            # 11. Actualizar proyecto
            project.status = 'completed'
            project.completed_at = datetime.now()
            self.db.commit()
            
            logger.success(f"✓ Pipeline completado: Proyecto {self.project_id}")
            
        except Exception as e:
            project.status = 'failed'
            self.db.commit()
            log_stage(self.project_id, 'pipeline', 'failed', str(e))
            logger.error(f"✗ Pipeline failed: {e}")
            raise
```

### 6.2 Procesamiento Paralelo

```python
async def extract_all(self, certificates: List[Certificate]) -> List[Professional]:
    """
    Extrae datos de todos los certificados en paralelo
    """
    llm_client = OllamaClient()
    
    # Crear tasks
    tasks = [
        llm_client.extract_professional(cert.ocr_text)
        for cert in certificates
    ]
    
    # Ejecutar en paralelo (máx 10 simultáneos)
    results = []
    for i in range(0, len(tasks), 10):
        batch = tasks[i:i+10]
        batch_results = await asyncio.gather(*batch, return_exceptions=True)
        results.extend(batch_results)
    
    # Guardar en BD
    professionals = []
    for cert, data in zip(certificates, results):
        if isinstance(data, Exception):
            logger.error(f"Error extracting cert {cert.id}: {data}")
            continue
        
        prof = Professional(
            certificate_id=cert.id,
            **data,
            raw_extraction=data
        )
        self.db.add(prof)
        professionals.append(prof)
    
    self.db.commit()
    return professionals
```

---

## 7. APIS Y ENDPOINTS

### 7.1 Endpoint: Upload

```python
@router.post("/upload")
async def upload_proposal(
    pdf: UploadFile,
    bases: UploadFile = None,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """
    Sube PDF de propuesta técnica
    """
    # Validar archivo
    if not pdf.filename.endswith('.pdf'):
        raise HTTPException(400, "Solo archivos PDF")
    
    if pdf.size > 500 * 1024 * 1024:  # 500MB
        raise HTTPException(400, "Archivo muy grande (máx 500MB)")
    
    # Crear proyecto
    project = Project(
        name=pdf.filename,
        pdf_filename=pdf.filename,
        status='uploaded'
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    
    # Guardar PDF
    upload_dir = f"/srv/infobras/data/uploads/{project.id}"
    os.makedirs(upload_dir, exist_ok=True)
    
    pdf_path = os.path.join(upload_dir, pdf.filename)
    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(pdf.file, buffer)
    
    project.pdf_path = pdf_path
    
    # Guardar bases (opcional)
    if bases:
        bases_path = os.path.join(upload_dir, bases.filename)
        with open(bases_path, "wb") as buffer:
            shutil.copyfileobj(bases.file, buffer)
        project.bases_path = bases_path
    
    db.commit()
    
    # Procesar en background
    background_tasks.add_task(
        process_pipeline,
        project.id
    )
    
    return {
        "project_id": project.id,
        "filename": pdf.filename,
        "status": "processing"
    }
```

### 7.2 Endpoint: Status (con WebSocket)

```python
@router.get("/status/{project_id}")
async def get_status(
    project_id: int,
    db: Session = Depends(get_db)
):
    """
    Estado del procesamiento
    """
    project = db.query(Project).get(project_id)
    
    if not project:
        raise HTTPException(404, "Project not found")
    
    # Obtener último log
    latest_log = db.query(ProcessingLog)\
        .filter_by(project_id=project_id)\
        .order_by(ProcessingLog.created_at.desc())\
        .first()
    
    # Calcular progreso
    progress = get_project_progress(db, project_id)
    
    return {
        "project_id": project.id,
        "status": project.status,
        "progress": progress,
        "stage": latest_log.stage if latest_log else None,
        "message": latest_log.message if latest_log else None,
        "uploaded_at": project.uploaded_at,
        "completed_at": project.completed_at
    }

# WebSocket para updates en tiempo real
@router.websocket("/ws/status/{project_id}")
async def websocket_status(
    websocket: WebSocket,
    project_id: int,
    db: Session = Depends(get_db)
):
    await websocket.accept()
    
    while True:
        # Enviar status cada 2 segundos
        status = await get_status(project_id, db)
        await websocket.send_json(status)
        
        # Si completado o fallido, cerrar
        if status['status'] in ['completed', 'failed']:
            break
        
        await asyncio.sleep(2)
    
    await websocket.close()
```

---

## 8. ESTRUCTURA DE ARCHIVOS

```
infobras-analyzer/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes/
│   │   │   │   ├── upload.py
│   │   │   │   ├── process.py
│   │   │   │   ├── download.py
│   │   │   │   └── health.py
│   │   │   └── dependencies.py
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   │
│   │   │   ├── ocr/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── paddle_ocr.py
│   │   │   │   ├── preprocessor.py
│   │   │   │   └── segmentation.py
│   │   │   │
│   │   │   ├── extraction/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── llm_client.py
│   │   │   │   ├── prompts.py
│   │   │   │   └── parser.py
│   │   │   │
│   │   │   ├── scrapers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   ├── infobras.py
│   │   │   │   ├── sunat.py
│   │   │   │   └── cip.py
│   │   │   │
│   │   │   ├── calculation/
│   │   │   │   ├── __init__.py
│   │   │   │   └── calculator.py
│   │   │   │
│   │   │   ├── rules/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── engine.py
│   │   │   │   ├── validators.py
│   │   │   │   └── alerts.py
│   │   │   │
│   │   │   ├── export/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── excel_generator.py
│   │   │   │   └── templates.py
│   │   │   │
│   │   │   └── pipeline.py
│   │   │
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── session.py
│   │   │   ├── models.py
│   │   │   └── crud.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── project.py
│   │   │   ├── certificate.py
│   │   │   ├── professional.py
│   │   │   └── alert.py
│   │   │
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── logger.py
│   │       └── helpers.py
│   │
│   ├── tests/
│   ├── alembic/
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx
│   │   │   ├── upload/
│   │   │   ├── process/[id]/
│   │   │   └── results/[id]/
│   │   │
│   │   ├── components/
│   │   │   ├── ui/
│   │   │   ├── FileUploader.tsx
│   │   │   ├── ProgressDashboard.tsx
│   │   │   ├── AlertsTable.tsx
│   │   │   └── ResultsView.tsx
│   │   │
│   │   ├── lib/
│   │   │   ├── api.ts
│   │   │   └── utils.ts
│   │   │
│   │   └── types/
│   │       └── index.ts
│   │
│   ├── public/
│   ├── package.json
│   └── next.config.js
│
├── data/
│   ├── uploads/
│   ├── processed/
│   └── downloads/
│
├── docker-compose.yml
├── .env
└── README.md
```

---

## 9. PLAN DE DESARROLLO 7 SEMANAS

### Semana 1: OCR + Segmentación + Base de Datos

**Objetivo:** Sistema de OCR funcionando + BD poblada

**Tareas:**

| Día | Tarea | Horas | Entregable |
|-----|-------|-------|------------|
| L | Setup proyecto + Docker + PostgreSQL | 4h | BD levantada |
| L | Esquema SQL completo | 4h | Tablas creadas |
| M | PaddleOCR engine | 6h | OCR funcional |
| M | Image preprocessing | 2h | Preprocesado |
| X | Segmentador de certificados | 6h | Detección certs |
| X | Testing con PDF real | 2h | 45 certs detectados |
| J | Guardar en BD | 4h | Certs en tabla |
| J | API upload endpoint | 4h | POST /upload |
| V | Testing integración | 6h | PDF → BD |
| V | Docs semana 1 | 2h | Documentación |

**Entregable:** PDF completo OCR + 45 certificados en BD

---

### Semana 2: Extracción LLM + Motor de Cálculo

**Objetivo:** Datos estructurados extraídos + cálculo de días

**Tareas:**

| Día | Tarea | Horas | Entregable |
|-----|-------|-------|------------|
| L | Ollama setup + modelo | 4h | LLM funcionando |
| L | LLM client básico | 4h | Cliente Python |
| M | Prompt engineering | 6h | Prompt óptimo |
| M | Parser JSON | 2h | Parseo robusto |
| X | Extracción batch paralelo | 6h | 45 certs en paralelo |
| X | Guardar professionals tabla | 2h | Data en BD |
| J | Calculator de días | 6h | Algoritmo completo |
| J | Testing cálculo | 2h | Casos de prueba |
| V | Integración pipeline | 6h | OCR → LLM → BD |
| V | Testing E2E semana 2 | 2h | Pipeline funcional |

**Entregable:** 45 profesionales extraídos + días calculados

---

### Semana 3: Scraping Infobras (Parte 1)

**Objetivo:** Scraper de Infobras funcional

**Tareas:**

| Día | Tarea | Horas | Entregable |
|-----|-------|-------|------------|
| L | Playwright setup | 2h | Navegador |
| L | Análisis HTML Infobras | 4h | Selectores |
| L | Scraper: Búsqueda CUI | 2h | Búsqueda func. |
| M | Scraper: Ficha pública | 4h | Datos generales |
| M | Scraper: Datos ejecución | 4h | Fechas + estado |
| X | Scraper: Avances mensuales | 6h | Tabla avances |
| X | Descarga valorizaciones | 2h | PDFs guardados |
| J | Testing scraper básico | 4h | 5 CUIs reales |
| J | Manejo de errores | 4h | Retry logic |
| V | Integración BD | 6h | obra_data tabla |
| V | Testing E2E | 2h | Pipeline + scraping |

**Entregable:** Scraper Infobras básico + datos en BD

---

### Semana 4: Scraping Infobras (Parte 2) + SUNAT/CIP

**Objetivo:** Scraper completo + verificaciones externas

**Tareas:**

| Día | Tarea | Horas | Entregable |
|-----|-------|-------|------------|
| L | Scraper: Informes control | 6h | Descarga informes |
| L | OCR informes + LLM | 2h | Suspensiones |
| M | Extracción suspensiones | 4h | Dates + motivos |
| M | Integración cálculo días | 4h | Descuentos automáticos |
| X | Scraper SUNAT | 6h | Fecha constitución |
| X | Scraper CIP | 2h | Vigencia |
| J | Manejo CAPTCHA | 4h | Fallback manual |
| J | Testing scrapers externos | 4h | 10 RUCs + CIPs |
| V | Integración verifications | 6h | Tabla completa |
| V | Testing completo | 2h | Todo integrado |

**Entregable:** Todos los scrapers + verificaciones en BD

---

### Semana 5: Motor de Reglas + Excel

**Objetivo:** Alertas generadas + Excel funcional

**Tareas:**

| Día | Tarea | Horas | Entregable |
|-----|-------|-------|------------|
| L | Rules engine estructura | 4h | Clase base |
| L | 9 reglas de alerta | 4h | Validadores |
| M | Generador alertas | 4h | Alerts en BD |
| M | Testing reglas | 4h | Casos de prueba |
| X | Excel generator | 6h | openpyxl setup |
| X | Hoja: Resumen | 2h | Primera hoja |
| J | Hoja: Detalle profesionales | 4h | Tabla principal |
| J | Hoja: Alertas | 2h | Tabla alertas |
| J | Hoja: Suspensiones | 2h | Tabla susp. |
| V | Formato + colores | 4h | Formato visual |
| V | Testing Excel completo | 4h | Validación manual |

**Entregable:** Excel completo con todas las hojas

---

### Semana 6: Frontend + API + ZIP

**Objetivo:** Interfaz web + descarga completa

**Tareas:**

| Día | Tarea | Horas | Entregable |
|-----|-------|-------|------------|
| L | Next.js setup | 2h | Frontend base |
| L | API endpoints completos | 6h | REST API |
| M | Upload interface | 4h | Componente upload |
| M | Progress dashboard | 4h | Real-time progress |
| X | WebSocket status | 4h | Updates live |
| X | Results view | 4h | Tabla resultados |
| J | Download buttons | 2h | Excel + ZIP |
| J | ZIP generator | 4h | Documentos ZIP |
| J | Testing descargas | 2h | Flujo completo |
| V | UI/UX polish | 6h | Diseño final |
| V | Testing E2E frontend | 2h | Todo funcional |

**Entregable:** Web completa funcional

---

### Semana 7: Testing + Deploy + Documentación

**Objetivo:** Sistema en producción

**Tareas:**

| Día | Tarea | Horas | Entregable |
|-----|-------|-------|------------|
| L | Testing con PDF real cliente | 8h | Casos reales |
| M | Fixes de bugs | 8h | Correcciones |
| X | Nginx config | 2h | Reverse proxy |
| X | Deploy en servidor | 4h | Producción |
| X | Testing en servidor | 2h | Validación |
| J | Manual de usuario | 6h | Documentación |
| J | Scripts de mantenimiento | 2h | Backup, etc. |
| V | Capacitación cliente | 2h | Training |
| V | Entrega final | 2h | Handover |
| V | Buffer contingencias | 4h | Tiempo extra |

**Entregable:** Sistema completo en producción

---

## 10. CRITERIOS DE VALIDACIÓN

### 10.1 Métricas de Éxito

| Métrica | Meta | Cómo se mide |
|---------|------|--------------|
| **OCR Accuracy** | ≥ 90% | Confianza promedio PaddleOCR |
| **Segmentación** | 100% | Todos los certificados detectados |
| **Extracción LLM** | ≥ 95% | Campos completos extraídos |
| **Scraping Infobras** | ≥ 85% | CUIs encontrados y descargados |
| **Cálculo Días** | 100% | Sin errores matemáticos |
| **Alertas** | ≥ 95% | Alertas correctas vs manual |
| **Tiempo Total** | < 30 min | 45 certificados procesados |
| **Excel Correcto** | 100% | Abre sin errores, datos OK |

### 10.2 Casos de Prueba

**Caso 1: PDF completo real**
- Input: PDF 2,300 páginas
- Esperado: 45 certificados, Excel completo, ZIP documentos
- Tiempo: < 30 minutos

**Caso 2: Certificado con suspensiones**
- Input: Certificado con periodo en obra paralizada
- Esperado: Alerta CALC-01, días descontados correctamente

**Caso 3: Fecha indefinida**
- Input: Certificado con "a la fecha" sin fecha emisión
- Esperado: Alerta ALT-05

**Caso 4: CUI no existe en Infobras**
- Input: CUI inventado
- Esperado: Error manejado, continúa con otros

**Caso 5: Multiple alertas**
- Input: Certificado con varios problemas
- Esperado: Todas las alertas generadas

---

## 11. RIESGOS Y MITIGACIÓN

### 11.1 Riesgos Técnicos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| **Infobras cambia estructura** | Media | Alto | Scraper resiliente + cache + fallback manual |
| **OCR falla en docs deteriorados** | Media | Alto | Preprocesamiento agresivo + Tesseract fallback |
| **SUNAT CAPTCHA** | Alta | Medio | Fallback manual asistido |
| **LLM extrae mal** | Baja | Alto | Validación post-extracción + corrección manual |
| **Performance lento** | Media | Medio | Procesamiento paralelo + cache |
| **Disco lleno** | Baja | Alto | Limpieza automática + monitoreo |

### 11.2 Riesgos de Proyecto

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| **Cliente no tiene PDFs de ejemplo** | Baja | Alto | Solicitar en Semana 1 |
| **Servidor sin GPU** | Media | Medio | CPU fallback (más lento) |
| **Cambio de alcance** | Media | Alto | Scope freeze después de Semana 2 |
| **Bugs en producción** | Media | Medio | Testing exhaustivo Semana 7 |

---

## 🎯 CONCLUSIÓN

Este documento define la arquitectura completa, esquemas de base de datos, módulos, y plan de desarrollo de 7 semanas para InfoObras Analyzer.

**Próximos pasos:**
1. Aprobación de arquitectura y pricing
2. Setup de infraestructura (Semana 1, Día 1)
3. Inicio de desarrollo según cronograma

**Entregables finales:**
- Sistema web 100% local funcional
- Excel con evaluación completa
- Documentos organizados descargables
- Manual de usuario
- Capacitación de 2 horas

---

**Versión:** 1.0  
**Fecha:** Marzo 2026  
**Autor:** Rafael Ramos Huamaní