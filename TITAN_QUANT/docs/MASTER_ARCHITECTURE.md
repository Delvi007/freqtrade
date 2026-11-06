# MASTER_ARCHITECTURE — TITAN QUANT v7

## Principio

El proyecto no se reconstruyó: la versión 7 añade el paquete `titan_quant/` encima de los módulos existentes, que siguen funcionando. La inteligencia (los 23 motores) y la ejecución (TITAN AUTO TRADER) están separadas. El bot nunca recalcula ni modifica una señal.

```
Navegador (web/index.html + tq_auth.js + tq_app.js)
   │  cookie de sesión HttpOnly + token CSRF
   ▼
titan_quant/servidor.py ── extiende api_web.Handler (las rutas heredadas exigen ahora sesión)
   ├── seguridad/  cuentas · bóveda cifrada · límites       ──► datos/titan_quant.db
   ├── motores/nucleo.py (1 CORE) ── capas por dependencias ──► 2..19
   │       mercado.py (2,3,4,5,9,10) · cuant.py (7,8,12,13,14,15) · info.py (6,11,16,17) · sistema.py (18..23)
   ├── alertas.py · historial.py · integraciones.py · correo.py
   └── trader/autotrader.py ── controles de riesgo ──► adaptadores: simulador · iqoption (PRACTICE) · ctrader (lectura)
Módulos heredados reutilizados: agente.py (Yahoo y noticias), chart_web.py, quotes_web.py, plan_web.py (vigilante),
lab_engine.py (Laboratorio), macro.py, escenarios.py, titan_bot.py + telegram_bot.py (bot de Telegram), iqoption_data.py
```

## Contrato de datos entre motores

Cada motor recibe `ctx` (activo, horizonte, parámetros efectivos del nivel y `res` con los resultados de los motores anteriores) y devuelve siempre un `ResultadoMotor` con esta forma:

`{motor, numero, nombre, estado, duracion_ms, salida, notas, faltantes, error}`.

Los estados posibles son: `completado`, `simplificado`, `sin_datos`, `aplazado` o `error`. Cuando un motor no tiene datos devuelve `sin_datos` y no inventa valores. El fallo de un motor no tumba a los demás.

Las series de precios llevan siempre su origen: `proveedor`, `simbolo_proveedor` y `tipo` (futuro, divisa_spot, cripto_spot, índice, acción/ETF o CFD), además de la hora y la calidad. Por eso el bot y los motores saben de dónde viene cada precio.

## Flujo del análisis (ANALIZAR MERCADO)

1. HARDWARE y ADAPTIVE fijan los parámetros efectivos del nivel elegido. Si reducen algo, lo dicen.
2. DATA obtiene las velas del horizonte y mide su calidad. FEATURES las transforma.
3. TECHNICAL, REGIME, STATISTICAL, ML, MICROSTRUCTURE, RISK, BACKTEST y MONTE CARLO se ejecutan en paralelo dentro de cada capa.
4. FUSION combina los votos (con pesos públicos) y aplica las puertas de seguridad. El resultado es un escenario completo o «no hay oportunidad válida» acompañado de vigilancia prospectiva.
5. RESEARCH redacta el informe. El análisis se guarda y, si corresponde, genera alertas, que se envían a Telegram cuando son altas o críticas.

## Flujo del bot operador (cada ciclo)

1. Comprueba la parada de emergencia.
2. Actualiza las operaciones abiertas.
3. Pide un análisis.
4. Si hay escenario, pasa los 14 controles.
5. Ejecuta con el adaptador de la modalidad.
6. Registra la decisión con los motores que participaron y los controles aplicados.

El modo real está bloqueado por diseño.

## Rendimiento medido (en la nube, datos sintéticos)

Un análisis completo tarda unos 0,5 s en nivel básico, 1,3 s en intermedio, 3,3 s en avanzado y 6,6 s en súper. En un teléfono puede tardar entre 3 y 10 veces más. El presupuesto de tiempo por nivel va de 60 a 240 s.
