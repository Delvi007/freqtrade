# CHANGELOG

## 7.2.1-sin-simulacion — 09/11/2026 (retirada de la simulación interna; backtesting conservado)

Detalle completo, pruebas y limitaciones: `docs/INFORME_RETIRO_SIMULACION.md`.

### Retirado
- Modalidad `simulacion` del autotrader y su adaptador `trader/simulador.py` (aperturas, cierres, P&L y saldos ficticios).
- Bot binario de simulación `binaria/bot.py`, su base de operaciones simuladas (`binaria/almacen.py`), su riesgo (`binaria/riesgo.py`) y el adaptador desactivado.
- Motores A (espejo) y B (operaciones autónomas) y supervisor de fills del Laboratorio: desactivados en la operativa; `titan_lab.db` queda como ARCHIVO.
- Ruta de órdenes con dinero real: bloqueada por código (autotrader y adaptador cTrader en LIVE).

### Añadido
- **Orden maestra C2–C9** (`docs/PLATAFORMA_AVANZADA.md`):
  - **C2:** matriz de 25 brokers/plataformas verificada en vivo.
  - **C3:** conectores OANDA, Alpaca y Tradier (implementados), Kraken y Coinbase (datos públicos verificados; firma de Kraken comprobada con el vector oficial).
  - **C4:** centro de brokers con interruptor ON/OFF, DEMO/REAL (REAL de solo lectura), credenciales en la bóveda, diagnóstico, registro de actividad y sincronización sin duplicados (posiciones, órdenes, ejecuciones con comisiones/swaps/parciales).
  - **C5:** biblioteca científica en numpy (bayes, GARCH, HMM, Kalman, OU, Hurst, entropías, Ledoit-Wolf, paridad de riesgo, CVaR, Kelly, CUSUM, Merton, logística walk-forward).
  - **C6:** cerebro autónomo bayesiano con decisiones trazables y reversibles (bloquea solo en práctica; en REAL solo recomienda; no toca protecciones).
  - **C7:** laboratorio cuántico experimental (QAOA, VQE y QAE con simulador propio y datos reales; sin ventaja atribuida).
  - **C8:** centro de servidores con racks de 5 LED de estado real y panel técnico al hacer doble clic.
  - **C9:** supervisor con prioridades, métricas reales con psutil, reinicio automático y gestión de carga.
