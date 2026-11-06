# IMPLEMENTATION_STATUS — TITAN QUANT v7.2.0 (05/11/2026)

Escala usada (sección 21 de la orden maestra):

- **Implementado**: el código existe.
- **Integrado**: está conectado al resto del sistema (API, interfaz, otros motores).
- **Probado**: pasa pruebas automáticas con datos sintéticos o simulados.
- **Validado**: comprobado con datos y servicios REALES. **Nada está validado todavía**: el entorno donde se construyó no tenía acceso a Yahoo, Google News, Telegram, IQ Option ni cTrader. Hay que validarlo en tu Termux.
- **Parcial**: funciona, pero no cubre todo lo que pide la orden.
- **Pendiente**: no existe.
- **Bloqueado**: no se puede hacer sin un requisito externo.

La palabra «terminado» no se usa en este documento.

## Los 23 motores

| # | Motor | Estado | Qué hace / límites |
|---|---|---|---|
| 1 | TITAN CORE | Integrado · Probado | Orquesta por capas de dependencias, con hilos y un presupuesto de tiempo por nivel; aplaza motores y lo informa. |
| 2 | DATA ENGINE (+ PRICE SYNC) | Integrado · Probado | Yahoo con proveedor, instrumento, edad, huecos y calidad. Sincroniza con IQ Option solo si está disponible. Sin bid/ask en Yahoo. |
| 3 | FEATURE ENGINEERING | Integrado · Probado | EMA, RSI, MACD, ATR, volatilidad, z-score y volumen relativo. Hay una prueba que confirma que no mira al futuro. |
| 4 | TECHNICAL INTELLIGENCE | Integrado · Probado | Tendencia, estructura, soportes y resistencias por pivotes, Bollinger y ADX. |
| 5 | CROSS-ASSET | Integrado · Probado | Correlaciones y beta diarias contra 3 a 12 referencias (DXY, ^TNX, ^GSPC, ^VIX…). |
| 6 | MACROECONOMIC | Parcial | Titulares macro por tipo y rendimientos de bonos. **No hay calendario con consenso** (no existe una fuente gratuita verificada). |
| 7 | STATISTICAL | Integrado · Probado | Momentos, Jarque-Bera, autocorrelación, Hurst y ratio de varianza. |
| 8 | MACHINE LEARNING | Integrado · Probado | Regresión logística (y Bayes en niveles altos) con walk-forward purgado. Solo se usa si mejora el Brier de la tasa base. |
| 9 | MARKET REGIME | Integrado · Probado | Eficiencia de Kaufman, ADX y percentil de volatilidad. |
| 10 | MICROSTRUCTURE | Parcial | Spread estimado con Corwin-Schultz y Roll, más liquidez por hora. **El spread real necesita bid/ask**, que Yahoo no da. |
| 11 | NEWS INTELLIGENCE | Integrado · Probado | Google News más un clasificador de palabras clave. No entiende contexto y pesa poco en la fusión. |
| 12 | RISK INTELLIGENCE | Integrado · Probado | VaR y ES históricos, stop por ATR y tamaño según capital y % de riesgo. |
| 13 | BACKTESTING | Integrado · Probado | Simulación vela a vela con costes, dentro y fuera de muestra, e IC de Wilson. Hay una prueba de que no mira al futuro. |
| 14 | MONTE CARLO | Integrado · Probado | Bootstrap por bloques del precio y remuestreo de las operaciones del backtest: de 300 a 10 000 simulaciones. |
| 15 | PORTFOLIO | Integrado · Probado | Pesos por volatilidad inversa y por mínima varianza, y ratio de diversificación. Necesita al menos 2 activos marcados. |
| 16 | RESEARCH | Integrado · Probado | Informe determinista con cuatro niveles de profundidad. |
| 17 | FUSION | Integrado · Probado | Escenario con todos los campos de la sección 7, más puertas de seguridad y vigilancia prospectiva. |
| 18 | ADAPTIVE PROCESSING | Integrado · Probado | Ajusta la carga a la memoria, los núcleos y la carga del sistema. Nunca cambia el nivel elegido. |
| 19 | HARDWARE DIAGNOSTICS | Integrado · Probado | CPU, memoria, disco, temperatura (si es accesible), red y procesos. **Sin GPU**: no hay acceso desde Python estándar, y se dice. |
| 20 | MONITORING | Integrado · Probado | Estado de los motores, hilos, integridad de las bases y el vigilante. |
| 21 | API ENGINE | Integrado · Probado | Más de 50 rutas, con sesión, CSRF, origen y límites. |
| 22 | WEB DASHBOARD | Integrado · Probado | Es la interfaz existente más las vistas nuevas. Probada en Chromium en escritorio (1366 px) y en móvil (390 px). |
| 23 | TELEGRAM NOTIFICATION | Integrado · Probado (simulado) | Envía alertas altas y críticas. El bot interactivo existente se conserva. |

