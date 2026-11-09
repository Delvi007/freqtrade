# TITAN QUANT · Plataforma avanzada (orden maestra C2–C9)

**Fecha:** 09/11/2026.

**Qué contiene:**
- matriz de brokers (C2);
- conectores (C3) y sincronización (C4);
- biblioteca científica (C5);
- cerebro autónomo (C6) y laboratorio cuántico (C7);
- centro de servidores (C8) y supervisor (C9);
- interruptor universal;
- pruebas de rendimiento;
- instalación, configuración y límites.

La auditoría está en `AUDITORIA_C1.md` y la seguridad (C10) en `CHANGELOG.md`.

**Principios:**
- Nada se marca como funcional sin una prueba real.
- El broker es la fuente de verdad.
- En las cuentas REAL de los brokers nuevos, TITAN solo lee.
- La inteligencia autónoma no puede desactivar protecciones.
- La computación cuántica es un laboratorio experimental y no se le atribuye ninguna ventaja.

---

## 1. Instalación

```bash
python -m pip install --user numpy psutil cryptography
```

| Paquete | Para qué | Obligatorio |
|---|---|---|
| numpy | biblioteca científica, cerebro, laboratorio cuántico | sí, para C5–C7 |
| psutil | CPU y RAM reales por proceso en el centro de servidores | recomendado: sin él, C8/C9 funcionan sin métricas |
| cryptography | bóveda con AES-256-GCM (los secretos nuevos se cifran con v2; los v1 siguen siendo legibles) | recomendado |

Se arranca igual que siempre: `python -m titan_quant.cli servidor`. Al iniciar se ponen en marcha, además:
- la sincronización de brokers;
- el cerebro autónomo;
- el supervisor de procesos.

---

## 2. Centro universal de brokers (C2/C3/C4) · módulo **⇆ Brokers**

### 2.1 Matriz verificada en vivo (09/11/2026)

| Broker | APIs oficiales | DEMO | Verificación en vivo | Conector TITAN |
|---|---|---|---|---|
| Interactive Brokers | TWS API, Client Portal Web API, FIX | paper | docs 200 | no: necesita TWS/IB Gateway en el equipo |
| tastytrade | REST + WebSocket | sandbox | docs 200 | no: necesita credenciales de sandbox |
| TradeStation | REST v3 + streaming | SIM | docs 200 | no: necesita clave aprobada |
| Charles Schwab | REST (Trader API) | **sin sandbox** | docs 200 | no: sin DEMO no se puede probar la ejecución |
| **Alpaca** | REST Trading + Market Data | paper gratuito | docs 200 · API paper 401 (pide claves) | **implementado** |
| **Tradier** | REST Brokerage | sandbox | docs 200 · sandbox responde | **implementado** |
| Webull | OpenAPI (con solicitud) | — | ruta de documentación 404 | no |
| NinjaTrader | NinjaScript dentro de la plataforma | simulador | docs 200 | no |
| Tradovate | REST + WebSocket | demo | docs 200 | no: API de pago |
| Moomoo | OpenAPI vía OpenD | paper | docs 200 | no: necesita OpenD |
| Saxo Bank | OpenAPI REST + streaming | SIM | docs 200 · SIM 401 | siguiente en la cola |
| IG | REST + Lightstreamer | demo | API demo 400 «api-key-missing» | siguiente en la cola |
| **OANDA** | REST v20 + streaming | practice | docs 200 · practice 401 | **implementado** |
| CMC Markets | sin API minorista (FIX institucional) | — | 404 | no |
| XTB | API **discontinuada** | — | el dominio ya no resuelve | no |
| Capital.com | REST + WebSocket | demo | API demo 400 «client.token» | siguiente en la cola |
| Swissquote | FIX/institucional | — | 404 | no |
| FXCM | — | demo | documentación 404 | no |
| Trading 212 | REST (beta) | practice | API demo 401 | siguiente en la cola |
| **Coinbase Advanced** | REST + WebSocket (JWT ES256) | sin sandbox | **datos públicos verificados** | **datos públicos** (cuenta: solo lectura) |
| **Kraken** | REST + WebSocket v2 + FIX | solo futuros | **datos públicos verificados** · firma con el vector oficial | **datos públicos** (las órdenes solo se validan, nunca se ejecutan) |
| cTrader | Open API | DEMO | en producción | **activo** |
| IQ Option | sin API oficial | PRACTICE | en producción | **activo** (librería no oficial) |
| MetaTrader 5 | paquete Python oficial (terminal local) | demo del broker | docs 200 | no: necesita el terminal MT5 |
| MetaTrader 4 | solo MQL4 dentro del terminal | demo del broker | docs 200 | no: haría falta un EA puente |

