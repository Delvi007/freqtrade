# TITAN QUANT · Inteligencia de noticias

Centro de inteligencia informativa financiera. Recopila, analiza y entrega a los motores información de fuentes
institucionales, reguladores, medios financieros y medios cripto, con preferencia por fuentes primarias gratuitas.

**Principios.** No se inventan noticias ni conexiones. Una fuente solo figura como *conectada* tras superar la prueba de
recepción. El contenido externo es un dato y nunca se toma como instrucción. Una noticia nunca es por sí sola una señal
de compra o de venta.

## 1. Dónde está

| Pieza | Archivo |
|---|---|
| Catálogo inicial, acceso y calificación | `titan_quant/noticias/catalogo.py` |
| Base de datos propia | `datos/noticias/noticias.db` (`titan_quant/noticias/almacen.py`) |
| Recopilación, validación y deduplicación | `titan_quant/noticias/recolector.py` |
| Análisis (entidades, sentimiento, tono, rumores, puntuaciones) | `titan_quant/noticias/analisis.py` |
| Calendario económico y alertas | `titan_quant/noticias/calendario.py` |
| Entrega a los motores y trazabilidad | `titan_quant/noticias/integracion.py` |
| Panel web | `web/tq_noticias.js`, en el módulo **📰 Noticias** de la barra superior |
| Pruebas | `titan_quant/pruebas/test_noticias.py` (18 pruebas, sin red) |

El recopilador arranca solo con el servidor (`python -m titan_quant.cli servidor`). Cada minuto revisa qué fuentes toca
consultar según la frecuencia de cada una.

## 2. Catálogo de fuentes y matriz de gratuidad

Resultado de la prueba en vivo del 09/11/2026. El estado se vuelve a comprobar en cada recogida.

| Fuente | Tipo | Calificación TITAN | Acceso | Estado | Frecuencia |
|---|---|---|---|---|---|
| Federal Reserve · comunicados | Banco central | ★★★★★★ | RSS público gratuito | conectada | 10 min |
| Federal Reserve · discursos | Banco central | ★★★★★★ | RSS público gratuito | conectada | 30 min |
| Banco Central Europeo · prensa | Banco central | ★★★★★★ | RSS público gratuito | conectada | 10 min |
| Banco Central Europeo · blog | Banco central | ★★★★★★ | RSS público gratuito | conectada | 60 min |
| Bank of England · noticias | Banco central | ★★★★★★ | RSS público gratuito | conectada | 10 min |
| Bank of Japan · novedades | Banco central | ★★★★★★ | RSS público gratuito | conectada | 15 min |
| Bank of Canada · comunicados | Banco central | ★★★★★★ | RSS público gratuito | conectada | 15 min |
| Reserve Bank of Australia | Banco central | ★★★★★★ | RSS público gratuito | conectada | 15 min |
| Reserve Bank of New Zealand | Banco central | ★★★★★★ | RSS público gratuito | conectada | 15 min |
| Swiss National Bank | Banco central | ★★★★★★ | RSS público gratuito | conectada | 15 min |
| U.S. Bureau of Labor Statistics | Estadística oficial | ★★★★★★ | RSS público gratuito | conectada | 30 min |
| SEC · comunicados | Regulador | ★★★★★★ | RSS público gratuito | conectada | 30 min |
| CFTC · comunicados | Regulador | ★★★★★★ | RSS público gratuito | conectada | 30 min |
| FINRA · novedades | Regulador | ★★★★★★ | RSS público gratuito | conectada | 60 min |
| ESMA · novedades | Regulador | ★★★★★★ | RSS público gratuito (sin fechas) | conectada | 60 min |
| FCA · noticias | Regulador | ★★★★★★ | RSS público gratuito (sin fechas) | conectada | 60 min |
| Eurostat · actualizaciones | Estadística oficial | ★★★★★★ | RSS público gratuito | desactivada por defecto (cientos de avisos técnicos) | 60 min |
| Bloomberg · mercados | Medio | ★★★★★ | Titulares gratis · artículo de pago | conectada | 10 min |
| Financial Times | Medio | ★★★★★ | Titulares gratis · artículo de pago | conectada | 10 min |
| The Wall Street Journal · mercados | Medio | ★★★★★ | Titulares gratis · artículo de pago | conectada | 10 min |
| The Economist · finanzas | Análisis | ★★★★★ | Titulares gratis · artículo de pago | conectada | 60 min |
| CNBC | Medio | ★★★★ | RSS público gratuito | conectada | 10 min |
| MarketWatch | Medio | ★★★★ | RSS público gratuito | conectada | 10 min |
| CME Group (relación con inversores) | Mercado | ★★★★ | RSS público gratuito | conectada | 60 min |
| Nasdaq · mercados | Mercado / agregador | ★★★ | RSS público gratuito | conectada | 15 min |
| Investing.com | Agregador | ★★★ | RSS público gratuito | conectada | 15 min |
| CoinDesk | Cripto | ★★★★ | RSS público gratuito | conectada | 10 min |
| The Block | Cripto | ★★★★ | RSS público gratuito | conectada | 10 min |
| Decrypt | Cripto | ★★★★ | RSS público gratuito | conectada | 15 min |
| Cointelegraph | Cripto | ★★★ | RSS público gratuito (incluye patrocinado) | conectada | 15 min |
| Bitcoin Magazine | Cripto | ★★★ | RSS público gratuito (línea de defensa de Bitcoin) | conectada | 30 min |
| Calendario semanal (Fair Economy / ForexFactory) | Calendario | ★★★ | JSON público gratuito (fuente secundaria) | conectada | 60 min |
| **No disponibles** | | | | | |
| Reuters | Medio | ★★★★★ | Sin RSS público desde 2020; acceso por licencia (Reuters Connect) | no se conecta | — |
| Barron's | Medio | ★★★★★ | Responde 403 a clientes automáticos | no se conecta | — |
| Fondo Monetario Internacional | Organismo | ★★★★★★ | Responde 403 a clientes automáticos | no se conecta | — |
| OCDE | Organismo | ★★★★★★ | Responde 403 a clientes automáticos | no se conecta | — |
| Banco Mundial | Organismo | ★★★★★★ | No se encontró RSS válido | no se conecta | — |
| U.S. Bureau of Economic Analysis | Estadística oficial | ★★★★★★ | Su robots.txt prohíbe lectores automáticos | se respeta: no se lee | — |
| Yahoo Finance | Agregador | ★★★ | Su robots.txt prohíbe leer el RSS | se respeta: no se lee | — |
| Federal Reserve Bank of New York | Banco central | ★★★★★★ | La URL de RSS devuelve una página web, no un feed | no se conecta | — |
| Cboe, NYSE/ICE | Mercado | ★★★★ | No se localizó RSS público | no se conecta | — |

