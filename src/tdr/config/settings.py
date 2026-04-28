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

# ── LLM principal (extraccion semantica + vision en TDR experimental) ───────
# Nota: las variables se llaman QWEN_* por historia. El runtime solo pasa el
# nombre al backend Ollama, asi que cualquier modelo compatible funciona:
# qwen2.5:14b, gemma4:26b, gemma4:e4b, etc. Override 100% via .env.
QWEN_OLLAMA_BASE_URL = f"{OLLAMA_BASE_URL}/v1"
QWEN_OLLAMA_API_KEY  = "ollama"
QWEN_MODEL           = os.getenv("QWEN_MODEL", "qwen2.5:14b")
QWEN_MAX_TOKENS      = int(os.getenv("QWEN_MAX_TOKENS", "8192"))
QWEN_TIMEOUT         = int(os.getenv("QWEN_TIMEOUT", "300"))

# Ventana de contexto (input+output). Ollama default es 4096 (TRUNCA prompts).
#
# Recomendaciones por modelo / VRAM:
#   qwen2.5:14b en 16GB → 12288 (default historico)
#   qwen2.5:14b custom 16k → 16384
#   gemma4:26b en 16GB → 32768 (Gemma 4 26B soporta 256k nativo, pero KV cache
#                               crece linealmente con num_ctx; 32k es el sweet
#                               spot que entra en VRAM con margen para output)
#   gemma4:e4b en 16GB → 32768 (modelo chico, mas margen)
# Override: QWEN_NUM_CTX=N en .env
QWEN_NUM_CTX         = int(os.getenv("QWEN_NUM_CTX", "12288"))

# Sampling. Qwen 2.5 fue entrenado para temperature=0 (deterministico).
# Gemma 4 fue entrenado con temp=1.0, top_p=0.95, top_k=64. Para extraccion
# estructurada (JSON) un compromiso es 0.3 / 0.9 / 40 — suficientemente
# bajo para reproducibilidad, alto para que Gemma no pierda calidad.
# Override por modelo via .env si hace falta.
QWEN_TEMPERATURE     = float(os.getenv("QWEN_TEMPERATURE", "0"))
QWEN_TOP_P           = float(os.getenv("QWEN_TOP_P", "1.0"))
QWEN_TOP_K           = int(os.getenv("QWEN_TOP_K", "0"))  # 0 = disabled

# Mantener el modelo cargado en VRAM entre requests para evitar cold starts.
# Especialmente importante con Gemma 4 (mas grande, carga toma ~30s).
QWEN_KEEP_ALIVE      = os.getenv("QWEN_KEEP_ALIVE", "10m")

# ── Modelo VL (vision para tablas en B.1/B.2 si USE_VL_TDR_EXTRACTION=true) ─
# Default qwen2.5vl:7b; con Gemma 4 se puede unificar al mismo modelo que
# QWEN_MODEL ya que gemma4:26b/e4b son nativamente multimodales.
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