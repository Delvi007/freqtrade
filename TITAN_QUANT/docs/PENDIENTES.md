# TITAN QUANT · Trabajos pendientes (organizados)

Actualizado el 09/11/2026. Va de lo más urgente a lo más amplio. Cada bloque se entrega con pruebas y sin romper lo que
ya funciona.

## A. Inmediato: puesta en marcha

| # | Tarea | Estado |
|---|---|---|
| A1 | Reiniciar el servidor para activar el centro de noticias, el escaneo completo de mercados, el R:B 1:2/1:3/1:4 de cTrader y la configuración de binarias sin límites (1 %, 10 operaciones, umbral 65) | **lo hace el usuario** |
| A2 | Vigilar los dos bots durante una sesión y confirmar los resultados con los brokers | después de A1 |
| A3 | Compilar en cTrader Automate el indicador `ctrader/TitanLineasSLTP.cs` (líneas de SL/TP de 3 px) | lo hace el usuario en cTrader |
| A4 | Guardar en git todo el trabajo hecho | ✔ hecho el 09/11/2026 |
| A5 | Si binarias sigue re-evaluando un solo par por ciclo, subir su tiempo máximo de re-backtest de 40 s a 90 s | según A2 |

## B. Inteligencia de noticias: segunda fase

| # | Tarea |
|---|---|
| B1 | Fuente oficial gratuita del **dato publicado** del calendario (p. ej. BLS por su API pública, FRED con clave gratuita) para comparar la previsión con lo publicado sin depender de los titulares |
| B2 | Alertas del calendario hacia la campana de TITAN y Telegram (hoy solo se ven en el panel) |
| B3 | Registro de errores por fuente (correcciones y titulares desmentidos) para recalcular las estrellas con datos reales |
| B4 | Léxico en español y más entidades (empresas del S&P 500 completo, más cripto) |
| B5 | Evaluar, con pruebas medidas, un modelo de sentimiento financiero (p. ej. FinBERT, licencia Apache-2.0). Solo se integra si mejora de forma medible al léxico actual y cabe en el hardware |

## C. Orden maestra: inteligencia autónoma y multibroker

Se hace por fases, cada una con auditoría previa, copia de seguridad y pruebas.

| Fase | Contenido | Requisito para darla por terminada |
|---|---|---|
| C1 | **Auditoría completa** ✔ hecha el 09/11/2026: `docs/AUDITORIA_C1.md`; copia de seguridad verificada en `../RESPALDO_20261109_C1_auditoria/` | terminada |
| C2 | **Centro Universal de Brokers**: matriz de los 24 brokers pedidos (documentación oficial, regulación, disponibilidad para República Dominicana, mercados, autenticación, APIs REST/WebSocket/FIX, DEMO/REAL, límites) | matriz con fuentes oficiales; nada inventado |
| C3 | **Conectores reales**, uno por broker que tenga API oficial y cuenta DEMO accesible (candidatos con API documentada: Interactive Brokers, Alpaca, OANDA, Tradier, tastytrade, Saxo, IG, Coinbase Advanced, Kraken; MT4/MT5 mediante puente) | autenticación, lectura, sincronización y ejecución en DEMO probadas; REAL nunca automático |
| C4 | **Sincronización con el broker como fuente de verdad**: posiciones, órdenes pendientes, ejecuciones parciales, comisiones, swaps, deslizamiento real, cambios de SL/TP y eventos de cuenta | conciliación sin duplicados y con identificadores del broker |
| C5 | **Biblioteca científica TITAN**: selección por rendimiento medido y licencia (XGBoost/LightGBM para ML tabular, modelos ocultos de Markov para régimen, GARCH para volatilidad, optimización convexa robusta para carteras, inferencia bayesiana) con versión, pruebas y documentación | cada algoritmo con prueba y referencia; sin copiar código con licencia incompatible |
| C6 | **Cerebro de inteligencia autónoma** que coordina los 23 motores y los nuevos: detección del deterioro de estrategias y de patrones de pérdida, con versiones recuperables | ningún modelo experimental modifica una cuenta REAL; cada cambio, trazable y autorizado |
| C7 | **Laboratorio cuántico experimental** e independiente (QAOA/VQE con Qiskit o PennyLane en simulador) | sin atribuir ventajas no demostradas |
| C8 | **TITAN Engine Server Center**: cada motor como servidor en rack con 5 LED de estado real, panel técnico al hacer doble clic (CPU, RAM, latencia, errores, último aprendizaje) y controles con dependencias | los LED reflejan estados reales, nunca actividad ficticia |
| C9 | **Procesamiento**: colas con prioridad (riesgo, ejecución y sincronización primero), concurrencia controlada, supervisión de CPU y RAM, recuperación automática | sin saturar el equipo; pruebas de rendimiento |
| C10 | **Seguridad** ✔ hecha el 09/11/2026: PARADA TOTAL, interruptor por broker, protección automática por errores, ajustes protegidos, LIVE solo por el usuario; la IA no puede desactivar protecciones (7 pruebas) | terminada · queda la recuperación tras caída del proceso (C9) |

### Notas de alcance (honestas)

- Varios brokers exigen requisitos que TITAN no puede cumplir solo: cuenta abierta, aprobación de la app, suscripción a datos o licencia FIX. En esos casos se entrega el conector preparado y se marca qué falta, no «funcional».
- La disponibilidad para clientes de República Dominicana debe confirmarse con cada broker; lo publicado en sus webs puede cambiar.
- Computación cuántica: hoy no hay ventaja demostrada frente a los métodos clásicos en estos problemas. Se mantiene como laboratorio.
