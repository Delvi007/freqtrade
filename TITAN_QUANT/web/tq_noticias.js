/* TITAN QUANT — NEWS INTELLIGENCE: panel de noticias, calendario económico y configuración de fuentes.
   Todo el texto que viene de fuentes externas se escapa con esc(): es DATO, nunca HTML ni instrucciones. */
(function () {
  'use strict';
  const CATS = { tipos_interes: 'Tipos de interés', inflacion: 'Inflación', empleo: 'Empleo', crecimiento: 'PIB / crecimiento', actividad: 'Actividad',
    bonos: 'Bonos', comercio: 'Comercio', geopolitica: 'Geopolítica', regulacion: 'Regulación', resultados: 'Resultados', materias_primas: 'Materias primas',
    cripto: 'Cripto', tecnologia: 'Tecnología' };
  const CAT_F = { banco_central: 'Bancos centrales', estadistica: 'Estadística oficial', organismo: 'Organismos', regulador: 'Reguladores', mercado: 'Mercados',
    medio: 'Medios', analisis: 'Análisis', cripto: 'Cripto', calendario: 'Calendario' };
  const EST_C = { conectada: 'ok', degradada: 'warn', desconectada: 'err', sin_probar: '', no_disponible: '' };
  const PUNT = [['confiabilidad_fuente', 'Fuente'], ['confiabilidad_informacion', 'Información'], ['relevancia', 'Relevancia'], ['impacto_potencial', 'Impacto'],
    ['urgencia', 'Urgencia'], ['confirmacion', 'Confirmación']];
  let H, vista = 'recientes', filtroActivo = '', temporizador = null;

  function estrellas(n) { n = +n || 0; return `<span class="tqn-est" title="Calificación interna TITAN (no es una certificación oficial)">${'★'.repeat(n)}<i>${'★'.repeat(6 - n)}</i></span>`; }
  function barra(v) { v = Math.max(0, Math.min(100, +v || 0)); const c = v >= 70 ? 'a' : v >= 40 ? 'm' : 'b'; return `<span class="tqn-bar ${c}"><i style="width:${v}%"></i></span>`; }
  function hace(ts) { if (!ts) return '—'; const s = Date.now() / 1000 - ts; if (s < 3600) return Math.max(1, Math.round(s / 60)) + ' min'; if (s < 86400) return Math.round(s / 3600) + ' h'; return Math.round(s / 86400) + ' d'; }

  async function render(v, helpers) {
    H = helpers;
    const { esc, cargando } = H;
    v.innerHTML = `<div class="head"><div class="eyebrow">NEWS INTELLIGENCE ENGINE · FUENTES PRIMARIAS Y MEDIOS VERIFICADOS</div><h1>Inteligencia de noticias</h1>
      <div class="muted">Titulares, resúmenes breves y enlace a la fuente original. Las noticias son información: nunca una orden de compra o venta.</div></div>
      <div id="tqnEstado">${cargando('Estado del centro de noticias…')}</div>
      <div class="tq-tabs" id="tqnTabs">${[['recientes', 'Recientes'], ['urgentes', 'Urgentes'], ['macro', 'Macroeconomía'], ['activo', 'Por activo'],
        ['calendario', 'Calendario económico'], ['fuentes', 'Fuentes y configuración']].map(([k, t]) => `<button data-v="${k}" class="${k === vista ? 'on' : ''}">${t}</button>`).join('')}</div>
      <div id="tqnCuerpo"></div>`;
    v.querySelector('#tqnTabs').onclick = e => { const b = e.target.closest('button'); if (!b) return; vista = b.dataset.v;
      v.querySelectorAll('#tqnTabs button').forEach(x => x.classList.toggle('on', x === b)); cuerpo(); };
    estado();
    cuerpo();
    clearInterval(temporizador);
    temporizador = setInterval(() => { if (document.getElementById('tqnCuerpo') && !document.hidden) { estado(); if (vista !== 'fuentes') cuerpo(true); } }, 60000);
  }

  async function estado() {
    const { api, esc, num, fecha } = H;
    const el = document.getElementById('tqnEstado'); if (!el) return;
    try {
      const d = await api('/api/tq/noticias/estado');
      const por = Object.fromEntries((d.fuentes || []).map(x => [x.estado, x.n]));
      const n = d.noticias_24h || {};
      el.innerHTML = `<div class="tq-kpis">
        <div class="tq-kpi"><small>Fuentes conectadas</small><b>${num(por.conectada || 0, 0)}</b><small>${num(por.degradada || 0, 0)} degradadas · ${num(por.desconectada || 0, 0)} desconectadas · ${num(por.no_disponible || 0, 0)} sin acceso gratuito</small></div>
        <div class="tq-kpi"><small>Noticias 24 h</small><b>${num(n.n || 0, 0)}</b><small>${num(n.verificadas || 0, 0)} verificadas · ${num(n.rumores || 0, 0)} con rasgos de rumor</small></div>
        <div class="tq-kpi"><small>Urgentes 24 h</small><b>${num(n.urgentes || 0, 0)}</b><small>uso por motores: ${(d.uso_motores_24h || []).map(x => esc(x.motor) + ' ' + x.n).join(' · ') || '—'}</small></div>
        <div class="tq-kpi"><small>Recopilación</small><b>${d.recolector.vivo ? 'activa' : 'detenida'}</b><small>última ronda ${fecha(d.recolector.ultima_ronda_ts)} · latencia media ${num(d.latencia_media_ms, 0)} ms</small></div></div>`;
    } catch (e) { el.innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  }

  function tarjeta(n) {
    const { esc, badge } = H;
    const p = n.puntuaciones || {};
    const act = (n.activos || []).slice(0, 8).map(a => `<span class="tqn-chip">${esc(a)}</span>`).join('');
    const otras = (n.fuentes_grupo || []).filter(f => f !== n.fuente_id);
    const sent = n.sentimiento > 0.2 ? 'positivo' : n.sentimiento < -0.2 ? 'negativo' : 'neutro';
    const tono = n.tono_monetario > 0.2 ? ' · tono restrictivo' : n.tono_monetario < -0.2 ? ' · tono expansivo' : '';
    let enlace = '';
    try { const u = new URL(n.enlace); if (u.protocol === 'https:' || u.protocol === 'http:') enlace = `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer nofollow">Fuente original ↗</a>`; } catch (e) {}
    return `<div class="tqn-card ${n.urgente ? 'urg' : ''}">
      <div class="tqn-top">${n.urgente ? badge('URGENTE', 'err') : ''}${n.primaria ? badge('FUENTE PRIMARIA', 'ok') : ''}${n.verificada ? badge('verificada', 'ok') : badge('sin verificar', 'warn')}
        ${n.rumor ? badge('posible rumor', 'warn') : ''}${n.contradiccion ? badge('fuentes contradictorias', 'err') : ''}
        <span class="muted">${esc(CATS[n.categoria] || 'General')} · ${n.fecha_estimada === 2 ? 'antigüedad desconocida' : 'hace ' + hace(n.publicada_ts)}${n.fecha_estimada === 2 ? ' · fecha no publicada por la fuente' : n.fecha_estimada ? ' (hora de recepción)' : ''}</span></div>
      <div class="tqn-tit">${esc(n.titulo)}</div>
      ${n.resumen && n.resumen !== n.titulo ? `<div class="tqn-res">${esc(n.resumen)}</div>` : ''}
      <div class="tqn-meta">${estrellas(n.estrellas)} <b>${esc(n.fuente)}</b>${n.autor ? ' · ' + esc(n.autor) : ''}${otras.length ? ` · confirmada también por ${otras.length} fuente(s)` : ''} · ${enlace}</div>
      ${act ? `<div class="tqn-chips">${act}</div>` : ''}
      ${n.sorpresa ? `<div class="tqn-sorp">Dato ${esc(n.sorpresa.publicado)} % frente a previsión ${esc(n.sorpresa.prevision)} %: ${esc(n.sorpresa.lectura)} <span class="muted">(${esc(n.sorpresa.metodo)})</span></div>` : ''}
      <div class="tqn-punt">${PUNT.map(([k, t]) => `<span title="${t}: ${p[k] ?? '—'}/100"><small>${t}</small>${barra(p[k])}</span>`).join('')}
        <span><small>Sentimiento</small><em class="tqn-s ${sent}">${sent}${tono}</em></span></div></div>`;
  }

  async function cuerpo(silencioso) {
    const { api, esc, cargando } = H;
    const el = document.getElementById('tqnCuerpo'); if (!el) return;
    if (vista === 'calendario') return calendario(el, silencioso);
    if (vista === 'fuentes') return fuentes(el);
    if (!silencioso) el.innerHTML = cargando('Cargando noticias…');
    let q = 'horas=72&limite=120';
    if (vista === 'urgentes') q = 'horas=168&urgentes=1&limite=100';
    if (vista === 'macro') q = 'horas=336&macro=1&limite=120';
    if (vista === 'activo') q = 'horas=336&limite=120&activo=' + encodeURIComponent(filtroActivo || 'EURUSD');
    const filtro = vista === 'activo' ? `<div class="tq-row" style="margin-bottom:10px"><input class="field" id="tqnAct" value="${esc(filtroActivo || 'EURUSD')}" placeholder="EURUSD, XAUUSD, BTCUSD, GERMANY 40…" style="max-width:280px">
      <button class="btn primary" id="tqnActB">Buscar</button><span class="muted">Monedas, oro, petróleo, cripto, índices o empresas.</span></div>` : '';
    try {
      const d = await api('/api/tq/noticias?' + q);
      el.innerHTML = filtro + (d.noticias.length ? `<div class="muted" style="margin-bottom:8px">${d.total} acontecimientos (las noticias repetidas en varias fuentes se agrupan). ${esc(d.nota)}</div>`
        + d.noticias.map(tarjeta).join('') : '<div class="card muted">Sin noticias en esta vista todavía.</div>');
    } catch (e) { el.innerHTML = filtro + `<div class="tq-msg err">${esc(e.message)}</div>`; }
    const b = document.getElementById('tqnActB');
    if (b) b.onclick = () => { filtroActivo = document.getElementById('tqnAct').value.trim().toUpperCase(); cuerpo(); };
  }

  async function calendario(el, silencioso) {
    const { api, esc, badge, cargando } = H;
    if (!silencioso) el.innerHTML = cargando('Cargando calendario…');
    try {
      const d = await api('/api/tq/noticias/calendario?dias=7');
      const c = d.config_alertas;
      const imp = { alto: 'err', medio: 'warn', bajo: '' };
      const dia = ts => new Date(ts * 1000).toLocaleDateString('es', { weekday: 'long', day: 'numeric', month: 'short' });
      let ult = '';
      const filas = d.eventos.map(e => { const dd = dia(e.ts); const cab = dd !== ult ? `<tr class="tqn-dia"><td colspan="6">${esc(dd)}</td></tr>` : ''; ult = dd;
        const pasado = e.ts < Date.now() / 1000;
        return cab + `<tr class="${pasado ? 'tqn-pas' : ''}"><td>${new Date(e.ts * 1000).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })}</td><td><b>${esc(e.moneda)}</b></td>
          <td>${badge(e.impacto || '—', imp[e.impacto] || '')}</td><td>${esc(e.titulo)}</td><td>${esc(e.prevision || '—')}</td><td>${esc(e.anterior || '—')}</td></tr>`; }).join('');
      el.innerHTML = `${d.alertas.length ? `<div class="card tqn-alerta"><b>🔔 Próximos eventos en tu ventana de aviso</b>${d.alertas.map(a => `<div>${new Date(a.ts * 1000).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' })} · <b>${esc(a.moneda)}</b> · ${esc(a.titulo)}</div>`).join('')}</div>` : ''}
        <div class="card"><b>Alertas del calendario</b><form id="tqnAl" class="tq-row" style="margin-top:8px;flex-wrap:wrap;gap:10px">
          <label class="tq-chk"><input type="checkbox" name="activo" ${c.activo ? 'checked' : ''}> Activas</label>
          ${['alto', 'medio', 'bajo'].map(i => `<label class="tq-chk"><input type="checkbox" name="imp_${i}" ${c.impactos.includes(i) ? 'checked' : ''}> Impacto ${i}</label>`).join('')}
          <label>Avisar <input class="field" name="minutos_antes" type="number" min="1" max="1440" value="${c.minutos_antes}" style="width:80px"> min antes</label>
          <label>Monedas <input class="field" name="monedas" value="${esc((c.monedas || []).join(','))}" placeholder="todas (o USD,EUR…)" style="width:170px"></label>
          <button class="btn primary">Guardar</button><span id="tqnAlM"></span></form></div>
        <div class="card" style="margin-top:12px"><div class="muted" style="margin-bottom:8px">${esc(d.nota)}</div><div class="tq-scroll"><table class="tq-table">
          <tr><th>Hora</th><th>Moneda</th><th>Impacto</th><th>Evento</th><th>Previsión</th><th>Anterior</th></tr>${filas || '<tr><td colspan="6" class="muted">Sin eventos.</td></tr>'}</table></div></div>`;
      document.getElementById('tqnAl').onsubmit = async ev => { ev.preventDefault(); const f = ev.target;
        const cfg = { activo: f.activo.checked, impactos: ['alto', 'medio', 'bajo'].filter(i => f['imp_' + i].checked), minutos_antes: +f.minutos_antes.value,
          monedas: f.monedas.value.split(',').map(x => x.trim()).filter(Boolean) };
        try { await api('/api/tq/noticias/alertas', cfg); document.getElementById('tqnAlM').innerHTML = H.badge('guardado', 'ok'); } catch (e) { document.getElementById('tqnAlM').innerHTML = H.badge(e.message, 'err'); } };
    } catch (e) { el.innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  }

  async function fuentes(el) {
    const { api, esc, num, badge, cargando } = H;
    el.innerHTML = cargando('Cargando fuentes…');
    try {
      const d = await api('/api/tq/noticias/fuentes');
      const grupos = {};
      d.fuentes.forEach(f => (grupos[f.categoria] = grupos[f.categoria] || []).push(f));
      const adm = H.admin;
      el.innerHTML = `<div class="card muted" style="margin-bottom:12px">Calificación interna TITAN de 1 a 6 estrellas (★★★★★★ = fuente primaria institucional de máxima prioridad; ★★★★★ = alta confiabilidad).
        <b>No es una certificación oficial</b>: se calcula con 10 criterios (autoridad, transparencia, autor, calidad documental, exactitud, correcciones, velocidad, independencia, fuentes primarias y errores). La popularidad no cuenta.
        Una fuente figura como <b>conectada</b> solo tras superar la prueba de recepción (responde, entrega titulares y contenido reciente).</div>
        ${adm ? `<details class="card" style="margin-bottom:12px"><summary><b>＋ Añadir fuente (RSS / Atom / JSON de calendario)</b></summary><form id="tqnNueva" class="tq-form" style="margin-top:10px">
          <div class="tq-grid3"><div><label class="label">Nombre</label><input class="field" name="nombre" required maxlength="120"></div>
          <div><label class="label">URL del RSS</label><input class="field" name="url" type="url" required placeholder="https://…"></div>
          <div><label class="label">Categoría</label><select class="field" name="categoria">${Object.entries(CAT_F).map(([k, t]) => `<option value="${k}">${t}</option>`).join('')}</select></div>
          <div><label class="label">Frecuencia (min)</label><input class="field" name="frecuencia_min" type="number" min="5" value="15"></div>
          <div><label class="label">Idioma</label><input class="field" name="idioma" value="en" maxlength="5"></div>
          <div><label class="label">Palabras clave (opcional, separadas por comas)</label><input class="field" name="palabras_clave"></div></div>
          <label class="tq-chk"><input type="checkbox" name="primaria"> Fuente primaria institucional (banco central, estadística oficial, regulador)</label>
          <div class="muted">Solo URL públicas http(s). Se respeta robots.txt y la frecuencia mínima es de 5 minutos. Las estrellas se ajustan después con los 10 criterios.</div>
          <button class="btn primary">Añadir y probar</button><div id="tqnNM"></div></form></details>` : ''}
        ${Object.entries(grupos).map(([cat, fs]) => `<div class="card" style="margin-bottom:12px"><b>${esc(CAT_F[cat] || cat)}</b><div class="tq-scroll"><table class="tq-table">
          <tr><th>Fuente</th><th>Calificación</th><th>Acceso</th><th>Estado</th><th>Última recepción</th><th>Noticias 24 h</th><th>Frecuencia</th>${adm ? '<th></th>' : ''}</tr>
          ${fs.map(f => `<tr><td><b>${esc(f.nombre)}</b>${f.primaria ? ' ' + badge('primaria', 'ok') : ''}<div class="muted" style="font-size:11px;word-break:break-all">${esc(f.url)}</div>${f.nota ? `<div class="muted" style="font-size:11px">${esc(f.nota)}</div>` : ''}</td>
            <td>${estrellas(f.estrellas)}</td><td>${esc(f.acceso_texto)}</td>
            <td>${badge(f.estado.replace('_', ' '), EST_C[f.estado] || '')}${f.activo ? '' : ' ' + badge('desactivada', '')}${f.ultimo_error ? `<div class="muted" style="font-size:11px">${esc(f.ultimo_error)}</div>` : ''}</td>
            <td>${f.ultima_ok_ts ? 'hace ' + hace(f.ultima_ok_ts) : '—'}<div class="muted" style="font-size:11px">${f.ultima_latencia_ms != null ? num(f.ultima_latencia_ms, 0) + ' ms' : ''}${f.items_ultima != null ? ' · ' + f.items_ultima + ' elementos' : ''}</div></td>
            <td>${num(f.noticias_24h, 0)}</td><td>${f.frecuencia_min} min</td>
            ${adm ? `<td style="white-space:nowrap">${f.acceso === 'sin_rss_publico' || f.acceso === 'bloqueado' ? '' : `<button class="btn" data-a="probar" data-id="${esc(f.id)}">Probar</button>
              <button class="btn" data-a="${f.activo ? 'desactivar' : 'activar'}" data-id="${esc(f.id)}">${f.activo ? 'Desactivar' : 'Activar'}</button>
              <button class="btn" data-a="editar" data-id="${esc(f.id)}">Editar</button>`}${f.personalizada ? ` <button class="btn" data-a="eliminar" data-id="${esc(f.id)}">Eliminar</button>` : ''}</td>` : ''}</tr>`).join('')}
          </table></div></div>`).join('')}`;
      const nueva = document.getElementById('tqnNueva');
      if (nueva) nueva.onsubmit = async ev => { ev.preventDefault(); const f = ev.target; const m = document.getElementById('tqnNM'); m.innerHTML = cargando('Probando la fuente…');
        try { const r = await api('/api/tq/noticias/fuente', { accion: 'crear', nombre: f.nombre.value, url: f.url.value, categoria: f.categoria.value, frecuencia_min: +f.frecuencia_min.value,
            idioma: f.idioma.value, palabras_clave: f.palabras_clave.value, primaria: f.primaria.checked });
          m.innerHTML = r.prueba.ok ? badge('conectada: ' + r.prueba.detalle, 'ok') : badge('añadida, pero la prueba falló: ' + r.prueba.detalle, 'warn'); setTimeout(() => fuentes(el), 2500);
        } catch (e) { m.innerHTML = badge(e.message, 'err'); } };
      el.querySelectorAll('button[data-a]').forEach(b => b.onclick = async () => {
        const id = b.dataset.id, a = b.dataset.a;
        const f = d.fuentes.find(x => x.id === id);
        let datos = { accion: a, id };
        if (a === 'eliminar' && !confirm('¿Eliminar la fuente «' + f.nombre + '»? Las noticias ya guardadas se conservan.')) return;
        if (a === 'editar') {
          const url = prompt('URL del RSS', f.url); if (url === null) return;
          const freq = prompt('Frecuencia de actualización (minutos, mínimo 5)', f.frecuencia_min); if (freq === null) return;
          const pal = prompt('Palabras clave (opcional, separadas por comas)', f.palabras_clave || ''); if (pal === null) return;
          datos = { accion: 'editar', id, frecuencia_min: +freq, palabras_clave: pal };
          if (url.trim() !== f.url) datos.url = url.trim();
        }
        b.disabled = true; b.textContent = '…';
        try { const r = await api('/api/tq/noticias/fuente', datos); if (r.prueba) alert((r.prueba.ok ? 'Conectada: ' : 'La prueba falló: ') + r.prueba.detalle); } catch (e) { alert(e.message); }
        fuentes(el);
      });
    } catch (e) { el.innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  }

  window.TQNoticias = { render };
})();
