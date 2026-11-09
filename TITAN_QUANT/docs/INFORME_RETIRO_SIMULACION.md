# Informe de entrega — Retirada de la simulación interna y conservación del backtesting

TITAN QUANT v7.2.1 · 09/11/2026

**Resultado:** el bot de binarias opera directamente en IQ Option PRACTICE y el bot cTrader opera directamente en cTrader DEMO (cuenta 49448233). Hay dos motores de backtesting independientes. La operativa ordinaria ya no tiene ninguna simulación interna de operaciones. Ampliación del mismo día (sección 8): cada bot tiene además su cuenta REAL con un interruptor MODO LIVE.

> El bot de cTrader usa la modalidad interna `demo` (cuenta DEMO de cTrader).

## 1. Respaldo verificable (antes de modificar)

| Elemento | Ubicación | Verificación |
|---|---|---|
| Árbol completo del proyecto (incluye `.git`) | `../RESPALDO_20261109_retiro_sim/TITAN_QUANT_v7_2.tar.gz` | SHA-256 en `.sha256` (`sha256sum -c` → OK). Extraído y comparado con `diff -r`: idéntico salvo `titan_lab.db` y `titan_planes.db`, que el servidor en marcha estaba escribiendo. |
| Copia consistente de las 10 bases SQLite | `../RESPALDO_20261109_retiro_sim/bases_consistentes/` | API de backup de SQLite; `PRAGMA integrity_check` = ok en todas; filas y SHA-256 en `bases_consistentes.txt`. |

## 2. Simuladores internos localizados y decisión

| Componente | Qué hacía | Dependencias comprobadas | Decisión |
|---|---|---|---|
| `trader/simulador.py` + modalidad `simulacion` del autotrader | Abría/cerraba operaciones ficticias con precios de Yahoo y calculaba P&L | autotrader, servidor (ficha de brokers), interfaz, pruebas. Ningún backtest | **Eliminado**. `datos/cuentas/simulacion.db` queda en disco como archivo; el código ya no lo abre |
| `binaria/bot.py`, `binaria/almacen.py`, `binaria/riesgo.py`, `binaria/adaptador_iqoption.py` | «Bot binaria en modo simulación» con su base de operaciones simuladas | Solo pruebas; nada en producción | **Eliminados** |
| `lab_engine.py` Motor A (espejo de planes), Motor B (operaciones autónomas) y supervisor (fills, costes, cierres) | Simulación continua en segundo plano con fills y R ficticios | Arrancado por el servidor; `titan_lab.db` | **Desactivados** en la operativa (`SIMULACION_RETIRADA = True`). Las operaciones simuladas abiertas se archivan como CANCELADA sin resultado. El hilo de noticias sigue. La interfaz muestra el Laboratorio como ARCHIVO |
| `binaria_bot/escaner.py` (offline) | Recorre archivos de la sonda y calcula «operaciones» | No envía nada; es un backtest sobre datos grabados | **Conservado** y re-etiquetado: «operaciones calculadas (backtest)» |
| Modalidad REAL | Ruta de órdenes en cTrader LIVE (con frase y contraseña) | autotrader, adaptador cTrader | **Bloqueada por código**: `habilitar_real` y el arranque fallan siempre; el ciclo REAL no opera aunque se fuerce la base; `CTrader.abrir/cerrar` se niegan en LIVE |

## 3. Componentes conservados (backtesting y análisis)

- **Motor 13 BACKTESTING** y Monte Carlo de los 23 motores (análisis; no ejecutan operaciones).
- `binaria_bot/backtest.py`, `binaria_bot/laboratorio.py`, `binaria_bot/estadistica.py`, `binaria_bot/autonomia.py` (walk-forward y evidencia).
- `binaria/senal.py`, `binaria/datos_csv.py` y `binaria/backtest_csv.py` (antes `simulador.py`: era un backtest, solo se renombró).
- `historico.py` (almacén de velas validadas), ahora reutilizable con una base propia por mercado.
- Todos los datos: `titan_lab.db`, `titan_planes.db`, `escaner_vivo.db`, cuentas y conocimiento.

## 4. Ejecución exclusiva en los brokers e integridad

Cada orden tiene una fila en la base de su cuenta (`demo.db` = cTrader DEMO, `binaria.db` = IQ Option PRACTICE) y una traza en `operacion_eventos` con hora, fase, id del broker y evidencia:

`oportunidad_detectada → orden_enviada → orden_aceptada → abierta_confirmada → cerrada_confirmada → resultado_recibido` · `error_broker`