- **Regulación:** es la que declara cada broker.
- **República Dominicana:** hay que **confirmarla con cada broker**, porque depende de la entidad y puede cambiar. TITAN no puede comprobarlo automáticamente.

### 2.2 Qué ofrece cada broker con conector

- **Interruptor ON/OFF:** verde = encendido, rojo = apagado, con la indicación encima. Al encenderlo, el broker se prueba en el acto.
- **Entorno:** DEMO o REAL. **REAL es de solo lectura.**
- **Credenciales:** cifradas en la bóveda. La interfaz solo muestra las máscaras y los mensajes de error se limpian para que nunca contengan una credencial.
- **Diagnóstico:** solo marca «conectado» si el broker responde de verdad.
- **Registro de actividad:** cada llamada queda guardada con método, resultado y milisegundos.
- **Sincronización periódica (C4):** cuenta, posiciones (con SL/TP y swap), órdenes y ejecuciones (precio real, comisión, swap y parciales).
  - Se guardan en `datos/brokers/brokers.db` con el **id original del broker**.
  - Reconciliar dos veces no duplica nada.
- **Orden de prueba en DEMO:** solo con el broker encendido y en DEMO. Respeta la PARADA TOTAL.

---

## 3. Biblioteca científica (C5) · `titan_quant/ciencia/`

Toda la biblioteca es implementación propia en numpy, con referencias académicas en el código y **18 pruebas de corrección**. Cada prueba comprueba un resultado concreto:

| Módulo | Algoritmos | Prueba |
|---|---|---|
| especiales | beta incompleta, t de Student, normal inversa | contra valores de tabla |
| bayes | Beta-Binomial (tasa de acierto), Normal-Gamma (expectativa en R), Kelly binario | posteriores y casos límite |
| volatilidad | GARCH(1,1) por máxima verosimilitud, EWMA, Parkinson, Garman-Klass | GARCH recupera α y α+β de datos simulados |
| regimen | modelo oculto de Markov gaussiano (Baum-Welch con escalado + Viterbi) | separa calma y turbulencia > 90 % |
| filtros | Kalman (nivel y tendencia), Ornstein-Uhlenbeck (vida media) | menos ruido; vida media recuperada |
| informacion | entropía de Shannon y de permutación, información mutua, Hurst, razón de varianzas | Hurst ≈ 0,5 en ruido; VR > 1 en AR(1) |
| cartera | Ledoit-Wolf, mínima varianza, paridad de riesgo, CVaR, Kelly fraccionado | contribuciones iguales; CVaR normal ≈ 2,063 |
| deterioro | CUSUM, Page-Hinkley | detecta la caída y no da falsas alarmas |
| estocastico | GBM, saltos de Merton, OU, probabilidad de tocar objetivo o stop | media teórica; 50 % simétrico |
| aprendizaje | regresión logística L2 (IRLS) con walk-forward y Brier frente a la referencia | detecta la señal y **rechaza el ruido** |
| optimizacion | Nelder-Mead adaptativo, recocido simulado | Rosenbrock → (1, 1) |

**Regla:** un modelo nuevo solo se usa si mejora a la referencia **fuera de muestra**. XGBoost, LightGBM, PyTorch y JAX no se instalaron:
- no hay una GPU compatible con CUDA;
- primero hace falta demostrar que mejoran a lo que ya hay.

