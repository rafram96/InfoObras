from __future__ import annotations
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from src.tdr.extractor.parser import parse_full_text
from src.tdr.extractor.scorer import score_page, group_into_blocks, Block, PageScore
from src.tdr.extractor.llm import extraer_bloque
from src.tdr.extractor.report import (
    DiagnosticData, LLMInteraction, generar_reporte,
)
from src.validation.matching import normalizar_cargo as _normalizar_cargo

logger = logging.getLogger(__name__)

# Máximo de caracteres por bloque antes de subdividir
# Con QWEN_NUM_CTX=16384 (~48k chars), un bloque de 30k chars + prompt (≈4k chars)
# deja margen para que el LLM responda. Antes era 15k porque Ollama truncaba a
# 4096 tok por defecto y habia que sub-dividir. Ahora permite que rtm_personal
# (9 paginas de tablas B.1+B.2) llegue ENTERO al LLM sin perder contexto global.
_MAX_BLOCK_CHARS = 30_000
_OVERLAP_PAGES = 1  # páginas de solapamiento entre sub-bloques


def _comprimir_tabla_vl(text: str, max_chars: int = 4000) -> str:
    """
    Comprime tablas markdown grandes generadas por Qwen VL.

    Qwen VL a veces genera dos tipos de filas en una página:
      1. Filas de tablas útiles (B.1/B.2): 3-4+ columnas con datos estructurados.
         En B.2 la columna "TRABAJOS O PRESTACIONES" puede tener 500-700 chars
         listando cargos similares válidos — contenido CRÍTICO, no descarte.
      2. Filas de "descripción de actividades": 2-3 columnas donde una celda tiene
         1000+ chars de narrativa libre.

    Estrategia: eliminar una fila SOLO si tiene celda > _MAX_CELDA_GRANDE chars Y
    la fila tiene pocas columnas no-vacías (<=3). Si tiene 4+ columnas es tabla
    legítima aunque alguna celda sea larga.
    """
    if len(text) <= max_chars:
        return text

    # Detectar si el texto tiene tablas markdown (líneas con |)
    lineas = text.split("\n")
    lineas_tabla = [l for l in lineas if "|" in l and l.strip().startswith("|")]
    if len(lineas_tabla) < 3:
        return text  # No es una tabla significativa

    # Umbral: las celdas de B.2 (cargos similares) llegan a ~700 chars; las
    # descripciones narrativas de Qwen VL suelen ser 1000+. 800 separa bien.
    _MAX_CELDA_GRANDE = 800
    # Guardia: solo eliminar si la fila es angosta (2-3 columnas significativas)
    _MAX_COLS_PARA_DESCARTE = 3

    resultado = []
    filas_eliminadas = 0

    for linea in lineas:
        if "|" not in linea or not linea.strip().startswith("|"):
            resultado.append(linea)
            continue

        celdas_raw = linea.split("|")
        # Remover primera y ultima celda si son vacias (bordes del markdown |...|)
        celdas = [c.strip() for c in celdas_raw]
        # Celdas no-vacias ni de separador ---
        celdas_significativas = [
            c for c in celdas
            if c and not set(c.replace(" ", "")) <= {"-", ":"}
        ]
        max_celda = max((len(c) for c in celdas), default=0)

        # Descartar solo si: celda MUY grande Y pocas columnas significativas
        # (tipico de descripcion pura de actividades, no B.1/B.2 legitima)
        if (
            max_celda > _MAX_CELDA_GRANDE
            and len(celdas_significativas) <= _MAX_COLS_PARA_DESCARTE
        ):
            filas_eliminadas += 1
            continue

        resultado.append(linea)

    texto_comprimido = "\n".join(resultado)

    if filas_eliminadas > 0:
        ahorro = len(text) - len(texto_comprimido)
        logger.info(
            f"[pipeline] Tabla VL comprimida: {len(text)} → {len(texto_comprimido)} chars "
            f"(−{ahorro}, {ahorro*100//len(text)}% reducción, "
            f"{filas_eliminadas} filas de descripción eliminadas)"
        )
    return texto_comprimido


def _es_pagina_tabla_vl(text: str) -> bool:
    """
    Detecta si una página es predominantemente una tabla markdown (VL-enhanced).

    Criterio: >60% de las líneas no-vacías son filas de tabla (empiezan con |)
    y hay al menos 5 filas de tabla.
    """
    lineas = [l for l in text.strip().split("\n") if l.strip()]
    if not lineas:
        return False
    lineas_tabla = [l for l in lineas if l.strip().startswith("|")]
    return len(lineas_tabla) >= 5 and len(lineas_tabla) / len(lineas) > 0.6


def _contar_items_tabla_vl(text: str) -> int:
    """Cuenta filas de datos en una tabla VL (filas que comienzan con | N |)."""
    count = 0
    for line in text.split("\n"):
        if re.match(r"\s*\|\s*\d+\s*\|", line):
            count += 1
    return count


def _subdividir_bloque(block: Block) -> list[Block]:
    """
    Si un bloque supera _MAX_BLOCK_CHARS, lo divide en sub-bloques
    más pequeños con _OVERLAP_PAGES de solapamiento.

    Orden de operaciones:
    1. Detecta páginas VL (tablas limpias) ANTES de comprimir — estas se
       aíslan intactas en sub-bloques propios.
    2. Comprime solo las páginas NO-VL que tengan tablas de descripción.
    3. Agrupa las páginas normales por tamaño.

    Esto garantiza que la tabla B.2 (experiencia, meses) llegue intacta
    al LLM, mientras que las tablas B.1 (descripciones enormes de 500+
    chars por celda) se comprimen para no reventar el contexto.
    """
    # Bloques de capacitación: no comprimir ni subdividir.
    # Las descripciones de capacitación (>200 chars) SON los datos objetivo
    # y _comprimir_tabla_vl las descartaría como "filas de descripción".
    if block.block_type == "capacitacion":
        return [block]


    # ── 1. Detectar páginas VL ANTES de cualquier compresión ────────────
    paginas_vl = []
    paginas_normales = []
    for p in block.pages:
        if _es_pagina_tabla_vl(p.text):
            paginas_vl.append(p)
            logger.debug(
                f"[pipeline] Pág {p.page_num}: detectada como tabla VL "
                f"({len(p.text)} chars)"
            )
        else:
            paginas_normales.append(p)

    # ── 2. Comprimir solo páginas normales con tablas grandes ───────────
    pages_comprimidas = []
    for p in paginas_normales:
        if len(p.text) > 4000 and "|" in p.text:
            texto_comprimido = _comprimir_tabla_vl(p.text)
            if texto_comprimido != p.text:
                p = PageScore(
                    page_num=p.page_num,
                    confidence=p.confidence,
                    text=texto_comprimido,
                    scores=p.scores,
                )
        pages_comprimidas.append(p)

    # ── 3. Si no hay páginas VL y el bloque cabe, devolver directo ──────
    if not paginas_vl:
        block_comprimido = Block(
            block_type=block.block_type, pages=pages_comprimidas,
        )
        if len(block_comprimido.text) <= _MAX_BLOCK_CHARS:
            return [block_comprimido]

    # ── 4. Construir sub-bloques ────────────────────────────────────────
    sub_bloques = []

    # 4a. Sub-bloques aislados para cada página VL (intactas, sin comprimir)
    for p in paginas_vl:
        sub_bloques.append(Block(block_type=block.block_type, pages=[p]))
        logger.info(
            f"[pipeline] Pág {p.page_num} aislada como sub-bloque VL "
            f"({len(p.text)} chars, tabla markdown)"
        )

    # 4b. Sub-bloques normales con las páginas comprimidas restantes
    pages = pages_comprimidas
    total_normal_chars = sum(len(p.text) for p in pages)

    if pages and total_normal_chars <= _MAX_BLOCK_CHARS:
        # Todas las normales caben en un solo sub-bloque
        sub_bloques.append(Block(block_type=block.block_type, pages=pages))
    elif pages:
        # Subdividir por tamaño
        i = 0
        while i < len(pages):
            sub_pages = []
            chars = 0
            while i < len(pages) and (chars + len(pages[i].text)) <= _MAX_BLOCK_CHARS:
                sub_pages.append(pages[i])
                chars += len(pages[i].text)
                i += 1

            if not sub_pages and i < len(pages):
                sub_pages.append(pages[i])
                i += 1

            if sub_pages:
                sub_bloques.append(Block(
                    block_type=block.block_type, pages=sub_pages,
                ))
                if len(sub_pages) > _OVERLAP_PAGES:
                    i -= _OVERLAP_PAGES

    # Ordenar sub-bloques por página inicial para mantener orden lógico
    sub_bloques.sort(key=lambda sb: sb.pages[0].page_num)

    if len(sub_bloques) > 1:
        n_pages = [len(sb.pages) for sb in sub_bloques]
        total_chars = sum(len(p.text) for sb in sub_bloques for p in sb.pages)
        logger.info(
            f"[pipeline] Bloque '{block.block_type}' págs {block.page_range} "
            f"({total_chars} chars) → {len(sub_bloques)} sub-bloques "
            f"({n_pages} págs)"
        )

    return sub_bloques if sub_bloques else [block]




