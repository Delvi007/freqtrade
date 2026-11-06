# CHANGELOG

## 7.2.0 — 05/11/2026 (cTrader DEMO y REAL, cuentas separadas)

### Añadido
- **cTrader opera de verdad**, por la Open API oficial (WebSocket + JSON, solo biblioteca estándar):
  - DEMO por `demo.ctraderapi.com` y REAL (LIVE) por `live.ctraderapi.com`.
  - Órdenes a mercado con stop y objetivo relativos, tamaño calculado con el riesgo y el saldo real de la cuenta (con conversión de divisa), redondeado hacia abajo al paso de volumen; si no llega al mínimo, la orden se rechaza.
  - Seguimiento de posiciones (reconcile), resultado neto real (bruto + swap + comisión) desde los deals de cierre, cierre en la parada de emergencia.
  - Velas del propio broker para el análisis (los motores ven el mismo precio con el que se ejecuta) y bid/ask reales para el control de spread.
  - Renovación automática del token; el nuevo token se guarda cifrado.
  - OAuth pide ahora `scope=trading` (antes `accounts`, solo lectura).
- **Tres bots independientes — tú eliges en cuál operar:** Simulación, DEMO y REAL. Cada uno tiene su configuración, su estado, sus límites de pérdida y **su propia base de datos**:
  `datos/cuentas/simulacion.db`, `datos/cuentas/demo.db`, `datos/cuentas/real.db`.
  Una cuenta real no se acepta en la modalidad demo ni al revés (se comprueba con cTrader en cada sesión).
- **Conocimiento compartido** (`datos/conocimiento.db`): lo único común. Guarda cada resultado en R (resultado ÷ riesgo) por estrategia e instrumento, sin importes, saldos ni números de cuenta. El Laboratorio y los modelos de los motores siguen siendo comunes.
- REAL exige: batería de pruebas superada, cTrader autorizado, al menos 1 operación DEMO cTrader abierta y cerrada por TITAN, frase + contraseña desde el propio teléfono, y contraseña otra vez cada vez que se inicia. Por defecto también exige **ventaja demostrada** (≥ 30 operaciones en el conocimiento con expectativa > 0) y riesgo 0,5 %.
- Interfaz: selector de cuenta [Simulación | DEMO | REAL LIVE], cuentas cTrader filtradas por tipo, símbolos de la cuenta, panel de conocimiento compartido, avisos de dinero real.
- Historial por cuenta (Operaciones · DEMO, Bot · REAL…). `respaldar` copia cada cuenta por separado.
- `importar-secretos` encuentra también `TITAN_CTRADER_CONNECTOR` dentro de proot y lee JSON/.env con nombres variados.
- Servidor cTrader simulado para pruebas (`pruebas/ctrader_falso.py`).

### Migración
- Al arrancar, las operaciones, decisiones y estado del bot que estaban en `titan_quant.db` se copian a la base de su modalidad (una sola vez). Los bots quedan **detenidos**. No se borra nada de `titan_quant.db`.

## 7.1.0 — 05/11/2026 (acceso del administrador y correo)

### Resuelto
- **No se podía entrar porque el correo de confirmación no llegaba.** Ahora la primera cuenta creada desde el propio teléfono (127.0.0.1) es la del ADMINISTRADOR PROPIETARIO y queda activada al instante, sin correo. Si ya te habías registrado, basta con iniciar sesión desde el teléfono: tu cuenta se activa al entrar.
- **Hotmail/Outlook.com no puede ENVIAR correo por SMTP** (Microsoft desactivó el acceso con contraseña). Integraciones → Correo (SMTP) trae ahora configuraciones listas para Gmail (con contraseña de aplicación) y Brevo, mensajes de error que explican qué hacer, y un botón de correo de prueba.

