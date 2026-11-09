# TITAN QUANT · Auditoría C1 (orden maestra, bloque 1)

**Fecha:** 09/11/2026.

**Alcance:** todo el frontend y backend, los motores, las bases de datos, las APIs, los conectores, los procesos y las dependencias.

**Método:**
- inventario automático por análisis del código (AST), sin ejecutar nada contra los brokers;
- análisis estático;
- revisión manual de las rutas críticas;
- batería completa de pruebas.

**En esta fase no se modificó ningún componente funcional.** Solo se crearon esta auditoría y la copia de seguridad.

---

## 1. Copia de seguridad verificable

`../RESPALDO_20261109_C1_auditoria/` (junto a la carpeta `TITAN_QUANT`)

| Archivo | Contenido |
|---|---|
| `codigo_TITAN_QUANT.tar.gz` | Todo el código: 364 entradas, 0,7 MB, sin cachés ni bases |
| `bases/*.db` | Copia **consistente** de las 14 bases SQLite, hecha con la API de respaldo de SQLite (válida con el servidor en marcha). 269 MB |
| `MANIFIESTO.json` | SHA-256, tamaño, `integrity_check` y número de filas por tabla de cada archivo |
| `SHA256SUMS.txt` | Sumas para verificar con `sha256sum -c SHA256SUMS.txt` |

**Verificación:** 15 de 15 hashes recalculados coinciden, y las 14 bases dan `integrity_check = ok`.

**La clave maestra `datos/.clave_maestra` no se incluye a propósito.** Es el secreto que descifra las credenciales de los brokers.
- Para restaurar en otro equipo hace falta copiarla aparte, a mano y por un medio seguro.
- Sin ella, las credenciales guardadas no se pueden leer y habría que volver a introducirlas.

Copia anterior: `../RESPALDO_20261109_retiro_sim/`.

---

## 2. Arquitectura actual

```
Navegador ──HTTP──► titan_quant.servidor (ThreadingHTTPServer, 127.0.0.1:8765, un solo proceso Python)
                      │  hereda api_web.Handler (rutas antiguas /api/assets, /api/chart, /api/plans, /api/lab/* … ahora con sesión)
                      │  31 rutas GET + 50 rutas POST propias (/api/auth/*, /api/tq/*)
                      ├── seguridad/ (sesiones, scrypt, bóveda cifrada, límites de peticiones, auditoría)
                      ├── motores/ (23 motores registrados) ──► agente.py, macro.py, activos.py, chart_web.py … (módulos raíz)
                      ├── trader/autotrader (bucle de bots) ──► trader/ctrader.py ─► ctrader_ws.py ─► cTrader Open API (WebSocket JSON)
                      │                                     └► trader/iqoption.py ─► iqoption_data.py ─► iqoptionapi (librería NO oficial)
                      ├── backtest_ctrader/, backtest_binaria/ (laboratorios separados, bases propias)
                      ├── recolector_continuo (velas de cTrader e IQ en todas las temporalidades)
                      ├── noticias/ (centro de noticias: 31 fuentes RSS/JSON)
                      └── hilos heredados: lab_engine (laboratorio), plan_web (vigilante de planes)
```

### 2.1 Tamaño del código

| Capa | Módulos | Líneas |
|---|---|---|
| Paquete `titan_quant/` | 122 | 19.257 |
| · pruebas | — | 5.607 |
| · núcleo (servidor, cli, db, config, integraciones, historial…) | — | 3.521 |
| · trader (bots, adaptadores de brokers) | — | 2.941 |
| · motores (23 motores) | — | 1.855 |
| · binaria_bot | — | 1.566 |
| · noticias | — | 1.107 |
| · seguridad | — | 708 |
| · backtest_binaria / backtest_ctrader | — | 597 / 585 |
| · binaria / binaria_sim / estrategias / indicadores | — | 236 / 200 / 211 / 123 |
| Módulos raíz heredados (28 archivos) | 28 | ~7.900 |
| **Total auditado** (sin `iqoptionapi/`, `legado/`, `datos/`) | 152 | 27.277 |