def _es_nulo(valor: Any) -> bool:
    """True si el valor es None, string vacío o string literal 'null'."""
    if valor is None:
        return True
    if isinstance(valor, str) and valor.strip().lower() in ("null", "none", ""):
        return True
    return False


def _limpiar_nulls(obj: Any) -> Any:
    """Convierte strings 'null'/'none' a None en cualquier estructura anidada."""
    if isinstance(obj, dict):
        return {k: _limpiar_nulls(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_limpiar_nulls(i) for i in obj]
    if isinstance(obj, str) and obj.strip().lower() in ("null", "none"):
        return None
    return obj


def _contar_campos(obj: Any) -> tuple[int, int]:
    """
    Cuenta (total_campos, campos_nulos) de forma recursiva.
    Para dicts anidados, cuenta sus campos internos en vez del dict como 1 campo.
    Para listas, cuenta como nulo si está vacía.
    """
    if isinstance(obj, dict):
        total = 0
        nulos = 0
        for v in obj.values():
            t, n = _contar_campos(v)
            total += t
            nulos += n
        return total, nulos
    # Un campo hoja
    es_nulo = _es_nulo(obj) or (isinstance(obj, list) and len(obj) == 0)
    return 1, (1 if es_nulo else 0)


_CARGO_KW_REGEX = (
    r"(?:ESPECIALISTA|GERENTE|JEFE|INGENIERO|SUPERVISOR|COORDINADOR|RESIDENTE|"
    r"INSTALACIONES|SUPERVISI[OÓ]N|CAMPO|CONTROL|ARQUITECTURA|ESTRUCTURAS|"
    r"COMUNICACIONES|EQUIPAMIENTO|SEGURIDAD|MEDIO|COSTOS|GEOTECNIA|BIM|"
    r"ELECTROMEC|AMBIENTE|CALIDAD|METRADOS|VALORIZACIONES|HOSPITALARIO|"
    r"SANITARIAS|ELECTRICAS|EL[EÉ]CTRICAS|MEC[AÁ]NICAS|CONTRATO)"
)


def _detectar_numeros_cargo(texto: str) -> set[int]:
    """
    Encuentra TODOS los numeros asociados a cargos de personal clave en el texto.
    Retorna el set de numeros detectados (ej: {1, 2, 3, ..., 17}).
    Uso: comparar contra los items extraidos para saber cuales N° faltan.
    """
    nums: set[int] = set()
    patron = (
        r"(?:^|\n|\|)\s*(\d{1,2})\s*[\n\s|]*"
        rf"{_CARGO_KW_REGEX}"
    )
    for m in re.finditer(patron, texto, re.IGNORECASE | re.MULTILINE):
        try:
            n = int(m.group(1))
            if 1 <= n <= 30:
                nums.add(n)
        except ValueError:
            continue
    return nums


def _detectar_max_numero_cargo(texto: str) -> int:
    """Alias retrocompatible: retorna solo el maximo detectado."""
    nums = _detectar_numeros_cargo(texto)
    return max(nums) if nums else 0


def _inferir_numero_cargo(cargo: str, texto: str) -> Optional[int]:
    """
    Dado un cargo extraido por el LLM, busca su N° correspondiente en el texto.
    Retorna el numero si lo encuentra, None si no.
    """
    if not cargo or not texto:
        return None
    palabras_distintivas = re.findall(r"\b[A-ZÁÉÍÓÚÑ]{4,}\b", cargo.upper())
    if not palabras_distintivas:
        return None
    # Tomar la ultima palabra distintiva (suele ser la mas especifica)
    for palabra in palabras_distintivas[-2:]:
        for m in re.finditer(
            rf"(\d{{1,2}})[\s\n\|]{{0,30}}{re.escape(palabra)}|{re.escape(palabra)}[\s\n\|]{{0,30}}(\d{{1,2}})",
            texto, re.IGNORECASE,
        ):
            try:
                n = int(m.group(1) or m.group(2))
                if 1 <= n <= 30:
                    return n
            except (ValueError, TypeError):
                continue
    return None


def _ordenar_rtm_personal_por_pdf(items: list[dict], full_text: str) -> list[dict]:
    """
    Ordena items de rtm_personal segun el N° del PDF.
    Prioridad: campo `numero_fila` del LLM > inferencia heuristica > orden relativo.
    """
    if not items:
        return items
    indexed: list[tuple[int, int, dict]] = []  # (numero, orden_original, item)
    for idx, item in enumerate(items):
        # 1. Campo explicito del LLM (preferido)
        num = item.get("numero_fila")
        if not (isinstance(num, int) and 1 <= num <= 30):
            # 2. Fallback heuristico
            num = _inferir_numero_cargo(item.get("cargo", ""), full_text)
        # 3. Los sin num van al final (99) manteniendo orden
        indexed.append((num if num is not None else 99, idx, item))
    indexed.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in indexed]


def _numeros_faltantes(texto: str, items_extraidos: list[dict]) -> list[int]:
    """
    Compara numeros detectados en el texto con los que el LLM efectivamente
    extrajo segun su campo `numero_fila`.

    Si un item no tiene numero_fila (LLM viejo o sin respeto al schema),
    cae al inferidor heuristico.
    """
    nums_texto = _detectar_numeros_cargo(texto)
    if not nums_texto:
        return []

    nums_cubiertos: set[int] = set()
    for item in items_extraidos:
        # Preferir el campo explicito del LLM
        n_explicito = item.get("numero_fila")
        if isinstance(n_explicito, int) and 1 <= n_explicito <= 30:
            nums_cubiertos.add(n_explicito)
            continue
        # Fallback heuristico solo si no hay numero_fila
        n_inferido = _inferir_numero_cargo(
            item.get("cargo") or "", texto,
        )
        if n_inferido is not None:
            nums_cubiertos.add(n_inferido)

    faltantes = sorted(nums_texto - nums_cubiertos)
    return faltantes


_PREFIJOS_CARGO = (
    "especialista", "jefe", "gerente", "supervisor", "coordinador",
    "responsable", "inspector", "residente", "ingeniero de campo",
    "asistente", "director", "arquitecto de obra", "arquitecto de campo",
    "arquitecto especialista",
)
_PREFIJOS_PROFESION = (
    "ingeniero", "arquitecto", "tecnologo", "tecnólogo", "medico", "médico",
    "licenciado", "bachiller", "quimico", "químico", "geologo", "geólogo",
    "economista", "administrador",
)


