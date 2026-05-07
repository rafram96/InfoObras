"""
Cache persistente SUNAT en PostgreSQL.

Tabla `sunat_cache` con TTL diferenciado:
  - found=TRUE  → TTL 30 días (datos cambian poco)
  - found=FALSE → TTL 1 día   (RUC puede activarse después)

Configurable via env:
  SUNAT_CACHE_TTL_DAYS     (default 30)
  SUNAT_NEG_CACHE_TTL_DAYS (default 1)

Uso típico:
  with _get_conn() as conn:
      sunat_cache.init_table(conn)
      hit, empresa = sunat_cache.get(conn, ruc)
      if not hit:
          empresa = consultar_ruc(ruc)
          sunat_cache.set(conn, ruc, empresa)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import psycopg2.extras

from src.scraping.sunat import EmpresaSUNAT

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = int(os.getenv("SUNAT_CACHE_TTL_DAYS", "30"))
NEG_CACHE_TTL_DAYS = int(os.getenv("SUNAT_NEG_CACHE_TTL_DAYS", "1"))


def init_table(conn) -> None:
    """
    Crea la tabla `sunat_cache` si no existe. Idempotente.
    Llamarla una vez al inicio de la app o antes del primer get/set.
    """
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sunat_cache (
                ruc        TEXT PRIMARY KEY,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                found      BOOLEAN NOT NULL,
                payload    JSONB
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS sunat_cache_fetched_at_idx "
            "ON sunat_cache (fetched_at)"
        )


def get(conn, ruc: str) -> tuple[bool, Optional[EmpresaSUNAT]]:
    """
    Busca un RUC en cache.

    Returns:
        (cache_hit, empresa)
          - (False, None): no hay entry o expiró → consultar SUNAT
          - (True, None):  cached como "no encontrado" (negative cache)
          - (True, EmpresaSUNAT): cached con datos válidos
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT fetched_at, found, payload FROM sunat_cache WHERE ruc = %s",
            (ruc,),
        )
        row = cur.fetchone()

    if not row:
        return False, None

    age = datetime.now(timezone.utc) - row["fetched_at"]
    ttl = timedelta(days=CACHE_TTL_DAYS if row["found"] else NEG_CACHE_TTL_DAYS)
    if age > ttl:
        # Expirado, ignorar (la próxima llamada a set lo sobrescribirá)
        return False, None

    if not row["found"]:
        return True, None

    return True, _empresa_from_payload(ruc, row["payload"] or {})


def set(conn, ruc: str, empresa: Optional[EmpresaSUNAT]) -> None:
    """Guarda o reemplaza un entry en cache (UPSERT)."""
    payload = json.dumps(empresa.to_dict(), ensure_ascii=False) if empresa else None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sunat_cache (ruc, fetched_at, found, payload)
            VALUES (%s, NOW(), %s, %s::jsonb)
            ON CONFLICT (ruc) DO UPDATE SET
                fetched_at = NOW(),
                found = EXCLUDED.found,
                payload = EXCLUDED.payload
        """, (ruc, empresa is not None, payload))


def purge_expired(conn) -> int:
    """
    Borra entries expiradas. Devuelve número de filas borradas.
    Llamar manualmente cuando quieras liberar espacio.
    """
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM sunat_cache
            WHERE (found = TRUE  AND fetched_at < NOW() - INTERVAL '%s days')
               OR (found = FALSE AND fetched_at < NOW() - INTERVAL '%s days')
        """, (CACHE_TTL_DAYS, NEG_CACHE_TTL_DAYS))
        return cur.rowcount


def _empresa_from_payload(ruc: str, payload: dict) -> EmpresaSUNAT:
    """Reconstruye EmpresaSUNAT desde el dict cacheado en JSONB."""
    if not payload:
        return EmpresaSUNAT(ruc=ruc)

    fi = payload.get("fecha_inscripcion")
    fia = payload.get("fecha_inicio_actividades")

    return EmpresaSUNAT(
        ruc=payload.get("ruc") or ruc,
        razon_social=payload.get("razon_social"),
        nombre_comercial=payload.get("nombre_comercial"),
        tipo_contribuyente=payload.get("tipo_contribuyente"),
        fecha_inscripcion=date.fromisoformat(fi) if fi else None,
        fecha_inicio_actividades=date.fromisoformat(fia) if fia else None,
        estado=payload.get("estado"),
        condicion=payload.get("condicion"),
        domicilio_fiscal=payload.get("domicilio_fiscal"),
        actividades_economicas=payload.get("actividades_economicas") or [],
    )
