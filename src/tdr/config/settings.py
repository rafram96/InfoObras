import os
from pathlib import Path

# Asegurar que .env este cargado antes de leer os.getenv()
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Motor OCR ─────────────────────────────────────────────────────────────────
MOTOR_OCR_REPO    = Path(r"D:\proyectos\motor-OCR")
MOTOR_OCR_TIMEOUT = 7200  # segundos

# ── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL      = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# ── Qwen 14B (extracción semántica) ─────────────────────────────────────────
QWEN_OLLAMA_BASE_URL = f"{OLLAMA_BASE_URL}/v1"
QWEN_OLLAMA_API_KEY  = "ollama"
QWEN_MODEL           = os.getenv("QWEN_MODEL", "qwen2.5:14b")
QWEN_MAX_TOKENS      = int(os.getenv("QWEN_MAX_TOKENS", "8192"))
QWEN_TIMEOUT         = int(os.getenv("QWEN_TIMEOUT", "300"))
# Ventana de contexto (input+output). Ollama default es 4096 tokens (~12k chars),
# lo que TRUNCA prompts largos silenciosamente y causa alucinaciones ("Gerente de
# Proyecto" en vez de "GERENTE DE CONTRATO", tipo_obra inventado, etc.).
#
# Qwen 2.5:14b soporta 128k tokens nativos. Recomendaciones por VRAM:
#   - 16GB VRAM (Quadro RTX 5000, etc.): 12288 (~36k chars) → default seguro
#   - 24GB+ VRAM: 16384-32768 (cubre TDRs gigantes sin truncar)
#   - Si hay OOM (out of memory en GPU): bajar a 8192
# Override via env: QWEN_NUM_CTX=16384 (por si quieres subir sin tocar codigo)
QWEN_NUM_CTX         = int(os.getenv("QWEN_NUM_CTX", "12288"))

# ── Qwen VL (lectura visual de tablas) ──────────────────────────────────────
QWEN_VL_MODEL   = os.getenv("QWEN_VL_MODEL", "qwen2.5vl:7b")
QWEN_VL_TIMEOUT = int(os.getenv("QWEN_VL_TIMEOUT", "120"))   # segundos por imagen

# ── Scorer ────────────────────────────────────────────────────────────────────
SCORER_MIN_SCORE  = 3.0   # score mínimo para considerar una página relevante
SCORER_MAX_GAP    = 3     # páginas de gap toleradas dentro de un bloque
SCORER_CONTEXT    = 1     # páginas de contexto antes/después de cada bloque

# ── Tablas (pipeline híbrido) ────────────────────────────────────────────────
TABLE_DETECT_THRESHOLD    = 0.4   # score mínimo heurística para pre-filtro
TABLE_DOCLING_DPI         = 150   # DPI para imágenes (200 generaba payloads de 21MB, fallaba en batches)
TABLE_VALIDATOR_MIN_SCORE = 0.5   # score mínimo para aceptar tabla de Qwen VL
TABLE_VL_MAX_BATCH        = 3     # máximo imágenes por llamada a Qwen VL cross-page
TABLE_VL_MAX_GROUP        = 2     # máximo páginas consecutivas por grupo VL (evita fusionar tablas distintas)
TABLE_VL_MAX_PX           = 640   # máximo px en el lado más largo antes de enviar a VL
USE_DOCLING               = False # False = saltar Docling, usar heurística + Qwen VL directo

# ── Paths de salida ───────────────────────────────────────────────────────────
OUTPUT_DIR = Path("output")