def _es_profesion_real(texto: str) -> bool:
    """True si `texto` parece un titulo universitario y NO un puesto de trabajo."""
    if not texto:
        return False
    t = texto.strip().lower()
    if len(t) < 4:
        return False
    # Si empieza con un prefijo de CARGO, NO es profesion (contaminacion de B.2)
    if any(t.startswith(p) for p in _PREFIJOS_CARGO):
        return False
    # Patrones de CARGO aunque empiecen con "Ingeniero"/"Arquitecto":
    # "Ingeniero Supervisor de Obra", "Arquitecto de Campo", "Ingeniero de
    # campo y de obra", etc. La marca son los sufijos "de obra/campo/proyecto/
    # contrato/supervisi0n/equipo".
    _CARGO_SUFIJOS = (
        "de obra", "de campo", "de proyecto", "de contrato",
        "de supervisi", "de equipo", "hospitalario de obra",
    )
    if any(suf in t for suf in _CARGO_SUFIJOS):
        return False
    # "Ingeniero" a secas (sin especialidad) no es una profesion valida:
    # necesita especialidad (Civil, Sanitario, Electromecanico, etc.). En
    # cambio, "Arquitecto", "Tecnologo", "Medico" a secas SI son titulos
    # completos validos segun la tabla B.1 (ej: ESPECIALISTA EN ARQUITECTURA
    # tiene profesion "Arquitecto" literal).
    if t in ("ingeniero", "supervisor"):
        return False
    # Si empieza con un prefijo de PROFESION, si es profesion
    return any(t.startswith(p) for p in _PREFIJOS_PROFESION)


def _limpiar_profesiones_y_cargos(item: dict) -> dict:
    """
    Separa contaminacion entre profesiones_aceptadas (titulos) y
    cargos_similares_validos (puestos). El LLM a veces mezcla ambas columnas.
    """
    profs = item.get("profesiones_aceptadas") or []
    if not isinstance(profs, list):
        return item
    exp = item.get("experiencia_minima") or {}
    if not isinstance(exp, dict):
        exp = {}
    cargos_sim = exp.get("cargos_similares_validos") or []
    if not isinstance(cargos_sim, list):
        cargos_sim = []

    profs_limpias = []
    cargos_movidos = []
    for p in profs:
        if not isinstance(p, str):
            continue
        if _es_profesion_real(p):
            profs_limpias.append(p)
        else:
            # No parece profesion — probable puesto contaminado desde B.2
            cargos_movidos.append(p)

    if cargos_movidos:
        logger.info(
            "[validador] Cargo '%s': %d puesto(s) movido(s) de profesiones a "
            "cargos_similares_validos: %s",
            item.get("cargo", "?"), len(cargos_movidos), cargos_movidos,
        )

    item["profesiones_aceptadas"] = profs_limpias
    # Agregar los movidos a cargos_similares_validos (sin duplicar)
    if cargos_movidos:
        existentes_lower = {c.lower() for c in cargos_sim if isinstance(c, str)}
        for c in cargos_movidos:
            if c.lower() not in existentes_lower:
                cargos_sim.append(c)
        exp["cargos_similares_validos"] = cargos_sim
        item["experiencia_minima"] = exp

    return item


def _normalizar_para_fuzzy(texto: str) -> str:
    """Normaliza texto para comparacion fuzzy: minusculas, sin tildes, sin signos."""
    import unicodedata
    txt = unicodedata.normalize("NFD", texto.lower())
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", txt)


def _cargo_aparece_en_texto(cargo: str, texto_fuente: str, min_ratio: float = 75) -> bool:
    """
    Verifica que `cargo` aparezca (aproximadamente) en `texto_fuente`.
    Usa substring case-insensitive primero. Si falla, usa fuzzy con RapidFuzz
    DESLIZANDO una ventana del mismo tamaño del cargo sobre el texto:
    calcula partial_ratio con una porcion del texto fuente del mismo tamaño
    para cada posicion razonable. Esto evita que "ESPECIALISTA EN EDIFICACIONES"
    sea aceptado solo porque "edificaciones" aparece aislado en "edificaciones
    y afines".

    Retorna False si el cargo no tiene evidencia en la fuente — probable alucinacion.
    """
    if not cargo or not texto_fuente:
        return True  # no filtrar si falta info

    cargo_norm = _normalizar_para_fuzzy(cargo).strip()
    texto_norm = _normalizar_para_fuzzy(texto_fuente)

    if not cargo_norm:
        return True
    # 1. Substring directo (caso normal)
    if cargo_norm in texto_norm:
        return True

    # 2. Verificar que TODOS los tokens significativos del cargo (>=4 chars)
    #    aparezcan en el texto. "ESPECIALISTA EN EDIFICACIONES" requiere que
    #    tanto "especialista" como "edificaciones" esten; no basta solo con
    #    "edificaciones".
    tokens_cargo = [
        t for t in re.split(r"\s+", cargo_norm)
        if len(t) >= 4 and t not in ("para", "como", "segun")
    ]
    if tokens_cargo:
        tokens_faltantes = [t for t in tokens_cargo if t not in texto_norm]
        # Permitir hasta 1 token faltante si el cargo es largo (tipos/accents)
        tolerancia = 1 if len(tokens_cargo) >= 3 else 0
        if len(tokens_faltantes) > tolerancia:
            return False

    # 3. Fuzzy adicional para casos con OCR/acentos: token_set_ratio
    try:
        from rapidfuzz import fuzz
        # token_set_ratio: compara tokens como conjunto, tolerante a orden
        # pero requiere que la mayoria de tokens del cargo esten presentes
        score = fuzz.token_set_ratio(cargo_norm, texto_norm)
        return score >= min_ratio
    except ImportError:
        return True  # sin rapidfuzz, aceptar si tokens_cargo paso


def _marcar_cargos_no_en_fuente(
    items: list[dict],
    texto_fuente: str,
    page_range: tuple,
) -> list[dict]:
    """
    Marca con _needs_review=True los items cuyo cargo no aparece en el texto fuente.
    No elimina — deja que el evaluador humano decida.
    """
    for item in items:
        cargo = item.get("cargo") or ""
        if not _cargo_aparece_en_texto(cargo, texto_fuente):
            item["_needs_review"] = True
            item["_review_reason"] = (
                f"Cargo '{cargo}' no aparece en texto fuente (pags {page_range}). "
                f"Posible alucinacion del LLM."
            )
            logger.warning(
                "[validador] Cargo '%s' (pags %s) no esta en la fuente — marcado _needs_review",
                cargo, page_range,
            )
    return items


def _detectar_copy_paste_fabricacion(items: list[dict]) -> list[dict]:
    """
    Detecta items que son copy-paste formulaico del LLM (patron tipico de alucinacion).
    Si >=2 items comparten EXACTAMENTE las mismas profesiones_aceptadas y
    cargos_similares_validos, probablemente son fabricados — marca _needs_review.
    """
    # Agrupar por firma (profesiones + cargos_similares)
    firmas: dict[tuple, list[int]] = {}
    for idx, item in enumerate(items):
        profs = tuple(sorted(item.get("profesiones_aceptadas") or []))
        exp = item.get("experiencia_minima") or {}
        cargos_sim = tuple(sorted(exp.get("cargos_similares_validos") or []))
        firma = (profs, cargos_sim)
        if profs or cargos_sim:  # ignorar firmas vacias
            firmas.setdefault(firma, []).append(idx)

    for firma, indices in firmas.items():
        if len(indices) < 2:
            continue
        # Patron sospechoso: multiples items con firma identica.
        # El CARGO puede ser real pero las profesiones/cargos_similares_validos
        # fueron resumidos formulaicamente por el LLM.
        profs, cargos_sim = firma
        for idx in indices:
            item = items[idx]
            if not item.get("_needs_review"):
                item["_needs_review"] = True
                item["_review_reason"] = (
                    f"Profesiones aceptadas y cargos similares identicos a otros "
                    f"{len(indices)-1} cargos (patron formulaico). El cargo puede ser "
                    f"real pero sus metadatos probablemente son un resumen vago del "
                    f"LLM — verificar contra el texto fuente."
                )
        logger.warning(
            "[validador] Detectado patron repetitivo: %d items con firma "
            "profesiones=%s cargos_sim=%s — marcados _needs_review",
            len(indices), list(profs), list(cargos_sim),
        )
    return items


