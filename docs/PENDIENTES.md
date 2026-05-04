# Pendientes y backlog

> Documento generado en sesión 2026-05-03 cuando ClickUp dejó de aceptar tasks
> por desautorización del MCP. Estos tasks deberían ser migrados a ClickUp
> cuando se restablezca el acceso.

## ⏳ Pendientes de validación (cosas pusheadas, no probadas)

### [VALIDAR-1] Filas 7/8/17 sin warning falso positivo (commit `fa317ad`)

**Branch**: `main` Alpamayo
**Estado**: Mergeado, no probado tras el reorden del validador.

Cambios:
- `_detectar_copy_paste_fabricacion` ahora corre AL FINAL del pipeline
- Skip si todos los items vienen del 3-capas
- Skip si descripciones B.2 son distintas >30%

Cómo probar:
1. Re-correr Huancavelica desde `/historial`
2. Verificar que filas 7, 8, 17 ya NO muestran warning naranja "patrón formulaico"

### [VALIDAR-2] Descripción B.2 expandible + listas verticales (Panel commit `9cdcee1`)

**Branch**: `main` Panel-InfoObras
**Estado**: Mergeado, falta confirmación visual.

Cambios:
- Columna "Experiencia Mín." con chevron `<details>` expandible (antes truncaba a 80 chars)
- Profesiones y Cargos similares como listas verticales con bullets

Cómo probar: abrir `/jobs/<id>` tab RTM Personal → click chevron "Ver descripción literal del PDF".

### [VALIDAR-3] Dark mode refinado (Panel commit `98ccefb`)

**Branch**: `main` Panel-InfoObras
**Estado**: Mergeado, falta confirmación visual.

Cambios paleta secondary, tertiary, on-surface, surfaces escalonadas, rojos del needs_review con dark variants.

Cómo probar: toggle dark mode + verificar contraste y filas needs_review en dark.

### [VALIDAR-4] Capa 3 robusta cuando Capa 2 falla (commit `b3c9159`)

**Branch**: `main` Alpamayo
**Estado**: Mergeado, difícil de probar (Capa 2 funciona ahora).

Cambios:
- threshold catálogo OSCE: 85 → 92
- partial_ratio → token_set_ratio
- Dedup global por cargo canónico
- Cap a `n_esperadas × 1.3` filas

Cómo probar: forzar fallo de Capa 2 (ej: comentar `MOTOR_OCR_PYTHON` en `.env`) y verificar que Capa 3 devuelve ~17 filas, no 51.

### [VALIDAR-5] Excel writer Lircay (branch `feat/excel-lircay`)

**Branch**: `feat/excel-lircay` (NO mergeado)
**Estado**: Construido, esperando prueba del usuario.

Módulo: `src/reporting/excel_writer_lircay.py` con 5 hojas formato Lircay:
- PROFESIONALES, REQUISITOS_TDR, BD_EXPERIENCIAS, ANALISIS_RTM, RESUMEN

Cómo probar: en server, `git checkout feat/excel-lircay`, generar contra job `e09f58ba` o `488fdd76`, comparar con `10. Lircay 16.04.26.xlsx`.

---

## 🚀 Pendientes de implementación

### [IMPL-1] Cruce automático InfoObras Nivel 1+2 (PRIORIDAD ALTA)

Decisión del usuario: solo lo contrastable, NO Especialistas.

- Nivel 1: paralizaciones del periodo del cert (cubre 17 cargos)
- Nivel 2: verif nominal Supervisor + Residente (2 cargos, detecta rotación)
- Branch: `feat/cruce-infoobras`
- Endpoint: `POST /api/jobs/{id}/cruce-infoobras`
- Estimación: ~3-4 horas

### [IMPL-2] Vista panel `/herramientas/profesionales/[jobId]` con cruce

Tabla con columnas: Profesional, Cargo, Proyecto, Periodo Cert, Periodo InfoObras, Match Nombre (✓/✗ + score), Paralizaciones detectadas, Alertas. Depende de IMPL-1.

### [IMPL-3] Mejorar Excel Lircay con cols Cowork

Agregar al BD_EXPERIENCIAS: Título Profesional, Universidad de Titulación, Fecha de Titulación, Entidad Contratante (separar de Empresa Emisora), Ubicación, Nivel/Categoría, Área Construida, Monto del Contrato. Total ~35 cols.

### [IMPL-4] Botón "Abrir SEACE" en panel

Pre-rellenar búsqueda en SEACE con datos de InfoObras (entidad, año, RUC contratista) para acelerar flujo manual del evaluador. ~1 hora.

### [IMPL-5] Validar pipeline 3-capas con 2-3 TDRs adicionales

Anti-overfit: anotar golden literal de 2-3 TDRs distintos (sector salud + construcción), medir F1, confirmar generalización. ~30 min por TDR = 2-3 horas total.