- Oportunidad descartada por controles: `rechazada / oportunidad_detectada`, nunca llega al broker.
- Rechazo del broker: `rechazada / error_broker`.
- Sin respuesta o respuesta ambigua: `error / error_broker` («sin confirmar»). El bot no envía nada más hasta conciliarla (`/api/tq/operador/conciliar` o botón «Conciliar» tras revisar el broker). Nunca se reintenta a ciegas.
- Aceptada pero sin confirmación de apertura: queda `aceptada` (pendiente); se reintenta la confirmación.
- El resultado solo sale del broker (IQ Option: registro `closed_options`; cTrader: deal de cierre con `closePositionDetail`). Si el broker no lo da, la operación sigue pendiente.
- Saldos, límites de pérdida, rachas, drawdown, resúmenes e informes solo cuentan filas con `fase='resultado_recibido'` y `fuente_resultado='broker'`.
- El conocimiento en R se filtra siempre por origen (`demo` o `binaria`): los mercados no se mezclan.
- Bases antiguas: se migran sin perder filas y sin inventar verificaciones (una fila sin id del broker queda en `error`).

## 5. Dos motores de backtesting independientes

| | Binarias | cTrader |
|---|---|---|
| Paquete | `titan_quant/backtest_binaria` | `titan_quant/backtest_ctrader` |
| Base propia | `datos/backtest_binaria/historico.db` | `datos/backtest_ctrader/historico.db` |
| Datos | Velas M1 cerradas de IQ Option (incremental), archivos de la sonda y CSV; payouts observados en IQ Option | Trendbars de la cuenta cTrader DEMO (incremental); bid/ask observados |
| Estrategia | La del bot: Keltner + RCI, vencimiento 5 velas M1 | Regla técnica del motor 13 (EMA+RSI, ATR) y Keltner+RCI con stop/objetivo ATR |
| Costes | Payout observado (mediana) o indicado; nunca uno por defecto | Medio spread medido en cTrader o indicado (marcado como SUPUESTO) |
| Validación | Walk-forward (K tramos), Wilson vs. equilibrio, sobreoptimización (rejilla dentro de muestra → rango fuera) | 70/30 dentro/fuera, walk-forward, IC 95 % de la expectativa en R, sobreoptimización |
| Etiqueta | «RESULTADO HISTÓRICO CALCULADO · … · no es una operación de IQ Option» | «… · no es una operación de cTrader» |

Uso: panel «Bots operadores» → tarjeta Backtesting, o `python -m titan_quant.cli backtest-binaria …` / `backtest-ctrader …`.

## 6. Pruebas ejecutadas

### Automáticas (`python -m titan_quant.cli probar`, sobre una copia temporal)
- Antes de modificar: 311 pruebas unitarias OK (2 omitidas).
- Después: **4/4 baterías correctas** — 330 pruebas unitarias OK (2 omitidas), autoprueba heredada 159/159, autoprueba del Laboratorio correcta (incluye que la simulación retirada no crea operaciones).
- Nuevas: ciclo de vida y conciliación (`test_operacion.py`), REAL bloqueado incluso forzando la base, migración de bases antiguas, estados de IQ Option con sesión falsa (`test_iqoption_estados.py`), los dos backtests (`test_backtesting.py`: bases separadas, sin ventaja ficticia en paseo aleatorio, sin payout/coste inventado, sin información futura, recolector incremental).

### Interfaz (navegador, servidor de pruebas con datos temporales)
Sin pestaña de simulación; REAL bloqueada sin formulario; columna «Fase (broker)» y «Traza»; panel de backtesting con su etiqueta. Ciclo del bot cTrader y backtest contra el servidor cTrader de pruebas. Sin errores de JavaScript.

### Reales en los brokers (`cli verificar-brokers`, base de cuentas aislada para no interferir con el servidor en marcha)

**cTrader DEMO 49448233 — VERIFICADO de extremo a extremo**
| Hora | Fase | Id broker | Evidencia |
|---|---|---|---|
| 01:54:45 | orden_enviada | — | XAUUSD alcista, volumen mínimo (1,00 oz) |
| 01:54:46 | orden_aceptada | 301886657 | ORDER_FILLED, precio 4125,26, bid 4125,15 / ask 4125,30 |
| 01:54:48 | abierta_confirmada | 301886657 | ProtoOAReconcileRes: posición abierta, stop 4112,88, objetivo 4150,01 |
| 01:54:52 | cerrada_confirmada | 301886657 | la posición ya no figura abierta |
| 01:54:52 | resultado_recibido | 301886657 | DealListRes closePositionDetail: salida 4125,03, **−0,43 USD** |

Lecturas: cuenta DEMO confirmada (no live), saldo 24 973,34 USD, cotización y 4 999 velas de 15 m.

**IQ Option PRACTICE — VERIFICADO de extremo a extremo (tras corregir tres fallos reales del conector)**

