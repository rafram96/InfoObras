# Módulo: Rules (Motor de Alertas + Paso 5)

> `src/validation/rules.py` — ~400 líneas — ✅ Completo

## Propósito
Motor de reglas determinístico: 9 alertas por experiencia + cálculo de días efectivos (Paso 5).

## Funciones

| Función | Líneas | Descripción |
|---------|--------|-------------|
| `check_alerts(exp, proposal_date, ...)` | ~150 | Aplica 9 reglas a una experiencia. Parámetros opcionales para datos externos. |
| `calculate_effective_days(experiences, proposal_date, suspension_periods)` | ~60 | Suma días brutos - COVID - paralizaciones. Fusiona periodos para no descontar doble. |
| `calculate_effective_years(...)` | ~15 | Convierte días a años (÷365.25, 1 decimal). |
| `_fecha_hace_20_anos(proposal_date)` | ~10 | Calcula fecha 20 años atrás. Maneja Feb 29. |
| `_periodos_solapan(a_start, a_end, b_start, b_end)` | ~15 | Retorna True si dos periodos se solapan. |
| `_overlap_days(a_start, a_end, b_start, b_end)` | ~20 | Retorna días de solapamiento entre dos periodos. |

## Sistema de alertas

| Código | Lógica | Severidad | Datos requeridos |
|--------|--------|-----------|------------------|
| ALT01 | `end_date > cert_issue_date` | WARNING | Automático |
| ALT02 | Periodo solapa COVID (16/03/2020–31/12/2021) | WARNING | Automático |
| ALT03 | `end_date < proposal_date - 20 años` | WARNING | Automático |
| ALT04 | `sunat_start > exp.start_date` | CRITICAL | Manual (SUNAT) |
| ALT05 | `end_date is None` | CRITICAL | Automático |
| ALT06 | Cargo no match con RTM | CRITICAL | RequisitoPersonal |
| ALT07 | Profesión no match con RTM | CRITICAL | RequisitoPersonal |
| ALT08 | Tipo obra no match con RTM | CRITICAL | RequisitoPersonal |
| ALT09 | Colegiatura no vigente | WARNING | Manual (colegios) |

## Degradación elegante
Cuando un dato externo es `None`, la alerta correspondiente NO se genera:
- `sunat_start_date=None` → ALT04 no se evalúa
- `requisito=None` → ALT06, ALT07, ALT08 no se evalúan
- `cip_vigente=None` → ALT09 no se evalúa

## Cálculo de días efectivos

```
Por cada experiencia con fecha_inicio y fecha_fin:
  1. días_brutos = (fin - inicio).days
  2. Colectar descuentos:
     ├─ COVID: solapamiento con 16/03/2020–31/12/2021
     └─ Paralizaciones: solapamiento con cada periodo de suspensión
  3. Fusionar descuentos (evitar doble descuento si COVID y paralización solapan)
  4. días_netos = max(0, brutos - total_descuento)
  5. Sumar al total
```

## Constantes
- `COVID_START = date(2020, 3, 16)`
- `COVID_END = date(2021, 12, 31)`

## Limitaciones
- COVID: descuento puede ser impreciso si varias experiencias solapan con el mismo periodo
- No implementado: ALT10 (días declarados vs calculados)
- Redondeo de años fijo a 1 decimal

## Dependencias
- `matching` (para ALT06, ALT07, ALT08)
- `models.Experience`, `models.RequisitoPersonal`
