# Módulo: Excel Writer

> `src/reporting/excel_writer.py` — ~600 líneas — ✅ Completo

## Propósito
Genera el Excel final con 5 hojas: el entregable principal al cliente.

## Función principal

```python
write_report(resultados, output_path, proposal_date, filename, infoobras_data) → Path
```

## Hojas

### Hoja 1 — Resumen
- Metadata: archivo, fecha propuesta, fecha análisis
- Totales: profesionales, match RTM, experiencias, alertas, críticas
- Tabla por profesional: #, Cargo, Nombre, RTM Match, Experiencias, **Años Efectivos**, Alertas, Críticas
- Colores: verde (RTM match) / rojo (sin match o críticas > 0)

### Hoja 2 — Base de Datos (27 columnas)
Datos completos por experiencia, accedidos via `ev.experiencia_ref`:

| Col | Campo | Fuente |
|-----|-------|--------|
| 1 | Nombre Profesional | Professional.name |
| 2 | DNI / Colegiatura | Professional.registro_colegio o Experience.dni |
| 3 | Nombre del Proyecto | EvaluacionRTM.proyecto_propuesto |
| 4 | Cargo en el Proyecto | EvaluacionRTM.cargo_experiencia |
| 5 | Empresa/Consorcio Emisor | Experience.company |
| 6 | RUC del Emisor | Experience.ruc |
| 7 | Tipo de Obra | tipo_obra_certificado o Experience.tipo_obra |
| 8 | Tipo de Acreditación | Experience.tipo_acreditacion |
| 9 | Fecha de Inicio | Experience.start_date |
| 10 | Fecha de Fin | Experience.end_date |
| 11 | Periodo COVID | Calculado (amarillo si solapa) |
| 12-13 | Reservadas | — |
| 14 | Duración | Calculada (meses) |
| 15 | Fecha de Emisión | Experience.cert_issue_date |
| 16 | Alerta Emisión | "ALERTA" si fin > emisión (amarillo) |
| 17 | Folio | EvaluacionRTM.folio_certificado |
| 18 | Nombre del Firmante | Experience.signer |
| 19 | Cargo del Firmante | — (no extraído aún) |
| 20 | Alerta Firmante | — (requiere validación manual) |
| 21 | Fecha Creación Emisor | — (requiere SUNAT, manual) |
| 22 | Alerta Antigüedad Emisor | — (requiere SUNAT) |
| 23 | Alerta Exp. Antigua | "ALERTA" si > 20 años (amarillo) |
| 24 | Tipo de Documento | Experience.tipo_acreditacion |
| 25 | Código CUI | Experience.cui |
| 26 | Código InfoObras | Experience.infoobras_code |
| 27 | Validación Cruzada Emisor | — (requiere SUNAT) |

### Hoja 3 — Evaluación RTM (22 columnas)
Las 22 columnas del Paso 4 con colores por cumplimiento:
- Verde: SI / CUMPLE
- Rojo: NO / NO CUMPLE / NO VALE
- Amarillo: NO EVALUABLE

### Hoja 4 — Alertas
| Col | Campo |
|-----|-------|
| 1 | Profesional |
| 2 | Cargo |
| 3 | Proyecto |
| 4 | Código alerta |
| 5 | Severidad (rojo=CRITICO, amarillo=OBSERVACION) |
| 6 | Descripción |

### Hoja 5 — Verificación InfoObras
| Col | Campo |
|-----|-------|
| 1 | Profesional |
| 2 | Proyecto (Certificado) |
| 3 | CUI |
| 4 | Obra InfoObras |
| 5 | Estado |
| 6 | Fecha Inicio Obra |
| 7 | Supervisores |
| 8 | Residentes |
| 9 | Paralizaciones |
| 10 | Días Suspensión (amarillo si > 0) |

## Estilos

| Estilo | Color | Uso |
|--------|-------|-----|
| GREEN | #C6EFCE | SI, CUMPLE |
| YELLOW | #FFEB9C | NO EVALUABLE, OBSERVACION, COVID |
| RED | #FFC7CE | NO, NO CUMPLE, CRITICO |
| HEADER_FILL | #022448 | Headers (azul oscuro, texto blanco) |
| THIN_BORDER | #D9D9D9 | Bordes de celda |

## Helpers

| Función | Descripción |
|---------|-------------|
| `_apply_header(ws, headers, row)` | Aplica estilos de header a una fila |
| `_auto_width(ws)` | Ajusta ancho de columnas (min 8, max 40) |
| `_fmt_date(d)` | date → "DD/MM/YYYY" o "" |
| `_cumple_fill(valor)` | Retorna fill según "SI"/"NO"/"NO EVALUABLE" |
| `_covid_check(start, end)` | "INCLUYE PERIODO COVID" si solapa |
| `_calc_duracion(start, end)` | Duración en meses o días |

## Limitaciones
- Columnas 19-22, 27 vacías (requieren SUNAT — verificación manual)
- Cargo del firmante (col 19) no se extrae del certificado
- Hoja 5 vacía si no se ejecutó scraping de InfoObras
- Auto-width puede truncar celdas muy largas

## Dependencias
- `openpyxl`
- `models` (Professional, Experience, EvaluacionRTM, ResultadoProfesional)
- `rules` (Alert, Severity, calculate_effective_years)
