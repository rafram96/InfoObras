"""
Worker subprocess para extraccion estructurada TDR con Qwen-VL.

Se ejecuta como proceso independiente para aislar el consumo de VRAM:
al terminar, el OS libera todos los recursos. Luego el proceso padre
puede cargar Qwen 14B sin contencion.

Invocado desde extraer_bases() en pipeline.py:

    python vl_extract_tdr_worker.py <project_root> <input_json> <output_json>

input_json (dict):
  {
    "pdf_path": "ruta/al/pdf",
    "paginas_b1": [2, 3, 4],
    "paginas_b2": [5, 6, 7, 8, 9],
    "settings": {...}  # overrides opcionales
  }

output_json (dict):
  {
    "b1": [{"numero": 1, "cargo": "...", "profesiones": [...]}, ...],
    "b2": [{"numero": 1, "cargo": "...", "tiempo_meses": 24,
            "cargos_similares": [...], "tipo_obra": "...",
            "descripcion": "..."}, ...],
    "diagnostico": {
      "paginas_b1": [...],
      "paginas_b2": [...],
      "error": null
    }
  }
"""
from __future__ import annotations
import sys
import json
import logging

# ── Setup path e imports ──────────────────────────────────────────────────────
if len(sys.argv) != 4:
    print("Usage: vl_extract_tdr_worker.py <project_root> <input_json> <output_json>")
    sys.exit(1)

project_root = sys.argv[1]
input_json_path = sys.argv[2]
output_json_path = sys.argv[3]

sys.path.insert(0, project_root)

with open(input_json_path, "r", encoding="utf-8") as f:
    datos = json.load(f)

pdf_path = datos["pdf_path"]
paginas_b1: list[int] = datos.get("paginas_b1", [])
paginas_b2: list[int] = datos.get("paginas_b2", [])
settings_override: dict = datos.get("settings", {})

# Aplicar settings override antes de imports
import src.tdr.config.settings as _cfg
for k, v in settings_override.items():
    if hasattr(_cfg, k):
        setattr(_cfg, k, v)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vl_extract_tdr_worker")

from src.tdr.tables.image_utils import extraer_multiples_paginas
from src.tdr.tables.vl_extractor import extraer_b1_visual, extraer_b2_visual

logger.info(
    f"Iniciando: B.1 paginas={paginas_b1}, B.2 paginas={paginas_b2}"
)


def _extraer_imagenes(pdf: str, paginas: list[int]) -> list:
    if not paginas:
        return []
    try:
        pi_list = extraer_multiples_paginas(pdf, sorted(set(paginas)))
        return [pi.imagen for pi in pi_list]
    except Exception as e:
        logger.error(f"Error extrayendo imagenes {paginas}: {e}")
        return []


# ── Extraccion B.1 ────────────────────────────────────────────────────────────
filas_b1 = []
error_b1 = None
if paginas_b1:
    try:
        imagenes_b1 = _extraer_imagenes(pdf_path, paginas_b1)
        if imagenes_b1:
            logger.info(f"B.1: llamando VL con {len(imagenes_b1)} imagen(es)")
            filas_b1 = extraer_b1_visual(imagenes_b1)
            logger.info(f"B.1: {len(filas_b1)} filas extraidas")
        else:
            error_b1 = "Sin imagenes extraidas"
    except Exception as e:
        logger.exception(f"Error en extraccion B.1: {e}")
        error_b1 = str(e)


# ── Extraccion B.2 ────────────────────────────────────────────────────────────
filas_b2 = []
error_b2 = None
if paginas_b2:
    try:
        imagenes_b2 = _extraer_imagenes(pdf_path, paginas_b2)
        if imagenes_b2:
            logger.info(f"B.2: llamando VL con {len(imagenes_b2)} imagen(es)")
            filas_b2 = extraer_b2_visual(imagenes_b2)
            logger.info(f"B.2: {len(filas_b2)} filas extraidas")
        else:
            error_b2 = "Sin imagenes extraidas"
    except Exception as e:
        logger.exception(f"Error en extraccion B.2: {e}")
        error_b2 = str(e)