**No se elude ninguna restricción.** No se leen artículos de pago, no se ignora robots.txt y no se cambia el
identificador del lector para saltarse un bloqueo.

## 3. Calificación de confiabilidad

Es una escala **interna de TITAN** de 1 a 6 estrellas. **No es una certificación oficial.**

- **★★★★★★ Fuente primaria institucional:** banco central, estadística oficial o regulador. Es la máxima prioridad interna.
- **★★★★★ Alta confiabilidad:** medio de referencia con equipo editorial identificado y correcciones públicas.
- **★★★★:** confiable, con matices (medio generalista o especializado).
- **★★★:** útil, pero conviene verificar (agregador, contenido patrocinado o línea editorial de defensa).

Se calcula con 10 criterios valorados de 0 a 5:
1. Autoridad.
2. Transparencia editorial.
3. Autor identificado.
4. Calidad documental.
5. Exactitud histórica.
6. Correcciones públicas.
7. Velocidad.
8. Independencia.
9. Fuentes primarias.
10. Tasa de errores.

La popularidad no cuenta. Los criterios de cada fuente se pueden ajustar desde la configuración.

## 4. Cómo se recopila

- **Formatos:** RSS 2.0, Atom y RDF. Si el XML viene mal formado, se usa un lector tolerante. El calendario llega en JSON.
- **Ahorro de peticiones:** se usan peticiones condicionales con ETag e If-Modified-Since; si el servidor responde 304, no se descarga nada.
- **Ritmo:**
  - frecuencia mínima de 5 minutos por fuente;
  - 2 segundos entre peticiones al mismo servidor;
  - límite configurable de consultas por hora.
- **Reintentos:** hasta 3, con espera creciente. Después de 3 fallos seguidos, la fuente se consulta con menos frecuencia.
- **robots.txt:** se consulta y se respeta, con caché de 24 horas.
- **Seguridad:** solo se admiten URL http(s) públicas. Se rechazan localhost y las redes privadas.
- **Qué se guarda:** titular, resumen de 400 caracteres como máximo, enlace, autor, fechas y fuente. **Nunca el artículo completo.**
- **Validación:** una fuente queda *conectada* solo si:
  - responde;
  - entrega elementos con titular;
  - y su publicación más reciente es lo bastante nueva para su tipo: 72 h en medios, 10 días en análisis, 30–45 días en instituciones.

  Cada prueba queda registrada con: HTTP, número de elementos, elementos con fecha, antigüedad, latencia y duplicados.
- **Deduplicación:** dos titulares de distintas fuentes se tratan como el mismo acontecimiento si coinciden al menos un 55 % (índice Jaccard) en 48 h. Se conservan todas las fuentes que lo confirman, y la confirmación por otra fuente marca el acontecimiento como verificado.
- **Fuentes sin fecha (ESMA, FCA):**
  - en la primera carga se marcan como «fecha no publicada por la fuente» y no aparecen como recientes;
  - después se fechan por la hora de recepción.

## 5. Análisis

Usa reglas y léxicos propios, deterministas y revisables. No es un modelo de lenguaje: no entiende la ironía ni el contexto largo.