Se pueden evaluar con el mismo protocolo walk-forward.

---

## 4. Cerebro autónomo (C6) · módulo **✦ IA y cuántico**

Cada ciclo (cada 15 minutos, solo si el supervisor lo permite) hace lo siguiente:
1. Lee **solo** las operaciones cerradas y **verificadas por el broker** de cada cuenta.
2. **Inferencia bayesiana** por estrategia y por estrategia×activo:
   - en binarias, P(acierto > equilibrio);
   - en cTrader, P(expectativa > 0).

   La previa escéptica impide sacar conclusiones con pocas operaciones.
3. **Deterioro:** CUSUM sobre la secuencia de resultados.
4. **Patrones de pérdida:** por hora UTC, día, dirección, activo y estrategia.
5. **Estado del mercado** con velas reales de cTrader: régimen (modelo de Markov), volatilidad GARCH, Hurst, entropía y razón de varianzas.
6. **Decisiones trazables:**
   - **en práctica** bloquea una combinación con 6 o más operaciones y P(ventaja) < 10 %, lo que es más prudente y nunca añade riesgo;
   - **en REAL** solo **propone**;
   - todo es **reversible** desde la interfaz, y una decisión que tú revertiste no se vuelve a imponer.

Se conservan 200 versiones. El cerebro **no puede** cambiar límites de riesgo, encender el MODO LIVE ni levantar la PARADA TOTAL; lo impiden el código y las pruebas.

**Primera ejecución sobre tus datos reales:**
- **Binarias:** 27 operaciones; acierto posterior del 48,2 % frente a un equilibrio del 54,2 %; P(ventaja) del 26 %.
- **Patrones de pérdida:** a las 8:00 UTC y en las entradas alcistas.
- **Mercado:** EURUSD en calma, GERMANY 40 en turbulencia.
- **Bloqueos:** ninguno todavía, por muestra insuficiente.

---

## 5. Laboratorio cuántico experimental (C7)

- **Simulador:** de vector de estado propio, exacto, hasta 16 cúbits. Está aislado: no tiene acceso a bots ni brokers.
- **QAOA:** selección de cartera formulada como QUBO, con datos diarios reales de cTrader y covarianza de Ledoit-Wolf.
- **VQE:** ansatz RY + CZ sobre el mismo hamiltoniano.
- **QAE:** estimación de amplitud canónica, comparada con un Monte Carlo clásico que usa el mismo número de consultas.
- **Resultado con datos reales:**
  - QAOA coincide con el óptimo clásico (EURUSD, GBPUSD, AUDUSD), con 4,1 veces la probabilidad del azar;
  - VQE encuentra el óptimo;
  - QAE da un error de 0,0005 frente a 0,018 del Monte Carlo clásico.
- **Conclusión honesta:** es una simulación clásica, así que no hay ventaja de tiempo. A este tamaño, la fuerza bruta clásica es exacta. Sirve para tener preparadas las formulaciones por si algún día hay hardware cuántico útil.

---

## 6. Centro de servidores (C8) y supervisor (C9) · módulo **▦ Servidores**

- **Qué aparece:** cada motor (23), proceso (7) y broker activo como un servidor en rack con **5 LED de estado real**:
  1. ejecución;
  2. datos;
  3. inteligencia;
  4. conectividad;
  5. aprendizaje.
- **Colores:**
  - verde: funcionando;
  - **verde parpadeando**: procesando en este momento (CPU medida o actividad de menos de 2 minutos);
  - ámbar: en espera o con aviso;
  - **rojo parpadeando**: error;
  - gris: no aplica.

  **No hay actividad ficticia:** un motor que no se ha ejecutado aparece «en espera».
- **Doble clic en un servidor:** abre su panel técnico con identidad, función, algoritmos, entradas y salidas, dependencias, archivo, ejecuciones, errores, latencia, CPU y RAM, tiempo activo y eventos.
- **Controles de los procesos:** interruptor ON/OFF, pausar y reanudar, respetando las dependencias.
- **Supervisor:**
  - **prioridades:** 1 = ejecución, riesgo y brokers; 2 = datos; 3 = investigación;
  - **métricas reales** con psutil, con CPU por hilo;
  - **reinicio automático** de los procesos caídos, con espera creciente;
  - **gestión de carga:** con CPU > 85 % o RAM > 90 % pausa la investigación y la reanuda al bajar del 60 % / 75 %. Nunca fuerza el equipo al 100 %.
