"""
Verificación de vigencia de colegiatura CIP (ALT09).
"""
from typing import Optional


def is_active(cip_number: str) -> Optional[bool]:
    """Retorna True si el CIP está vigente, False si no, None si no se pudo consultar."""
    raise NotImplementedError