La prueba real destapó fallos que impedían operar, también presentes en el código anterior:
1. `get-instruments` nunca responde para `turbo`/`binary`: `resolve()` caía siempre al «estado desconocido» y **ninguna binaria podía enviarse**. Ahora el estado abierto/suspendido sale de `get_all_init_v2` (enabled y no is_suspended), con tiempo máximo.
2. La tabla estática de ids de la librería no contiene la mayoría de los pares OTC (`buy()` fallaba con KeyError). Ahora el id se toma de `get_all_init_v2` (coincide 25/25 con la tabla estática donde ambos existen); sin id conocido, la orden se rechaza ANTES de enviarse.
3. `get_options_v2` (operaciones cerradas) dejó de responder. El resultado se lee ahora del historial de posiciones del broker (`portfolio.get-history-positions`), con tiempo máximo; `closed_options` queda como respaldo.
Además, el payout del mensaje de creación (`profit_income`=183) se interpreta ahora como 0,83 (antes se habría guardado 1,83).

Primer intento (EURGBP-OTC): rechazado **antes de enviar** porque IQ Option tenía el par suspendido. Queda registrado como `rechazada / error_broker`, sin id ni resultado.

| Hora | Fase | Id broker | Evidencia |
|---|---|---|---|
| 02:03:57 | orden_enviada | — | USDMXN-OTC, CALL, 1 USD, 5 min |
| 02:03:58 | orden_aceptada | 14433471986 | mensaje de creación: created 1794204238, exp 1794204540, apertura 18,434495 |
| 02:03:58 | abierta_confirmada | 14433471986 | mensaje de creación del broker con el mismo id |
| 02:12:05 | cerrada_confirmada | 14433471986 | historial: status closed, close_time 1794204540000 |
| 02:12:05 | resultado_recibido | 14433471986 | historial: close_quote 18,420905, close_reason «loose», **pnl −1,00 USD** |

Lecturas: cuenta PRACTICE confirmada, saldo 10 000,72, velas M1, payout turbo 0,83, estado de cada par.
Evidencia completa: `../RESPALDO_20261109_retiro_sim/verificacion_brokers/` (bases de la verificación, `traza_verificacion.json` y salidas).

### Backtesting con datos reales
- cTrader: 5 863 velas XAUUSD 15 m de cTrader DEMO (90 días, 64 huecos de cierre de mercado), coste = medio spread medido (0,15). EMA+RSI: 359 operaciones calculadas, expectativa +0,027 R (IC 95 % −0,084…+0,138); fuera de muestra 109 operaciones, +0,032 R (IC −0,171…+0,236) → **sin ventaja demostrada**. Al optimizar parámetros dentro de muestra, la mejor combinación pierde fuera (−0,089 R) → **sobreoptimización probable** detectada.
- Binarias: 6 000 velas M1 de EURGBP-OTC de IQ Option (04/11 22:03 → 09/11 02:12, 2 huecos), payout observado 0,83. Keltner+RCI: 264 operaciones decisivas, acierto 48,5 % (IC 95 % 42,5–54,5 %) frente a un equilibrio de 54,6 %, EV −0,113 por unidad → **sin ventaja**; ningún tramo walk-forward con ventaja significativa; la optimización dentro de muestra (+0,256) cae a −0,161 fuera → **sobreoptimización probable**.
- Lectura: con los datos disponibles, ninguna de las dos estrategias demuestra ventaja estadística. El bot de binarias se abstiene por diseño mientras el escáner no la demuestre; el bot cTrader depende de las puertas del FUSION ENGINE.

## 7. Limitaciones pendientes

1. **Despliegue:** el servidor TITAN que estaba en marcha (`python -m titan_quant.cli servidor`, PID 24424) sigue ejecutando el código ANTERIOR (con el bot de simulación activo). No se pudo reiniciar desde esta sesión (permiso denegado). Hay que reiniciarlo para que todo lo anterior entre en vigor. Al arrancar con el código nuevo: la modalidad `simulacion` desaparece, el Laboratorio archiva sus operaciones simuladas abiertas, el bot `demo` pasa de IQ Option (configuración antigua, que fallaba) a cTrader DEMO 49448233 y, como estaba «activo», empezará a enviar órdenes a esa cuenta DEMO cuando el FUSION ENGINE encuentre oportunidad.
2. **Órdenes de verificación:** se registraron en una base de cuentas aislada (en el scratchpad de la sesión) para no interferir con el servidor en marcha; constan en los propios brokers con sus ids. La traza completa se copia a `../RESPALDO_20261109_retiro_sim/verificacion_brokers/`.
3. **IQ Option** usa una librería NO oficial; puede romperse con cambios de IQ Option y su uso automatizado puede infringir sus términos. El par configurado (EURGBP-OTC) estaba **suspendido** en IQ Option durante la prueba; el bot se abstiene mientras lo esté.
4. **Backtesting cTrader:** valida la regla técnica del motor 13 y la señal Keltner+RCI; el FUSION ENGINE completo (23 motores, noticias, macro) no se reproduce vela a vela.
5. **Planes de la web (`plan_web`)** siguen evaluando sus hipótesis con velas reales: son análisis informativos, no operaciones ni saldos.
6. **REAL**: ya no está bloqueado por código; ver sección 8 (interruptor MODO LIVE por bot, encendido con contraseña). No se envió ninguna orden con dinero real en las pruebas.

