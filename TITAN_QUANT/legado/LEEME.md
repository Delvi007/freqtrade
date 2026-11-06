# TITAN GOLD NEWS v2 — instalación

Herramienta informativa: recopila noticias, las resume en español y las contrasta con datos de mercado.
No opera ni da señales de compra/venta. Solo usa la biblioteca estándar de Python.

## 1. Pasar el archivo a Ubuntu (desde Termux, una sola vez)
    termux-setup-storage
    cp ~/storage/downloads/TITAN_GOLD_NEWS_v2.tar.gz $PREFIX/var/lib/proot-distro/installed-rootfs/ubuntu/root/
    proot-distro login ubuntu

## 2. Instalar (dentro de Ubuntu) — conserva tu token y tu estado
    cd /root && cp -r TITAN_GOLD_NEWS TITAN_GOLD_NEWS_respaldo_$(date +%Y%m%d)
    tar -xzf TITAN_GOLD_NEWS_v2.tar.gz -C /root
    cd /root/TITAN_GOLD_NEWS

## 3. Probar (sin internet, no toca tus archivos)
    python3 probar.py          # debe terminar con: 28 de 28 pruebas correctas

## 4. Probar con internet real
    python3 pipeline_titan.py  # recopila, integra y analiza

## 5. Arrancar el bot de Telegram
    echo 'TU_TOKEN_NUEVO' > .telegram_token && chmod 600 .telegram_token
    bash iniciar.sh            # en Telegram escribe /start ; detener: Ctrl+C

## Qué cambió respecto a tu versión
- Si falla internet ya NO se borran las noticias guardadas; el pipeline se detiene con un aviso claro.
- El botón Analizar ejecuta el pipeline completo (recopilar → oro → integrar → análisis).
- Un texto cualquiera ya no repite el menú; solo /start o /menu.
- Ya no hay rutas fijas a /root/TITAN_GOLD_NEWS: funciona desde cualquier carpeta.
- auditar_ejecucion_titan.py corregido (se bloqueaba a sí mismo).
- Nuevo: probar.py, iniciar.sh, pruebas/.

## Carpeta archivo_historico/ (no se usa al ejecutar)
Todo lo anterior, por si lo necesitas: módulos antiguos, parches v3–v8, auditorías, informes y datos
(noticias_*.json, titan_integral.db del 25/10), copias de seguridad y los informes de auditoría.
No pisa tus archivos vivos. Los tokens fueron reemplazados por TU_TOKEN_PRIVADO.
`crear_titan_integral.py` está roto (pegado dos veces): no lo ejecutes; el sistema ya no lo necesita.

## v3 — Mis activos (futuros, cripto, divisas, acciones)
En Telegram, menú /menu:
- 📌 Mis activos: marca hasta 8 (Oro, Plata, Petróleo, S&P, Nasdaq, Bitcoin, Ethereum, EUR/USD, USD/DOP, Apple, Tesla...).
- /agregar SIMBOLO: cualquier símbolo de Yahoo Finance (ej. /agregar AMD, /agregar DOGE-USD).
- 🔮 Analizar mis activos: por cada uno, noticias de 48 h clasificadas, análisis técnico (EMA, MACD, RSI, niveles),
  hora próxima de más movimiento con su tendencia histórica, y una hipótesis a 4 h.
- 🎯 Precisión: cada hipótesis se guarda en titan_activos.db y se verifica sola 4 h después; aquí ves el % de acierto.
- Los envíos automáticos ahora incluyen también el análisis de tus activos.
Límites: las opciones no tienen datos gratuitos fiables, así que se sigue la acción subyacente. Son hipótesis,
no predicciones; con pocas hipótesis evaluadas el % de acierto no es concluyente (el azar da ~50%).

## v4 — Flujo guiado
Menú → 🎯 Activo analizar → categoría → activo → zona horaria → hora → "🧭 Resumen previo" en lenguaje natural
(sesgo, niveles, movimiento típico a esa hora y por qué). Luego: otra hora, otro activo o análisis completo.
Cada pronóstico por hora se guarda y se verifica solo cuando pasa (📈 Precisión).

## v5 — Teclado fijo, preguntas en el mismo mensaje y hoja PDF
- Teclado fijo abajo: 🎯 Analizar activo y 🟢/🔴 Prender/Apagar bot. Más opciones: /menu y los comandos (/oro, /sesgo, /sesiones, /precision, /horas, /zona, /activos, /estado).
- Las preguntas (categoría → activo → zona → hora) reemplazan el mismo mensaje; al final se entrega la hoja PDF.
- Hoja PDF: resumen ejecutivo, cifras clave, gráfico 48 h, lectura técnica, noticias, contexto (por qué importa),
  actividad/volumen por sesión, y escenarios de ruptura o rechazo para la hora elegida con checklist de señales.

## v6 — TITAN QUANT (escenarios, riesgo, vigilancia) y zonas de todo el mundo
- Zonas: /zona (todas las regiones y ciudades, con desfase UTC), /zona Madrid (búsqueda), y también dentro de 🎯 Analizar activo.
- Hoja PDF ampliada: ¿qué pasó y por qué?, macro/gobiernos/geopolítica, escenarios con stop-loss, take-profit, R/R y tamaño, fuentes.
- /riesgo CAPITAL PORCENTAJE: define el capital de referencia y el riesgo por operación (máximo 5%).
- /vigilar [minutos|apagar]: vigila los activos marcados en /activos y envía alertas por Telegram sin duplicados.
- /escenarios: escenarios activos y estadísticas. Todo es informativo: TITAN no ejecuta órdenes.
