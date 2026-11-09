/* TITAN QUANT — portada pública (pantalla de acceso). Ilustraciones SVG propias, sin recursos externos.
   Expone window.TQPortada(der) → HTML de la página con el formulario `der` integrado en la portada. */
(function () {
  const svgGlobo = `<svg class="tqp-globo" viewBox="0 0 420 420" aria-hidden="true">
    <defs><radialGradient id="tqpG" cx="38%" cy="32%" r="70%"><stop offset="0" stop-color="#1b8270"/><stop offset=".35" stop-color="#0b473e"/><stop offset=".75" stop-color="#05231f"/><stop offset="1" stop-color="#020c0b"/></radialGradient>
      <linearGradient id="tqpL" x1="0" x2="1"><stop offset="0" stop-color="#00f0a0" stop-opacity="0"/><stop offset=".5" stop-color="#00f0a0"/><stop offset="1" stop-color="#00f0a0" stop-opacity="0"/></linearGradient></defs>
    <ellipse class="tqp-orbita" cx="210" cy="210" rx="200" ry="70" transform="rotate(-18 210 210)"/>
    <ellipse class="tqp-orbita r" cx="210" cy="210" rx="190" ry="80" transform="rotate(42 210 210)"/>
    <circle cx="210" cy="210" r="122" fill="url(#tqpG)"/>
    <g class="tqp-red" clip-path="circle(122px at 210px 210px)">
      ${[...Array(9)].map((_, i) => `<ellipse cx="210" cy="210" rx="${122 - i * 14}" ry="122" fill="none"/>`).join('')}
      ${[...Array(9)].map((_, i) => `<line x1="80" x2="340" y1="${100 + i * 27}" y2="${100 + i * 27}"/>`).join('')}
    </g>
    <circle cx="210" cy="210" r="122" fill="none" stroke="#22f2cb" stroke-opacity=".45"/>
    ${[[150, 150], [265, 175], [190, 265], [300, 250], [240, 120], [120, 230]].map(([x, y], i) => `<circle class="tqp-nodo" style="animation-delay:${i * .4}s" cx="${x}" cy="${y}" r="4"/>`).join('')}
    <path class="tqp-arco" d="M150 150 Q210 80 265 175 T300 250"/><path class="tqp-arco r" d="M120 230 Q170 300 190 265 T300 250"/>
    <circle class="tqp-sat" r="5"><animateMotion dur="9s" repeatCount="indefinite" path="M10 210 a200 70 0 1 0 400 0 a200 70 0 1 0 -400 0"/></circle>
  </svg>`;

  const svgVelas = `<svg viewBox="0 0 320 150" class="tqp-ilus" aria-hidden="true"><g stroke="#163c32">${[25, 60, 95, 130].map(y => `<line x1="0" x2="320" y1="${y}" y2="${y}"/>`).join('')}</g>
    ${[[20, 95, 115, 80, 120, 1], [45, 85, 100, 70, 108, 1], [70, 90, 80, 72, 96, 0], [95, 78, 60, 52, 84, 1], [120, 62, 70, 48, 78, 0], [145, 68, 50, 42, 74, 1],
       [170, 52, 58, 40, 64, 0], [195, 56, 38, 30, 62, 1], [220, 40, 46, 30, 52, 0], [245, 44, 28, 20, 50, 1], [270, 30, 34, 18, 40, 0], [295, 32, 16, 10, 38, 1]]
      .map(([x, o, c, h, l, up]) => `<line x1="${x}" x2="${x}" y1="${h}" y2="${l}" stroke="${up ? '#00f0a0' : '#ff405d'}"/><rect x="${x - 6}" y="${Math.min(o, c)}" width="12" height="${Math.max(2, Math.abs(o - c))}" fill="${up ? '#00f0a0' : '#ff405d'}" rx="1"/>`).join('')}
    <path d="M10 118 C80 96 120 82 170 62 S260 34 310 18" fill="none" stroke="#18d9d2" stroke-width="1.6" stroke-dasharray="4 4"/>
    <g font-size="9" fill="#9fe3c4"><rect x="226" y="96" width="86" height="40" rx="6" fill="#04120f" stroke="#00f0a055"/><text x="234" y="112">STOP · OBJETIVO</text><text x="234" y="127" fill="#e9c66b">ATR × 1,5 · × 2</text></g></svg>`;

  const svgBinaria = `<svg viewBox="0 0 320 150" class="tqp-ilus" aria-hidden="true"><g stroke="#163c32">${[25, 60, 95, 130].map(y => `<line x1="0" x2="320" y1="${y}" y2="${y}"/>`).join('')}</g>
    <path d="M0 100 L25 92 45 98 70 80 95 86 120 70 145 76 165 64" fill="none" stroke="#00f0a0" stroke-width="2"/>
    <line x1="165" x2="165" y1="10" y2="140" stroke="#e9c66b" stroke-dasharray="3 3"/><text x="170" y="20" font-size="9" fill="#e9c66b">ENTRADA</text>
    <path d="M165 64 L190 58 215 50 240 54 265 44" fill="none" stroke="#00f0a0" stroke-width="2" stroke-dasharray="5 4"/>
    <line x1="265" x2="265" y1="10" y2="140" stroke="#18d9d2" stroke-dasharray="3 3"/><text x="232" y="138" font-size="9" fill="#18d9d2">VENCE 5 MIN</text>
    <g><rect x="40" y="16" width="64" height="24" rx="6" fill="#003d2a" stroke="#00f0a0"/><text x="52" y="32" font-size="11" fill="#7dffc8" font-weight="700">▲ CALL</text></g>
    <g><rect x="40" y="112" width="64" height="24" rx="6" fill="#3a0b14" stroke="#ff405d"/><text x="56" y="128" font-size="11" fill="#ff9b9b" font-weight="700">▼ PUT</text></g>
    <text x="276" y="48" font-size="10" fill="#7dffc8">+83 %</text></svg>`;

  const ico = {
    analisis: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />',
    bot: '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6"/>',
    backtest: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    escudo: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/>',
    capas: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  };
  const icono = k => `<svg class="tqp-ico" viewBox="0 0 24 24" aria-hidden="true">${ico[k]}</svg>`;

  const MOTORES = ['Datos', 'Características', 'Técnico', 'Intermarket', 'Macro', 'Estadístico', 'Machine Learning', 'Régimen', 'Microestructura', 'Noticias',
    'Riesgo', 'Backtesting', 'Monte Carlo', 'Portafolio', 'Investigación', 'Fusión', 'Adaptativo', 'Hardware', 'Monitoreo', 'API', 'Web', 'Telegram', 'Núcleo'];

  window.TQPortada = function (der) {
    return `<div class="tqp">
  <header class="tqp-top"><div class="tqp-marca"><div class="tqp-mark"><span>T</span></div><div><b>TITAN <em>QUANT</em></b><small>INTELIGENCIA FINANCIERA GLOBAL</small></div></div>
    <nav><a href="#tqp-que">Qué es</a><a href="#tqp-bots">Bots</a><a href="#tqp-motores">Motores</a><a href="#tqp-como">Cómo trabaja</a><a href="#tqp-seguridad">Seguridad</a></nav>
    <div class="tqp-cta"><button class="tqp-btn s" data-p="login">Iniciar sesión</button><button class="tqp-btn" data-p="registro">Crear cuenta</button></div></header>

  <section class="tqp-hero"><div class="tqp-hero-txt">
      <div class="tqp-eyebrow"><i></i>PLATAFORMA CUANTITATIVA MULTIMERCADO</div>
      <h1>Inteligencia cuantitativa que busca ventajas con <span>evidencia</span>, no con corazonadas.</h1>
      <p>Dos bots recorren todos los activos de tu broker, prueban cada estrategia con sus datos históricos reales,
         <b>confirman cada señal con los 23 motores</b> de análisis y operan directamente en tus cuentas de <b>cTrader</b> e
         <b>IQ Option</b>, con controles de riesgo en cada orden. Primero exploran en práctica; después solo operan lo que tiene
         <b>ventaja estadística demostrada</b>.</p>
      <div class="tqp-kpis"><div><b>23</b><small>motores de análisis</small></div><div><b>2</b><small>brokers conectados</small></div>
        <div><b>5</b><small>estrategias configurables</small></div><div><b>100 %</b><small>resultados del broker</small></div></div>
      <div class="tqp-hero-vis">${svgGlobo}<div class="tqp-core"><b>TITAN <em>QUANT</em></b><small>NÚCLEO DE INTELIGENCIA</small></div></div>
    </div>
    <div class="tqp-hero-form">${der}</div></section>

  <section class="tqp-sec" id="tqp-que"><div class="tqp-h"><small>PARA QUÉ ESTÁ DISEÑADO</small><h2>De la idea a la orden, con cada paso verificable</h2></div>
    <div class="tqp-grid4">
      <div class="tqp-card">${icono('analisis')}<b>Analizar el mercado</b><p>23 motores combinan datos, indicadores técnicos, contexto macro, noticias, estadística y machine learning en un escenario con probabilidad, stop y objetivos.</p></div>
      <div class="tqp-card">${icono('backtest')}<b>Probar antes de arriesgar</b><p>Backtesting con datos del propio broker, fuera de muestra y walk-forward. Detecta la sobreoptimización y descarta lo que no tiene ventaja.</p></div>
      <div class="tqp-card">${icono('bot')}<b>Operar de forma automática</b><p>Bots que buscan oportunidades en todos los activos disponibles con estrategias que antes pasan el backtesting, y envían las órdenes directamente al broker, en DEMO o en REAL.</p></div>
      <div class="tqp-card">${icono('escudo')}<b>Controlar el riesgo</b><p>Riesgo por operación, pérdida diaria y semanal, exposición, rachas, spread, datos frescos, duplicados y parada de emergencia.</p></div>
    </div></section>

  <section class="tqp-sec" id="tqp-bots"><div class="tqp-h"><small>DOS BOTS, DOS BROKERS</small><h2>Cada bot opera directamente en su broker</h2></div>
    <div class="tqp-grid2">
      <div class="tqp-card tqp-bot">${svgVelas}<div class="tqp-tag">cTrader · Open API oficial</div><b>Bot cTrader</b>
        <p>Forex, metales, índices, energía y CFD. Analiza todos los símbolos de tu cuenta con sus nombres reales de cTrader, prueba cada estrategia y opera con stop y objetivo calculados por ATR.</p>
        <ul><li>Cuenta DEMO y cuenta REAL con interruptor <b>MODO LIVE</b></li><li>Precios, spread y resultados leídos del broker</li><li>Volumen ajustado al riesgo y al mínimo del símbolo</li></ul></div>
      <div class="tqp-card tqp-bot">${svgBinaria}<div class="tqp-tag">IQ Option · opciones binarias</div><b>Bot IQ Option</b>
        <p>Opciones binarias con vencimiento de 5 minutos. Recorre todos los pares abiertos, usa el payout real de cada uno y solo opera cuando el acierto histórico supera el punto de equilibrio.</p>
        <ul><li>Cuenta PRACTICE y cuenta REAL con interruptor <b>MODO LIVE</b></li><li>Estado abierto/suspendido y payouts en tiempo real</li><li>Resultado de cada opción leído del historial del broker</li></ul></div>
    </div></section>

  <section class="tqp-sec" id="tqp-motores"><div class="tqp-h"><small>23 MOTORES ESPECIALIZADOS</small><h2>El análisis de mercado: un equipo cuantitativo en paralelo</h2></div>
    <div class="tqp-motores">${MOTORES.map((m, i) => `<span style="animation-delay:${(i % 8) * .25}s"><i></i>${m}</span>`).join('')}</div>
    <p class="tqp-nota">Cuatro niveles de profundidad (básico, intermedio, avanzado y súper avanzado), adaptados a la potencia de tu equipo.
       Los bots buscan la señal con <b>5 estrategias básicas validadas con backtesting</b> y, antes de enviarla, los <b>23 motores
       la confirman o la vetan</b>: si apuntan en contra, si el régimen es de alta volatilidad o tras un evento macro de alto impacto.
       Cada motor indica sus límites: por ejemplo, si el modelo de machine learning no mejora a la tasa base, no se usa para decidir.</p></section>

  <section class="tqp-sec" id="tqp-como"><div class="tqp-h"><small>CÓMO TRABAJA</small><h2>Cinco pasos en cada ciclo del bot</h2></div>
    <div class="tqp-pasos">${[['radar', 'Escanea', 'Todos los activos disponibles en el broker, con sus datos reales.'],
      ['backtest', 'Prueba', 'Cada estrategia con backtesting fuera de muestra; el ranking se recalcula y se adapta al mercado.'],
      ['analisis', 'Detecta y confirma', 'La señal en la última vela cerrada; los 23 motores la confirman o la vetan.'],
      ['escudo', 'Controla', 'Todos los límites de riesgo y los resultados reales del broker; si uno falla, la oportunidad se descarta.'],
      ['bot', 'Ejecuta', 'La orden en el broker y registra cada fase con el identificador del broker.']]
      .map(([k, t, d], i) => `<div class="tqp-paso"><div class="tqp-num">${i + 1}</div>${icono(k)}<b>${t}</b><p>${d}</p></div>`).join('')}</div></section>

  <section class="tqp-sec" id="tqp-seguridad"><div class="tqp-h"><small>SEGURIDAD E INTEGRIDAD</small><h2>Nada se inventa: todo es verificable</h2></div>
    <div class="tqp-grid3">
      <div class="tqp-card">${icono('capas')}<b>Cuentas separadas</b><p>DEMO, PRACTICE y REAL tienen cada una su propia base de datos. Los mercados y sus resultados nunca se mezclan.</p></div>
      <div class="tqp-card">${icono('escudo')}<b>Credenciales cifradas</b><p>Las claves de los brokers se guardan cifradas. Sesiones protegidas, límites de intentos y registro de seguridad.</p></div>
      <div class="tqp-card">${icono('analisis')}<b>Traza de cada orden</b><p>Oportunidad, envío, aceptación, apertura, cierre y resultado, con la evidencia del broker. Sin confirmación, queda pendiente.</p></div>
    </div></section>

  <section class="tqp-final"><h2>Empieza en la cuenta de práctica.</h2><p>Los bots exploran en DEMO y PRACTICE hasta reunir una muestra de operaciones reales
    y después pasan solos al modo evidencia. Activa el MODO LIVE solo cuando tú lo decidas. Ninguna estrategia garantiza ganancias.</p>
    <div class="tqp-cta"><button class="tqp-btn" data-p="registro">Crear cuenta</button><button class="tqp-btn s" data-p="login">Ya tengo cuenta</button></div></section>

  <footer class="tqp-pie"><div>TITAN QUANT · INTELIGENCIA FINANCIERA GLOBAL · ANALIZAR · PROBAR · OPERAR · APRENDER</div>
    <small>TITAN es una herramienta de análisis y ejecución, no un asesor financiero. Operar en mercados financieros y opciones binarias conlleva riesgo de pérdida;
    los resultados históricos no garantizan resultados futuros. Las opciones binarias están prohibidas a inversores minoristas en varios países.</small></footer>
</div>`;
  };
})();