## 8. Ampliación (09/11/2026, a petición del usuario)

**Interfaz.** Barra superior FIJA (no se mueve al desplazar) con el estilo del «Centro de Inteligencia Global»: marca, un botón por módulo y estado de los bots. Cada bot tiene su pestaña: **Bot cTrader** (DEMO | REAL) y **Bot IQ Option** (PRACTICE | REAL).

**Interruptor MODO LIVE** en cada cuenta real (`real` = cTrader live, `binaria_real` = IQ Option REAL): botón rojo «MODO LIVE APAGADO» → con tu contraseña de TITAN pasa a verde «MODO LIVE ACTIVADO» y el bot de esa cuenta queda activo. Práctica y real funcionan a la vez, cada una con su base. Apagarlo detiene la apertura de operaciones (las vivas se siguen conciliando). Se audita y genera alerta crítica.
- IQ Option: la librería guarda la cuenta activa en una variable global del proceso; por eso cada operación sensible a la cuenta (orden, saldo, historial) se hace dentro de un cerrojo único que selecciona la cuenta, la VERIFICA y vuelve a PRACTICE al terminar. Si no se puede verificar, la orden no se envía.
- cTrader: la cuenta REAL solo por el host live y la DEMO solo por el host demo (se comprueba con el broker en cada sesión).

**Nombres legítimos.** El bot cTrader usa los símbolos, descripciones, velas, bid/ask y resultados de cTrader (p. ej. «EURUSD · Euro vs US Dollar»); las operaciones se registran con el nombre del símbolo de cTrader. El bot IQ Option usa los nombres, estado abierto/suspendido, payouts e ids que publica IQ Option.

**Estrategias básicas configurables** (`estrategias/simples.py`, exigencia básica): cruce de EMA, RSI salida de sobreventa/sobrecompra, Bollinger regreso a la banda, ruptura de Donchian y Keltner+RCI. Cada una se activa y se parametriza en la pestaña de cada bot; los parámetros se validan con rangos.

**Escáner multiactivo con aprendizaje continuo** (modo por defecto de ambos bots):
- cTrader: recorre TODOS los símbolos activos de la cuenta (443 en la DEMO 49448233) por lotes, descarga sus velas de cTrader y hace backtest de cada estrategia (70/30, coste = medio spread medido). Apto con exigencia básica: ≥ 20 operaciones fuera de muestra y expectativa fuera > 0 R (configurable). Solo busca señales en la última vela cerrada de los pares aptos mejor clasificados; cada señal pasa por todos los controles de riesgo y el flujo de fases.
- IQ Option: recorre los pares ABIERTOS (41 durante la prueba) con su payout real; backtest con vencimiento de 5 velas M1; apto si el acierto fuera de muestra supera el punto de equilibrio 1/(1+payout) y el EV total > 0.
- El ranking se recalcula continuamente con los datos más recientes: una estrategia que deja de funcionar en un activo deja de ser apta (así se ajusta al mercado). Los resultados del ranking son históricos calculados (bases de backtesting), nunca operaciones.

**Pruebas.** `cli probar`: 4/4 baterías, 340 pruebas unitarias OK. Nuevas: `test_multiactivo.py` (estrategias sin información futura, validación de parámetros, ranking de todos los símbolos contra el servidor cTrader de pruebas, señal enviada con controles y fases, cuenta REAL/PRACTICE de IQ Option con verificación y vuelta a PRACTICE, ciclo binario multiactivo). Interruptor LIVE probado en `test_operacion.py`, `test_ctrader.py` (órdenes al host live del servidor de pruebas solo con LIVE encendido) y en el navegador. Escaneo real de solo lectura en ambos brokers: correcto (sin órdenes).

**Pendiente / avisos.**
- Reiniciar el servidor TITAN para cargar todo este código.
- Al usar el MODO LIVE operas con dinero real; los resultados de backtest no garantizan resultados futuros. Las opciones binarias para minoristas están prohibidas en varios países y la librería de IQ Option no es oficial.
- El escáner de cTrader re-evalúa 4 símbolos por ciclo (configurable): recorrer los 443 símbolos lleva varias horas.