- **Categoría:** tipos de interés, inflación, empleo, PIB, actividad, bonos, comercio, geopolítica, regulación, resultados, materias primas, cripto y tecnología.
- **Entidades:**
  - monedas: USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD;
  - países;
  - materias primas: oro, plata, petróleo, gas, cobre;
  - criptoactivos: BTC, ETH, SOL, XRP, stablecoins, exchanges y regulación cripto;
  - índices: S&P 500, Nasdaq, Dow, DAX, FTSE, Nikkei, Stoxx, ASX;
  - grandes empresas, tickers y sectores.

  Los comunicados de un banco central se asocian a su moneda aunque el texto no la nombre.
- **Sentimiento:** léxico financiero con tratamiento de la negación, de −1 a +1.
- **Tono monetario:** restrictivo (+1) o expansivo (−1).
- **Rumores:** expresiones como «reportedly», «sources say», «in talks» o «could». Bajan la confiabilidad y la noticia no se verifica.
- **Urgencia:** última hora, emergencia, decisiones imprevistas, suspensiones o hackeos.
- **Sorpresa frente a la previsión:** cuando el texto la cita, por ejemplo «0.4% … above the 0.3% expected».
- **Contradicciones:** se señalan cuando varias fuentes del mismo acontecimiento tienen sentimientos opuestos.
- **Seis puntuaciones de 0 a 100:**
  1. Confiabilidad de la fuente.
  2. Confiabilidad de la información.
  3. Relevancia financiera.
  4. Impacto potencial.
  5. Urgencia.
  6. Nivel de confirmación.
- **Impacto en los mercados:** indica los mercados expuestos (forex, acciones/ETF, cripto, materias primas), con su horizonte y su incertidumbre. Describe a qué está expuesto cada mercado, **no hacia dónde se moverá**.
- **Reanálisis:** cuando cambian las reglas (`analisis.VERSION`), al arrancar se recalculan las noticias guardadas.

## 6. Calendario económico

- **Fuente:** el calendario semanal público de Fair Economy (formato ForexFactory). Es una fuente **secundaria**.
- **Qué trae:** hora, moneda, impacto, previsión y dato anterior.
- **Qué no trae:** el **dato publicado**. TITAN lo deja vacío y no lo inventa. El dato real llega por las fuentes oficiales: el BLS, los bancos centrales o los medios que lo citan, de donde se extrae la sorpresa.
- **Tipos de evento:** tipos de interés, inflación (IPC/PCE/PPI), empleo (NFP, paro), PIB, PMI, ventas minoristas, discursos y subastas de bonos.
- **Alertas configurables:** impacto, minutos de antelación y monedas.

## 7. Integración con los motores

`integracion.para_motor(motor, activo)` entrega a cada motor **solo** noticias verificadas: de fuente primaria, confirmadas por 2 o más fuentes, o de fuente de 5 estrellas o más sin rasgos de rumor. Además, solo recibe las categorías de su responsabilidad:

| Motor | Categorías |
|---|---|
| Macro | Tipos, inflación, empleo, PIB, actividad, bonos, comercio, geopolítica, más el calendario de alto impacto |
| Noticias | Todas las del activo |
| Riesgo | Tipos, geopolítica, regulación, cripto, inflación, empleo |
| Forex | Macro y monedas |
| Cripto | Cripto, regulación, tipos |
| Acciones | Resultados, regulación, tecnología, tipos, actividad |

- Ya conectados: el motor 6 (MACRO) y el motor 11 (NEWS) añaden el bloque `centro_noticias` a su salida.
- **No cambian puntuaciones ni vetos.** Las noticias son contexto y no pueden disparar una operación por sí solas.
- Cada uso queda registrado en la tabla `uso_motor` (motor, activo y noticias usadas).

## 8. Panel web: módulo 📰 Noticias

- **Pestañas:**
  - Recientes, Urgentes, Macroeconomía y Por activo (EURUSD, XAUUSD, BTCUSD, GERMANY 40…);
  - Calendario económico, con las alertas;
  - Fuentes y configuración.
- **Cada noticia muestra:**
  - insignias: fuente primaria, verificada, posible rumor, contradicción, urgente;
  - estrellas y número de fuentes que la confirman;
  - activos relacionados y sorpresa frente a la previsión;
  - las seis puntuaciones, el sentimiento y el tono;
  - el enlace a la fuente original.
- **Configuración, solo administrador:**
  - añadir una fuente RSS/Atom/JSON, que se prueba al momento;
  - probar, activar, desactivar, editar (URL, frecuencia, palabras clave) y eliminar las fuentes añadidas.
- **Estado del centro:** fuentes conectadas, degradadas, desconectadas o sin acceso gratuito; noticias e indicadores de las últimas 24 h; uso por motor; latencia media.

## 9. Límites declarados

- El análisis es por reglas: puede fallar con titulares ambiguos, irónicos o en idiomas sin léxico (el léxico es inglés, con algunos términos en español).
- El calendario no trae el dato publicado. Para tenerlo hace falta una fuente oficial gratuita, que aún está pendiente.
- Reuters, FMI, OCDE, Banco Mundial, Barron's, BEA y Yahoo no se leen por licencia, bloqueo o robots.txt.
- De los medios de pago (Bloomberg, FT, WSJ, Economist) solo se guardan los titulares públicos.
- Las estrellas son una valoración interna inicial. Conviene revisarlas con el historial de errores que se vaya registrando.
