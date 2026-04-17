"""
Evaluador RTM — Paso 4: evaluación de experiencias contra criterios RTM.

Produce 22 columnas por par (profesional, experiencia) según manual.md.
Motor determinístico: sin IA, sin llamadas externas.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from src.extraction.models import (
    Professional,
    Experience,
    RequisitoPersonal,
    EvaluacionRTM,
    ResultadoProfesional,
)
from src.validation.rules import check_alerts, _fecha_hace_20_anos
from src.validation.matching import (
    normalizar_cargo,
    match_profesion,
    match_cargo,
    match_tipo_obra,
    match_intervencion,
    inferir_tipo_obra,
    inferir_intervencion,
    _son_cargos_sinonimos,
)


# ---------------------------------------------------------------------------
# Búsqueda de requisito RTM para un profesional
# ---------------------------------------------------------------------------

def _buscar_requisito(
    profesional: Professional,
    requisitos: list[RequisitoPersonal],
) -> Optional[RequisitoPersonal]:
    """
    Busca el RequisitoPersonal que corresponde al cargo del profesional.

    Estrategia (en orden de prioridad):
      1. Match exacto por cargo normalizado
      2. Substring: cargo del profesional contenido en el del requisito o viceversa
      3. Similitud por palabras (overlap de tokens)

    Retorna None si no se encuentra match.
    """
    if not requisitos:
        return None

    cargo_norm = normalizar_cargo(profesional.role)

    # Preparar requisitos normalizados
    pares: list[tuple[str, RequisitoPersonal]] = [
        (normalizar_cargo(r.cargo), r) for r in requisitos
    ]

    # 1. Match exacto
    for norm, req in pares:
        if cargo_norm == norm:
            return req

    # 2. Substring bidireccional
    for norm, req in pares:
        if cargo_norm in norm or norm in cargo_norm:
            return req

    # 3. Sinónimos de cargo OSCE
    for norm, req in pares:
        if _son_cargos_sinonimos(profesional.role, req.cargo):
            return req

    # 4. Similitud por overlap de tokens (Jaccard)
    tokens_prof = set(cargo_norm.split())
    mejor_score = 0.0
    mejor_req = None
    for norm, req in pares:
        tokens_req = set(norm.split())
        if not tokens_prof or not tokens_req:
            continue
        interseccion = tokens_prof & tokens_req
        union = tokens_prof | tokens_req
        score = len(interseccion) / len(union) if union else 0.0
        if score > mejor_score:
            mejor_score = score
            mejor_req = req

    # Umbral mínimo: al menos 40% de overlap
    if mejor_score >= 0.4:
        return mejor_req

    return None


# ---------------------------------------------------------------------------
# Evaluación de 22 columnas
# ---------------------------------------------------------------------------

def evaluar_rtm(
    profesional: Professional,
    experiencia: Experience,
    requisito: Optional[RequisitoPersonal],
    proposal_date: date,
) -> EvaluacionRTM:
    """
    Evalúa UNA experiencia contra los criterios RTM.
    Retorna un EvaluacionRTM con las 22 columnas del manual.

    Cuando requisito es None (profesional sin match en RTM):
      → columnas de cumplimiento = "NO EVALUABLE"

    Cuando un campo del RTM es None (bases no especifican):
      → se asume cumplido (favorabilidad OSCE)
    """
    ev = EvaluacionRTM()

    # --- Cols 1-3: Identificación ---
    ev.cargo_postulado = profesional.role
    ev.nombre = profesional.name
    ev.profesion_propuesta = profesional.profession

    # --- Col 4-5: Profesión ---
    if requisito is None:
        ev.profesion_requerida = None
        ev.cumple_profesion = "NO EVALUABLE"
    else:
        # Unir profesiones aceptadas como texto
        if requisito.profesiones_aceptadas:
            ev.profesion_requerida = " / ".join(requisito.profesiones_aceptadas)
        else:
            ev.profesion_requerida = None
        # Evaluar
        ev.cumple_profesion = (
            "SI" if match_profesion(profesional.profession, requisito.profesiones_aceptadas)
            else "NO"
        )

    # --- Col 6: Folio ---
    ev.folio_certificado = experiencia.folio

    # --- Cols 7-9: Cargo ---
    ev.cargo_experiencia = experiencia.role
    if requisito is None:
        ev.cargos_validos_bases = None
        ev.cumple_cargo = "NO EVALUABLE"
    else:
        # Construir lista de cargos válidos
        cargos_validos: list[str] = []
        if requisito.experiencia_minima and requisito.experiencia_minima.cargos_similares_validos:
            cargos_validos = requisito.experiencia_minima.cargos_similares_validos
        if not cargos_validos and requisito.cargo:
            cargos_validos = [requisito.cargo]
        ev.cargos_validos_bases = " / ".join(cargos_validos) if cargos_validos else None
        ev.cumple_cargo = (
            "CUMPLE" if match_cargo(experiencia.role, cargos_validos or None)
            else "NO CUMPLE"
        )

    # --- Cols 10-12: Proyecto/obra ---
    ev.proyecto_propuesto = experiencia.project_name
    if requisito is None:
        ev.proyecto_valido_bases = None
        ev.cumple_proyecto = "NO EVALUABLE"
    else:
        ev.proyecto_valido_bases = requisito.tipo_obra_valido
        if not requisito.tipo_obra_valido:
            # Bases no especifican tipo de obra → cumple por favorabilidad
            ev.cumple_proyecto = "SI"
        else:
            texto_comparar = experiencia.tipo_obra or experiencia.project_name
            resultado = match_tipo_obra(texto_comparar, requisito.tipo_obra_valido)
            if resultado is True:
                ev.cumple_proyecto = "SI"
            elif resultado is False:
                ev.cumple_proyecto = "NO"
            else:
                ev.cumple_proyecto = "NO EVALUABLE"

    # --- Cols 13-14: Fecha de término ---
    # Regla "a la fecha": si end_date es None pero hay cert_issue_date,
    # usar cert_issue_date como fecha fin efectiva (el cliente pidió esto).
    # ALT05 sigue disparando porque technically no hay fecha fin explícita.
    fecha_fin_efectiva = experiencia.end_date
    if fecha_fin_efectiva is None and experiencia.cert_issue_date is not None:
        fecha_fin_efectiva = experiencia.cert_issue_date

    ev.fecha_termino = fecha_fin_efectiva
    ev.alerta_fecha_termino = "NO VALE" if experiencia.end_date is None else ""

    # --- Cols 15-17: Tipo de obra ---
    # Usar campo explícito si existe, sino inferir del nombre
    tipo_obra_cert = experiencia.tipo_obra or inferir_tipo_obra(experiencia.project_name)
    ev.tipo_obra_certificado = tipo_obra_cert

    if requisito is None:
        ev.tipo_obra_requerido = None
        ev.cumple_tipo_obra = "NO EVALUABLE"
    else:
        ev.tipo_obra_requerido = requisito.tipo_obra_valido
        if not requisito.tipo_obra_valido:
            ev.cumple_tipo_obra = "CUMPLE"
        else:
            resultado = match_tipo_obra(
                tipo_obra_cert or experiencia.project_name,
                requisito.tipo_obra_valido,
            )
            if resultado is True:
                ev.cumple_tipo_obra = "CUMPLE"
            elif resultado is False:
                ev.cumple_tipo_obra = "NO CUMPLE"
            else:
                ev.cumple_tipo_obra = "NO EVALUABLE"

    # --- Cols 18-20: Intervención ---
    intervencion_cert = experiencia.tipo_intervencion or inferir_intervencion(experiencia.project_name)
    ev.intervencion_certificado = intervencion_cert

    if requisito is None:
        ev.intervencion_requerida = None
        ev.cumple_intervencion = "NO EVALUABLE"
    else:
        # Para intervención, usar tipo_obra_valido como referencia
        # (las bases suelen especificar "supervisión de obras de salud")
        intervencion_req = inferir_intervencion(requisito.tipo_obra_valido) if requisito.tipo_obra_valido else None
        ev.intervencion_requerida = intervencion_req

        if not intervencion_req:
            # Bases no especifican intervención → "no importa"
            ev.intervencion_requerida = "El tipo de intervención no importa"
            ev.cumple_intervencion = "CUMPLE"
        else:
            resultado = match_intervencion(intervencion_cert, intervencion_req)
            if resultado is True:
                ev.cumple_intervencion = "CUMPLE"
            elif resultado is False:
                ev.cumple_intervencion = "NO CUMPLE"
            else:
                ev.cumple_intervencion = "NO EVALUABLE"

    # --- Col 21: Complejidad ---
    # Derivada de cumple_cargo AND cumple_proyecto AND cumple_tipo_obra AND cumple_intervencion
    # Si alguno es "NO EVALUABLE", no se puede determinar complejidad
    campos_cumplimiento = [
        ev.cumple_cargo, ev.cumple_proyecto,
        ev.cumple_tipo_obra, ev.cumple_intervencion,
    ]
    if any(c in ("NO CUMPLE", "NO") for c in campos_cumplimiento):
        ev.acredita_complejidad = "NO"
    elif any(c == "NO EVALUABLE" for c in campos_cumplimiento):
        ev.acredita_complejidad = "NO EVALUABLE"
    else:
        ev.acredita_complejidad = "SI"

    # --- Col 22: Dentro de los últimos 20 años ---
    # Usa fecha_fin_efectiva (cert_issue_date si end_date es None)
    if fecha_fin_efectiva is not None:
        limite_20 = _fecha_hace_20_anos(proposal_date)
        ev.dentro_20_anos = "SI" if fecha_fin_efectiva >= limite_20 else "NO"
    else:
        ev.dentro_20_anos = "NO"  # Sin fecha fin ni fecha emisión

    return ev


# ---------------------------------------------------------------------------
# Evaluación por profesional
# ---------------------------------------------------------------------------

def evaluar_profesional(
    profesional: Professional,
    experiencias: list[Experience],
    requisitos: list[RequisitoPersonal],
    proposal_date: date,
    sunat_dates: Optional[dict[str, date]] = None,
    cip_vigente: Optional[bool] = None,
) -> ResultadoProfesional:
    """
    Evalúa todas las experiencias de UN profesional contra los RTM.

    Args:
        profesional: datos del profesional (Paso 2).
        experiencias: certificados del profesional (Paso 3).
        requisitos: todos los requisitos RTM (Paso 1).
        proposal_date: fecha de presentación de la propuesta.
        sunat_dates: dict {ruc: fecha_inicio_actividades} de SUNAT.
        cip_vigente: True/False/None del scraper CIP.

    Returns:
        ResultadoProfesional con evaluaciones y alertas.
    """
    # Buscar requisito que corresponde a este profesional
    requisito = _buscar_requisito(profesional, requisitos)

    resultado = ResultadoProfesional(
        profesional=profesional,
        requisito=requisito,
        requisito_encontrado=requisito is not None,
    )

    for exp in experiencias:
        # Evaluación de 22 columnas
        evaluacion = evaluar_rtm(profesional, exp, requisito, proposal_date)

        # Alertas
        sunat_date = None
        if sunat_dates and exp.ruc:
            sunat_date = sunat_dates.get(exp.ruc)

        alertas = check_alerts(
            exp=exp,
            proposal_date=proposal_date,
            requisito=requisito,
            profesion_propuesta=profesional.profession,
            sunat_start_date=sunat_date,
            cip_vigente=cip_vigente,
        )
        evaluacion.alertas = alertas
        evaluacion.experiencia_ref = exp
        resultado.evaluaciones.append(evaluacion)

    return resultado


# ---------------------------------------------------------------------------
# Orquestador de propuesta completa
# ---------------------------------------------------------------------------

def _normalizar_nombre(nombre: str) -> str:
    """Normaliza nombre para agrupar experiencias por profesional."""
    return nombre.lower().strip()


def evaluar_propuesta(
    profesionales: list[Professional],
    experiencias: list[Experience],
    requisitos_rtm: list[dict] | list[RequisitoPersonal],
    proposal_date: date,
    sunat_dates: Optional[dict[str, date]] = None,
    cip_estados: Optional[dict[str, bool]] = None,
) -> list[ResultadoProfesional]:
    """
    Evalúa TODA la propuesta: todos los profesionales contra los RTM.

    Args:
        profesionales: lista de profesionales (Paso 2).
        experiencias: todas las experiencias de todos los profesionales (Paso 3).
        requisitos_rtm: requisitos RTM — acepta dicts del TDR o RequisitoPersonal.
        proposal_date: fecha de presentación de la propuesta.
        sunat_dates: {ruc: fecha_inicio} de SUNAT (opcional).
        cip_estados: {registro_colegio: vigente} de CIP (opcional).

    Returns:
        Lista de ResultadoProfesional, uno por profesional.
    """
    # Convertir dicts a RequisitoPersonal si es necesario
    requisitos: list[RequisitoPersonal] = []
    for r in requisitos_rtm:
        if isinstance(r, dict):
            requisitos.append(RequisitoPersonal.from_dict(r))
        else:
            requisitos.append(r)

    # Agrupar experiencias por nombre de profesional
    exp_por_profesional: dict[str, list[Experience]] = {}
    for exp in experiencias:
        key = _normalizar_nombre(exp.professional_name)
        exp_por_profesional.setdefault(key, []).append(exp)

    # Evaluar cada profesional
    resultados: list[ResultadoProfesional] = []
    for prof in profesionales:
        key = _normalizar_nombre(prof.name)
        exps = exp_por_profesional.get(key, [])

        # Obtener estado CIP si está disponible
        cip_vigente = None
        if cip_estados and prof.registro_colegio:
            cip_vigente = cip_estados.get(prof.registro_colegio)

        resultado = evaluar_profesional(
            profesional=prof,
            experiencias=exps,
            requisitos=requisitos,
            proposal_date=proposal_date,
            sunat_dates=sunat_dates,
            cip_vigente=cip_vigente,
        )
        resultados.append(resultado)

    return resultados