def _filtrar_registros_vacios(
    lista: list[dict],
    nombre_seccion: str,
    umbral: float = 0.80,
) -> list[dict]:
    """
    Elimina registros donde el porcentaje de campos nulos >= umbral.
    Por defecto elimina registros con 80% o más de campos nulos.
    """
    filtrados = []
    for registro in lista:
        total, nulos = _contar_campos(registro)
        if total == 0:
            logger.debug(f"[validador] {nombre_seccion}: descartado registro sin campos")
            continue
        ratio = nulos / total
        if ratio >= umbral:
            # Vista previa del registro para el log
            preview = {k: v for k, v in registro.items()
                       if not _es_nulo(v) and k != "archivo"}
            logger.info(
                f"[validador] {nombre_seccion}: descartado registro "
                f"({nulos}/{total} campos nulos = {ratio:.0%}): {preview}"
            )
            continue
        filtrados.append(registro)
    descartados = len(lista) - len(filtrados)
    if descartados:
        logger.info(
            f"[validador] {nombre_seccion}: {descartados} registro(s) descartado(s) "
            f"por tener ≥{umbral:.0%} campos nulos"
        )
    return filtrados


def _extraer_numero_de_string(s: str) -> int | None:
    """
    Extrae el primer número entero de un string como "48 meses" → 48.
    Retorna None si no hay número o si el string es demasiado largo
    (no es un campo de cantidad, sino texto libre).
    """
    if len(s) > 30:  # textos largos no son cantidades
        return None
    m = re.match(r"(\d+)", s.strip())
    return int(m.group(1)) if m else None


def _merge_deep(base: dict, nuevo: dict, base_es_vl: bool = False) -> dict:
    """
    Fusiona dos dicts: campos no-nulos de 'nuevo' rellenan los nulos de 'base'.
    Para sub-dicts (experiencia_minima, capacitacion), fusiona recursivamente.
    Para listas, conserva la más larga.
    Para strings, si ambos son no-nulos conserva el más largo (más informativo).
    Para numéricos, conserva el mayor — EXCEPTO cuando base proviene de una
    tabla VL validada (base_es_vl=True): en ese caso se confía en el valor
    de la tabla limpia y no se sobreescribe con el OCR fragmentado.
    """
    resultado = dict(base)
    for k, v in nuevo.items():
        if k.startswith("_"):
            continue
        base_v = resultado.get(k)
        if isinstance(base_v, dict) and isinstance(v, dict):
            resultado[k] = _merge_deep(base_v, v, base_es_vl)
        elif isinstance(base_v, list) and isinstance(v, list):
            # Si base proviene de una tabla VL, confiar en su lista —
            # no sobreescribir aunque la nueva sea más larga (puede haber
            # confundido columnas adyacentes, como ocurre en tablas densas).
            if not base_es_vl and len(v) > len(base_v):
                resultado[k] = v
        elif _es_nulo(base_v) and not _es_nulo(v):
            resultado[k] = v
        elif (isinstance(base_v, (int, float)) and isinstance(v, (int, float))
              and not _es_nulo(base_v) and not _es_nulo(v)):
            # Si base es VL, sus valores numéricos son los correctos — no sobreescribir
            if not base_es_vl and v > base_v:
                resultado[k] = v
        elif (isinstance(base_v, str) and isinstance(v, str)
              and not _es_nulo(base_v) and not _es_nulo(v)):
            num_base = _extraer_numero_de_string(base_v)
            num_nuevo = _extraer_numero_de_string(v)
            if num_base is not None and num_nuevo is not None:
                # Si base es VL, respetar su número aunque sea menor
                if not base_es_vl and num_nuevo > num_base:
                    resultado[k] = v
            elif len(v) > len(base_v):
                resultado[k] = v
    return resultado


# _normalizar_cargo se importa desde src.validation.matching (ver import arriba)


def _dedup_personal(lista: list[dict]) -> list[dict]:
    """
    Fusiona duplicados de personal clave por cargo normalizado.
    Cuando hay dos entradas del mismo cargo (ej. "Gestor BIM" y
    "Gestor BIM y/o líder BIM..."), combina sus campos:
    los no-nulos de cada entrada se complementan mutuamente.

    Prioridad VL: si una entrada viene de un sub-bloque VL (tabla validada
    visualmente), se usa como base en el merge para que sus valores numéricos
    exactos no sean sobreescritos por el OCR fragmentado.
    """
    por_cargo: dict[str, dict] = {}
    for entrada in lista:
        cargo = entrada.get("cargo")
        if _es_nulo(cargo):
            continue

        cargo_key = _normalizar_cargo(str(cargo))
        es_vl = bool(entrada.get("_vl_source"))

        if cargo_key not in por_cargo:
            por_cargo[cargo_key] = entrada
        else:
            existente = por_cargo[cargo_key]
            existente_es_vl = bool(existente.get("_vl_source"))

            if es_vl and not existente_es_vl:
                # Nueva entrada es VL: usarla como base (sus valores son correctos)
                por_cargo[cargo_key] = _merge_deep(entrada, existente, base_es_vl=True)
                logger.debug(f"[dedup] Fusionado '{cargo}' → '{cargo_key}' (VL base)")
            else:
                por_cargo[cargo_key] = _merge_deep(existente, entrada, base_es_vl=existente_es_vl)
                logger.debug(f"[dedup] Fusionado '{cargo}' → '{cargo_key}'")

    # Quitar campo interno _vl_source antes de devolver
    resultado = []
    for entrada in por_cargo.values():
        entrada.pop("_vl_source", None)
        resultado.append(entrada)
    return resultado


def _extraer_especialidad(cargo: str) -> str | None:
    """
    Extrae la especialidad base de un cargo, independientemente de si es
    "Asistente de X", "Asistente en X", o "Especialista en X".

    Ejemplos:
      "Asistente de Arquitectura"              → "arquitectura"
      "Asistente en Ingeniería Sanitaria"      → "ingeniería sanitaria"
      "Asistente en Instalaciones Eléctricas"   → "instalaciones eléctricas"
      "Especialista en Arquitectura"            → "arquitectura"
      "Especialista en Inst. Mecánicas"         → "instalaciones mecánicas"
      "Jefe de elaboración..."                  → None (no aplica)
    """
    m = re.match(
        r"(?:asistente|especialista)\s+(?:de|en)\s+(.+)$",
        cargo.strip(), re.IGNORECASE,
    )
    return m.group(1).strip().lower() if m else None


def _filtrar_asistentes(lista: list[dict]) -> list[dict]:
    """
    Elimina roles de "Asistente" cuando existen "Especialistas" en los
    resultados. En documentos OSCE, los Asistentes aparecen en la sección
    TDR/Funciones (págs 36-42) y son roles de soporte, NO personal clave
    del concurso (que son los Especialistas de las tablas B.1/B.2).

    Estrategia:
    1. Si hay al menos un Especialista, activar filtro.
    2. Recopilar especialidades normalizadas de Especialistas
       (usa _normalizar_cargo para "en la especialidad de X" → "x").
    3. Para cada Asistente, normalizar su especialidad y comparar.
    4. Si hay match directo → descartar.
    5. Si no hay match pero hay Especialistas → descartar también
       (ej: "Asistente en Ingeniería Civil" no matchea ningún
       Especialista porque el equivalente es "Estructuras", pero
       sigue siendo un rol TDR, no personal clave).
    """
    # Recopilar especialidades normalizadas de Especialistas
    especialidades_cubiertas: set[str] = set()
    tiene_especialistas = False
    for entrada in lista:
        cargo = str(entrada.get("cargo", ""))
        normalizado = _normalizar_cargo(cargo)
        if normalizado.startswith("especialista"):
            tiene_especialistas = True
            # Extraer la parte después de "especialista en "
            m = re.match(r"especialista\s+(?:de|en)\s+(.+)$", normalizado)
            if m:
                especialidades_cubiertas.add(m.group(1).strip())

    if not tiene_especialistas:
        return lista

    resultado = []
    for entrada in lista:
        cargo = str(entrada.get("cargo", ""))
        normalizado = _normalizar_cargo(cargo)
        if normalizado.startswith("asistente"):
            # Extraer especialidad del asistente normalizado
            m = re.match(r"asistente\s+(?:de|en)\s+(.+)$", normalizado)
            esp_asist = m.group(1).strip() if m else None

            if esp_asist and esp_asist in especialidades_cubiertas:
                logger.info(
                    f"[filtro] Descartado '{cargo}' — match directo con "
                    f"Especialista en '{esp_asist}'"
                )
            else:
                # No hay match directo, pero es un Asistente de sección TDR
                # y existen Especialistas → descartar igualmente
                logger.info(
                    f"[filtro] Descartado '{cargo}' — rol de soporte TDR, "
                    f"no es personal clave del concurso"
                )
            continue
        resultado.append(entrada)

    descartados = len(lista) - len(resultado)
    if descartados:
        logger.info(
            f"[filtro] {descartados} Asistente(s) descartado(s) "
            f"(sección TDR, no personal clave)"
        )
    return resultado