## Plataforma

| Componente | Estado | Nota |
|---|---|---|
| 4 niveles + 3 políticas | Integrado · Probado | Los 23 motores se ejecutan en los 4 niveles; hay una prueba para cada nivel. |
| Horizontes (scalping … largo plazo) | Integrado · Probado | |
| Cuentas: registro, verificación, inicio de sesión, recuperación, sesiones, eventos | Integrado · Probado | La primera cuenta (administrador) se activa sin correo desde el propio teléfono. |
| Correo SMTP | Integrado · Probado (SMTP simulado) · no validado | Configuraciones listas para Gmail (contraseña de aplicación) y Brevo, con botón de correo de prueba. Hotmail/Outlook.com personal no permite enviar (Microsoft exige OAuth2). |
| Panel de Administración | Integrado · Probado | Solicitudes, aprobación con correo de aceptación, suspensión, administradores y bloqueo por intentos. |
| Credenciales cifradas (bóveda) | Integrado · Probado | AES-256-GCM si el paquete `cryptography` está instalado; si no, HMAC-SHA256-CTR con HMAC. |
| Configuración e integraciones (9.x) | Integrado · Probado | Estados reales. Solo pasa a «conectada» tras una prueba real. |
| Centro de alertas + sonidos | Integrado · Probado | No duplica alertas ni suena dos veces por la misma. |
| Historial: ocultar, archivar, restaurar y eliminar permanentemente | Integrado · Probado | Ocultar no borra nada. Solo se pueden eliminar análisis que ya estén archivados. |
| TITAN AUTO TRADER, tres cuentas | Integrado · Probado | Simulación, DEMO y REAL independientes, cada una con su base; 14 controles + spread real + ventaja demostrada (REAL); parada de emergencia por cuenta. |
| Conocimiento compartido | Integrado · Probado | Resultados en R de las tres cuentas; nada más se comparte. |
| Adaptador IQ Option, modo demo | Implementado · **no probado** | Usa una librería no oficial (no instalada aquí), solo en PRACTICE y solo binarias. |
| Adaptador cTrader DEMO y REAL | Integrado · Probado (servidor cTrader simulado) · **no validado** | Órdenes a mercado con stop/objetivo, tamaño por riesgo, seguimiento, cierre y renovación de token por la Open API JSON. Validar primero con tu cuenta DEMO. |
| Modo REAL (cTrader live) | Disponible **bajo bloqueo** | Exige pruebas superadas, token con permiso de trading, ≥ 1 operación DEMO cTrader completa, frase + contraseña desde el teléfono, contraseña al iniciar y, por defecto, ventaja demostrada. |
| XTB y otros brokers | Pendiente | La arquitectura de adaptadores está lista. XTB no tiene una API pública verificada. |
| HTTPS | Pendiente (configurable) | Para publicar fuera de localhost hace falta un proxy con TLS. Con `TITAN_HTTPS=1` las cookies llevan `Secure`. |
| Aprendizaje progresivo | Parcial | Lo cubre el Laboratorio existente (validación y rechazo de modelos). El motor de ML no se reentrena solo en segundo plano. |
