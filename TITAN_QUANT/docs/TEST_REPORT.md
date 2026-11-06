# TEST_REPORT — TITAN QUANT v7.2.0 (05/11/2026)

**Entorno de construcción:** Linux en la nube, Python 3.13 y Chromium + Playwright. No había acceso a internet: todas las pruebas usan datos de mercado **sintéticos y deterministas** (`titan_quant/pruebas/sintetico.py`).

En tu Termux, el comando `python3 -m titan_quant.cli probar` repite las baterías 1 a 4 sobre una copia temporal, sin tocar tus datos.

| # | Batería | Resultado |
|---|---|---|
| 1 | Sintaxis: compilación de todos los módulos (`compileall`) + `node --check` de los 3 JS nuevos y los 8 scripts del index | Correcto |
| 2 | Pruebas TITAN QUANT (`unittest`): seguridad, 23 motores, bot operador, alertas, historial, integraciones y servidor HTTP | **92 de 92** |
| 3 | Autoprueba heredada `probar.py`: bot de Telegram, pipeline, escenarios y PDF | **159 de 159** |
| 4 | Autoprueba del Laboratorio (`lab_engine.py --autoprueba`) | **17 de 17** |
| 5 | Navegador real (Chromium) en escritorio (1366 px) y móvil (390 px): registro → verificación → login → las 12 vistas → ANALIZAR MERCADO → ciclo del bot → credencial enmascarada → salir | **54 de 54**, sin errores de JavaScript (incluye: alta del administrador, aprobación de un segundo usuario, selector de cuenta, DEMO sin datos de la simulación, cuentas cTrader filtradas demo/live, ciclo del bot DEMO contra cTrader simulado, REAL bloqueado sin contraseña) |
| 6 | Conexiones entre módulos: grafo de imports, símbolos usados entre módulos e imports relativos de los 39 módulos del paquete | 0 referencias rotas, 0 ciclos |
| 7 | Migración con TUS bases reales del backup (titan_activos, titan_planes, titan_lab) y rutas heredadas con sesión | Correcto; 5 727 filas corruptas reparadas |
| 8 | Instalador `instalar_termux.sh` en un HOME simulado con una instalación anterior | Correcto: migra los datos, aparta `~/TITAN_QUANT` y pasa las pruebas |

**Nota:** `probar.py` tenía 177 pruebas y ahora tiene 159. Las 18 que faltan eran comprobaciones de sintaxis de archivos que se movieron a `legado/` o que no se incluyen (como los `parche_*.py`).

## Pruebas nuevas de la v7.2 (cTrader y cuentas separadas)

Contra un **servidor cTrader simulado** (DEMO y LIVE en puertos distintos, cada uno solo con sus cuentas) que habla el protocolo JSON oficial:
- Saludo WebSocket, heartbeat y ping; credenciales de app incorrectas; enums como número o texto.
- Tamaño por riesgo (USD y cuenta en EUR con conversión), redondeo hacia abajo, rechazo bajo el mínimo, stops relativos múltiplos del paso de precio.
- Cuenta REAL usada en DEMO (y al revés) → rechazada. Token de solo lectura → no envía órdenes. Token caducado → se renueva y se guarda cifrado.
- Bot DEMO completo: velas y saldo del broker, apertura, objetivo tocado en el broker, resultado y R, aprendizaje en el conocimiento sin datos de cuenta.
- Emergencia que cierra en el broker. Broker caído → no opera y avisa.
- REAL: bloqueado sin habilitar, sin operación DEMO previa, sin contraseña y sin ventaja; cuando se permite, la orden va SOLO al servidor LIVE y se guarda SOLO en `real.db`, con el saldo real.
- Bases: una base no se puede abrir como otra modalidad; migración desde la v7.1 reparte las operaciones por cuenta sin borrar el original.
- API: cuentas filtradas por modalidad, símbolos por cuenta, arranque REAL sin contraseña → 403, decisiones de una cuenta invisibles en otra.

## Qué cubren las pruebas de la v7.0/7.1 (selección)

- **Cifrado:** ida y vuelta con los dos algoritmos, detección de manipulación, cifrado ligado a la fila y permiso 600 de la clave maestra.
- **Contraseñas:** scrypt y PBKDF2.
- **Cuentas:**
  - Mensaje genérico que no permite enumerar cuentas.
  - Bloqueo tras 5 fallos.
  - Tokens de un solo uso que caducan.
  - El restablecimiento cierra las sesiones.
  - En la base solo se guardan hashes de los tokens.
- **Servidor:** todas las rutas exigen sesión; se rechazan las peticiones sin CSRF o con un Origin ajeno; cabeceras de seguridad; límite de inicios de sesión (429); permisos de propietario; privacidad entre usuarios; un error 500 no revela detalles; los secretos no aparecen en ninguna respuesta ni en el registro.
- **Motores:**
  - Los 23 motores, con ficha completa y sin dependencias circulares.
  - Los 4 niveles se ejecutan sin errores.
  - Cambiar el FUTURO no altera los indicadores, las variables de ML ni las operaciones del backtest pasadas.
  - Con un paseo aleatorio, el ML no se declara calibrado.
  - Sin datos no se inventa ningún escenario.
  - Si se agota el presupuesto de tiempo, los motores restantes quedan aplazados y se informa.
  - Con memoria baja se reduce la carga sin cambiar el nivel.
- **Bot operador:**
  - Duplicados.
  - Datos obsoletos.
  - Desconexión.
  - Volatilidad.
  - Slippage.
  - Pérdida diaria.
  - Racha de pérdidas.
  - Binaria sin probabilidad calibrada.
  - Emergencia.
  - Rechazo del broker.
  - Modo real bloqueado.
  - No se puede cambiar la configuración con el bot activo.
  - En el simulador, cierres por stop, objetivo y vencimiento.
- **Alertas e historial:** sin duplicados, silenciar categorías, ocultar sin borrar, archivar y restaurar, y eliminación permanente con todas sus restricciones.
- **Administración:** primera cuenta local activada sin correo; desde la red sí exige correo; propietario atascado que se activa al entrar desde el dispositivo; solicitud, aprobación y correo de aceptación (también por un SMTP simulado); suspensión que corta la sesión; solo el propietario nombra administradores; errores SMTP explicados (Hotmail, Gmail).
- **Integraciones:** máscaras, estados, errores que no filtran secretos y `state` de OAuth.

## Lo que NO se pudo probar aquí (hay que validarlo en tu dispositivo)

1. Datos reales de Yahoo, Google News y el Tesoro. La lógica es la misma que ya usabas, pero los motores nuevos no se han ejecutado con datos reales.
2. Envío real a Telegram y correo SMTP real.
3. IQ Option: la librería `iqoptionapi` no estaba instalada. El adaptador demo **no está probado**.
4. cTrader con tus cuentas reales de Spotware: el protocolo se probó con un servidor simulado fiel a la documentación, pero **la primera validación debe ser en DEMO** (abre y cierra una operación pequeña y compárala con la app de cTrader).
5. Rendimiento en el teléfono: en la nube, el nivel súper tarda unos 7 s con datos sintéticos; en Android puede tardar varias veces más.
6. Python 3.14 de tu proot: aquí se probó con 3.13. No hay sintaxis exclusiva de 3.14.

## Resultados financieros

Ninguna estrategia ha demostrado ventaja. El laboratorio del backup acumula −161,8 R en 371 operaciones simuladas. TITAN v7 lo refleja así:

- La fusión exige expectativa positiva fuera de muestra antes de declarar una oportunidad.
- Las binarias exigen una probabilidad calibrada.

El rendimiento pasado no garantiza resultados futuros.
