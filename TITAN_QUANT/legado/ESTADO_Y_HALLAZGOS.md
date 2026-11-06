# Estado y hallazgos (revisión del 26–27/10/2026)

## Corregido en esta versión
1. titan_gold_news.py borraba noticias_recopiladas.json (55 → 0) si fallaba internet y salía con código 0.
2. recopilador_noticias.py sobrescribía noticias_en_vivo.json con 0 noticias en el mismo caso.
3. Botón Analizar no usaba pipeline_titan.py (se saltaba recopilar e integrar).
4. Cualquier texto repetía el menú de Telegram.
5. auditar_ejecucion_titan.py se bloqueaba (candado no reentrante en el tracer): la sesión del 25/10 nunca arrancó el bot.
6. Rutas fijas /root/TITAN_GOLD_NEWS eliminadas.

## No resuelto / pendiente
- crear_titan_integral.py: pegado dos veces, sintaxis rota en la línea 1284 (en archivo_historico).
- Clasificador por palabras clave débil (53 de 55 noticias "indeterminadas"); no son probabilidades.
- Análisis técnico (titan_tecnico.py) solo probado con datos sintéticos.
- Fechas "27 de octubre" en el informe: probablemente UTC (tu hora local aún era 26); verificar el timestamp crudo.
- Probado solo con internet simulado: falta validar con fuentes reales y con Telegram real.
- Seguridad: regenerar el token (/revoke en @BotFather); estaba en crear_titan_integral.py y en el historial de comandos.

## v3 (multi-activo) — notas
- Nuevo: activos.py (catálogo), agente.py (noticias por activo, técnico, horas de más movimiento, verificación a 4 h).
- Clasificación de titulares por reglas de palabras completas (inglés/español); simple y revisable, no entiende el contexto.
- Las horas de más movimiento son estadística histórica de 30 días por hora local, no una señal.
- Probado con internet simulado (60 pruebas); falta validarlo con fuentes reales y acumular hipótesis para medir acierto.

## v6 — qué cubre la especificación TITAN QUANT y qué no
Cubierto: escenarios estructurados con estados, rupturas/rechazos/rebotes/falsas rupturas/rango, stop-loss y take-profit
condicionales, riesgo y tamaño, alertas (aproximación, provisional, confirmada, invalidada, objetivo, stop, tendencia,
macro, tipos, volatilidad, datos obsoletos/errores, reanudación, resumen), registro en SQLite y estadísticas con muestra mínima.
No cubierto (sin fuente de datos gratuita verificada): calendario económico con consenso, COT/posicionamiento, flujos de ETF,
compras de bancos centrales, interés abierto, opciones, XAU/USD al contado, EMA200/Bandas/VWAP, correlaciones.
La especificación recibida llegaba cortada en la sección 15 (validación estadística); se aplicó una versión básica.
