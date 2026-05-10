"""
CLI para regenerar Excel desde un JSON exportado del server.

Diseñado para iterar el cruce/excel/writer en local sin re-correr el
pipeline pesado de OCR + LLM (que solo corre en el servidor con GPU).

Workflow tipico:

    # 1. Exportar el JSON del job desde server:
    curl http://server:8000/api/jobs/d1f8c718/export -o job.json
    curl http://server:8000/api/jobs/96e5492f/export -o tdr.json   # opcional

    # 2. Iterar en local — regenera Excel en segundos:
    python -m src.tools.regenerate_excel \\
        --input job.json \\
        --tdr tdr.json \\
        --output eval_local.xlsx

    # 3. (opcional) Re-ejecutar SUNAT contra el portal real en local:
    python -m src.tools.regenerate_excel \\
        --input job.json --tdr tdr.json \\
        --output eval_local.xlsx \\
        --refresh-sunat

El JSON exportado debe seguir el formato de GET /api/jobs/{id}/export
(format_version: 1).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date as _date
from pathlib import Path
from typing import Optional


logger = logging.getLogger("regenerate_excel")


def _try_parse_iso_date(s) -> Optional[_date]:
    if not s:
        return None
    if isinstance(s, _date):
        return s
    if isinstance(s, str):
        try:
            return _date.fromisoformat(s[:10])
        except (ValueError, TypeError):
            return None
    return None


def _load_json(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"ERROR: Archivo no encontrado: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: JSON invalido en {path}: {e}")


def _reconstruir_modelos(extraction_json: dict):
    """De `extraction.secciones[]` -> list[Professional] + list[Experience]."""
    from src.extraction.models import Professional, Experience

    profesionales = []
    experiencias = []

    secciones = (extraction_json or {}).get("secciones", [])
    for sec in secciones:
        prof_data = sec.get("profesional") or {}
        nombre = prof_data.get("nombre") or f"(sin nombre - {sec.get('cargo', '')})"

        prof = Professional(
            name=nombre,
            role=sec.get("cargo", ""),
            role_number=sec.get("numero") or "",
            profession=prof_data.get("profesion"),
            tipo_colegio=prof_data.get("tipo_colegio"),
            registro_colegio=prof_data.get("registro_colegio"),
            registration_date=_try_parse_iso_date(prof_data.get("fecha_colegiacion")),
            folio=prof_data.get("folio"),
            source_file="json_import",
        )
        profesionales.append(prof)

        for exp_data in sec.get("experiencias", []):
            start = _try_parse_iso_date(
                exp_data.get("fecha_inicio_parsed") or exp_data.get("fecha_inicio")
            )
            end = _try_parse_iso_date(
                exp_data.get("fecha_fin_parsed") or exp_data.get("fecha_fin")
            )
            cert = _try_parse_iso_date(
                exp_data.get("fecha_emision_parsed") or exp_data.get("fecha_emision")
            )

            exp = Experience(
                professional_name=nombre,
                dni=prof_data.get("dni"),
                project_name=exp_data.get("proyecto"),
                role=exp_data.get("cargo"),
                company=exp_data.get("empresa_emisora"),
                ruc=exp_data.get("ruc"),
                start_date=start,
                end_date=end,
                cert_issue_date=cert,
                folio=exp_data.get("folio"),
                cui=exp_data.get("cui") or exp_data.get("codigo_cui") or None,
                infoobras_code=(
                    exp_data.get("codigo_infoobras") or exp_data.get("infoobras_code")
                ),
                signer=exp_data.get("firmante"),
                raw_text="",
                source_file="json_import",
                tipo_obra=exp_data.get("tipo_obra"),
                tipo_intervencion=exp_data.get("tipo_intervencion"),
                tipo_acreditacion=exp_data.get("tipo_acreditacion"),
                cargo_firmante=exp_data.get("cargo_firmante"),
            )
            experiencias.append(exp)

    return profesionales, experiencias


def _reconstruir_sunat_desde_export(export_json: dict) -> tuple[dict, dict]:
    """
    Reconstruye {ruc: EmpresaSUNAT} y {ruc: fecha_inscripcion} desde el
    snapshot de cruce_sunat del JSON exportado. Asi no es necesario
    re-consultar SUNAT si ya se hizo en server.
    """
    from src.scraping.sunat import EmpresaSUNAT

    sunat_por_ruc: dict = {}
    sunat_dates: dict = {}

    cruce = (export_json or {}).get("cruce_sunat") or {}
    cruces = cruce.get("cruces") or []
    for c in cruces:
        emp_data = c.get("empresa_sunat")
        if not emp_data:
            continue
        empresa = EmpresaSUNAT(
            ruc=emp_data.get("ruc", ""),
            razon_social=emp_data.get("razon_social"),
            nombre_comercial=emp_data.get("nombre_comercial"),
            tipo_contribuyente=emp_data.get("tipo_contribuyente"),
            fecha_inscripcion=_try_parse_iso_date(emp_data.get("fecha_inscripcion")),
            fecha_inicio_actividades=_try_parse_iso_date(
                emp_data.get("fecha_inicio_actividades")
            ),
            estado=emp_data.get("estado"),
            condicion=emp_data.get("condicion"),
            domicilio_fiscal=emp_data.get("domicilio_fiscal"),
            actividades_economicas=emp_data.get("actividades_economicas") or [],
        )
        for ruc_key in filter(None, [c.get("ruc_declarado"), c.get("ruc_resuelto")]):
            sunat_por_ruc[ruc_key] = empresa
            if empresa.fecha_inscripcion:
                sunat_dates[ruc_key] = empresa.fecha_inscripcion

    return sunat_por_ruc, sunat_dates


def main():
    parser = argparse.ArgumentParser(
        description="Regenera el Excel de un job desde JSON exportado (sin OCR/LLM).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", required=True, type=Path,
        help="JSON exportado del job (GET /api/jobs/{id}/export).",
    )
    parser.add_argument(
        "--tdr", type=Path,
        help="JSON TDR aparte si el principal no lo incluye (caso type=extraction).",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Path al .xlsx a generar.",
    )
    parser.add_argument(
        "--refresh-sunat", action="store_true",
        help="Re-consulta SUNAT contra el portal real (requiere internet). "
             "Si no, reusa el snapshot del JSON.",
    )
    parser.add_argument(
        "--proposal-date", type=str, default=None,
        help="Fecha de propuesta en formato YYYY-MM-DD. Default: hoy.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Logs INFO en stderr.",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # 1. Cargar JSON principal
    main_json = _load_json(args.input)
    if main_json.get("format_version") != 1:
        logger.warning("format_version != 1 — el formato puede no ser compatible")

    print(f"[INFO] Job: {main_json.get('job_id')} ({main_json.get('job_type')})")
    print(f"       archivo: {main_json.get('filename')}")

    # 2. Extraction
    extraction = main_json.get("extraction")
    if not extraction:
        sys.exit(
            "ERROR: El JSON no tiene 'extraction'. Si es job TDR, usalo como --tdr."
        )
    profesionales, experiencias = _reconstruir_modelos(extraction)
    print(f"       profesionales: {len(profesionales)}, "
          f"experiencias: {len(experiencias)}")

    # 3. TDR (del mismo JSON o de --tdr)
    tdr_data = main_json.get("tdr")
    if (not tdr_data or not tdr_data.get("rtm_personal")) and args.tdr:
        tdr_json = _load_json(args.tdr)
        tdr_data = tdr_json.get("tdr") or tdr_json
    rtm_personal = (tdr_data or {}).get("rtm_personal", [])
    if not rtm_personal:
        sys.exit(
            "ERROR: No se encontro rtm_personal ni en el JSON principal ni en "
            "--tdr. El Excel no se puede generar sin TDR."
        )
    print(f"       cargos TDR: {len(rtm_personal)}")

    # 4. Convertir rtm_personal a RequisitoPersonal
    from src.extraction.models import RequisitoPersonal
    requisitos_rtm_completo = []
    for r in rtm_personal:
        if isinstance(r, dict):
            try:
                requisitos_rtm_completo.append(RequisitoPersonal.from_dict(r))
            except Exception as exc:
                logger.warning("No se pudo parsear requisito: %s", exc)
        else:
            requisitos_rtm_completo.append(r)

    # 5. SUNAT - reusar snapshot o refresh
    if args.refresh_sunat:
        print("[NET]  Refresh SUNAT activo - consultando portal...")
        from src.validation.cruce_sunat import cruzar_experiencias
        # sin conn -> cache solo memoria (no toca PostgreSQL)
        resultado_sunat = cruzar_experiencias(experiencias)
        sunat_por_ruc: dict = {}
        sunat_dates: dict = {}
        for c in resultado_sunat.cruces:
            if not c.empresa_sunat:
                continue
            for ruc_key in filter(None, [c.ruc_declarado, c.ruc_resuelto]):
                sunat_por_ruc[ruc_key] = c.empresa_sunat
                if c.empresa_sunat.fecha_inscripcion:
                    sunat_dates[ruc_key] = c.empresa_sunat.fecha_inscripcion
        print(f"       {len(sunat_por_ruc)} RUCs con datos SUNAT")
    else:
        sunat_por_ruc, sunat_dates = _reconstruir_sunat_desde_export(main_json)
        if sunat_por_ruc:
            print(f"[CACHE] SUNAT reusado del JSON: {len(sunat_por_ruc)} RUCs")
        else:
            print("[WARN] Sin datos SUNAT en JSON (usa --refresh-sunat para consultar)")

    # 6. Evaluacion (motor de reglas)
    proposal_date = _try_parse_iso_date(args.proposal_date) or _date.today()
    from src.validation.evaluator import evaluar_propuesta
    resultados = evaluar_propuesta(
        profesionales=profesionales,
        experiencias=experiencias,
        requisitos_rtm=rtm_personal,
        proposal_date=proposal_date,
        sunat_dates=sunat_dates,
    )
    total_alertas = sum(len(ev.alertas) for r in resultados for ev in r.evaluaciones)
    print(f"[EVAL] {len(resultados)} prof, {total_alertas} alertas")

    # 7. Generar Excel
    from src.reporting.excel_writer_lircay import write_report_lircay
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report_lircay(
        resultados=resultados,
        output_path=args.output,
        proposal_date=proposal_date,
        filename=main_json.get("filename", ""),
        sunat_por_ruc=sunat_por_ruc,
        requisitos_rtm_completo=requisitos_rtm_completo,
    )

    size_kb = args.output.stat().st_size / 1024
    print(f"[OK]   Excel generado: {args.output} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