No hay errores de sintaxis. Ninguna función pasa de 120 líneas.

### 2.2 Motores registrados (23)

| # | Id | Nombre | Módulo | Consumo |
|---|---|---|---|---|
| 1 | core | TITAN CORE | motores.nucleo | bajo |
| 2 | data | DATA ENGINE | motores.mercado | bajo (red) |
| 3 | features | FEATURE ENGINEERING | motores.mercado | bajo |
| 4 | technical | TECHNICAL INTELLIGENCE | motores.mercado | bajo |
| 5 | cross_asset | CROSS-ASSET INTELLIGENCE | motores.mercado | medio (red) |
| 6 | macro | MACROECONOMIC INTELLIGENCE | motores.info | bajo (red) |
| 7 | statistical | STATISTICAL INTELLIGENCE | motores.cuant | bajo |
| 8 | ml | MACHINE LEARNING | motores.cuant | alto (CPU) |
| 9 | regime | MARKET REGIME | motores.mercado | bajo |
| 10 | microstructure | MARKET MICROSTRUCTURE | motores.mercado | bajo |
| 11 | news | NEWS INTELLIGENCE | motores.info | bajo (red) |
| 12 | risk | RISK INTELLIGENCE | motores.cuant | bajo |
| 13 | backtesting | BACKTESTING | motores.cuant | bajo |
| 14 | montecarlo | MONTE CARLO | motores.cuant | medio-alto |
| 15 | portfolio | PORTFOLIO INTELLIGENCE | motores.cuant | medio (red) |
| 16 | research | RESEARCH | motores.info | bajo |
| 17 | fusion | FUSION | motores.info | bajo |
| 18 | adaptive | ADAPTIVE PROCESSING | motores.sistema | bajo |
| 19 | hardware | HARDWARE DIAGNOSTICS | motores.sistema | bajo |
| 20 | monitoring | MONITORING | motores.sistema | bajo |
| 21 | api | API ENGINE | motores.sistema | bajo |
| 22 | web | WEB DASHBOARD | motores.sistema | bajo |
| 23 | telegram | TELEGRAM NOTIFICATION | motores.sistema | bajo |

- **Están implementados en Python puro**, sin numpy, scikit-learn ni modelos externos.
- **Se ejecutan bajo demanda:** al analizar un activo o al confirmar la señal de un bot. **No corren de forma continua.**
- **Guardan su estado** de la última ejecución en la tabla `estado_motores`.

### 2.3 Bases de datos (14 archivos SQLite)

| Base | MB | Tablas | Filas | Uso |
|---|---|---|---|---|
| `datos/titan_quant.db` | 0,6 | 18 | 511 | usuarios, sesiones, credenciales cifradas, integraciones, auditoría, análisis, alertas, estado de motores |
| `datos/cuentas/demo.db` | 0,2 | 7 | 346 | bot cTrader DEMO (operaciones, eventos, decisiones, saldos, conocimiento) |
| `datos/cuentas/real.db` | 0,1 | 7 | 2 | bot cTrader REAL (sin operaciones) |
| `datos/cuentas/binaria.db` | 0,8 | 7 | 1.119 | bot IQ Option PRACTICE |
| `datos/cuentas/binaria_real.db` | 0,1 | 7 | 2 | bot IQ Option REAL (sin operaciones) |
| `datos/cuentas/simulacion.db` | 0,3 | 6 | 268 | **archivo de la simulación retirada**: ya no se escribe |
| `datos/backtest_ctrader/historico.db` | **239,2** | 5 | 1.914.206 | velas de cTrader, spreads, ranking del escáner, informes |
| `datos/backtest_binaria/historico.db` | 33,9 | 6 | 280.253 | velas de IQ, payouts, ranking por temporalidad |
| `datos/binaria_bot/escaner_vivo.db` | 0,0 | 3 | 20 | escáner del bot binario de un solo activo |
| `datos/conocimiento.db` | 0,0 | 1 | 31 | conocimiento compartido |
| `datos/noticias/noticias.db` | 1,2 | 7 | 1.955 | centro de noticias |
| `titan_lab.db` (raíz) | 5,1 | 13 | 17.987 | laboratorio de aprendizaje heredado (operaciones A/B archivadas) |
| `titan_planes.db` (raíz) | 0,1 | 1 | 24 | planes vigilados |
| `titan_activos.db` (raíz) | 0,0 | 5 | 0 | **vacía** |