- **Interruptor universal:** verde ON / rojo OFF con la indicación encima, en toda la plataforma.
- **Noticias fase 2:** datos oficiales del BLS, alertas del calendario y de noticias urgentes en la campana y Telegram, y léxico en español.
- **Pruebas de rendimiento:** `python -m titan_quant.rendimiento`.
- **Pruebas:** 33 nuevas (426 + 159, todas correctas).
- **C10 · Seguridad** (`titan_quant/seguridad/interruptores.py`): botón **⛔ PARADA TOTAL** en la barra superior (bloquea toda orden nueva a todos los brokers, detiene los 4 bots y opcionalmente pide el cierre de todas las posiciones) e **interruptor por broker** (cTrader, IQ Option). Detener: siempre permitido; reanudar/desbloquear: solo el usuario, con contraseña y desde el propio dispositivo — cualquier origen automático (IA, sistema, bot) recibe PermissionError. Comprobación en el ciclo, en los controles de cada orden y de nuevo en el punto único de envío (defensa en profundidad). Protección automática: 3 órdenes sin confirmar en 30 min bloquean el broker (solo el usuario lo desbloquea). Ajustes de riesgo PROTEGIDOS que un proceso automático no puede cambiar y MODO LIVE que solo enciende el usuario (y nunca con la parada activa). Banner rojo, alerta crítica y auditoría de cada acción. 7 pruebas nuevas.
- **C1 · Auditoría** (`docs/AUDITORIA_C1.md`) y copia de seguridad verificada (`../RESPALDO_20261109_C1_auditoria/`).
- **Inteligencia de noticias** (`titan_quant/noticias/`, módulo 📰 Noticias, `docs/NOTICIAS.md`): 42 fuentes catalogadas (31 conectadas y probadas en vivo el 09/11/2026: Fed, BCE, BoE, BoJ, BoC, RBA, RBNZ, SNB, BLS, SEC, CFTC, FINRA, ESMA, FCA, CME, Bloomberg/FT/WSJ/Economist solo titulares, CNBC, MarketWatch, Nasdaq, Investing, CoinDesk, The Block, Decrypt, Cointelegraph, Bitcoin Magazine y calendario semanal), y no disponibles documentadas (Reuters, FMI, OCDE, Banco Mundial, Barron's, BEA y Yahoo por robots.txt). Calificación interna de 1 a 6 estrellas por 10 criterios; recopilación con ETag, robots.txt, frecuencia mínima, reintentos y protección SSRF; deduplicación entre fuentes con confirmación; análisis de categoría, entidades, sentimiento, tono monetario, rumores, urgencia, sorpresa frente a la previsión y 6 puntuaciones; calendario económico con alertas; entrega de noticias verificadas a los motores 6 (MACRO) y 11 (NEWS) con registro de uso; panel con configuración de fuentes. 18 pruebas nuevas.
- `docs/PENDIENTES.md`: trabajos pendientes organizados (puesta en marcha, noticias fase 2 y la orden maestra por fases).
- Ciclo de vida verificable de cada orden (`fase` + `operacion_eventos`): oportunidad detectada → orden enviada → aceptada →
  abierta confirmada → cerrada confirmada → resultado recibido / error del broker. Conciliación manual de órdenes sin confirmar.
- Dos motores de backtesting con bases propias: `backtest_binaria` (IQ Option, M1, payout observado) y `backtest_ctrader`
  (cTrader DEMO, spread medido): walk-forward, fuera de muestra, ventaja estadística y detección de sobreoptimización.
- `cli verificar-brokers` (prueba real trazable de ambos conectores), `cli backtest-binaria`, `cli backtest-ctrader`, panel web.

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
- Bot de binarias (PRACTICE) que no se detiene: 1 % del capital leído de IQ Option antes de CADA operación, hasta 10 operaciones simultáneas (exposición 10,5 %), sin límites de pérdida diaria/semanal/drawdown ni pausa por racha (`sin_limites_perdida`, forzado a False en REAL), y si IQ Option tarda en dar el saldo se usa el último saldo real de menos de 15 min en vez de saltarse el ciclo. Umbral de Keltner+RCI en 65. Indicador `ctrader/TitanLineasSLTP.cs` para ver stop loss y take profit a 3 px en cTrader.
- Escaneo de TODOS los mercados del broker: las señales en vivo se buscan en todos los pares aptos del ranking (antes solo los 15 mejores), de mejor a peor y con tiempo máximo por ciclo (cTrader 150 s, binarias 45 s); las velas de cada activo y temporalidad se piden una vez por ciclo. El re-backtest procesa 10 activos por ciclo en cTrader y 6 en binarias, con tiempo máximo (150 s / 40 s); el cursor avanza solo lo procesado, y el spread de cTrader se mide como mucho cada 15 min por símbolo.
- Riesgo:beneficio de cTrader: riesgo = 0,5 % del capital; objetivo SIEMPRE 1:2; 1:3 solo con ventaja (tendencia a favor y ≥ 0,1 R fuera de muestra, ≥ 20 ops); 1:4 con ventaja fuerte (≥ 0,3 R). Máximo 1:4 (antes 1:5) y la tendencia sola ya no sube el objetivo.
- Bot de binarias detenido por un solo par: si el recolector continuo y el bot consultaban a la vez el estado de las binarias (get_all_init_v2), el segundo recibía «desconocido», caía a get-instruments (que no responde para turbo/binary) y el fallo de un par (p. ej. COFFEE-OTC) abortaba el escaneo entero. Ahora la consulta en curso se comparte, se usa el último estado real si tiene menos de 5 min, un par OTC con estado conocido no consulta get-instruments y cada par se aísla en el escaneo.
- Bot de binarias bloqueado por el drawdown diario: el perfil de práctica usa 0,5 % por operación y límites diarios/semanales más amplios; la cuenta REAL mantiene límites estrictos explícitos (1 %, 3 % diario, 5 % drawdown) y ya no hereda los de práctica.

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
