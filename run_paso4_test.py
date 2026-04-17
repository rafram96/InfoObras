"""
Test del Paso 4 — Evaluación RTM.

Carga datos reales de la DB (un job de extracción + un job TDR)
y ejecuta evaluar_propuesta() para verificar que funciona.

Uso:
    python run_paso4_test.py
"""
import json
import sys
from datetime import date

import psycopg2
from dotenv import load_dotenv
import os

# Importar parser de fechas
from src.extraction.llm_extractor import _parsear_fecha

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://admin:admin123@localhost:5432/infoobras",
)

# IDs de los jobs a cruzar
EXTRACTION_JOB = "6c1f0fe9"  # Profesionales.pdf (nuevo, con 12 profesionales extraídos)
TDR_JOB = "1a5495be"         # Bases del concurso

# Fecha ficticia de propuesta (ajustar si se conoce la real)
PROPOSAL_DATE = date(2025, 12, 15)


def load_job_result(job_id: str) -> dict:
    """Carga el resultado JSON de un job desde la DB."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT result FROM jobs WHERE id = %s", (job_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        print(f"ERROR: Job {job_id} no tiene resultado")
        sys.exit(1)
    result = row[0]
    if isinstance(result, str):
        result = json.loads(result)
    return result


def main():
    print("=" * 70)
    print("TEST PASO 4 — Evaluación RTM")
    print("=" * 70)

    # ── Cargar datos ──────────────────────────────────────────────────────
    print(f"\n📄 Cargando extracción: job {EXTRACTION_JOB}")
    ext_result = load_job_result(EXTRACTION_JOB)

    print(f"📋 Cargando TDR: job {TDR_JOB}")
    tdr_result = load_job_result(TDR_JOB)

    # ── Mostrar qué hay ──────────────────────────────────────────────────
    secciones = ext_result.get("secciones", [])
    rtm_personal = tdr_result.get("rtm_personal", [])
    factores = tdr_result.get("factores_evaluacion", [])

    print(f"\n📊 Datos cargados:")
    print(f"   Profesionales (secciones): {len(secciones)}")
    print(f"   Requisitos RTM (cargos):   {len(rtm_personal)}")
    print(f"   Factores evaluación:       {len(factores)}")

    # ── Extraer profesionales y experiencias ──────────────────────────────
    from src.extraction.models import Professional, Experience

    profesionales = []
    experiencias = []

    for sec in secciones:
        prof_data = sec.get("profesional") or {}
        nombre = prof_data.get("nombre") or f"(sin nombre - {sec['cargo']})"

        prof = Professional(
            name=nombre,
            role=sec.get("cargo", ""),
            role_number=sec.get("numero") or "",
            profession=prof_data.get("profesion"),
            tipo_colegio=prof_data.get("tipo_colegio"),
            registro_colegio=prof_data.get("registro_colegio"),
            registration_date=None,
            folio=None,
            source_file="db",
        )
        profesionales.append(prof)

        for exp_data in sec.get("experiencias", []):
            # Parsear fechas: usar _parsed si existe, sino parsear el string crudo
            start = None
            end = None
            cert = None

            # Intentar fecha parseada primero, luego parsear el string
            start_str = exp_data.get("fecha_inicio_parsed") or exp_data.get("fecha_inicio")
            end_str = exp_data.get("fecha_fin_parsed") or exp_data.get("fecha_fin")
            cert_str = exp_data.get("fecha_emision_parsed") or exp_data.get("fecha_emision")

            if isinstance(start_str, str) and len(start_str) == 10 and "-" in start_str:
                try:
                    start = date.fromisoformat(start_str)
                except ValueError:
                    pass
            if not start:
                start = _parsear_fecha(exp_data.get("fecha_inicio"))

            if isinstance(end_str, str) and len(end_str) == 10 and "-" in end_str:
                try:
                    end = date.fromisoformat(end_str)
                except ValueError:
                    pass
            if not end:
                end = _parsear_fecha(exp_data.get("fecha_fin"))

            if isinstance(cert_str, str) and len(cert_str) == 10 and "-" in cert_str:
                try:
                    cert = date.fromisoformat(cert_str)
                except ValueError:
                    pass
            if not cert:
                cert = _parsear_fecha(exp_data.get("fecha_emision"))

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
                cui=None,
                infoobras_code=None,
                signer=exp_data.get("firmante"),
                raw_text="",
                source_file="db",
                tipo_obra=exp_data.get("tipo_obra"),
                tipo_intervencion=exp_data.get("tipo_intervencion"),
                tipo_acreditacion=exp_data.get("tipo_acreditacion"),
                cargo_firmante=exp_data.get("cargo_firmante"),
            )
            experiencias.append(exp)

    print(f"   Profesionales construidos: {len(profesionales)}")
    print(f"   Experiencias construidas:  {len(experiencias)}")

    if not profesionales:
        print("\n❌ No hay profesionales con datos — la extracción no produjo resultados.")
        print("   Esto pasa si el job se corrió sin Ollama o sin extracción LLM.")
        sys.exit(1)

    # ── Mostrar profesionales ─────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print("PROFESIONALES EXTRAÍDOS:")
    print(f"{'─' * 70}")
    for i, p in enumerate(profesionales, 1):
        n_exp = sum(1 for e in experiencias if e.professional_name == p.name)
        print(f"  {i:2}. {p.role:<50} | {p.name or '—':<30} | {n_exp} exp.")

    # ── Mostrar requisitos TDR ────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print("REQUISITOS RTM (del TDR):")
    print(f"{'─' * 70}")
    if not rtm_personal:
        print("  (sin requisitos — el job TDR no produjo rtm_personal)")
    for i, req in enumerate(rtm_personal, 1):
        cargo = req.get("cargo", "?")
        profs = req.get("profesiones_aceptadas") or []
        tipo_obra = req.get("tipo_obra_valido") or "—"
        print(f"  {i:2}. {cargo:<50} | {', '.join(profs) or '—':<25} | {tipo_obra}")

    # ── Ejecutar Paso 4 ──────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("EJECUTANDO PASO 4 — evaluar_propuesta()")
    print(f"{'=' * 70}")

    from src.validation.evaluator import evaluar_propuesta

    resultados = evaluar_propuesta(
        profesionales=profesionales,
        experiencias=experiencias,
        requisitos_rtm=rtm_personal,
        proposal_date=PROPOSAL_DATE,
    )

    # ── Mostrar resultados ────────────────────────────────────────────────
    for res in resultados:
        prof = res.profesional
        print(f"\n{'━' * 70}")
        print(f"👤 {prof.name or '(sin nombre)'} — {prof.role}")
        print(f"   RTM encontrado: {'✅ ' + res.requisito.cargo if res.requisito else '❌ Sin match'}")
        print(f"   Evaluaciones: {len(res.evaluaciones)}")

        for j, ev in enumerate(res.evaluaciones, 1):
            print(f"\n   📋 Experiencia {j}: {ev.proyecto_propuesto or '—'}")
            print(f"      Profesión:    {ev.cumple_profesion:<15} ({ev.profesion_propuesta} vs {ev.profesion_requerida})")
            print(f"      Cargo:        {ev.cumple_cargo:<15} ({ev.cargo_experiencia} vs {ev.cargos_validos_bases})")
            print(f"      Proyecto:     {ev.cumple_proyecto:<15}")
            print(f"      Tipo obra:    {ev.cumple_tipo_obra:<15} ({ev.tipo_obra_certificado} vs {ev.tipo_obra_requerido})")
            print(f"      Intervención: {ev.cumple_intervencion:<15}")
            print(f"      Complejidad:  {ev.acredita_complejidad:<15}")
            print(f"      20 años:      {ev.dentro_20_anos:<15}")

            if ev.alertas:
                for alerta in ev.alertas:
                    icono = "🔴" if alerta.severity.value == "CRITICO" else "🟡"
                    print(f"      {icono} {alerta.code.value}: {alerta.description}")

    # ── Resumen ───────────────────────────────────────────────────────────
    total_ev = sum(len(r.evaluaciones) for r in resultados)
    total_alertas = sum(
        len(a) for r in resultados for ev in r.evaluaciones for a in [ev.alertas]
    )
    con_rtm = sum(1 for r in resultados if r.requisito_encontrado)

    print(f"\n{'=' * 70}")
    print("RESUMEN")
    print(f"{'=' * 70}")
    print(f"  Profesionales evaluados: {len(resultados)}")
    print(f"  Con match RTM:           {con_rtm}/{len(resultados)}")
    print(f"  Total evaluaciones:      {total_ev}")
    print(f"  Total alertas:           {total_alertas}")
    print(f"{'=' * 70}")

    # ── Generar Excel ─────────────────────────────────────────────────────
    from src.reporting.excel_writer import write_report
    from pathlib import Path

    output_path = Path("data/test_paso4_resultado.xlsx")
    write_report(
        resultados=resultados,
        output_path=output_path,
        proposal_date=PROPOSAL_DATE,
        filename="Profesionales.pdf",
    )
    print(f"\n📊 Excel generado: {output_path.absolute()}")


if __name__ == "__main__":
    main()
