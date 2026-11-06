# DATABASE_SCHEMA — TITAN QUANT v7.2

## Bases y separación

| Base | Contenido | Quién escribe |
|---|---|---|
| `datos/titan_quant.db` (permiso 600, WAL) | Usuarios, sesiones, tokens, eventos de seguridad, credenciales cifradas, integraciones, configuración, auditoría, análisis, alertas, visibilidad y estado de motores | `titan_quant` |
| `datos/cuentas/simulacion.db` | Bot de SIMULACIÓN: `bot_estado`, `operaciones`, `decisiones_bot`, `eventos_broker`, `saldos`, `identidad` | `trader/almacen.py` |
| `datos/cuentas/demo.db` | Bot DEMO (cTrader demo / IQ Option PRACTICE): mismas tablas | `trader/almacen.py` |
| `datos/cuentas/real.db` | Bot REAL (cTrader live): mismas tablas | `trader/almacen.py` |
| `datos/conocimiento.db` | **Lo único compartido**: `resultados(ts, origen, estrategia, instrumento, horizonte, direccion, r, motivo)` — R normalizado, sin importes, saldos ni IDs | `trader/almacen.py` |
| `titan_activos.db` (heredada) | Hipótesis del bot de Telegram, noticias por activo y escenarios | `agente.py`, `escenarios.py` |
| `titan_planes.db` (heredada) | Planes de la web y su seguimiento | `plan_web.py` |
| `titan_lab.db` (heredada) | Laboratorio: operaciones simuladas, decisiones, modelos, alertas y métricas | `lab_engine.py` |

Lo existente no se duplica: el historial unificado lee los planes y el laboratorio directamente de sus bases, en solo lectura.

## Esquema nuevo (migraciones versionadas en `titan_quant/db.py`)

- **v1:** `usuarios` (correo único sin distinguir mayúsculas; rol propietario o usuario), `sesiones` (id = SHA-256 del token), `tokens` (hash, tipo, caducidad, uso), `eventos_seguridad`, `credenciales` (blob cifrado y máscara; único por usuario, proveedor y campo), `integraciones` (estado y ajustes no secretos), `config_usuario`, `config_sistema` y `auditoria` (solo se añade, nunca se borra).
- **v2:** `analisis` (resultado completo en JSON), `alertas` (único por usuario y clave anti-duplicados), `alertas_silencio`, `visibilidad` (ocultar o archivar sin borrar) y `estado_motores`.
- **v3:** `bot_estado`, `operaciones` (modalidad simulación/demo/real, controles y motores en JSON, índice único anti-duplicados) y `decisiones_bot`.

- **v7.2:** las tablas del bot pasan a las bases por cuenta. Cada base guarda su modalidad en `identidad`; si un archivo se abre como otra modalidad, TITAN se niega («no se mezclan cuentas»). Las copias v3 de `titan_quant.db` se conservan sin uso.

Todas las tablas de usuario tienen `FOREIGN KEY … ON DELETE CASCADE` y hay índices por usuario y fecha.

## Políticas

- Antes de cada migración se hace un respaldo automático. Cada migración es una transacción: si falla, se revierte entera.
- Ocultar o archivar no borra nada. La eliminación permanente solo es posible para análisis archivados, la hace el propietario con una frase de confirmación y queda en la auditoría.
- Las operaciones, alertas, decisiones y la auditoría no se eliminan nunca.
- **Reparación v7:** se eliminaron 5 727 filas corruptas de `titan_lab.db/lab_procesos` (eran latidos técnicos guardados con un nombre igual a la hora, por un fallo). Queda constancia en `lab_aprendizaje`. Antes de la reparación, el instalador guarda el backup `datos/respaldos/migracion_*.tar.gz`.
