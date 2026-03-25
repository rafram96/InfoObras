"""
Script de prueba de extracción.
Procesa uno o más profesionales y muestra el resultado en consola.

Uso:
    python run_extraction.py                    # procesa el primero
    python run_extraction.py --index 2          # procesa el segundo
    python run_extraction.py --all              # procesa todos
    python run_extraction.py --parse-only       # solo parseo, sin LLM
"""
import argparse
import json
import sys
from pathlib import Path

# Agrega el directorio raíz al path para que funcionen los imports de src/
sys.path.insert(0, str(Path(__file__).parent))

from src.extraction.md_parser import parse_professional_blocks
from src.extraction.llm_extractor import extract_block

# Archivos de prueba en data/
DATA_DIR = Path(__file__).parent / "data"


def find_data_files() -> tuple[Path, Path]:
    """Busca automáticamente los archivos *_profesionales_*.md y *_texto_*.md en data/."""
    prof_files = list(DATA_DIR.glob("*_profesionales_*.md"))
    texto_files = list(DATA_DIR.glob("*_texto_*.md"))

    if not prof_files:
        raise FileNotFoundError(f"No se encontró *_profesionales_*.md en {DATA_DIR}")
    if not texto_files:
        raise FileNotFoundError(f"No se encontró *_texto_*.md en {DATA_DIR}")

    return prof_files[0], texto_files[0]


def print_block_summary(block) -> None:
    """Imprime resumen del bloque sin llamar al LLM."""
    print(f"\n{'='*60}", flush=True)
    print(f"  #{block.index} — {block.cargo}", end="")
    print(f"  {block.numero}" if block.numero else "")
    print(f"  Bloques de páginas: {block.page_ranges}")
    total = sum(e - s + 1 for s, e in block.page_ranges)
    print(f"  Total páginas: {total}")
    print(f"  Texto extraído: {len(block.full_text):,} caracteres")
    print()
    # Muestra los primeros 500 chars del texto
    preview = block.full_text[:500].replace("\n", " ")
    print(f"  Preview: {preview}...")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=1, help="Índice del profesional (1-based)")
    parser.add_argument("--all", action="store_true", help="Procesa todos los profesionales")
    parser.add_argument("--parse-only", action="store_true", help="Solo parsea sin llamar al LLM")
    parser.add_argument("--output", type=str, help="Guarda resultado en este archivo JSON")
    args = parser.parse_args()

    # Encuentra archivos
    prof_path, texto_path = find_data_files()
    print(f"Profesionales: {prof_path.name}")
    print(f"Texto:         {texto_path.name}")

    # Parsea bloques
    print("\nParsando archivos...", end=" ", flush=True)
    blocks = parse_professional_blocks(prof_path, texto_path)
    print(f"{len(blocks)} profesionales encontrados.")

    # Selecciona qué procesar
    if args.all:
        targets = blocks
    else:
        idx = args.index - 1
        if idx < 0 or idx >= len(blocks):
            print(f"Error: índice {args.index} fuera de rango (1–{len(blocks)})")
            sys.exit(1)
        targets = [blocks[idx]]

    # Modo parse-only: solo muestra resumen
    if args.parse_only:
        for block in targets:
            print_block_summary(block)
        return

    # Modo LLM: extrae datos
    results = []
    for block in targets:
        print(f"\n{'-'*60}")
        label = f"#{block.index} {block.cargo}"
        if block.numero:
            label += f" {block.numero}"
        print(f"Extrayendo: {label}")
        print("Llamando al LLM (Paso 2 — profesional)...", end=" ", flush=True)

        try:
            result = extract_block(block)
            print("OK")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            results.append(result)
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"error": str(e), "cargo": block.cargo})

    # Guarda si se pidió
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nResultado guardado en: {out_path}")


if __name__ == "__main__":
    main()