# Patrones que identifican cargos genéricos de la sección funcional TDR,
# no del cuadro de personal clave B.1/B.2.
# "Consultoría" y "Consultor de Ingeniería" son meta-descriptores del servicio,
# no especialidades técnicas reales en documentos OSCE.
# "Modelador BIM" es personal no clave (soporte técnico).
_CARGO_META_PATTERNS = [
    r"\bconsultor[ií]a\b",          # "Supervisor de Consultoría", etc.
    r"^consultor\s+de\s+ingenier[ií]a$",  # "Consultor de Ingeniería" exacto
    r"^modelador\b",                # "Modelador BIM" — personal no clave
    r"^especialidad\s*:",           # nota (*) de especialidades, no un cargo
]


def _filtrar_meta_cargos(lista: list[dict]) -> list[dict]:
    """
    Descarta cargos genéricos de secciones TDR funcionales (no personal clave real).

    Activa solo cuando existen Especialistas u otros cargos específicos, para
    no filtrar en documentos donde el único cargo es genérico.
    """
    tiene_especializados = any(
        re.match(
            r"(especialista|jefe|gestor|director|coordinador|arquitecto|ingeniero)\b",
            str(e.get("cargo", "")).strip(), re.IGNORECASE,
        )
        for e in lista
        if not any(
            re.search(p, str(e.get("cargo", "")), re.IGNORECASE)
            for p in _CARGO_META_PATTERNS
        )
    )
    if not tiene_especializados:
        return lista

    resultado = []
    for entry in lista:
        cargo = str(entry.get("cargo", ""))
        if any(re.search(p, cargo, re.IGNORECASE) for p in _CARGO_META_PATTERNS):
            logger.info(
                f"[filtro] Descartado '{cargo}' — cargo genérico de sección funcional TDR"
            )
            continue
        resultado.append(entry)

    descartados = len(lista) - len(resultado)
    if descartados:
        logger.info(
            f"[filtro] {descartados} cargo(s) meta-genérico(s) descartado(s)"
        )
    return resultado


def _limpiar_anos_colegiado(valor: Any) -> Any:
    """
    Elimina sufijos y prefijos OSCE estándar del campo anos_colegiado.

    Ejemplos:
      "24 meses (Computada desde la fecha de la colegiatura)"
        → "24 meses"
      "Título profesional, 36 meses"
        → "36 meses"
      "48 meses (contabilizada desde la emisión del grado o título)"
        → "48 meses"
    """
    if not isinstance(valor, str):
        return valor
    s = valor
    # "N meses" es un placeholder OSCE (valor no especificado) → null
    if re.match(r"^N\s+meses$", s.strip(), re.IGNORECASE):
        return None
    # Quitar prefijo "Título profesional[,] "
    s = re.sub(r"^[Tt][ií]tulo\s+profesional,?\s*", "", s)
    # Quitar paréntesis que contengan términos OSCE sobre cómputo de plazos
    s = re.sub(
        r"\s*\([^)]*(?:colegiatura|grado\s+o\s+t[ií]tulo|t[ií]tulo\s+profesional"
        r"|computada|contabilizada)[^)]*\)",
        "", s, flags=re.IGNORECASE,
    )
    return s.strip()