### 2.4 APIs y rutas

- **Rutas propias** (`titan_quant/servidor.py`): 31 GET y 50 POST.
  - `/api/auth/*`: acceso, sesiones, preferencias;
  - `/api/tq/*`: motores, análisis, integraciones, alertas, historial, operador/bots, backtest, escáner, cTrader, noticias, diagnóstico.
- **Rutas heredadas** (`api_web.py`, accesibles por herencia, ahora con sesión): `/api/assets`, `/api/history`, `/api/stats`, `/api/alerts`, `/api/quotes`, `/api/chart`, `/api/mtf`, `/api/plans`, `/api/analyze`, `/api/report`, `/api/plan*` y `/api/lab/*`.

### 2.5 Conectores externos

| Conector | Implementación | Oficial | Uso |
|---|---|---|---|
| **cTrader Open API** | `trader/ctrader_ws.py` (WebSocket JSON propio: auth, cuentas, símbolos, trendbars, spot, órdenes 2106, amend 2110, reconcile 2124, deals 2133) + OAuth en `integraciones.py` | **Sí** (Spotware) | bot DEMO/REAL, velas, backtest |
| **IQ Option** | `iqoptionapi/` (librería comunitaria incluida en el proyecto) + `iqoption_data.py` | **No.** IQ Option no publica una API oficial | bot PRACTICE/REAL, velas, payouts |
| Yahoo Finance (`query1.finance.yahoo.com`) | `agente.py` / `chart_web.py` | API no documentada | velas para el análisis manual |
| Google News RSS | `agente.py`, `macro.py`, `recopilador_noticias.py`, `titan_gold_news.py` | RSS público | noticias de los motores 6 y 11 |
| Telegram Bot API | `telegram_bot.py`, motor 23 | Sí | notificaciones |
| 31 fuentes RSS/JSON | `titan_quant/noticias/` | RSS públicos | centro de noticias |

### 2.6 Procesos e hilos (todos en un único proceso Python)

| Hilo | Origen | Función |
|---|---|---|
| `titan-autotrader` | `trader/autotrader.py` | ciclo de los 4 bots (demo, real, binaria, binaria_real) |
| `titan-recolector-ctrader` / `titan-recolector-iqoption` | `recolector_continuo.py` | descarga continua de velas |
| `titan-noticias` | `noticias/recolector.py` | recopilación de noticias (pool de 4 hilos por ronda) |
| `lab_engine._bucle` | `lab_engine.py` | laboratorio heredado |
| `titan-vigilante-planes` | `plan_web.py` | vigilancia de planes |
| hilos efímeros | `iqoption_data`, `trader/iqoption`, `binaria_bot/capital`, `backtest_binaria/escaner`, `motores/sistema` | llamadas con tiempo máximo a IQ Option y Telegram |
| servidor HTTP | `ThreadingHTTPServer` | un hilo por petición |

- **No hay supervisor central:** ningún componente prioriza, reinicia ni mide CPU y RAM por hilo.
- **Actualizar el código Python exige reiniciar el proceso a mano.** No hay recarga en caliente ni servicio del sistema.

### 2.7 Dependencias