### Añadido
- Panel de **Administración** (solo administradores):
  - Lista de cuentas y solicitudes.
  - Aprobar con envío de correo de aceptación, rechazar, suspender y reactivar.
  - Reenviar la confirmación, cerrar sesiones y quitar el bloqueo por intentos fallidos.
  - Elegir si las cuentas nuevas necesitan aprobación.
  - Nombrar o retirar administradores (solo el propietario).
- Flujo de solicitud: el usuario pide una cuenta y confirma su correo. Los administradores reciben un aviso (alerta, Telegram y correo). El administrador aprueba y el usuario recibe el correo de aceptación.
- CLI: `verificar-correo` ahora confirma y aprueba; nuevos comandos `hacer-admin` y `usuarios`.
- Migración 4 del esquema: columnas `aprobado`, `admin`, `suspendido` y `ultimo_acceso_ts`.
- `actualizar_termux.sh`: actualiza una instalación v7 conservando cuentas y datos. Si el instalador detecta una v7 existente, pasa a actualizar.
- Pruebas: 73 automáticas (antes 62) y 45 comprobaciones de navegador (antes 38).

## 7.0.0 — 05/11/2026 (implementación de la Orden Maestra sobre el backup del mismo día)

### Añadido

- Paquete `titan_quant/` con los 23 motores y su contrato común, 4 niveles, 3 políticas, procesamiento adaptativo y diagnóstico de hardware.
- Cuentas: registro, verificación por correo, inicio de sesión, recuperación, sesiones, eventos de seguridad y roles.
- Bóveda de credenciales cifradas, Configuración e integraciones (9 proveedores, estados reales, OAuth de cTrader dentro de TITAN).
- TITAN AUTO TRADER: simulación con precios reales, 14 controles de riesgo, parada de emergencia y registro de decisiones. Adaptador de IQ Option solo en PRACTICE; adaptador de cTrader solo de lectura; modo real bloqueado.
- Centro de alertas con sonidos configurables. Historial unificado con ocultar, archivar y restaurar, y eliminación permanente separada.
- Interfaz: pantalla de bienvenida, registro e inicio de sesión, ANALIZAR MERCADO y las vistas Motores, Inteligencia, Hardware, Diagnóstico, Integraciones, Bot operador, Alertas, Historial, Preferencias y Mi cuenta. Se conserva el diseño existente.
- CLI `python3 -m titan_quant.cli`, `titan.sh`, `instalar_termux.sh`, 62 pruebas nuevas y una prueba de navegador.

### Corregido

- `lab_engine._latido`: los argumentos estaban invertidos. La tabla `lab_procesos` crecía sin límite y el panel no veía los hilos. Se repararon las filas corruptas.
- `api_web.py`: escuchaba en `0.0.0.0` sin autenticación mientras decía «solo loopback». Ahora usa `127.0.0.1` por defecto y todo pasa por el servidor con sesión.
- `api_web.py`: la ruta fija de Termux para el HTML impedía restaurar el proyecto. La interfaz ahora vive en `web/`.
- `quotes_web`/`chart_web`: los futuros GC=F se mostraban como «XAU/USD» (spot). Ahora la etiqueta indica la fuente real.
- `probar.py`: dos pruebas estaban desactualizadas tras añadir la categoría ETF y AMD al catálogo.
- `titan_bot.py`: se eliminaron 3 funciones duplicadas (código muerto), sin cambiar el comportamiento.
- Errores 500 que devolvían el texto de la excepción.
- `api_web.py`: `with sqlite3.connect()` no cierra la conexión; se perdía una conexión por petición. Ahora se usa `closing()`.
- Cada hilo de petición y del grupo de motores cierra su conexión SQLite al terminar.

### Movido a `legado/`

Módulos que nadie importaba: `titan_integral.py`, `titan_tecnico.py`, `analisis_macro.py` v1, `reparar_integracion.py`, `resumen_noticias.py` y `auditar_*.py`. Siguen disponibles.

No se incluyen: los 8 `parche_*.py`, las 33 carpetas `respaldo_*`, las copias `.bak` ni ningún secreto. Todo eso sigue en tu dispositivo.