def _similarity_cargo(a: str, b: str) -> float:
    """Overlap de palabras entre dos strings de cargo normalizados."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))


def _cruzar_personal_con_factores(
    personal: list[dict],
    factores: list[dict],
) -> list[dict]:
    """
    Popula tiempo_adicional_factores en cada cargo de rtm_personal buscando
    si existe un factor de evaluación de experiencia que lo mencione.

    Estrategia en dos pasadas:
    1. Matching específico: cargo_personal del factor coincide con algún cargo.
    2. Fallback genérico: factores cuyo cargo_personal no coincide con ningún
       cargo específico (ej: "Consultoría de Obra") se aplican a todos los
       cargos que aún no tengan tiempo_adicional_factores.
    """
    factores_personal = [
        f for f in factores
        if f.get("aplica_a") == "personal" and not _es_nulo(f.get("cargo_personal"))
    ]
    if not factores_personal:
        return personal

    personal_norms = [
        _normalizar_cargo(str(e.get("cargo", ""))) for e in personal
    ]

    # ── Pasada 1: matching específico ────────────────────────────────────
    factores_matched: set[int] = set()
    for cargo_entry in personal:
        cargo = cargo_entry.get("cargo")
        if _es_nulo(cargo) or not _es_nulo(cargo_entry.get("tiempo_adicional_factores")):
            continue
        cargo_norm = _normalizar_cargo(str(cargo))

        for i_f, factor in enumerate(factores_personal):
            cargo_factor_norm = _normalizar_cargo(str(factor.get("cargo_personal", "")))
            if (cargo_norm == cargo_factor_norm
                    or cargo_norm in cargo_factor_norm
                    or cargo_factor_norm in cargo_norm
                    or _similarity_cargo(cargo_norm, cargo_factor_norm) >= 0.6):
                puntaje = factor.get("puntaje_maximo")
                metodologia = factor.get("metodologia", "")
                cargo_entry["tiempo_adicional_factores"] = (
                    metodologia[:300] if metodologia
                    else (f"Hasta {puntaje} puntos" if puntaje else "Sí evalúa")
                )
                factores_matched.add(i_f)
                logger.debug(
                    f"[cruce] '{cargo}' → factor '{factor.get('factor')}' (específico)"
                )
                break

    # ── Pasada 2: fallback genérico ───────────────────────────────────────
    # Un factor es "genérico" si su cargo_personal no coincide con ningún
    # cargo del personal clave con similaridad ≥ 0.5.
    factores_genericos = [
        factores_personal[i] for i in range(len(factores_personal))
        if i not in factores_matched
        and all(
            _similarity_cargo(
                _normalizar_cargo(str(factores_personal[i].get("cargo_personal", ""))),
                pn,
            ) < 0.5
            for pn in personal_norms
        )
    ]

    if factores_genericos:
        factor_gen = factores_genericos[0]
        puntaje = factor_gen.get("puntaje_maximo")
        metodologia = factor_gen.get("metodologia", "")
        texto_gen = (
            metodologia[:300] if metodologia
            else (f"Hasta {puntaje} puntos" if puntaje else "Sí evalúa")
        )
        for cargo_entry in personal:
            if _es_nulo(cargo_entry.get("tiempo_adicional_factores")):
                cargo_entry["tiempo_adicional_factores"] = texto_gen
                logger.debug(
                    f"[cruce] '{cargo_entry.get('cargo')}' → "
                    f"factor genérico '{factor_gen.get('factor')}'"
                )

    return personal


def _cruzar_postor_con_factores(
    postor: list[dict],
    factores: list[dict],
) -> list[dict]:
    """
    Popula otros_factores_postor en rtm_postor con los factores de evaluación
    que aplican al postor (excluye oferta económica).
    """
    factores_postor = [
        f for f in factores
        if f.get("aplica_a") == "postor"
        and not re.search(
            r"oferta econ[oó]mica|propuesta econ[oó]mica",
            str(f.get("factor", "")), re.IGNORECASE,
        )
    ]
    if not postor or not factores_postor:
        return postor

    factores_text = "; ".join(
        f"{f.get('factor', '')} ({f.get('puntaje_maximo', '')} pts)"
        for f in factores_postor
    )
    for entry in postor:
        if _es_nulo(entry.get("otros_factores_postor")):
            entry["otros_factores_postor"] = factores_text

    return postor


def _guardar_debug_bloques(
    blocks: list[Block],
    output_dir: Path,
) -> None:
    """
    Escribe output/bloques_debug.md con el texto exacto que cada sub-bloque
    envía al LLM. Permite verificar:
    - Si las páginas VL (tablas markdown) están aisladas
    - Si la compresión destruyó datos útiles
    - Qué texto ve el LLM para cada rango de páginas
    """
    from datetime import datetime

    lineas = [
        f"# Debug Sub-bloques → LLM — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**Bloques detectados:** {len(blocks)}",
        "",
        "---",
        "",
    ]

    bloque_num = 0
    for block in blocks:
        sub_blocks = _subdividir_bloque(block)
        for i_sub, sb in enumerate(sub_blocks, 1):
            bloque_num += 1
            es_vl = any(
                _es_pagina_tabla_vl(p.text) for p in sb.pages
            )
            tag = " 🟢 VL AISLADO" if es_vl and len(sb.pages) == 1 else ""

            lineas.append(
                f"## Bloque {bloque_num}: [{block.block_type}] "
                f"págs {sb.page_range} "
                f"({len(sb.text)} chars){tag}"
            )
            lineas.append("")

            if len(sub_blocks) > 1:
                lineas.append(
                    f"*Sub-bloque {i_sub}/{len(sub_blocks)} "
                    f"del bloque original págs {block.page_range}*"
                )
                lineas.append("")

            # Texto por página
            for p in sb.pages:
                es_tabla = _es_pagina_tabla_vl(p.text)
                tag_pag = " 📊 TABLA VL" if es_tabla else ""
                lineas.append(
                    f"### Página {p.page_num} ({len(p.text)} chars){tag_pag}"
                )
                lineas.append("```")
                # Mostrar completo si es tabla VL (son los datos clave),
                # truncar si es texto normal largo
                if es_tabla or len(p.text) <= 2000:
                    lineas.append(p.text)
                else:
                    lineas.append(p.text[:1000])
                    lineas.append(f"\n... ({len(p.text) - 1000} chars más) ...")
                    lineas.append(p.text[-500:])
                lineas.append("```")
                lineas.append("")

            lineas.append("---")
            lineas.append("")

    output_path = Path(output_dir) / "bloques_debug.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lineas), encoding="utf-8")
    logger.info(f"[pipeline] Debug bloques guardado en {output_path}")


def _merge_capacitacion(
    personal: list[dict],
    capacitaciones: list[dict],
) -> list[dict]:
    """
    Cruza capacitaciones extraídas (de la sección TDR) con rtm_personal
    (de la sección B.1/B.2) por cargo normalizado.

    Solo rellena el campo 'capacitacion' si está vacío/null en rtm_personal.
    """
    # Indexar capacitaciones por cargo normalizado
    cap_por_cargo: dict[str, dict] = {}
    for cap in capacitaciones:
        cargo = cap.get("cargo")
        if _es_nulo(cargo):
            continue
        key = _normalizar_cargo(str(cargo))
        cap_por_cargo[key] = cap

    if not cap_por_cargo:
        return personal

    merges = 0
    for entry in personal:
        cargo = entry.get("cargo")
        if _es_nulo(cargo):
            continue

        # Siempre sobreescribir: el bloque capacitacion (tabla VL dedicada)
        # tiene datos más fiables que lo extraído del OCR garbled en rtm_personal.
        key = _normalizar_cargo(str(cargo))
        cap_match = cap_por_cargo.get(key)
        if cap_match:
            entry["capacitacion"] = {
                "tema": cap_match.get("tema"),
                "tipo": cap_match.get("tipo"),
                "duracion_minima_horas": cap_match.get("duracion_minima_horas"),
                "es_factor_evaluacion": False,
            }
            merges += 1
            logger.info(
                f"[capacitacion] Merge '{cargo}' ← capacitación: "
                f"{cap_match.get('tema', '?')} ({cap_match.get('duracion_minima_horas', '?')}h)"
            )

    if merges:
        logger.info(f"[capacitacion] {merges} profesional(es) enriquecido(s) con capacitación")
    else:
        logger.warning(
            f"[capacitacion] 0 matches — cargos en capacitación: "
            f"{list(cap_por_cargo.keys())}"
        )

    # Crear registros esqueleto para cargos que están en capacitacion
    # pero no en rtm_personal (el LLM/VL no los extrajo de B.1/B.2).
    cargos_presentes = {_normalizar_cargo(str(e.get("cargo", ""))) for e in personal}
    # Excluir cargos que son meta/soporte (modelador, asistente, etc.)
    _excluidos = _CARGO_META_PATTERNS + [r"^asistente\b"]

    creados = 0
    for key, cap in cap_por_cargo.items():
        if key in cargos_presentes:
            continue
        # Verificar si el cargo está en la lista de excluidos
        if any(re.search(p, key, re.IGNORECASE) for p in _excluidos):
            continue

        personal.append({
            "cargo": cap.get("cargo"),
            "profesiones_aceptadas": None,
            "anos_colegiado": None,
            "experiencia_minima": {
                "cantidad": None, "unidad": None,
                "descripcion": None, "cargos_similares_validos": None,
                "puntaje_por_experiencia": None, "puntaje_maximo": None,
            },
            "tipo_obra_valido": None,
            "tiempo_adicional_factores": None,
            "capacitacion": {
                "tema": cap.get("tema"),
                "tipo": cap.get("tipo"),
                "duracion_minima_horas": cap.get("duracion_minima_horas"),
                "es_factor_evaluacion": False,
            },
            "pagina": cap.get("pagina"),
        })
        creados += 1
        logger.info(
            f"[capacitacion] Registro esqueleto creado para '{cap.get('cargo')}' "
            f"(no encontrado en B.1/B.2)"
        )

    if creados:
        logger.info(f"[capacitacion] {creados} registro(s) esqueleto creado(s)")

    return personal


def extraer_bases(
    full_text: str,
    nombre_archivo: str = "",
    pdf_path: str = "",
    output_dir: Path | None = None,
) -> dict:
    """
    Pipeline completo: full_text del motor OCR → JSON estructurado.

    Args:
        full_text: Texto completo del _texto_*.md
        nombre_archivo: Nombre del PDF (para metadatos)
        pdf_path: Ruta al PDF original (para mejora de tablas)
        output_dir: Directorio de salida (para generar reporte diagnóstico)

    Returns:
        {
            "rtm_postor":          [...],
            "rtm_personal":        [...],
            "factores_evaluacion": [...],
            "_bloques_detectados": [...],
            "_tablas_stats":       {...}   # estadísticas de mejora de tablas
        }
    """
    # ── Inicializar datos de diagnóstico ──────────────────────────────────
    diag = DiagnosticData(nombre_archivo=nombre_archivo)

    pages  = parse_full_text(full_text)
    scored = [score_page(p) for p in pages]

    # ── Mejora de tablas (antes de agrupar bloques) ──────────────────────
    #    FASE VL: usa Qwen VL para leer tablas visualmente.
    #    Al terminar, descarga VL de Ollama para liberar VRAM antes de Qwen 14B.
    tablas_stats = None
    if pdf_path:
        try:
            from src.tdr.tables.enhancer import mejorar_texto_con_tablas
            # Usar todas las páginas de los bloques (incluye gap pages como 39,40
            # y páginas con heurística baja que sí están dentro de bloques importantes)
            _bloques_pre = group_into_blocks(scored)
            paginas_relevantes = sorted({
                p.page_num for b in _bloques_pre for p in b.pages
            })
            full_text, tablas_stats = mejorar_texto_con_tablas(
                full_text, pdf_path, paginas_relevantes,
            )
            # Re-parsear con el texto mejorado
            pages = parse_full_text(full_text)
            scored = [score_page(p) for p in pages]

        except ImportError as e:
            logger.warning(f"[pipeline] Módulo tables no disponible ({e}), saltando mejora de tablas")
        except Exception as e:
            logger.warning(f"[pipeline] Error en mejora de tablas: {e}")

    # Guardar scores para diagnóstico
    diag.all_scores = list(scored)

    # Capturar datos de tablas si existen
    if tablas_stats:
        diag.tablas_paginas_heuristicas = getattr(
            tablas_stats, "paginas_detectadas_heuristica", []
        )
        diag.tablas_docling_confirmadas = getattr(
            tablas_stats, "paginas_confirmadas_docling", []
        )
        diag.tablas_detalles = getattr(tablas_stats, "detalles", [])

    blocks = group_into_blocks(scored)
    diag.blocks = list(blocks)

    logger.info(f"[pipeline] {len(pages)} páginas → {len(blocks)} bloques")
    for b in blocks:
        logger.info(f"  [{b.block_type}] págs {b.page_range}")

    resultado: dict = {
        "rtm_postor":          [],
        "rtm_personal":        [],
        "factores_evaluacion": [],
        "_bloques_detectados": [],
        "_tablas_stats":       vars(tablas_stats) if tablas_stats else None,
    }
    # Almacén temporal para capacitación extraída (se cruza con rtm_personal después)
    _capacitaciones_raw: list[dict] = []

    # ── Debug: guardar texto de sub-bloques para inspección ──────────────
    if output_dir:
        try:
            _guardar_debug_bloques(blocks, output_dir)
        except Exception as e:
            logger.warning(f"[pipeline] Error guardando debug bloques: {e}")

    t_llm_total = time.perf_counter()
    for i_block, block in enumerate(blocks, 1):
        resultado["_bloques_detectados"].append({
            "tipo":    block.block_type,
            "paginas": list(block.page_range),
        })

        logger.info(
            f"[pipeline] Bloque {i_block}/{len(blocks)}: "
            f"'{block.block_type}' págs {block.page_range} "
            f"({len(block.text)} chars)"
        )

        # Subdividir bloques grandes para que el LLM no pierda contexto
        sub_blocks = _subdividir_bloque(block)

        for i_sub, sub_block in enumerate(sub_blocks, 1):
            # Detectar si este sub-bloque es una tabla VL validada (página única
            # con markdown estructurado). Sus valores numéricos son más fiables
            # que el OCR fragmentado y no deben ser sobreescritos en el merge.
            es_sub_vl = (
                len(sub_block.pages) == 1
                and _es_pagina_tabla_vl(sub_block.pages[0].text)
            )

            # Inyectar conteo de ítems para sub-bloques VL — evita que el LLM
            # salte ítems del medio de la tabla (patrón "skip middle items").
            if es_sub_vl:
                n_items = _contar_items_tabla_vl(sub_block.pages[0].text)
                if n_items >= 3:
                    nota = (
                        f"NOTA: La tabla tiene {n_items} ítems de personal clave "
                        f"(numerados del 1 al {n_items}). "
                        f"Extrae TODOS los {n_items}, uno por uno en orden. "
                        f"No omitas ningún ítem."
                    )
                
                    p = sub_block.pages[0]
                    p_mod = PageScore(
                        page_num=p.page_num,
                        confidence=p.confidence,
                        text=nota + "\n\n" + p.text,
                        scores=p.scores,
                    )
                    sub_block = Block(
                        block_type=sub_block.block_type, pages=[p_mod],
                    )
                    logger.info(
                        f"[pipeline]   VL: {n_items} ítems detectados en tabla, "
                        f"instrucción inyectada"
                    )

            if len(sub_blocks) > 1:
                tag_vl = " [VL]" if es_sub_vl else ""
                logger.info(
                    f"[pipeline]   Sub-bloque {i_sub}/{len(sub_blocks)} "
                    f"págs {sub_block.page_range} ({len(sub_block.text)} chars){tag_vl}"
                )
            t_bloque = time.perf_counter()
            data, llm_diag = extraer_bloque(sub_block)
            dt = time.perf_counter() - t_bloque
            logger.info(
                f"[pipeline]   → {sub_block.block_type} págs {sub_block.page_range}: "
                f"{'OK' if data else 'VACÍO'} en {dt:.1f}s"
            )

            # Registrar interacción LLM para diagnóstico
            diag.llm_interactions.append(LLMInteraction(
                block_type=llm_diag["block_type"],
                page_range=tuple(llm_diag["page_range"]),
                pages_included=llm_diag["pages_included"],
                prompt_chars=llm_diag["prompt_chars"],
                text_preview=llm_diag["text_preview"],
                raw_response=llm_diag["raw_response"],
                cleaned_response=llm_diag["cleaned_response"],
                parsed_ok=llm_diag["parsed_ok"],
                parsed_keys=llm_diag["parsed_keys"],
                items_extracted=llm_diag["items_extracted"],
                error=llm_diag["error"],
            ))

            if not data:
                continue
            data = _limpiar_nulls(data)

            if block.block_type == "rtm_postor":
                items = data.get("items_concurso", [])
                for item in items:
                    if nombre_archivo:
                        item["archivo"] = nombre_archivo
                resultado["rtm_postor"].extend(items)
            elif block.block_type == "rtm_personal":
                items = data.get("personal_clave", [])
                if es_sub_vl:
                    for item in items:
                        item["_vl_source"] = True

                # Retry con numeros faltantes especificos. Detecta que N° aparecen
                # en el FULL TEXT pero no fueron cubiertos por los items extraidos.
                nums_faltantes = _numeros_faltantes(full_text, items)
                n_esperados = _detectar_max_numero_cargo(full_text)
                if nums_faltantes:
                    logger.warning(
                        "[pipeline] LLM extrajo %d cargos pero faltan numeros "
                        "especificos: %s (N max detectado: %d). Disparando retry.",
                        len(items), nums_faltantes, n_esperados,
                    )
                    try:
                        from src.tdr.extractor.llm import retry_cargos_faltantes
                        items_nuevos = retry_cargos_faltantes(
                            full_text, items, n_esperados,
                            numeros_faltantes=nums_faltantes,
                        )
                        if items_nuevos:
                            # Aplicar filtro de contaminacion de columnas
                            # tambien a items del retry (antes se agregaban
                            # directo con profesiones = cargos de B.2).
                            items_nuevos = [
                                _limpiar_profesiones_y_cargos(it)
                                for it in items_nuevos
                            ]
                            # Deduplicar: saltar items del retry cuyo numero_fila
                            # o cargo YA existan en items principales. Evita que
                            # el retry sobreescriba items buenos con versiones
                            # pobres.
                            nums_principales = {
                                it.get("numero_fila") for it in items
                                if it.get("numero_fila") is not None
                            }
                            cargos_principales = {
                                str(it.get("cargo", "")).strip().lower()
                                for it in items
                                if it.get("cargo")
                            }
                            items_nuevos_unicos = []
                            for it in items_nuevos:
                                n_fila = it.get("numero_fila")
                                cargo_norm = str(it.get("cargo", "")).strip().lower()
                                if n_fila is not None and n_fila in nums_principales:
                                    logger.info(
                                        "[pipeline] Retry duplicado: #%s ya en "
                                        "principal, descartando version retry",
                                        n_fila,
                                    )
                                    continue
                                if cargo_norm and cargo_norm in cargos_principales:
                                    logger.info(
                                        "[pipeline] Retry duplicado: '%s' ya en "
                                        "principal, descartando version retry",
                                        cargo_norm,
                                    )
                                    continue
                                items_nuevos_unicos.append(it)
                            items = items + items_nuevos_unicos
                            logger.info(
                                "[pipeline] Retry recupero %d cargo(s) unicos "
                                "(descarto %d duplicados) → total %d",
                                len(items_nuevos_unicos),
                                len(items_nuevos) - len(items_nuevos_unicos),
                                len(items),
                            )
                    except Exception as e:
                        logger.warning("[pipeline] Retry fallo: %s", e)

                # Verificar que cada cargo extraido aparezca en el texto fuente
                # del sub-bloque. Marca _needs_review si no — probable alucinacion.
                items = _marcar_cargos_no_en_fuente(
                    items, sub_block.text, sub_block.page_range,
                )
                # Separar contaminacion de columnas: los "Especialista en X",
                # "Jefe de Y" metidos en profesiones_aceptadas se mueven a
                # cargos_similares_validos (su lugar correcto).
                items = [_limpiar_profesiones_y_cargos(it) for it in items]
                resultado["rtm_personal"].extend(items)
            elif block.block_type == "factores_evaluacion":
                resultado["factores_evaluacion"].extend(data.get("factores_evaluacion", []))
            elif block.block_type == "capacitacion":
                _capacitaciones_raw.extend(data.get("capacitaciones", []))

    # Detectar items con firma copy-paste identica (sintoma de alucinacion LLM).
    # No se descartan — se marcan _needs_review para revision manual.
    resultado["rtm_personal"] = _detectar_copy_paste_fabricacion(
        resultado["rtm_personal"],
    )

    # Post-proceso: deduplicar personal y limpiar entradas vacías
    resultado["rtm_personal"] = _dedup_personal(resultado["rtm_personal"])

    # Ordenar por N° del PDF para que los items del retry queden en su posicion
    # natural (el retry concatena al final, lo que desordena la tabla final).
    resultado["rtm_personal"] = _ordenar_rtm_personal_por_pdf(
        resultado["rtm_personal"], full_text,
    )

    # Pasada dedicada a B.1: una llamada LLM enfocada EXCLUSIVAMENTE en extraer
    # profesiones correctas por numero_fila. Corrige errores del LLM principal
    # y del retry:
    # - Profesiones inventadas ("Ingeniero Geotecnico" en ESTRUCTURAS)
    # - Cross-fila ("Tecnologo Medico" en COMUNICACIONES)
    # - Cargos mezclados como profesiones ("Gerente de Obra" en GERENTE DE CONTRATO)
    # - Profesiones vacias o a secas ("Ingeniero" sin especialidad)
    if resultado["rtm_personal"]:
        try:
            from src.tdr.extractor.llm import reextraer_profesiones_b1
            profs_por_fila = reextraer_profesiones_b1(
                full_text, resultado["rtm_personal"],
            )
            if profs_por_fila:
                actualizados = 0
                for item in resultado["rtm_personal"]:
                    num = item.get("numero_fila")
                    if num is None:
                        num = _inferir_numero_cargo(item.get("cargo", ""), full_text)
                    if num not in profs_por_fila:
                        continue

                    nuevas_profs = profs_por_fila[num]
                    # Filtrar profesiones invalidas en AMBAS fuentes
                    nuevas_limpias = [p for p in nuevas_profs if _es_profesion_real(p)]
                    existentes = item.get("profesiones_aceptadas") or []
                    if not isinstance(existentes, list):
                        existentes = []
                    existentes_limpias = [
                        p for p in existentes
                        if isinstance(p, str) and _es_profesion_real(p)
                    ]

                    # MERGE: union de ambas fuentes para maximizar recall.
                    # Evita regresiones cuando la pasada B.1 devuelve menos
                    # profesiones (ej: pierde 'Arquitecto' en GERENTE DE CONTRATO).
                    # Normaliza por lowercase para dedup case-insensitive.
                    combinado: list[str] = []
                    seen: set[str] = set()
                    for p in list(nuevas_limpias) + list(existentes_limpias):
                        key = p.lower().strip()
                        if key and key not in seen:
                            seen.add(key)
                            combinado.append(p)

                    if combinado:
                        item["profesiones_aceptadas"] = combinado
                        actualizados += 1

                logger.info(
                    "[pipeline] Profesiones B.1 mergeadas: %d/%d items actualizados",
                    actualizados, len(resultado["rtm_personal"]),
                )
        except Exception as e:
            logger.warning("[pipeline] Reextraccion de profesiones B.1 fallo: %s", e)

    # Cruce capacitación → rtm_personal por cargo normalizado
    if _capacitaciones_raw:
        resultado["rtm_personal"] = _merge_capacitacion(
            resultado["rtm_personal"], _capacitaciones_raw,
        )

    # Limpiar sufijos OSCE estándar en anos_colegiado
    for entry in resultado["rtm_personal"]:
        if not _es_nulo(entry.get("anos_colegiado")):
            entry["anos_colegiado"] = _limpiar_anos_colegiado(entry["anos_colegiado"])

    # Corrección de consistencia: anos_colegiado no puede superar la experiencia mínima.
    # Si el OCR extrajo un valor mayor (ej. 48 del Jefe aplicado a un Especialista de 24),
    # se corrige al valor de la experiencia, que es el límite lógico.
    for entry in resultado["rtm_personal"]:
        anos = entry.get("anos_colegiado")
        exp_cantidad = entry.get("experiencia_minima", {}).get("cantidad")
        if (
            isinstance(exp_cantidad, (int, float))
            and exp_cantidad > 0
        ):
            # Extraer número de anos_colegiado si es string ("48 meses" → 48)
            if isinstance(anos, str):
                anos_num = _extraer_numero_de_string(anos)
            elif isinstance(anos, (int, float)):
                anos_num = anos
            else:
                anos_num = None
            if anos_num is not None and anos_num > exp_cantidad:
                logger.info(
                    f"[pipeline] Corrigiendo anos_colegiado de '{entry.get('cargo')}': "
                    f"{anos_num} → {int(exp_cantidad)} (supera experiencia mínima)"
                )
                entry["anos_colegiado"] = int(exp_cantidad)

    # Filtrar "Asistentes" espurios cuando existe un "Especialista" equivalente.
    resultado["rtm_personal"] = _filtrar_asistentes(resultado["rtm_personal"])

    # Filtrar cargos meta-genéricos de secciones funcionales TDR.
    resultado["rtm_personal"] = _filtrar_meta_cargos(resultado["rtm_personal"])

    # Cruce personal ↔ factores: popula tiempo_adicional_factores
    resultado["rtm_personal"] = _cruzar_personal_con_factores(
        resultado["rtm_personal"], resultado["factores_evaluacion"],
    )

    # Validación final: eliminar registros con ≥80% de campos nulos
    resultado["rtm_postor"] = _filtrar_registros_vacios(
        resultado["rtm_postor"], "rtm_postor",
    )
    resultado["rtm_personal"] = _filtrar_registros_vacios(
        resultado["rtm_personal"], "rtm_personal",
    )
    resultado["factores_evaluacion"] = _filtrar_registros_vacios(
        resultado["factores_evaluacion"], "factores_evaluacion",
    )

    # Cruce postor ↔ factores: popula otros_factores_postor
    resultado["rtm_postor"] = _cruzar_postor_con_factores(
        resultado["rtm_postor"], resultado["factores_evaluacion"],
    )

    dt_llm_total = time.perf_counter() - t_llm_total
    logger.info(
        f"[pipeline] Resultado: "
        f"{len(resultado['rtm_postor'])} items postor · "
        f"{len(resultado['rtm_personal'])} profesionales · "
        f"{len(resultado['factores_evaluacion'])} factores · "
        f"LLM total: {dt_llm_total:.1f}s"
    )

    # ── Generar reporte de diagnóstico ────────────────────────────────────
    diag.resultado = resultado
    if output_dir:
        try:
            generar_reporte(diag, output_dir)
        except Exception as e:
            logger.warning(f"[pipeline] Error generando reporte diagnóstico: {e}")

    return resultado