- **Registro de eventos en tiempo real**, con filtro.

---

## 7. Interruptor universal

En toda la plataforma, cada casilla de activar o desactivar es ahora un **interruptor pequeño**:
- verde con «ON» encima = encendido;
- rojo con «OFF» encima = apagado.

Se aplica a: brokers, fuentes de noticias, procesos, bloqueo de brokers del panel de seguridad, ajustes de los bots, alertas del calendario y cualquier opción nueva. Se aplica solo, sin tener que tocar cada pantalla.

---

## 8. Noticias (fase 2)

- **Datos OFICIALES publicados** desde la API pública del BLS: IPC general y subyacente (variación mensual e interanual), tasa de paro, nóminas no agrícolas y salario por hora. Se consultan como mucho 4 veces al día.
- **Alertas en la campana y en Telegram** (según tus preferencias), sin duplicados:
  - eventos de alto impacto del calendario dentro de tu ventana de aviso;
  - noticias urgentes y verificadas de alto impacto.
- **Léxico de sentimiento en español.**

---

## 9. Pruebas

**Batería completa:** 426 pruebas del paquete y 159 de la autoprueba, todas correctas. Incluye:
- `test_ciencia` (18);
- `test_plataforma` (15): conectores con respuestas simuladas según la documentación, firma de Kraken con el vector oficial, centro de brokers, supervisor, cerebro, laboratorio cuántico y centro de servidores;
- `test_interruptores` (7);
- `test_noticias` (18).

**Rendimiento** (`python -m titan_quant.rendimiento`) en este equipo (12 CPU, Python 3.13, numpy 2.5):

| Prueba | Mediana |
|---|---|
| HMM 2 estados · 1.000 velas | 1.509 ms |
| GARCH(1,1) por máxima verosimilitud · 1.000 velas | 57 ms |
| Hurst + entropía de permutación | 10 ms |
| Ledoit-Wolf + paridad de riesgo · 20 activos | 2,7 ms |
| Inferencia bayesiana · 1.000 resultados | 3,7 ms |
| QAOA p=2 · 8 cúbits | 464 ms |
| Estimación de amplitud · 8 cúbits de fase | 0,2 ms |
| Análisis de 1.000 noticias | 112 ms |
| Métricas de CPU y RAM por hilo | 38 ms |

---

## 10. Límites y pendientes (declarados)

1. **Conectores OANDA, Alpaca y Tradier:** están implementados según la documentación oficial y probados con respuestas simuladas, pero **la autenticación real está pendiente** de que abras la cuenta DEMO/paper e introduzcas las claves en ⇆ Brokers. Hasta entonces no figuran como conectados.
2. **Saxo, IG, Capital.com y Trading 212:** sus API se verificaron (piden credenciales) y son los siguientes en la cola.
3. **IBKR, MT5 y Moomoo:** requieren software local (TWS/IB Gateway, terminal MT5, OpenD).
4. **Schwab y Coinbase:** no tienen DEMO, así que **no se opera**.
5. **Bots:** siguen operando solo en cTrader DEMO e IQ Option PRACTICE. Los brokers nuevos sincronizan y permiten órdenes de prueba en DEMO; conectarlos a los bots será otra fase, después de verificar cada broker.
6. **Sin aceleración por GPU:** la AMD Radeon 760M no es compatible con CUDA.
7. **Cerebro:** con pocas operaciones verificadas no decide nada. Necesita muestra.
8. **Laboratorio cuántico:** es experimental y no tiene ventaja demostrada.
9. **HMM:** tarda unos 1,5 s por activo. Es aceptable para un ciclo de 15 minutos; se puede vectorizar más si hace falta.
