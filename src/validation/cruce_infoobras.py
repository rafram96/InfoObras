"""
Cruce automatico de experiencias declaradas vs InfoObras (Contraloria).

Decision del cliente: solo lo contrastable, NO Especialistas (no hay fuente
publica estructurada para esos cargos).

Niveles de cruce:
- Nivel 1: paralizaciones del periodo del certificado (cubre los 17 cargos)
- Nivel 2: verificacion nominal Supervisor + Residente (2 cargos, detecta
           rotacion: si declara mas tiempo del que figura en InfoObras)

Senales adicionales (validaciones del CV, no requieren InfoObras):
- Periodo cert > duracion total de la obra
- Periodo cert antes del inicio de la obra
- Solapamientos del mismo profesional en la misma obra
- Multiples profesionales del concurso actual con mismo cargo+obra

Patron del modulo:
- Recibe los `list[ResultadoProfesional]` que ya produjo el Paso 4.
- Por cada experiencia con CUI, hace fetch_by_cui (con cache).
- Calcula senales y devuelve `ResultadoCruceJob` con todas las alertas.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.extraction.models import (
    Experience,
    Professional,
    ResultadoProfesional,
    EvaluacionRTM,
)
from src.scraping.infoobras import (
    WorkInfo,
    fetch_by_cui,
    buscar_obra_por_certificado,
    verificar_profesional_en_obra,
    VerificacionProfesional,
)

logger = logging.getLogger(__name__)


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class SenalCruce:
    """Una senal/alerta producida por el cruce con InfoObras o validacion del CV."""
    severidad: str                  # "critica" | "observacion" | "informativa"
    fuente: str                     # "infoobras_paralizacion" | "infoobras_nominal" | "cv_interno"
    mensaje: str                    # texto natural

    def to_dict(self) -> dict:
        return {
            "severidad": self.severidad,
            "fuente": self.fuente,
            "mensaje": self.mensaje,
        }


@dataclass
class ResultadoCruceExperiencia:
    """Resultado del cruce para una experiencia (un certificado)."""
    nombre_profesional: str
    cargo_postulado: str            # cargo que ostenta en el concurso actual
    proyecto: str
    cargo_experiencia: Optional[str] = None  # cargo segun el certificado
    cui: Optional[str] = None
    folio: Optional[str] = None
    fecha_inicio_cert: Optional[date] = None
    fecha_fin_cert: Optional[date] = None

    # Datos de InfoObras
    obra_encontrada: bool = False
    nombre_obra_infoobras: Optional[str] = None
    fecha_inicio_obra: Optional[date] = None
    fecha_fin_obra: Optional[date] = None
    estado_obra: Optional[str] = None

    # Verificacion nominal (solo Sup/Res)
    aplica_verif_nominal: bool = False
    nombre_coincide: Optional[bool] = None
    score_nombre: Optional[float] = None
    nombre_encontrado_infoobras: Optional[str] = None
    periodo_valido: Optional[bool] = None

    # Paralizaciones detectadas en el periodo del cert
    paralizaciones: list[dict] = field(default_factory=list)
    dias_paralizado_en_periodo: int = 0

    # Senales / alertas
    senales: list[SenalCruce] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nombre_profesional": self.nombre_profesional,
            "cargo_postulado": self.cargo_postulado,
            "proyecto": self.proyecto,
            "cargo_experiencia": self.cargo_experiencia,
            "cui": self.cui,
            "folio": self.folio,
            "fecha_inicio_cert": self.fecha_inicio_cert.isoformat() if self.fecha_inicio_cert else None,
            "fecha_fin_cert": self.fecha_fin_cert.isoformat() if self.fecha_fin_cert else None,
            "obra_encontrada": self.obra_encontrada,
            "nombre_obra_infoobras": self.nombre_obra_infoobras,
            "fecha_inicio_obra": self.fecha_inicio_obra.isoformat() if self.fecha_inicio_obra else None,
            "fecha_fin_obra": self.fecha_fin_obra.isoformat() if self.fecha_fin_obra else None,
            "estado_obra": self.estado_obra,
            "aplica_verif_nominal": self.aplica_verif_nominal,
            "nombre_coincide": self.nombre_coincide,
            "score_nombre": self.score_nombre,
            "nombre_encontrado_infoobras": self.nombre_encontrado_infoobras,
            "periodo_valido": self.periodo_valido,
            "paralizaciones": self.paralizaciones,
            "dias_paralizado_en_periodo": self.dias_paralizado_en_periodo,
            "senales": [s.to_dict() for s in self.senales],
        }


@dataclass
class ResultadoCruceJob:
    """Resultado agregado del cruce de un job completo."""
    cruces: list[ResultadoCruceExperiencia] = field(default_factory=list)
    cuis_consultados: int = 0
    cuis_no_encontrados: list[str] = field(default_factory=list)
    senales_globales: list[SenalCruce] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cruces": [c.to_dict() for c in self.cruces],
            "cuis_consultados": self.cuis_consultados,
            "cuis_no_encontrados": self.cuis_no_encontrados,
            "senales_globales": [s.to_dict() for s in self.senales_globales],
            "total_experiencias": len(self.cruces),
            "total_alertas": sum(len(c.senales) for c in self.cruces) + len(self.senales_globales),
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

# Cargos que SI pueden verificarse nominalmente en InfoObras
_CARGOS_NOMINALES = {
    "supervisor": "supervisor",
    "jefe de supervision": "supervisor",
    "jefe de supervisión": "supervisor",
    "inspector": "supervisor",  # InfoObras los agrupa con supervisor
    "residente": "residente",
    "residente de obra": "residente",
}


def _clasificar_cargo_para_infoobras(cargo: str) -> Optional[str]:
    """
    Determina si un cargo puede verificarse nominalmente en InfoObras.

    InfoObras solo guarda Supervisor y Residente con nombre. Los Especialistas
    NO se registran nominalmente.

    Returns:
        "supervisor" | "residente" | None (no aplica verif nominal)
    """
    if not cargo:
        return None
    c = cargo.lower().strip()
    # Match flexible
    for keyword, tipo in _CARGOS_NOMINALES.items():
        if keyword in c:
            return tipo
    return None


def _calcular_senales_cv(
    exp: Experience,
    obra: Optional[WorkInfo],
) -> list[SenalCruce]:
    """
    Calcula senales que NO requieren InfoObras (validaciones del CV
    contra duracion de la obra si se conoce).
    """
    senales: list[SenalCruce] = []
    inicio_cert = exp.start_date
    fin_cert = exp.end_date

    if not inicio_cert or not fin_cert:
        return senales

    if not obra:
        return senales

    # Senal: periodo cert antes del inicio de la obra
    if obra.fecha_inicio and inicio_cert < obra.fecha_inicio:
        dias_antes = (obra.fecha_inicio - inicio_cert).days
        senales.append(SenalCruce(
            severidad="critica",
            fuente="cv_interno",
            mensaje=(
                f"El certificado declara inicio el {inicio_cert.strftime('%d/%m/%Y')}, "
                f"pero la obra recien comenzo el {obra.fecha_inicio.strftime('%d/%m/%Y')} "
                f"({dias_antes} dias antes). Imposible haber trabajado antes de que la obra existiera."
            ),
        ))

    # Senal: periodo cert despues del fin de la obra
    if obra.fecha_fin and fin_cert > obra.fecha_fin:
        dias_despues = (fin_cert - obra.fecha_fin).days
        # Solo critico si la diferencia es grande (>30 dias),
        # tolerar pequenas discrepancias por demoras administrativas.
        sev = "critica" if dias_despues > 30 else "observacion"
        senales.append(SenalCruce(
            severidad=sev,
            fuente="cv_interno",
            mensaje=(
                f"El certificado declara fin el {fin_cert.strftime('%d/%m/%Y')}, "
                f"pero la obra termino el {obra.fecha_fin.strftime('%d/%m/%Y')} "
                f"({dias_despues} dias despues)."
            ),
        ))

    # Senal: duracion declarada > duracion total de la obra
    if obra.fecha_inicio and obra.fecha_fin:
        duracion_obra_dias = (obra.fecha_fin - obra.fecha_inicio).days
        duracion_cert_dias = (fin_cert - inicio_cert).days
        if duracion_cert_dias > duracion_obra_dias + 30:  # tolerancia de 1 mes
            sobreexceso = duracion_cert_dias - duracion_obra_dias
            senales.append(SenalCruce(
                severidad="critica",
                fuente="cv_interno",
                mensaje=(
                    f"Duracion declarada en el certificado ({duracion_cert_dias} dias / "
                    f"~{duracion_cert_dias // 30} meses) supera la duracion total de la obra "
                    f"({duracion_obra_dias} dias / ~{duracion_obra_dias // 30} meses) "
                    f"por {sobreexceso} dias."
                ),
            ))

    return senales


def _detectar_solapamientos_mismo_profesional(
    cruces_de_un_profesional: list[ResultadoCruceExperiencia],
) -> list[SenalCruce]:
    """
    Detecta si un mismo profesional declara periodos solapados en la MISMA obra.
    Puede ser legitimo (rotacion entre cargos) pero amerita revisar.
    """
    senales: list[SenalCruce] = []
    if len(cruces_de_un_profesional) < 2:
        return senales

    # Agrupar por CUI
    por_cui: dict[str, list[ResultadoCruceExperiencia]] = {}
    for c in cruces_de_un_profesional:
        if c.cui:
            por_cui.setdefault(c.cui, []).append(c)

    for cui, lista in por_cui.items():
        if len(lista) < 2:
            continue
        # Buscar pares que solapan
        for i in range(len(lista)):
            for j in range(i + 1, len(lista)):
                a, b = lista[i], lista[j]
                if not (a.fecha_inicio_cert and a.fecha_fin_cert and
                        b.fecha_inicio_cert and b.fecha_fin_cert):
                    continue
                # Solapamiento
                if a.fecha_inicio_cert <= b.fecha_fin_cert and b.fecha_inicio_cert <= a.fecha_fin_cert:
                    senales.append(SenalCruce(
                        severidad="observacion",
                        fuente="cv_interno",
                        mensaje=(
                            f"Periodos solapados en la misma obra (CUI {cui}): "
                            f"'{a.cargo_experiencia}' ({a.fecha_inicio_cert.strftime('%d/%m/%Y')} - "
                            f"{a.fecha_fin_cert.strftime('%d/%m/%Y')}) vs "
                            f"'{b.cargo_experiencia}' ({b.fecha_inicio_cert.strftime('%d/%m/%Y')} - "
                            f"{b.fecha_fin_cert.strftime('%d/%m/%Y')}). "
                            "Puede ser rotacion legitima entre cargos pero revisar."
                        ),
                    ))
    return senales


def _detectar_misma_obra_mismo_cargo_distinto_profesional(
    cruces: list[ResultadoCruceExperiencia],
) -> list[SenalCruce]:
    """
    Detecta si dos profesionales DEL CONCURSO ACTUAL declaran haber tenido
    el mismo cargo en la misma obra en periodos solapados. Uno de los dos
    podria estar mintiendo (o hubo rotacion legitima).
    """
    senales: list[SenalCruce] = []
    # Agrupar por (cui, cargo_experiencia normalizado)
    por_obra_cargo: dict[tuple, list[ResultadoCruceExperiencia]] = {}
    for c in cruces:
        if not c.cui or not c.cargo_experiencia:
            continue
        cargo_norm = c.cargo_experiencia.lower().strip()
        por_obra_cargo.setdefault((c.cui, cargo_norm), []).append(c)

    for (cui, cargo_norm), lista in por_obra_cargo.items():
        # Filtrar a profesionales DISTINTOS
        nombres_distintos = {c.nombre_profesional for c in lista}
        if len(nombres_distintos) < 2:
            continue
        # Hay 2+ profesionales del concurso declarando el mismo cargo en la misma obra
        nombres = ", ".join(sorted(nombres_distintos))
        senales.append(SenalCruce(
            severidad="observacion",
            fuente="cv_interno",
            mensaje=(
                f"Multiples profesionales del concurso actual declaran el cargo "
                f"'{cargo_norm}' en la obra CUI {cui}: {nombres}. "
                "Puede ser rotacion legitima o uno de los dos esta declarando mal."
            ),
        ))
    return senales


# ── Cruce por experiencia ────────────────────────────────────────────────────

def cruzar_experiencia(
    exp: Experience,
    cargo_postulado: str,
    nombre_profesional: str,
    obra: Optional[WorkInfo],
) -> ResultadoCruceExperiencia:
    """
    Cruza una experiencia individual contra los datos de InfoObras de su obra.
    """
    res = ResultadoCruceExperiencia(
        nombre_profesional=nombre_profesional,
        cargo_postulado=cargo_postulado,
        proyecto=exp.project_name or "",
        cargo_experiencia=exp.role,
        cui=exp.cui,
        folio=exp.folio,
        fecha_inicio_cert=exp.start_date,
        fecha_fin_cert=exp.end_date,
    )

    # Si la experiencia no tiene CUI, no hay como cruzar con InfoObras
    if not exp.cui:
        return res

    # Si no se pudo encontrar la obra (CUI invalido o obra eliminada)
    if not obra:
        res.obra_encontrada = False
        res.senales.append(SenalCruce(
            severidad="informativa",
            fuente="infoobras_paralizacion",
            mensaje=f"No se pudo encontrar la obra con CUI {exp.cui} en InfoObras (puede que el CUI sea invalido o la obra no este registrada).",
        ))
        return res

    res.obra_encontrada = True
    res.nombre_obra_infoobras = obra.nombre
    res.fecha_inicio_obra = obra.fecha_inicio
    res.fecha_fin_obra = obra.fecha_fin
    res.estado_obra = obra.estado

    # ── Senales de validacion CV vs duracion obra ──────────────────────────
    res.senales.extend(_calcular_senales_cv(exp, obra))

    # ── Nivel 1: paralizaciones del periodo del cert ──────────────────────
    if exp.start_date and exp.end_date:
        for av in obra.avances:
            estado = (av.estado or "").lower()
            if "paraliz" not in estado and "suspend" not in estado:
                continue
            if not av.anio or not av.mes:
                continue
            try:
                # Convertir mes string a int si hace falta
                mes_int = av.mes if isinstance(av.mes, int) else int(av.mes)
                anio_int = av.anio if isinstance(av.anio, int) else int(av.anio)
                ini_mes = date(anio_int, mes_int, 1)
                if mes_int == 12:
                    fin_mes = date(anio_int, 12, 31)
                else:
                    fin_mes = date(anio_int, mes_int + 1, 1)
                # Verificar solapamiento con periodo del cert
                if exp.start_date <= fin_mes and exp.end_date >= ini_mes:
                    res.paralizaciones.append({
                        "anio": anio_int,
                        "mes": mes_int,
                        "estado": av.estado,
                        "tipo": av.tipo_paralizacion,
                        "dias": av.dias_paralizado,
                        "causal": av.causal,
                    })
                    res.dias_paralizado_en_periodo += int(av.dias_paralizado or 0)
            except (ValueError, TypeError):
                continue

    if res.paralizaciones:
        sev = "observacion" if res.dias_paralizado_en_periodo < 30 else "critica"
        res.senales.append(SenalCruce(
            severidad=sev,
            fuente="infoobras_paralizacion",
            mensaje=(
                f"La obra estuvo paralizada {len(res.paralizaciones)} mes(es) durante el periodo "
                f"del certificado ({res.dias_paralizado_en_periodo} dias en total). "
                "Esos dias deberian descontarse del computo de experiencia efectiva (Paso 5)."
            ),
        ))

    # ── Nivel 2: verificacion nominal (solo Supervisor/Residente) ─────────
    cargo_tipo = _clasificar_cargo_para_infoobras(cargo_postulado)
    if not cargo_tipo and exp.role:
        cargo_tipo = _clasificar_cargo_para_infoobras(exp.role)
    if cargo_tipo:
        res.aplica_verif_nominal = True
        verif: VerificacionProfesional = verificar_profesional_en_obra(
            obra=obra,
            nombre_profesional=nombre_profesional,
            cargo_tipo=cargo_tipo,
            fecha_inicio_cert=exp.start_date,
            fecha_fin_cert=exp.end_date,
        )
        res.nombre_coincide = verif.nombre_coincide
        res.score_nombre = verif.score_nombre
        res.nombre_encontrado_infoobras = verif.nombre_encontrado
        res.periodo_valido = verif.periodo_valido

        # Generar senales especificas de la verificacion nominal
        if not verif.nombre_coincide:
            res.senales.append(SenalCruce(
                severidad="critica",
                fuente="infoobras_nominal",
                mensaje=(
                    f"El nombre '{nombre_profesional}' NO coincide con ningun "
                    f"{cargo_tipo} registrado en InfoObras para esta obra "
                    f"(score maximo: {verif.score_nombre:.2f}). "
                    + (f"InfoObras tiene a '{verif.nombre_encontrado}' como {cargo_tipo}." if verif.nombre_encontrado else "")
                ),
            ))
        elif verif.nombre_coincide and not verif.periodo_valido and exp.start_date:
            # Nombre matchea pero el periodo declarado no cae dentro del que figura en InfoObras
            res.senales.append(SenalCruce(
                severidad="critica",
                fuente="infoobras_nominal",
                mensaje=(
                    f"'{nombre_profesional}' SI figura como {cargo_tipo} en InfoObras pero "
                    f"el periodo del certificado ({exp.start_date.strftime('%d/%m/%Y')} - "
                    f"{exp.end_date.strftime('%d/%m/%Y') if exp.end_date else 'a la fecha'}) "
                    "no coincide con el periodo registrado oficialmente. "
                    "Probable sobredeclaracion del tiempo trabajado."
                ),
            ))

    return res


# ── API publica ──────────────────────────────────────────────────────────────

def cruzar_resultados(
    resultados: list[ResultadoProfesional],
    cache_obras: Optional[dict[str, Optional[WorkInfo]]] = None,
) -> ResultadoCruceJob:
    """
    Cruza todas las experiencias de un job (post-Paso 4) contra InfoObras.

    Args:
        resultados: list[ResultadoProfesional] del Paso 4 (motor de reglas).
        cache_obras: cache opcional para evitar fetch_by_cui duplicados.
                     Si None, se crea uno interno. Pasalo desde fuera para
                     persistir entre llamadas.

    Returns:
        ResultadoCruceJob agregando cruces de todas las experiencias +
        senales globales (cross-CV, cross-profesional).
    """
    if cache_obras is None:
        cache_obras = {}

    job_resultado = ResultadoCruceJob()
    cuis_no_encontrados: set[str] = set()

    for rp in resultados:
        prof = rp.profesional
        nombre_prof = prof.name or ""
        cargo_postulado = prof.role or ""

        # Iterar evaluaciones del Paso 4 (cada una envuelve una Experience)
        cruces_del_profesional: list[ResultadoCruceExperiencia] = []
        for ev in rp.evaluaciones:
            exp = ev.experiencia_ref
            if not exp:
                continue

            # Resolver obra (con cache). Estrategia:
            # 1. Si exp.cui existe -> fetch_by_cui (directo, rapido)
            # 2. Si no -> buscar_obra_por_certificado por nombre+fecha (puede no
            #    encontrar pero al menos lo intentamos)
            obra: Optional[WorkInfo] = None
            cache_key: Optional[str] = None

            if exp.cui:
                cache_key = f"cui:{exp.cui}"
                if cache_key in cache_obras:
                    obra = cache_obras[cache_key]
                else:
                    try:
                        obra = fetch_by_cui(exp.cui)
                        cache_obras[cache_key] = obra
                        job_resultado.cuis_consultados += 1
                        if not obra:
                            cuis_no_encontrados.add(exp.cui)
                    except Exception as e:
                        logger.warning("[cruce-infoobras] fetch_by_cui(%s) fallo: %s", exp.cui, e)
                        cache_obras[cache_key] = None
                        cuis_no_encontrados.add(exp.cui)
            elif exp.project_name and len(exp.project_name) >= 10:
                # Fallback: buscar por nombre del proyecto
                cache_key = f"proj:{exp.project_name[:80].lower().strip()}"
                if cache_key in cache_obras:
                    obra = cache_obras[cache_key]
                else:
                    try:
                        obra = buscar_obra_por_certificado(
                            project_name=exp.project_name,
                            cert_date=exp.cert_issue_date,
                            entidad=None,
                        )
                        cache_obras[cache_key] = obra
                        if obra:
                            job_resultado.cuis_consultados += 1
                    except Exception as e:
                        logger.warning(
                            "[cruce-infoobras] buscar_obra_por_certificado fallo para '%s': %s",
                            exp.project_name[:60], e,
                        )
                        cache_obras[cache_key] = None

            cruce = cruzar_experiencia(
                exp=exp,
                cargo_postulado=cargo_postulado,
                nombre_profesional=nombre_prof,
                obra=obra,
            )
            cruces_del_profesional.append(cruce)

        # Senales por solapamiento dentro del mismo profesional
        senales_solapamiento = _detectar_solapamientos_mismo_profesional(cruces_del_profesional)
        # Pegar al primer cruce del profesional (no inflar la lista global)
        if senales_solapamiento and cruces_del_profesional:
            cruces_del_profesional[0].senales.extend(senales_solapamiento)

        job_resultado.cruces.extend(cruces_del_profesional)

    job_resultado.cuis_no_encontrados = sorted(cuis_no_encontrados)

    # Senales globales: misma obra + mismo cargo entre profesionales del concurso
    job_resultado.senales_globales.extend(
        _detectar_misma_obra_mismo_cargo_distinto_profesional(job_resultado.cruces)
    )

    logger.info(
        "[cruce-infoobras] %d experiencias cruzadas, %d CUIs consultados, "
        "%d alertas, %d obras no encontradas",
        len(job_resultado.cruces),
        job_resultado.cuis_consultados,
        sum(len(c.senales) for c in job_resultado.cruces) + len(job_resultado.senales_globales),
        len(job_resultado.cuis_no_encontrados),
    )
    return job_resultado