# ── Guardar output ────────────────────────────────────────────────────────────
resultado = {
    "b1": filas_b1,
    "b2": filas_b2,
    "diagnostico": {
        "paginas_b1": paginas_b1,
        "paginas_b2": paginas_b2,
        "error_b1": error_b1,
        "error_b2": error_b2,
        "filas_b1_count": len(filas_b1),
        "filas_b2_count": len(filas_b2),
    },
}
with open(output_json_path, "w", encoding="utf-8") as f:
    json.dump(resultado, f, ensure_ascii=False)

logger.info(
    f"Completado: B.1={len(filas_b1)} filas, B.2={len(filas_b2)} filas"
)


# ── Liberar VL + pre-cargar Qwen 14B (copiado de qwen_vl_worker) ─────────────
import time
import requests as _req

_ollama_url = settings_override.get("OLLAMA_BASE_URL", _cfg.OLLAMA_BASE_URL)
_vl_model = settings_override.get("QWEN_VL_MODEL", _cfg.QWEN_VL_MODEL)
_qwen_model = settings_override.get("QWEN_MODEL", _cfg.QWEN_MODEL)
_poll_timeout = 120
_poll_interval = 2.0

# Descargar VL
try:
    _req.post(
        f"{_ollama_url}/api/generate",
        json={"model": _vl_model, "keep_alive": 0},
        timeout=10,
    )
    logger.info(f"Solicitud de descarga VL enviada: {_vl_model}")
except Exception as e:
    logger.warning(f"No se pudo solicitar descarga VL: {e}")

# Polling hasta que VL este fuera de VRAM
transcurrido = 0.0
while transcurrido < _poll_timeout:
    time.sleep(_poll_interval)
    transcurrido += _poll_interval
    try:
        resp = _req.get(f"{_ollama_url}/api/ps", timeout=5)
        activos = [m.get("name", "") for m in resp.json().get("models", [])]
        if not any(_vl_model in m for m in activos):
            logger.info(
                f"VL descargado ({transcurrido:.0f}s) — listo para 14B"
            )
            break
    except Exception:
        continue

time.sleep(5)  # pausa CUDA

# Pre-cargar Qwen 14B en GPU
for intento in range(1, 4):
    try:
        logger.info(f"Pre-cargando {_qwen_model} en GPU (intento {intento}/3)...")
        _req.post(
            f"{_ollama_url}/api/generate",
            json={
                "model": _qwen_model,
                "prompt": "",
                "keep_alive": "10m",
                "options": {"num_gpu": 99},
            },
            timeout=120,
        )
        # Verificar que este en VRAM
        time.sleep(3)
        resp = _req.get(f"{_ollama_url}/api/ps", timeout=5)
        en_gpu = False
        for m in resp.json().get("models", []):
            if _qwen_model in m.get("name", ""):
                size_total = m.get("size", 0)
                size_vram = m.get("size_vram", 0)
                if size_vram > 0 and size_total > 0 and (size_vram / size_total) > 0.9:
                    logger.info(
                        f"{_qwen_model} en GPU: {size_vram/1e9:.1f}GB/{size_total/1e9:.1f}GB"
                    )
                    en_gpu = True
                break
        if en_gpu:
            break
        logger.warning(f"{_qwen_model} no se cargo en GPU — descargando y reintentando")
        _req.post(
            f"{_ollama_url}/api/generate",
            json={"model": _qwen_model, "keep_alive": 0},
            timeout=10,
        )
        time.sleep(5)
    except Exception as e:
        logger.warning(f"Intento {intento}: error pre-cargando {_qwen_model}: {e}")
        time.sleep(5)

logger.info("Worker VL-TDR finalizado.")