| Paquete | Estado | Uso |
|---|---|---|
| Python 3.13 (biblioteca estándar) | ✔ | casi todo |
| `requests` 2.34 | ✔ | módulos heredados |
| `certifi` 2026.10 | ✔ | cadena de certificados para BCE y Eurostat |
| `cryptography` | ✘ **no instalado** | la bóveda usa el cifrado v1 (HMAC-SHA256 en contador + HMAC). Es correcto, pero AES-256-GCM (v2) es el estándar recomendado |
| `psutil` | ✘ no instalado | CPU y RAM por proceso (necesario para C8/C9) |
| `playwright` | ✘ no instalado | las pruebas de navegador se omiten (2 omitidas) |
| numpy / pandas / scikit-learn / xgboost / lightgbm / torch | ✘ | no se usan; los motores son Python puro |

**Hardware:** 12 CPU lógicas y GPU integrada AMD Radeon 760M. Sin CUDA, así que no hay aceleración GPU para PyTorch o XGBoost.

---

## 3. Mapa de conexiones

```
motores/nucleo ──► activos.py (catálogo)          motores/info ──► agente.py, macro.py (Google News) + noticias/integracion (verificadas)
motores/datos  ──► chart_web.py ──► quotes_web.py (Yahoo)  · iqoption_data.py (velas IQ)
motores/sistema ─► plan_web.py · telegram
servidor ──────► api_web.py (rutas heredadas) ──► lab_engine.py, plan_web.py, informe_web.py, chart_web.py, quotes_web.py, activos.py
trader/autotrader ─► confirmacion.py ─► motores/nucleo (23 motores sobre las MISMAS velas del broker)
                 ─► backtest_ctrader/escaner · backtest_binaria/escaner (ranking + señales en vivo)
                 ─► binaria_bot/puente_trader (solo en modo de UN activo, no en multiactivo)
                 ─► trader/almacen (datos/cuentas/*.db) · trader/ctrader · trader/iqoption
backtest_binaria ─► binaria/datos_csv.py · iqoption_data.py · binaria_sim (captura de opciones)
```

Módulos raíz que **ningún** otro módulo importa: `auditoria.py`, `integrar_noticias.py`, `pipeline_titan.py`, `probar.py` (herramienta de línea de comandos), `recopilador_noticias.py` y `titan_gold_news.py`.

---

## 4. Hallazgos

### 4.1 Duplicaciones

1. **Cinco caminos de noticias:**
   - `agente.noticias_activo` (Google News por activo);
   - `macro.escanear` (Google News macro);
   - `recopilador_noticias.py`, `titan_gold_news.py` e `integrar_noticias.py` (scripts sueltos sin uso);
   - la tabla `lab_noticias` del laboratorio;
   - el nuevo centro de noticias.

   → Propuesta: que los motores 6 y 11 usen el centro de noticias como fuente principal, con Google News como respaldo, y archivar los tres scripts sueltos.
2. **Cuatro implementaciones relacionadas con binarias:**
   - modalidad `binaria` del autotrader (**la activa**, multiactivo);
   - `binaria_bot/` (escáner de un solo activo y puente, que solo se usa si la estrategia no es «multiactivo»);
   - `binaria_bot/orquestador.py` + `binaria_sim/adaptador_practica.py` (camino anterior, sin uso en producción, solo en pruebas);
   - `binaria/` (backtest histórico de la señal original desde CSV).

   → Propuesta: dejar una sola ruta de ejecución (la del autotrader) y archivar el orquestador y `binaria_sim`, conservando las pruebas que aún aporten.
3. **Dos servidores web superpuestos:** `api_web.Handler` (heredado) y `servidor.Handler` (nuevo, que hereda del primero).
4. **Dos laboratorios de aprendizaje:** `lab_engine.py` + `titan_lab.db` (heredado, con motores A/B desactivados) y `backtest_*` + `conocimiento` por cuenta (el actual).
5. **Nombres de módulo repetidos** en subpaquetes distintos (`escaner.py` ×3, `recolector.py` ×3, `almacen.py` ×3, `motor.py`, `datos.py`, `base.py`, `niveles.py` ×2). Es legítimo, pero confunde al buscar.