### [IMPL-6] Test manual SEACE — confirmar plantel profesional

Verificar empíricamente si la propuesta técnica del adjudicatario es pública en SEACE para el caso Hospital Espinar (concurso 67-2020-PRONIS). 10 minutos manual. Bloquea decisión sobre invertir en scraping anti-CAPTCHA.

### [IMPL-7] Fix CUDNN paddlepaddle-gpu en server

```powershell
& "D:\proyectos\InfoObras\motor-OCR\venv\Scripts\python.exe" -m pip install paddlepaddle-gpu==3.2.0 --force-reinstall --no-deps -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

Para que Capa 2 (PP-Structure) deje de crashear con segfault `0xC0000005`. ~15 minutos.

---

## 💡 Ideas / mejoras de diseño

### [IDEA-1] LIS sobre números detectados — segmentación robusta Capa 3

Encontrar la longest increasing subsequence sobre números (1, 2, 3, ..., 17) en el OCR para identificar inicios de fila independiente del catálogo OSCE. Reduce cross-row.

### [IDEA-2] Agregar `grado_titulo_profesional` al schema

Hoy se descarta "Titulado profesional" / "Bachiller" / "Colegiado" del TDR. Agregarlo permite alertar si postor presenta solo "Bachiller" cuando se pide "Titulado".

### [IDEA-3] Agregar `especialidades_aplicables` (Lista B de B.2) al schema

Hoy se descarta la lista después de "en/de:" (Telecomunicaciones, Cableado Estructurado, etc.). Para Paso 4: cuando CV declara "Especialista en X", verificar X contra Lista B.

### [IDEA-4] Validación cruzada profesión↔cargo determinística

Tabla de incompatibilidades por keyword: ej `COMUNICACIONES` rechaza `MEDICO`, `TECNOLOGO`, etc. ~30 líneas en cell_parser.py.

### [IDEA-5] LAYER3_MAX_WORKERS via env var

Hoy hardcoded a 4 en `layer3_regex_rows.py`. Convertir a `int(os.getenv("LAYER3_MAX_WORKERS", "4"))` para tunear según VRAM disponible.

---

## 🐛 Bugs menores

### [BUG-1] `_diagnostico_3capas` no se persiste en `result` JSON

Solo se loguea, no se guarda en BD. Imposible debuguear post-mortem desde Postgres.

Fix:
```python
resultado["_diagnostico_3capas"] = extraccion_3capas.diagnostico
resultado["_capa_usada"] = extraccion_3capas.capa_usada
```

### [BUG-2] pgAdmin reiniciándose en docker compose

`docker compose ps` muestra `pgadmin Restarting (1)`. Probable problema de permisos del volumen del config. No bloqueante (psql del container `db` funciona).

---

## 🧹 Cleanup

### [CLEAN-1] Mover `excel_writer.py` viejo a `_legacy.py`

Cuando el writer Lircay sea validado por el cliente, reemplazar el writer principal. Alternativa: query param `?format=lircay|legacy` en `/api/jobs/{id}/excel`.

### [CLEAN-2] Eliminar o re-anotar `rtm_huancavelica.json` viejo

El golden viejo tiene combinaciones inventadas (Lista A × Lista B). El cliente quiere fidelidad al PDF. La versión `rtm_huancavelica_literal.json` es la buena. El viejo es engañoso → eliminar.

---

## ❌ Investigado y descartado (no repetir)

### [DESCARTADO-1] Decolecta API para ALT04

Decolecta `/v1/sunat/ruc/full` NO devuelve `fecha_inscripcion_RUC`. ALT04 (empresa post-experiencia) NO se puede automatizar con Decolecta.

APIs probadas:
- Decolecta — no tiene fecha inscripción
- apis.net.pe — comparte token con Decolecta, mismo backend
- apisperu.com — requiere token, no verificado
- SUNAT directo — CAPTCHA, costoso automatizar

ALT04 sigue como verificación manual del evaluador.

### [DESCARTADO-2] Informes de Control para listar personal

PDFs de auditoría son narrativos. Mencionan ausencias de personal pero NO listan plantel completo. No vale la pena parsear.

### [DESCARTADO-3] Documentos del Sumario InfoObras (Acta, Calendario)

Son administrativos (entrega terreno, ajustes presupuestales, actas de constatación). No incluyen plantel profesional. El campo `lPersonal` en `DatosPreparacion` existe estructuralmente pero está VACÍO en los 4 CUIs probados.

### [DESCARTADO-4] Verificación nominal de Especialistas

InfoObras solo registra Supervisor y Residente nominalmente. Para los 15 cargos restantes (Especialistas) NO hay fuente pública estructurada. Decisión del cliente: aceptar y enfocarse solo en lo contrastable (Sup/Res + paralizaciones).
