"""
Script de evaluacion TDR — mide la precision del pipeline vs un golden set anotado.

Uso:
    python tests/evaluar_tdr.py tests/golden/rtm_huancavelica.json data/ocr_outputs/{job_id}/resultado.json

O apuntando directo a un resultado de la BD:
    python tests/evaluar_tdr.py tests/golden/rtm_huancavelica.json --job-id=abc123

Produce un reporte por stdout + JSON con metricas:
- precision / recall / F1 por campo (profesiones, cargos_similares, etc.)
- conteo de cargos correctos, faltantes, extras
- alucinaciones (items en output que no estan en golden)
- rankings por cargo (que cargos van peor)
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any
import unicodedata


# ── Normalizacion de strings ──────────────────────────────────────────────────

def _normalizar(txt: str) -> str:
    """Minusculas + sin tildes + trim + colapsar espacios."""
    if not isinstance(txt, str):
        return ""
    nfd = unicodedata.normalize("NFD", txt.lower())
    sin_tilde = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return " ".join(sin_tilde.split())


def _set_normalizado(lista: list) -> set[str]:
    if not isinstance(lista, list):
        return set()
    return {_normalizar(x) for x in lista if isinstance(x, str) and x.strip()}


# ── Metricas por item ─────────────────────────────────────────────────────────

def _precision_recall_sets(extraido: set, esperado: set) -> dict:
    """Calcula precision/recall/F1 comparando 2 sets."""
    tp = len(extraido & esperado)
    fp = len(extraido - esperado)  # en extraido pero no en esperado (alucinacion)
    fn = len(esperado - extraido)  # en esperado pero no en extraido (faltante)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0 if not esperado else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0 if not extraido else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {
        "precision": round(prec, 3),
        "recall": round(rec, 3),
        "f1": round(f1, 3),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "faltantes": sorted(esperado - extraido),
        "extras": sorted(extraido - extraido),
        "alucinaciones": sorted(extraido - esperado),
    }


def _comparar_cargo(extraido: dict, esperado: dict) -> dict:
    """Compara un cargo individual y retorna metricas por campo."""
    metricas = {
        "cargo": esperado.get("cargo"),
        "numero_fila": esperado.get("numero_fila"),
    }

    # Profesiones
    metricas["profesiones"] = _precision_recall_sets(
        _set_normalizado(extraido.get("profesiones_aceptadas") or []),
        _set_normalizado(esperado.get("profesiones_aceptadas") or []),
    )

    # Cargos similares validos
    exp_ext = (extraido.get("experiencia_minima") or {}).get("cargos_similares_validos") or []
    exp_esp = (esperado.get("experiencia_minima") or {}).get("cargos_similares_validos") or []
    metricas["cargos_similares"] = _precision_recall_sets(
        _set_normalizado(exp_ext),
        _set_normalizado(exp_esp),
    )

    # Tiempo de experiencia (match exacto)
    t_ext = (extraido.get("experiencia_minima") or {}).get("cantidad")
    t_esp = (esperado.get("experiencia_minima") or {}).get("cantidad")
    metricas["tiempo_meses_correcto"] = (t_ext == t_esp)
    metricas["tiempo_meses"] = {"extraido": t_ext, "esperado": t_esp}

    # Tipo de obra (match normalizado por substring)
    obr_ext = _normalizar(extraido.get("tipo_obra_valido") or "")
    obr_esp = _normalizar(esperado.get("tipo_obra_valido") or "")
    metricas["tipo_obra_correcto"] = (obr_ext == obr_esp) or (
        obr_esp and obr_esp in obr_ext
    ) or (obr_ext and obr_ext in obr_esp)

    return metricas


# ── Matching de cargos entre output y golden ──────────────────────────────────

def _match_cargos(extraidos: list[dict], esperados: list[dict]) -> list[tuple]:
    """
    Empareja cargos extraidos con esperados por numero_fila o nombre normalizado.
    Retorna [(extraido_or_None, esperado_or_None)].
    """
    pares = []
    extraidos_usados: set[int] = set()

    for esp in esperados:
        match = None
        # Intento 1: match por numero_fila
        n_esp = esp.get("numero_fila")
        if n_esp is not None:
            for i, ext in enumerate(extraidos):
                if i in extraidos_usados:
                    continue
                if ext.get("numero_fila") == n_esp:
                    match = ext
                    extraidos_usados.add(i)
                    break

        # Intento 2: match por cargo normalizado (substring)
        if match is None:
            cargo_esp = _normalizar(esp.get("cargo") or "")
            for i, ext in enumerate(extraidos):
                if i in extraidos_usados:
                    continue
                cargo_ext = _normalizar(ext.get("cargo") or "")
                if cargo_ext == cargo_esp or (
                    cargo_esp and cargo_esp in cargo_ext
                ) or (cargo_ext and cargo_ext in cargo_esp):
                    match = ext
                    extraidos_usados.add(i)
                    break

        pares.append((match, esp))

    # Extraidos sin match = posibles alucinaciones
    for i, ext in enumerate(extraidos):
        if i not in extraidos_usados:
            pares.append((ext, None))

    return pares


# ── Reporte global ────────────────────────────────────────────────────────────

def evaluar(
    golden: dict,
    extraido: dict,
) -> dict:
    """
    Evalua un extraido contra un golden.
    Ambos tienen estructura: {"rtm_personal": [...]}.
    """
    esperados = golden.get("rtm_personal", [])
    extractados = extraido.get("rtm_personal", [])

    pares = _match_cargos(extractados, esperados)

    cargos_evaluados = []
    cargos_faltantes = []  # en golden pero no en extraido
    cargos_alucinados = []  # en extraido pero no en golden

    for ext, esp in pares:
        if ext is None and esp is not None:
            cargos_faltantes.append(esp.get("cargo") or f"fila_{esp.get('numero_fila')}")
            continue
        if esp is None and ext is not None:
            cargos_alucinados.append(ext.get("cargo") or "sin_cargo")
            continue
        if ext is not None and esp is not None:
            cargos_evaluados.append(_comparar_cargo(ext, esp))

    # Agregar metricas
    def _agregar_pr(campo: str) -> dict:
        tp = sum(m[campo]["tp"] for m in cargos_evaluados)
        fp = sum(m[campo]["fp"] for m in cargos_evaluados)
        fn = sum(m[campo]["fn"] for m in cargos_evaluados)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        return {
            "precision": round(prec, 3),
            "recall": round(rec, 3),
            "f1": round(f1, 3),
            "tp": tp, "fp": fp, "fn": fn,
        }

    tiempo_ok = sum(1 for m in cargos_evaluados if m["tiempo_meses_correcto"])
    obra_ok = sum(1 for m in cargos_evaluados if m["tipo_obra_correcto"])
    total_match = len(cargos_evaluados)

    return {
        "totales": {
            "esperados": len(esperados),
            "extraidos": len(extractados),
            "matched": total_match,
            "faltantes": len(cargos_faltantes),
            "alucinados": len(cargos_alucinados),
        },
        "agregados": {
            "profesiones": _agregar_pr("profesiones"),
            "cargos_similares": _agregar_pr("cargos_similares"),
            "tiempo_meses_pct": round(tiempo_ok / total_match, 3) if total_match else 0.0,
            "tipo_obra_pct": round(obra_ok / total_match, 3) if total_match else 0.0,
        },
        "cargos_faltantes": cargos_faltantes,
        "cargos_alucinados": cargos_alucinados,
        "por_cargo": cargos_evaluados,
    }


def imprimir_reporte(metricas: dict, golden_path: str, extraido_path: str) -> None:
    """Imprime reporte legible por stdout."""
    tot = metricas["totales"]
    agg = metricas["agregados"]
    print("=" * 70)
    print(f"Golden:    {golden_path}")
    print(f"Extraido:  {extraido_path}")
    print("=" * 70)
    print(f"\nRecall de cargos:       {tot['matched']}/{tot['esperados']} encontrados")
    if tot["faltantes"]:
        print(f"  Faltantes: {', '.join(metricas['cargos_faltantes'])}")
    if tot["alucinados"]:
        print(f"  Alucinados: {', '.join(metricas['cargos_alucinados'])}")

    print(f"\nProfesiones:")
    p = agg["profesiones"]
    print(f"  Precision={p['precision']:.1%}  Recall={p['recall']:.1%}  F1={p['f1']:.3f}")
    print(f"  TP={p['tp']} FP={p['fp']} FN={p['fn']}")

    print(f"\nCargos similares:")
    c = agg["cargos_similares"]
    print(f"  Precision={c['precision']:.1%}  Recall={c['recall']:.1%}  F1={c['f1']:.3f}")
    print(f"  TP={c['tp']} FP={c['fp']} FN={c['fn']}")

    print(f"\nTiempo meses correcto:  {agg['tiempo_meses_pct']:.1%}")
    print(f"Tipo obra correcto:     {agg['tipo_obra_pct']:.1%}")

    # Top 5 peores cargos (menor F1 combinado)
    if metricas["por_cargo"]:
        peores = sorted(
            metricas["por_cargo"],
            key=lambda m: (m["profesiones"]["f1"] + m["cargos_similares"]["f1"]) / 2,
        )[:5]
        print(f"\nTop 5 cargos con menor precision:")
        for m in peores:
            f1_prof = m["profesiones"]["f1"]
            f1_carg = m["cargos_similares"]["f1"]
            print(f"  #{m['numero_fila']} {m['cargo']:50s} prof_F1={f1_prof:.2f} carg_F1={f1_carg:.2f}")
            if m["profesiones"]["faltantes"]:
                print(f"      Profesiones faltantes: {m['profesiones']['faltantes']}")
            if m["profesiones"]["alucinaciones"]:
                print(f"      Profesiones alucinadas: {m['profesiones']['alucinaciones']}")

    print("=" * 70)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cargar_resultado_job(job_id: str) -> dict:
    """Lee el JSON result de un job desde la BD."""
    import os
    import psycopg2
    import psycopg2.extras
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin123@localhost:5432/infoobras")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT result FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Job {job_id} no encontrado")
            result = row["result"]
            if isinstance(result, str):
                result = json.loads(result)
            return result
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluar output TDR vs golden")
    parser.add_argument("golden", help="Ruta al JSON golden anotado")
    parser.add_argument(
        "extraido",
        nargs="?",
        default=None,
        help="Ruta al JSON del resultado del pipeline (o usar --job-id)",
    )
    parser.add_argument(
        "--job-id", default=None,
        help="ID del job en BD (alternativa a path del archivo)",
    )
    parser.add_argument(
        "--salida-json", default=None,
        help="Si se pasa, guarda metricas detalladas en este path",
    )
    args = parser.parse_args()

    golden_path = Path(args.golden)
    if not golden_path.exists():
        print(f"ERROR: no existe {golden_path}", file=sys.stderr)
        return 1
    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    if args.job_id:
        extraido = _cargar_resultado_job(args.job_id)
        etiqueta = f"job {args.job_id}"
    elif args.extraido:
        p = Path(args.extraido)
        if not p.exists():
            print(f"ERROR: no existe {p}", file=sys.stderr)
            return 1
        extraido = json.loads(p.read_text(encoding="utf-8"))
        etiqueta = str(p)
    else:
        print("ERROR: pasar extraido.json o --job-id=...", file=sys.stderr)
        return 1

    metricas = evaluar(golden, extraido)
    imprimir_reporte(metricas, str(golden_path), etiqueta)

    if args.salida_json:
        Path(args.salida_json).write_text(
            json.dumps(metricas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nMetricas detalladas guardadas en: {args.salida_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