### 4.2 Restos y archivos huérfanos

| Elemento | Situación |
|---|---|
| `titan_quant/binaria_bot/*.previo_*` (9 archivos) | copias de versiones anteriores dentro del paquete |
| `datos/respaldo_*` (8 carpetas o archivos con código copiado) | respaldos antiguos mezclados con los datos |
| `datos/.clave_maestra.NO_USAR_20261107` | clave antigua: conviene borrarla tras confirmar que ningún secreto la usa |
| `datos/cuentas/simulacion.db` | datos de la simulación retirada (archivo) |
| `titan_activos.db` | vacía |
| `web/index_nuevo.html`, `web/centro_nuevo.html`, `web/tq_nuevo.css` | no los referencia la interfaz activa |
| `legado/` (7 scripts) | herramientas antiguas, no se importan |

### 4.3 Calidad del código (análisis estático)

- **Imports sin usar:** 3 reales (`Vela` en `binaria_bot/motores_puente.py`, `keltner` y `rci` en `estrategias/simples.py`). El resto son `from __future__ import annotations`, que es correcto.
- **24 bloques `except Exception: pass`:**
  - la mayoría son cierres de conexión y registros, y son correctos;
  - hay que revisar en la fase C10 los de `trader/iqoption.py:319`, `trader/iqoption.py:344` y `backtest_ctrader/escaner.py:153`, porque pueden ocultar fallos del broker;
  - el de `trader/autotrader.py:909` es intencionado: usa el último saldo leído si IQ Option no responde.
- **Pruebas:**
  - 386 pruebas del paquete y 159 de la autoprueba, todas correctas;
  - 2 omitidas por falta de `playwright`;
  - **no hay pruebas de rendimiento**.
- **Git:** **nada está guardado desde la línea base v7.2.1.** Hay más de 30 archivos modificados y más de 20 carpetas nuevas sin guardar. Es el mayor riesgo operativo actual: una pérdida del disco o un error de edición no tendría vuelta atrás salvo por las copias de seguridad.

### 4.4 Seguridad

| Punto | Estado |
|---|---|
| Contraseñas | scrypt (N=2^14, r=8, p=1) ✔ |
| Credenciales de brokers | cifradas en la bóveda y ligadas a usuario/proveedor/campo ✔. Usan el cifrado v1 porque falta `cryptography` (recomendado: instalarlo; los secretos v1 siguen siendo legibles) |
| Sesiones | cookie HttpOnly, límites de peticiones por IP ✔ |
| Separación DEMO/REAL | bases separadas por cuenta, REAL solo con el interruptor LIVE y contraseña ✔ |
| Kill switch | estado `emergencia` **por bot**; **no hay un interruptor global** de todos los brokers (pendiente en C10) |
| Fuentes externas | contenido de noticias tratado como dato; protección SSRF ✔ |
| IQ Option | librería no oficial: puede romperse con cambios de IQ Option y su uso automatizado puede no estar permitido por sus términos |
| Servidor | solo en 127.0.0.1 por defecto ✔; sin HTTPS (correcto en local) |

### 4.5 Rendimiento y recursos

- `backtest_ctrader/historico.db` crece rápido: 239 MB y 1,9 millones de velas. Falta una política de retención y compactación (VACUUM).
- Todo corre en un solo proceso Python: el GIL limita el cálculo en paralelo, aunque la mayor parte del trabajo es de red.
- Los 23 motores solo corren bajo demanda. «Trabajar continuamente» (C8/C9) exige un planificador con prioridades y límites de CPU, que todavía no existe.

---

## 5. Limitaciones actuales (declaradas)

1. Solo dos brokers conectados: cTrader (oficial) e IQ Option (no oficial).
2. El ML del motor 8 es Python puro (sin XGBoost ni LightGBM) y los motores no tienen modelos entrenados persistentes de gran tamaño.
3. Sin supervisor de procesos, sin medición de CPU y RAM por motor y sin un centro visual de servidores.
4. Sin kill switch global.
5. El calendario económico no trae el dato publicado.
6. Sin pruebas de rendimiento ni de carga.
7. La interfaz se sirve desde el mismo proceso que los bots: un fallo grave del proceso detiene ambos.

