# BROKER_ADAPTERS — TITAN QUANT v7.2

Todos los adaptadores implementan `trader/base.py`: `conectado`, `cotizacion`, `abrir`, `actualizar`, `cerrar` y `verificar`, además de una ficha documental (mercados, órdenes, modalidades, autenticación, comisiones, spreads, límites, restricciones y compatibilidad).

| Adaptador | Mercados | Órdenes | Modalidad | Autenticación | Compatibilidad demostrada |
|---|---|---|---|---|---|
| IQ Option (no oficial) | Binarias, forex, cripto, CFD | Binaria | Demo (PRACTICE) | Correo y contraseña cifrados | **No**: la librería `iqoptionapi` no estaba instalada. Compruébalo con «Probar conexión». |
| cTrader Open API | Forex, metales, índices, energía, CFD | A mercado con stop y objetivo relativos | **Demo y Real (LIVE)**, cada una con su base | OAuth 2.0 con `scope=trading` dentro de TITAN | Probado contra un servidor cTrader simulado (protocolo JSON oficial). **Valídalo primero con tu cuenta DEMO.** |

## cTrader: cómo opera TITAN

- **Conexión:** WebSocket TLS a `demo.ctraderapi.com:5036` (DEMO) o `live.ctraderapi.com:5036` (REAL), mensajes JSON `{clientMsgId, payloadType, payload}`. Una sesión corta por operación: autentica la app, comprueba que la cuenta elegida pertenece al token **y es del tipo de la modalidad**, y autentica la cuenta.
- **Datos:** velas (trendbars) del propio broker para el análisis y bid/ask reales al suscribirse a spots.
- **Tamaño:** unidades = riesgo (divisa de la cuenta) ÷ (distancia al stop × conversión). Volumen en centésimas de unidad, redondeado **hacia abajo** al paso; por debajo del mínimo la orden se rechaza.
- **Niveles:** `relativeStopLoss`/`relativeTakeProfit` en 1/100000, múltiplos de los decimales del símbolo (obligatorio en órdenes a mercado).
- **Seguimiento:** reconcile para saber si sigue abierta; deals de cierre para el resultado neto (bruto + swap + comisión) en la divisa de la cuenta.
- **Emergencia:** cierra las posiciones del bot en el broker. Si una no se puede cerrar, alerta crítica para cerrarla a mano.
- **Token:** se renueva solo con el refresh token; si no tiene permiso de trading, TITAN no envía órdenes y te pide volver a autorizar.
- **No implementado:** órdenes pendientes (limit/stop), cierres parciales, modificar stops de una posición abierta.

## IQ Option: capacidades y límites

IQ Option no publica una API oficial. La librería comunitaria permite conectar, cambiar el balance entre PRACTICE y REAL, consultar el catálogo por categoría, pedir velas históricas (en lotes de 1000) y en tiempo real, y `buy(monto, activo, call/put, minutos)` con su `check_win_v3`.

No ofrece bid, ask ni spread en las velas, y sus límites no están documentados.

TITAN comprueba que el balance sea **PRACTICE** justo antes de cada orden y no implementa el modo REAL. Una binaria solo se abre si el motor de ML está calibrado fuera de muestra y la probabilidad supera el punto de equilibrio del payout (1/(1+payout)) más 2 puntos.

**Aviso legal:** las opciones binarias están prohibidas a minoristas en la UE, el Reino Unido y otros países. Además, el uso automatizado de una API no oficial puede infringir los términos de IQ Option.

## Cómo añadir un broker

1. Crea `trader/mi_broker.py` con una clase que herede de `Adaptador` y rellene su ficha.
2. Añade el proveedor a `integraciones.CATALOGO` con sus campos.
3. Conéctalo en `autotrader.adaptador_para` y en `BROKERS`.
4. Escribe sus pruebas. La compatibilidad solo se declara cuando las pruebas pasan.