---

## 6. Plan de integración (C2–C10) sin destruir lo que funciona

Reglas para todas las fases:
- copia de seguridad antes de empezar;
- cambios en módulos nuevos siempre que se pueda;
- las interfaces existentes no se rompen;
- cada capacidad nueva se demuestra con pruebas;
- nada toca dinero real de forma automática.

| Fase | Dónde se integra | Contrato con lo existente |
|---|---|---|
| **C10 (base de seguridad, primero)** | `trader/autotrader.py` + `seguridad/` | **kill switch global** (detiene todos los bots y bloquea `_enviar`), interruptor por broker y revisión de los `except` silenciosos de los adaptadores. Va antes que los conectores nuevos |
| **C2 · Matriz de brokers** | `docs/BROKERS_MATRIZ.md` + `titan_quant/brokers/catalogo.py` | solo información verificada con documentación oficial (fecha y enlace); nada se marca como disponible sin comprobarlo |
| **C3 · Conectores** | nuevo paquete `titan_quant/brokers/` con una interfaz común (`conectar`, `cuentas`, `saldo`, `simbolos`, `velas`, `cotizacion`, `abrir`, `modificar_sltp`, `cerrar`, `posiciones`, `ordenes`, `historial`, `conciliar`), basada en `trader/base.py` | `trader/ctrader.py` y `trader/iqoption.py` pasan a ser los dos primeros adaptadores sin cambiar su comportamiento. Primero los brokers con API oficial y cuenta DEMO/paper gratuita |
| **C4 · Sincronización** | `titan_quant/brokers/sincronizacion.py` + columnas nuevas en `datos/cuentas/*.db` (comisión, swap, ejecución parcial, precio real, deslizamiento real) | migraciones con `ALTER TABLE` como las ya existentes; identificador original del broker como clave de conciliación |
| **C9 · Supervisor** | `titan_quant/supervisor.py` | registra los hilos actuales (autotrader, recolectores, noticias, laboratorio), mide CPU y RAM (con `psutil`), reinicia los que caen y da prioridad a riesgo/ejecución/sincronización frente a investigación |
| **C8 · Centro de servidores** | módulo web nuevo + `/api/tq/servidores` | lee el registro de motores, `estado_motores` y el supervisor; 5 LED con **estados reales**; los controles de iniciar/detener actúan a través del supervisor respetando dependencias |
| **C5 · Biblioteca científica** | `titan_quant/ciencia/` (versionada, con pruebas) | cada algoritmo (modelos ocultos de Markov para régimen, GARCH, optimización de carteras robusta, XGBoost/LightGBM) se compara contra el motor actual en el backtest. **Solo sustituye al actual si mejora de forma medible** |
| **C6 · Cerebro autónomo** | `titan_quant/ia/` | coordina los motores y lee el conocimiento por cuenta. Propone cambios con trazabilidad; **en REAL nunca aplica cambios sin autorización** y no puede tocar las protecciones de C10 |
| **C7 · Laboratorio cuántico** | `titan_quant/cuantico/` (aislado, opcional) | simulador de Qiskit o PennyLane; sin acceso a los bots; resultados etiquetados como experimentales |

**Orden recomendado:**
1. **A4 (guardar en git).**
2. C10.
3. C2.
4. C3 + C4, broker a broker.
5. C9.
6. C8.
7. C5.
8. C6.
9. C7.

**Limpieza previa propuesta** (solo con tu aprobación; todo queda en la copia de seguridad):
- archivar los scripts de noticias sueltos, el orquestador y `binaria_sim` sin uso en producción, los archivos `*.previo_*`, las páginas web no referenciadas y `titan_activos.db` vacía;
- instalar `cryptography` y `psutil`.
