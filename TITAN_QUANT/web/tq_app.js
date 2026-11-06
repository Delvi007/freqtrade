/* TITAN QUANT v7 — plataforma: acceso, análisis con 23 motores, inteligencia, integraciones, bot operador,
   alertas con sonido, historial con ocultar/archivar, motores, hardware, diagnóstico y cuenta.
   Se monta sobre la interfaz existente sin cambiar su diseño. Todo texto del servidor se escapa con esc(). */
(function () {
  'use strict';
  const TQ = window.TQ;
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (x, d = 2) => (x == null || !isFinite(x)) ? '—' : Number(x).toLocaleString('es', { maximumFractionDigits: d, minimumFractionDigits: 0 });
  const pct = (x, d = 1) => x == null ? '—' : num(x * 100, d) + ' %';
  const fecha = ts => ts ? new Date(ts * 1000).toLocaleString('es', { dateStyle: 'short', timeStyle: 'short' }) : '—';
  const ls = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
               set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };

  async function api(ruta, datos) {
    const op = datos === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(datos) };
    const r = await fetch(ruta, op);
    let d = {};
    try { d = await r.json(); } catch (e) { d = { ok: false, error: 'Respuesta no válida del servidor' }; }
    if (!r.ok || d.ok === false) { const e = new Error(d.error || ('HTTP ' + r.status)); e.status = r.status; e.datos = d; throw e; }
    return d;
  }
  const msg = (el, texto, tipo) => { if (el) el.innerHTML = texto ? `<div class="tq-msg ${tipo || ''}">${esc(texto)}</div>` : ''; };
  const cargando = t => `<div class="muted"><span class="tq-spin"></span>${esc(t || 'Cargando…')}</div>`;
  const badge = (t, c) => `<span class="tq-b ${c || ''}">${esc(t)}</span>`;
  const ESTADO_C = { completado: 'ok', conectada: 'ok', simplificado: 'warn', configurada: 'warn', pendiente_autorizacion: 'warn',
    sin_datos: 'warn', aplazado: 'warn', error: 'err', deshabilitada: '', no_configurada: '', desconectada: 'err', sin_ejecutar: '' };

  // =========================================================================== ACCESO
  const gate = document.createElement('div');
  gate.className = 'tq-gate';
  gate.id = 'tqGate';
  document.body.appendChild(gate);
  const CAPS = [['23 motores', 'Datos, técnico, intermarket, macro, estadística, ML, régimen, riesgo, backtest, Monte Carlo, fusión…'],
    ['4 niveles', 'Básico, intermedio, avanzado y súper avanzado, adaptados a tu hardware.'],
    ['Bot operador', 'Simulación con precios reales y controles de riesgo independientes.'],
    ['Seguridad', 'Credenciales cifradas, sesiones protegidas y registro de seguridad.']];

  function pantalla(nombre, extra) {
    gate.hidden = false;
    const izq = `<div><div class="tq-logo">TITAN QUANT<small>INTELIGENCIA CUANTITATIVA MULTIMERCADO</small></div>
      <div class="tq-claim">Investiga, analiza y simula con 23 motores especializados. Sin promesas: con evidencia y sus límites.</div>
      <div class="tq-caps">${CAPS.map(c => `<div class="tq-cap"><b>${c[0]}</b>${c[1]}</div>`).join('')}</div>
      <div class="muted">Herramienta de análisis. No es asesoramiento financiero. Operar conlleva riesgo de pérdida.</div></div>`;
    let der = '';
    const ini = TQ.estadoAcceso || {};
    const primera = ini.hay_usuarios === false;
    if (nombre === 'bienvenida') {
      der = primera
        ? `<div class="card"><b>Configuración inicial</b><p class="muted">Todavía no hay ninguna cuenta. La primera que crees será la del <b>administrador</b> (acceso total).
           ${ini.local ? 'Como la creas desde este mismo dispositivo, quedará activada al instante, sin necesidad de correo.' : 'Desde otro dispositivo hará falta confirmar el correo.'}</p>
        <div class="tq-row"><button class="btn primary" data-p="registro">CREAR CUENTA DE ADMINISTRADOR</button><button class="btn" data-p="login">INICIAR SESIÓN</button></div>`
        : `<div class="card"><b>Bienvenido</b><p class="muted">Crea tu cuenta o inicia sesión para entrar al panel.${ini.requiere_aprobacion ? ' Las cuentas nuevas las aprueba el administrador.' : ''}</p>
        <div class="tq-row"><button class="btn primary" data-p="registro">CREAR CUENTA</button><button class="btn" data-p="login">INICIAR SESIÓN</button></div>`;
      der += `
        <p style="margin-top:14px"><button class="tq-link" data-p="olvide">¿Olvidaste tu contraseña?</button></p><div id="tqGm">${extra || ''}</div></div>`;
    } else if (nombre === 'registro') {
      der = `<form class="card tq-form" id="tqFReg" autocomplete="on"><b>${primera ? 'Crear cuenta de administrador' : 'Solicitar cuenta'}</b>
        <div class="formrow"><label class="label">Nombre</label><input class="field" name="nombre" required maxlength="80" autocomplete="name"></div>
        <div class="formrow"><label class="label">Correo electrónico</label><input class="field" name="correo" type="email" required autocomplete="email"></div>
        <div class="formrow"><label class="label">Contraseña (mín. 10, tres tipos de carácter)</label><input class="field" name="clave" type="password" required minlength="10" autocomplete="new-password"></div>
        <div class="formrow"><label class="label">Confirmar contraseña</label><input class="field" name="clave2" type="password" required autocomplete="new-password"></div>
        <div class="tq-hp" aria-hidden="true"><input name="web" tabindex="-1" autocomplete="off"></div>
        <label class="tq-chk"><input type="checkbox" name="acepta" required> Acepto los términos de uso y la política de privacidad</label>
        <div class="tq-row"><button class="btn primary">Crear cuenta</button><button type="button" class="tq-link" data-p="login">Ya tengo cuenta</button></div><div id="tqGm"></div></form>`;
    } else if (nombre === 'login') {
      der = `<form class="card tq-form" id="tqFLog"><b>Iniciar sesión</b>
        <div class="formrow"><label class="label">Correo electrónico</label><input class="field" name="correo" type="email" required autocomplete="email"></div>
        <div class="formrow"><label class="label">Contraseña</label><input class="field" name="clave" type="password" required autocomplete="current-password"></div>
        <label class="tq-chk"><input type="checkbox" name="recordar"> Mantener la sesión 14 días en este dispositivo</label>
        <div class="tq-row"><button class="btn primary">Entrar</button><button type="button" class="tq-link" data-p="olvide">¿Olvidaste tu contraseña?</button>
        <button type="button" class="tq-link" data-p="registro">Crear cuenta</button></div>
        <p style="margin-top:10px"><button type="button" class="tq-link" id="tqReenv">Reenviar el correo de verificación</button></p><div id="tqGm">${extra || ''}</div></form>`;
    } else if (nombre === 'olvide') {
      der = `<form class="card tq-form" id="tqFOlv"><b>Recuperar contraseña</b><p class="muted">Te enviaremos un enlace temporal de un solo uso.</p>
        <div class="formrow"><label class="label">Correo electrónico</label><input class="field" name="correo" type="email" required autocomplete="email"></div>
        <div class="tq-row"><button class="btn primary">Enviar enlace</button><button type="button" class="tq-link" data-p="login">Volver</button></div><div id="tqGm"></div></form>`;
    } else if (nombre === 'restablecer') {
      der = `<form class="card tq-form" id="tqFRes"><b>Nueva contraseña</b>
        <div class="formrow"><label class="label">Nueva contraseña</label><input class="field" name="clave" type="password" required minlength="10" autocomplete="new-password"></div>
        <div class="formrow"><label class="label">Confirmar</label><input class="field" name="clave2" type="password" required autocomplete="new-password"></div>
        <button class="btn primary">Guardar contraseña</button><div id="tqGm"></div></form>`;
    }
    gate.innerHTML = `<div class="tq-panel"><div class="tq-hero">${izq}${der}</div></div>`;
    gate.querySelectorAll('[data-p]').forEach(b => b.onclick = ev => { ev.preventDefault(); pantalla(b.dataset.p); });
    const t0 = Date.now();
    const f = gate.querySelector('form');
    const datosF = form => { const o = {}; new FormData(form).forEach((v, k) => o[k] = v); form.querySelectorAll('input[type=checkbox]').forEach(c => o[c.name] = c.checked); return o; };
    const enviar = async (ruta, extraD, ok) => {
      const m = $('tqGm');
      const boton = f.querySelector('button.primary');
      boton.disabled = true;
      try { const d = await api(ruta, Object.assign(datosF(f), extraD || {})); ok(d, m); }
      catch (e) { msg(m, e.message, 'err'); }
      finally { boton.disabled = false; }
    };
    if (nombre === 'registro') f.onsubmit = ev => { ev.preventDefault(); enviar('/api/auth/registro', { t: t0 }, (d, m) => {
      if (d.activado) { TQ.estadoAcceso = Object.assign({}, ini, { hay_usuarios: true }); return pantalla('login', `<div class="tq-msg ok">${esc(d.mensaje)}</div>`); }
      f.reset(); msg(m, d.mensaje, 'ok'); }); };
    if (nombre === 'login') {
      f.onsubmit = ev => { ev.preventDefault(); enviar('/api/auth/login', {}, () => { location.hash = ''; location.reload(); }); };
      $('tqReenv').onclick = async () => { const c = f.correo.value; if (!c) return msg($('tqGm'), 'Escribe tu correo arriba.', 'err');
        try { const d = await api('/api/auth/reenviar', { correo: c }); msg($('tqGm'), d.mensaje, 'ok'); } catch (e) { msg($('tqGm'), e.message, 'err'); } };
    }
    if (nombre === 'olvide') f.onsubmit = ev => { ev.preventDefault(); enviar('/api/auth/olvide', {}, (d, m) => msg(m, d.mensaje, 'ok')); };
    if (nombre === 'restablecer') f.onsubmit = ev => { ev.preventDefault();
      enviar('/api/auth/restablecer', { token: extra }, (d) => { history.replaceState(null, '', location.pathname); pantalla('login', `<div class="tq-msg ok">${esc(d.mensaje)}</div>`); }); };
    const foco = gate.querySelector('input:not([tabindex])');
    if (foco) foco.focus();
  }

  async function iniciarAcceso() {
    const h = location.hash;
    const ses = await TQ.cargarSesion();
    try { TQ.estadoAcceso = await api('/api/auth/estado'); } catch (e) { TQ.estadoAcceso = {}; }
    if (h.startsWith('#restablecer=')) return pantalla('restablecer', decodeURIComponent(h.slice(13)));
    if (ses && ses.ok) { gate.hidden = true; return montar(); }
    if (h === '#verificado') return pantalla('login', '<div class="tq-msg ok">Correo verificado. Ya puedes iniciar sesión.</div>');
    if (h === '#verificacion-fallida') return pantalla('login', '<div class="tq-msg err">El enlace de verificación no es válido o caducó. Pide uno nuevo.</div>');
    pantalla('bienvenida');
  }
  TQ.alCaducar = () => { TQ.usuario = null; pantalla('login', '<div class="tq-msg err">Tu sesión terminó. Vuelve a iniciar sesión.</div>'); };

  // =========================================================================== MONTAJE EN LA INTERFAZ EXISTENTE
  const NUEVAS = [['motores', '⚙ Motores (23)'], ['inteligencia', '◇ Inteligencia'], ['hardware', '▤ Hardware'], ['diagnostico', '✚ Diagnóstico'], ['admin', '★ Administración']];
  const RENOMBRAR = { brokers: '▣ Configuración e integraciones', settings: '⚙ Preferencias', analysis: '◈ Analizar mercado' };
  const TITULOS = { admin: 'Administración', motores: 'Motores', inteligencia: 'Inteligencia', hardware: 'Hardware', diagnostico: 'Diagnóstico', brokers: 'Configuración e integraciones', settings: 'Preferencias', analysis: 'Analizar mercado' };
  const RENDER = {};

  function montar() {
    const nav = document.querySelector('.nav');
    Object.entries(RENOMBRAR).forEach(([v, t]) => { const b = nav && nav.querySelector(`[data-view="${v}"]`); if (b) b.textContent = t; });
    const ref = nav && nav.querySelector('[data-view="brokers"]');
    const contenido = document.querySelector('.content');
    const pie = contenido && contenido.querySelector('.footer');
    NUEVAS.filter(([id]) => id !== 'admin' || TQ.usuario.admin).filter(([id]) => id !== 'diagnostico' || TQ.usuario.admin).forEach(([id, t]) => {
      if (!$('view-' + id)) {
        const s = document.createElement('section');
        s.className = 'view'; s.id = 'view-' + id;
        contenido.insertBefore(s, pie);
      }
      if (nav && !nav.querySelector(`[data-view="${id}"]`)) {
        const b = document.createElement('button'); b.dataset.view = id; b.textContent = t;
        b.onclick = () => window.go(id);
        nav.insertBefore(b, ref);
      }
      const mn = $('mobileNav');
      if (mn && !mn.querySelector(`option[value="${id}"]`)) { const o = document.createElement('option'); o.value = id; o.textContent = t.replace(/^\S+\s/, ''); mn.appendChild(o); }
    });
    try { Object.assign(labels, TITULOS); } catch (e) {}
    if (pie) pie.textContent = 'TITAN QUANT v7.2 · Análisis informativo · Simulación, DEMO y REAL en cuentas y bases separadas';
    const hint = document.querySelector('.side .hint');
    if (hint) { hint.id = 'tqModoSide'; hint.innerHTML = '<span class="muted">Bot operador…</span>'; }
    const top = document.querySelector('header.top');
    const pill = top && top.querySelector('.pill');
    if (pill) {
      pill.outerHTML = `<div class="tq-user"><button class="tq-bell" id="tqBell" title="Alertas">🔔<i id="tqBellN" hidden></i></button>
        <span id="tqModoTop" class="tq-b sim">SIMULACIÓN</span><span id="tqUser">${esc(TQ.usuario.nombre)}</span>
        <button class="btn" id="tqSalir" style="padding:5px 9px">Salir</button></div>`;
      $('tqBell').onclick = () => window.go('alerts');
      $('tqSalir').onclick = async () => { try { await api('/api/auth/logout', {}); } catch (e) {} location.reload(); };
    }
    const dashBtn = document.querySelector('#view-dashboard .head .btn.primary');
    if (dashBtn) dashBtn.textContent = '◈ ANALIZAR MERCADO';
    // enganchar navegación para renderizar al entrar
    const goOrig = window.go;
    window.go = function (n) { goOrig(n); if (RENDER[n]) RENDER[n](); };
    modoBot();
    sondearAlertas();
    setInterval(sondearAlertas, 20000);
    setInterval(modoBot, 60000);
    if (location.hash === '#integraciones-ok' || location.hash === '#integraciones-error') { window.go('brokers'); }
    if (location.hash === '#admin' && TQ.usuario.admin) { history.replaceState(null, '', location.pathname); window.go('admin'); }
  }

  const NOMBRE_MOD = { simulacion: 'SIMULACIÓN', demo: 'DEMO', real: 'REAL LIVE' };
  async function modoBot() {
    try {
      const d = await api('/api/tq/operador');
      const activos = ['real', 'demo', 'simulacion'].filter(m => d.bots[m].estado === 'activo' || d.bots[m].estado === 'emergencia');
      const m = activos[0] || 'simulacion';
      const top = $('tqModoTop');
      if (top) { top.textContent = activos.length ? activos.map(x => NOMBRE_MOD[x]).join(' + ') + ' · ACTIVO' : 'BOTS DETENIDOS'; top.className = 'tq-b ' + (m === 'simulacion' ? 'sim' : m); }
      const side = $('tqModoSide');
      if (side) side.innerHTML = ['simulacion', 'demo', 'real'].map(x => `<div class="tq-mode ${x}" style="margin-bottom:4px;opacity:${d.bots[x].estado === 'activo' ? 1 : .55}">${NOMBRE_MOD[x]} · ${esc(d.bots[x].estado)}</div>`).join('');
    } catch (e) {}
  }

  // =========================================================================== ALERTAS + SONIDOS
  let audio = null;
  const sonados = new Set(ls.get('tq_sonados', []));
  function pref() { return (TQ.preferencias && TQ.preferencias.sonidos) || { activado: false, volumen: 0.6 }; }
  function tono(patron) {
    const p = pref();
    if (!p.activado || !audio || audio.state !== 'running') return;
    let t = audio.currentTime;
    patron.forEach(([f, d]) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = f; o.type = 'sine';
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(Math.max(0.001, p.volumen * 0.4), t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + d);
      o.connect(g).connect(audio.destination); o.start(t); o.stop(t + d + 0.02); t += d + 0.05;
    });
  }
  const PATRONES = { oportunidad: [[660, .15], [880, .2]], entrada: [[523, .12], [659, .12], [784, .2]], operacion: [[440, .25]], critica: [[880, .18], [440, .18], [880, .18], [440, .3]] };
  function sonarAlerta(a) {
    if (sonados.has(a.id)) return;                       // nunca dos veces por la misma alerta
    sonados.add(a.id); ls.set('tq_sonados', Array.from(sonados).slice(-300));
    const p = pref();
    if (a.silenciada) return;
    if (a.importancia === 'critica' && p.critica) return tono(PATRONES.critica);
    if (a.categoria === 'oportunidad' && p.oportunidad) return tono(PATRONES.oportunidad);
    if (a.categoria === 'entrada' && p.entrada) return tono(PATRONES.entrada);
    if (a.categoria === 'operacion' && p.operacion) return tono(PATRONES.operacion);
  }
  function botonSonido() {
    if (!pref().activado || (audio && audio.state === 'running') || $('tqSnd')) return;
    const b = document.createElement('button');
    b.className = 'btn primary tq-sound'; b.id = 'tqSnd'; b.textContent = '🔊 Activar sonidos de alertas';
    b.onclick = () => { try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); audio.resume(); } catch (e) {} b.remove(); tono(PATRONES.operacion); };
    document.body.appendChild(b);
  }
  async function sondearAlertas() {
    if (!TQ.usuario) return;
    try {
      const c = await api('/api/tq/alertas/contadores');
      const n = $('tqBellN');
      if (n) { n.hidden = !c.nuevas; n.textContent = c.nuevas > 99 ? '99+' : c.nuevas; }
      botonSonido();
      const ultima = ls.get('tq_ult_alerta', null);
      if (ultima == null) { ls.set('tq_ult_alerta', c.ultima_id || 0); return; }
      if (c.ultima_id && c.ultima_id > ultima) {
        const d = await api('/api/tq/alertas?desde_id=' + ultima + '&limite=20');
        d.alertas.reverse().forEach(sonarAlerta);
        ls.set('tq_ult_alerta', c.ultima_id);
        if (document.querySelector('#view-alerts.active')) RENDER.alerts();
      }
    } catch (e) {}
  }

  RENDER.alerts = async function () {
    const v = $('view-alerts');
    const f = v._f || (v._f = { ver: 'normal', categoria: '', estado: '', importancia: '', buscar: '' });
    if (!v._m) {
      v._m = 1;
      v.innerHTML = `<div class="head"><div class="eyebrow">Centro de alertas</div><h1>Alertas y notificaciones</h1>
        <div class="muted">Todas las alertas quedan registradas. Ocultar solo las quita de esta vista.</div></div>
        <div class="card" style="margin-bottom:12px"><div class="tq-row">
          <select class="field" id="taCat" style="width:auto"><option value="">Todas las categorías</option></select>
          <select class="field" id="taEst" style="width:auto"><option value="">Leídas y no leídas</option><option value="nueva">No leídas</option><option value="leida">Leídas</option></select>
          <select class="field" id="taImp" style="width:auto"><option value="">Toda importancia</option><option>critica</option><option>alta</option><option>media</option><option>baja</option></select>
          <select class="field" id="taVer" style="width:auto"><option value="normal">Vista normal</option><option value="ocultos">Ocultas</option><option value="todo">Todas</option></select>
          <input class="field" id="taBus" placeholder="Buscar…" style="width:160px"><button class="btn" id="taLeer">Marcar todo leído</button></div>
          <div id="taSil" class="tq-row" style="margin-top:10px"></div></div><div id="taLista"></div>`;
      const cats = await api('/api/tq/alertas/categorias');
      $('taCat').innerHTML += cats.categorias.map(c => `<option value="${esc(c.id)}">${esc(c.nombre)}</option>`).join('');
      $('taSil').innerHTML = '<span class="muted">Silenciar:</span> ' + cats.categorias.map(c => `<label class="tq-chk" style="margin:0 8px 0 0"><input type="checkbox" data-sil="${esc(c.id)}" ${c.silenciada ? 'checked' : ''}>${esc(c.nombre)}</label>`).join('');
      $('taSil').querySelectorAll('[data-sil]').forEach(x => x.onchange = () => api('/api/tq/alertas/silenciar', { categoria: x.dataset.sil, silenciar: x.checked }).catch(e => alert(e.message)));
      ['taCat', 'taEst', 'taImp', 'taVer'].forEach(id => $(id).onchange = () => { f.categoria = $('taCat').value; f.estado = $('taEst').value; f.importancia = $('taImp').value; f.ver = $('taVer').value; RENDER.alerts(); });
      let tm; $('taBus').oninput = () => { clearTimeout(tm); tm = setTimeout(() => { f.buscar = $('taBus').value; RENDER.alerts(); }, 350); };
      $('taLeer').onclick = async () => { const d = await api('/api/tq/alertas?estado=nueva&limite=500'); await api('/api/tq/alertas/leer', { ids: d.alertas.map(a => a.id) }); RENDER.alerts(); sondearAlertas(); };
    }
    const L = $('taLista');
    L.innerHTML = cargando();
    try {
      const qs = new URLSearchParams({ ver: f.ver, categoria: f.categoria, estado: f.estado, importancia: f.importancia, buscar: f.buscar, limite: 150 });
      const d = await api('/api/tq/alertas?' + qs);
      L.innerHTML = d.alertas.length ? d.alertas.map(a => `<div class="tq-alert ${esc(a.importancia)} ${a.estado === 'nueva' ? 'nueva' : ''}">
        <div class="tq-row" style="justify-content:space-between"><b>${esc(a.tipo)}</b><span class="muted">${fecha(a.ts)}</span></div>
        <div class="tq-row" style="margin:5px 0">${badge(a.categoria_nombre)} ${badge(a.importancia, a.importancia === 'critica' ? 'err' : a.importancia === 'alta' ? 'warn' : '')}
          ${a.activo ? badge(a.activo) : ''}${a.mercado ? badge(a.mercado) : ''}${a.direccion ? badge(a.direccion) : ''}${a.modalidad ? badge(a.modalidad, a.modalidad === 'simulacion' ? 'sim' : a.modalidad) : ''}
          ${a.precio_ref != null ? `<span class="muted">ref. ${num(a.precio_ref, 5)}</span>` : ''}${a.horizonte ? `<span class="muted">· ${esc(a.horizonte)}</span>` : ''}</div>
        ${a.justificacion ? `<div class="muted">${esc(a.justificacion)}</div>` : ''}
        <div class="muted" style="margin-top:4px">Motores: ${esc((a.motores || []).join(', ') || '—')} · Estado: ${esc(a.estado)}</div>
        <div class="tq-row" style="margin-top:6px">
          <button class="tq-link" data-a="${a.estado === 'nueva' ? 'leer' : 'noleer'}" data-id="${a.id}">${a.estado === 'nueva' ? 'Marcar leída' : 'Marcar no leída'}</button>
          <button class="tq-link" data-a="${a.visibilidad === 'oculto' ? 'restaurar' : 'ocultar'}" data-id="${a.id}">${a.visibilidad === 'oculto' ? 'Mostrar de nuevo' : 'Ocultar de la vista'}</button>
          ${a.datos ? `<button class="tq-link" data-det="${a.id}">Detalles</button>` : ''}</div>
        <pre class="tq-md" id="tqDet${a.id}" hidden>${esc(JSON.stringify(a.datos, null, 2))}</pre></div>`).join('') : '<div class="card muted">No hay alertas con estos filtros.</div>';
      L.querySelectorAll('[data-a]').forEach(b => b.onclick = async () => { await api('/api/tq/alertas/' + b.dataset.a, { ids: [b.dataset.id] }); RENDER.alerts(); sondearAlertas(); });
      L.querySelectorAll('[data-det]').forEach(b => b.onclick = () => { const p = $('tqDet' + b.dataset.det); p.hidden = !p.hidden; });
    } catch (e) { L.innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== ANALIZAR MERCADO
  RENDER.analysis = async function () {
    const v = $('view-analysis');
    if (v._m) return;
    v._m = 1;
    v.innerHTML = `<div class="head"><div class="eyebrow">TITAN CORE · 23 motores</div><h1>Analizar mercado</h1>
      <div class="muted">Análisis inmediato y vigilancia prospectiva. Si no hay condiciones suficientes, TITAN lo dice: no inventa entradas.</div></div>
      <div class="card" style="margin-bottom:14px"><div class="grid two"><div>
        <div class="formrow"><label class="label">Activo</label><select class="field" id="anAct"></select></div>
        <div class="formrow"><label class="label">O escribe un símbolo de Yahoo Finance</label><input class="field" id="anSym" placeholder="p. ej. AMD, DOGE-USD, ^GSPC" autocapitalize="characters"></div></div><div>
        <div class="formrow"><label class="label">Horizonte</label><select class="field" id="anHz"></select></div>
        <div class="formrow"><label class="label">Nivel de inteligencia</label><div id="anNiv" class="muted">—</div></div>
        <button class="btn primary" id="anGo" style="width:100%;padding:13px;font-size:15px;letter-spacing:1px">◈ ANALIZAR MERCADO</button></div></div></div>
      <div id="anOut"></div>`;
    const [as, nv] = await Promise.all([api('/api/assets').catch(() => ({ activos: [] })), api('/api/tq/niveles')]);
    $('anAct').innerHTML = as.activos.map(a => `<option value="${esc(a.simbolo)}">${esc(a.categoria)} · ${esc(a.nombre)} (${esc(a.simbolo)})</option>`).join('');
    $('anHz').innerHTML = Object.entries(nv.horizontes).map(([k, h]) => `<option value="${k}">${esc(h.nombre)} · velas ${esc(h.intervalo)}</option>`).join('');
    $('anHz').value = (TQ.preferencias && TQ.preferencias.horizonte) || 'corto';
    $('anNiv').innerHTML = `${badge(nv.niveles[nv.seleccion.nivel].nombre, 'ok')} política ${esc(nv.seleccion.politica)} · <button class="tq-link" onclick="go('inteligencia')">cambiar</button>`;
    $('anGo').onclick = async () => {
      const sim = ($('anSym').value || $('anAct').value).trim().toUpperCase();
      const out = $('anOut'); out.innerHTML = `<div class="card">${cargando('Ejecutando los motores para ' + sim + '… (puede tardar según el nivel)')}</div>`;
      $('anGo').disabled = true;
      try { const d = await api('/api/tq/analizar', { simbolo: sim, horizonte: $('anHz').value }); out.innerHTML = pintarAnalisis(d.resultado, d.id); enlazarAnalisis(out); sondearAlertas(); }
      catch (e) { out.innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
      finally { $('anGo').disabled = false; }
    };
  };

  function pintarAnalisis(r, id) {
    const fu = r.fusion || {};
    const e = r.escenario || fu.escenario_descartado;
    const fd = r.fuente_datos || {};
    const cal = fd.calidad || {};
    let h = `<div class="tq-kpis"><div class="tq-kpi"><small>Activo</small><b>${esc(r.activo.nombre)}</b><small>${esc(r.activo.simbolo)} · ${esc(fd.tipo || '?')}</small></div>
      <div class="tq-kpi"><small>Resultado</small><b class="${r.hay_oportunidad ? 'up' : ''}">${r.hay_oportunidad ? 'Escenario válido' : 'Sin oportunidad'}</b><small>${esc(fu.direccion || 'sin dirección')} · puntuación ${num(fu.puntuacion, 2)}</small></div>
      <div class="tq-kpi"><small>Datos</small><b>${esc(fd.proveedor || '—')}</b><small>calidad ${esc(cal.calidad || '?')} · ${esc(fd.intervalo || '')} · ${esc(fd.rango || '')}</small></div>
      <div class="tq-kpi"><small>Nivel</small><b>${esc(r.nivel)}</b><small>${esc(r.politica)} · ${(r.ajustes_adaptativos || []).length} ajustes</small></div></div>`;
    if (e) {
      h += `<div class="tq-esc ${r.hay_oportunidad ? '' : 'no'}" style="margin-bottom:14px"><b>${r.hay_oportunidad ? 'Escenario' : 'Escenario descartado (no superó las puertas de seguridad)'} · ${esc(e.direccion)} · ${esc(e.horizonte)}</b>
        <div class="tq-grid3" style="margin-top:10px"><div><small class="muted">Precio de referencia</small><div class="big">${num(e.precio_referencia, 5)}</div></div>
        <div><small class="muted">Zona de entrada</small><div class="big">${num(e.zona_entrada[0], 5)} – ${num(e.zona_entrada[1], 5)}</div></div>
        <div><small class="muted">Riesgo/beneficio</small><div class="big">${num(e.riesgo_beneficio, 2)}</div></div>
        <div><small class="muted">Stop loss</small><div class="big">${num(e.stop_loss, 5)}</div></div>
        <div><small class="muted">Take profit</small><div class="big">${num(e.take_profit[0], 5)} / ${num(e.take_profit[1], 5)}</div></div>
        <div><small class="muted">Probabilidad estimada</small><div class="big">${e.probabilidad == null ? '—' : pct(e.probabilidad)}</div><small class="muted">${esc(e.metodo_probabilidad)}</small></div></div>
        <div class="grid two" style="margin-top:10px"><div><b>Confirmación</b><ul>${e.confirmacion.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>
        <div><b>Invalidación</b><ul>${e.invalidacion.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div></div>
        <div class="muted">Vigente hasta ${fecha(e.vigencia_hasta_ts)}${e.tamano && e.tamano.unidades ? ` · tamaño orientativo ${num(e.tamano.unidades, 4)} unidades (riesgo ${num(e.tamano.riesgo_importe)})` : ''}</div></div>`;
    }
    if (!r.hay_oportunidad) {
      h += `<div class="card" style="margin-bottom:14px"><b>${esc(fu.mensaje || 'No hay oportunidad válida')}</b><ul>${(fu.motivo_sin_oportunidad || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
        ${fu.vigilancia ? `<b>Vigilancia prospectiva</b><div class="grid two"><div><small class="muted">Resistencias</small><div>${(fu.vigilancia.resistencias || []).map(x => num(x.precio, 5) + ` (${x.toques})`).join(' · ') || '—'}</div></div>
        <div><small class="muted">Soportes</small><div>${(fu.vigilancia.soportes || []).map(x => num(x.precio, 5) + ` (${x.toques})`).join(' · ') || '—'}</div></div></div>
        <ul>${(fu.vigilancia.condiciones || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}</div>`;
    }
    h += `<div class="grid two"><div class="card"><b>Justificación por motor</b><ul>${(fu.justificacion || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <b>Incertidumbre y datos faltantes</b><ul>${(fu.incertidumbre || []).slice(0, 12).map(x => `<li class="muted">${esc(x)}</li>`).join('') || '<li class="muted">—</li>'}</ul></div>
      <div class="card"><b>Informe (RESEARCH ENGINE)</b><div class="tq-md" style="max-height:340px;overflow:auto">${esc(r.informe_md || '—')}</div></div></div>
      <div class="card" style="margin-top:14px"><b>Estado de los motores en este análisis</b><div class="tq-scroll"><table class="tq-table"><tr><th>#</th><th>Motor</th><th>Estado</th><th>ms</th><th>Notas / faltantes</th><th></th></tr>
      ${r.motores.map(m => `<tr><td>${m.numero}</td><td>${esc(m.nombre)}</td><td>${badge(m.estado, ESTADO_C[m.estado])}</td><td>${m.duracion_ms}</td>
      <td class="muted">${esc([].concat(m.faltantes || [], m.error ? [m.error] : [], (m.notas || []).filter(x => x.length < 200)).slice(0, 3).join(' · '))}</td>
      <td><button class="tq-link" data-sal="${esc(m.motor)}">salida</button></td></tr>
      <tr hidden id="tqSal${esc(m.motor)}"><td colspan="6"><pre class="tq-md" style="max-height:260px;overflow:auto">${esc(JSON.stringify(m.salida, null, 2))}</pre></td></tr>`).join('')}</table></div>
      <div class="muted" style="margin-top:8px">Análisis #${esc(id)} guardado en el historial. El rendimiento pasado no garantiza resultados futuros.</div></div>`;
    return h;
  }
  function enlazarAnalisis(el) {
    el.querySelectorAll('[data-sal]').forEach(b => b.onclick = () => { const t = $('tqSal' + b.dataset.sal); t.hidden = !t.hidden; });
  }

  // =========================================================================== MOTORES
  RENDER.motores = async function () {
    const v = $('view-motores');
    v.innerHTML = `<div class="head"><div class="eyebrow">Arquitectura</div><h1>Los 23 motores</h1><div class="muted">Disponibles en los cuatro niveles. Estado de la última ejecución.</div></div><div id="moL">${cargando()}</div>`;
    try {
      const d = await api('/api/tq/motores');
      $('moL').innerHTML = `<div class="tq-motores">${d.motores.map(m => `<div class="tq-motor"><h4><span class="n">${m.numero}</span>${esc(m.nombre)}</h4>
        <div class="tq-row">${badge(m.estado, ESTADO_C[m.estado])}<span class="muted">${m.ejecuciones} ejec. · ${m.errores} err.</span></div>
        <div class="muted" style="margin-top:6px">${esc(m.ficha.objetivo)}</div>
        <details style="margin-top:6px"><summary class="muted" style="cursor:pointer">Métodos y dependencias</summary><div class="muted" style="margin-top:4px">${esc(m.ficha.metodos)}</div>
        <div class="muted">Depende de: ${esc(m.ficha.dependencias.join(', ') || '—')}</div><div class="muted">Niveles: ${esc(m.ficha.niveles || 'igual en todos')}</div>
        ${m.ultimo_error ? `<div class="tq-msg err">${esc(m.ultimo_error)}</div>` : ''}</details>
        <div class="muted" style="margin-top:4px">Última: ${fecha(m.ultimo_ts)}${m.duracion_ms != null ? ' · ' + m.duracion_ms + ' ms' : ''}</div></div>`).join('')}</div>`;
    } catch (e) { $('moL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== INTELIGENCIA (niveles)
  RENDER.inteligencia = async function () {
    const v = $('view-inteligencia');
    v.innerHTML = `<div class="head"><div class="eyebrow">Configuración de inteligencia</div><h1>Nivel y procesamiento</h1>
      <div class="muted">El nivel cambia profundidad, datos, modelos y simulaciones; nunca elimina motores. TITAN puede recomendar, pero no cambia tu elección.</div></div><div id="inL">${cargando()}</div>`;
    try {
      const d = await api('/api/tq/niveles');
      const filas = ['rango_historico', 'ventanas', 'activos_max', 'modelos_ml', 'ml_epocas', 'montecarlo_sim', 'backtest_barras', 'walk_forward_cortes', 'escenarios', 'concurrencia', 'frecuencia_s', 'noticias_horas', 'investigacion', 'correlacion_activos'];
      $('inL').innerHTML = `<div class="card" style="margin-bottom:12px"><div class="tq-row">${d.orden.map(n => `<button class="btn ${n === d.seleccion.nivel ? 'primary' : ''}" data-niv="${n}">${esc(d.niveles[n].nombre)}</button>`).join('')}</div>
        <div class="muted" style="margin-top:8px">Recomendado para este dispositivo: <b>${esc(d.niveles[d.recomendacion.recomendado].nombre)}</b> (${esc(d.recomendacion.motivo)})</div>
        <div class="formrow" style="margin-top:12px"><label class="label">Política de procesamiento</label><select class="field" id="inPol">${Object.entries(d.politicas).map(([k, t]) => `<option value="${k}" ${k === d.seleccion.politica ? 'selected' : ''}>${k} — ${esc(t)}</option>`).join('')}</select></div><div id="inM"></div></div>
        <div class="card tq-scroll"><table class="tq-table"><tr><th>Parámetro</th>${d.orden.map(n => `<th>${esc(d.niveles[n].nombre)}</th>`).join('')}</tr>
        ${filas.map(f => `<tr><td>${f.replace(/_/g, ' ')}</td>${d.orden.map(n => `<td>${esc(Array.isArray(d.niveles[n][f]) ? d.niveles[n][f].join(', ') : d.niveles[n][f])}</td>`).join('')}</tr>`).join('')}</table></div>`;
      v.querySelectorAll('[data-niv]').forEach(b => b.onclick = async () => { await api('/api/tq/nivel', { nivel: b.dataset.niv }); TQ.preferencias.nivel = b.dataset.niv; const a = $('view-analysis'); a._m = 0; RENDER.inteligencia(); });
      $('inPol').onchange = async () => { try { await api('/api/tq/nivel', { politica: $('inPol').value }); msg($('inM'), 'Política guardada.', 'ok'); } catch (e) { msg($('inM'), e.message, 'err'); } };
    } catch (e) { $('inL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== HARDWARE
  RENDER.hardware = async function () {
    const v = $('view-hardware');
    v.innerHTML = `<div class="head"><div class="eyebrow">HARDWARE DIAGNOSTICS + ADAPTIVE COMPUTE</div><h1>Hardware</h1><div class="muted">Medido en el dispositivo donde corre TITAN. Lo no accesible se indica como tal.</div></div><div id="hwL">${cargando()}</div>`;
    try {
      const { diagnostico: d, recomendacion: r } = await api('/api/tq/hardware?red=1');
      $('hwL').innerHTML = `<div class="tq-kpis"><div class="tq-kpi"><small>CPU</small><b>${d.cpu.nucleos} núcleos</b><small>uso ${num(d.cpu.uso_pct, 1)} % · carga ${esc((d.cpu.carga_1_5_15 || []).join(' / '))}</small></div>
        <div class="tq-kpi"><small>Memoria</small><b>${num(d.memoria.disponible_mb, 0)} MB libres</b><small>de ${num(d.memoria.total_mb, 0)} MB</small></div>
        <div class="tq-kpi"><small>Almacenamiento</small><b>${num(d.disco.libre_gb, 1)} GB libres</b><small>de ${num(d.disco.total_gb, 1)} GB</small></div>
        <div class="tq-kpi"><small>Red</small><b>${d.red.latencia_ms == null ? 'sin conexión' : d.red.latencia_ms + ' ms'}</b><small>latencia a la fuente de datos</small></div></div>
        <div class="grid two"><div class="card"><b>Temperatura</b><div class="muted">${d.temperatura.sensores.length ? d.temperatura.sensores.map(s => esc(s.sensor) + ': ' + num(s.c, 1) + ' °C').join('<br>') : esc(d.temperatura.nota)}</div>
        <b style="display:block;margin-top:10px">GPU</b><div class="muted">${esc(d.gpu.nota)}</div></div>
        <div class="card"><b>Recomendación</b><div class="big">${esc(r.recomendado)}</div><div class="muted">${esc(r.motivo)}</div><div class="muted" style="margin-top:8px">Procesos: ${esc(d.procesos)} · Python ${esc(d.plataforma.python)} · Termux: ${d.plataforma.termux ? 'sí' : 'no'}</div></div></div>`;
    } catch (e) { $('hwL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== DIAGNÓSTICO
  RENDER.diagnostico = async function () {
    const v = $('view-diagnostico');
    v.innerHTML = `<div class="head"><div class="eyebrow">MONITORING ENGINE</div><h1>Diagnóstico</h1></div><div id="dgL">${cargando()}</div>`;
    try {
      const d = await api('/api/tq/diagnostico');
      const s = d.sistema;
      $('dgL').innerHTML = `<div class="grid two"><div class="card"><b>Sistema</b><table class="tq-table">
        <tr><td>Versión</td><td>${esc(d.version)}</td></tr><tr><td>Cifrado de credenciales</td><td>${esc(d.cifrado)}</td></tr>
        <tr><td>Servidor</td><td>${esc(d.host)}:${esc(d.puerto)} ${d.https ? '(HTTPS)' : ''}</td></tr><tr><td>Correo SMTP</td><td>${d.correo_configurado ? badge('configurado', 'ok') : badge('no configurado', 'warn')}</td></tr>
        <tr><td>Bot operador (hilo)</td><td>${d.autotrader.vivo ? badge('vivo', 'ok') : badge('detenido', 'warn')} ${esc(d.autotrader.error || '')}</td></tr>
        <tr><td>Vigilante de planes</td><td>${s.vigilante_planes.vivo ? badge('vivo', 'ok') : badge('detenido', 'warn')}</td></tr>
        <tr><td>Última batería de pruebas</td><td>${d.pruebas ? (d.pruebas.ok ? badge('superada', 'ok') : badge('con fallos', 'err')) + ' ' + fecha(d.pruebas.ts) + ' · ' + esc(d.pruebas.resumen || '') : badge('no ejecutada', 'warn')}</td></tr></table></div>
        <div class="card"><b>Bases de datos</b><table class="tq-table">${Object.entries(s.bases).map(([k, b]) => `<tr><td>${esc(k)}</td><td>${b.existe ? num(b.mb, 2) + ' MB' : 'no existe'}</td><td>${b.integridad ? badge(b.integridad, b.integridad === 'ok' ? 'ok' : 'err') : ''}</td></tr>`).join('')}</table>
        <b style="display:block;margin-top:10px">Errores recientes de motores</b>${d.errores_motores.length ? d.errores_motores.map(e => `<div class="muted">${esc(e.motor)}: ${esc(e.error)} (${fecha(e.ts)})</div>`).join('') : '<div class="muted">Ninguno</div>'}</div></div>`;
    } catch (e) { $('dgL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== CONFIGURACIÓN E INTEGRACIONES
  RENDER.brokers = async function () {
    const v = $('view-brokers');
    const avisoHash = location.hash === '#integraciones-ok' ? '<div class="tq-msg ok">cTrader autorizado correctamente.</div>' : location.hash === '#integraciones-error' ? '<div class="tq-msg err">No se completó la autorización de cTrader.</div>' : '';
    if (avisoHash) history.replaceState(null, '', location.pathname);
    v.innerHTML = `<div class="head"><div class="eyebrow">CONFIGURACIÓN E INTEGRACIONES</div><h1>Claves API, brokers y servicios</h1>
      <div class="muted">Las credenciales se guardan cifradas en el servidor. Después de guardarlas solo verás una versión enmascarada. Nunca se envían al navegador.</div>${avisoHash}</div><div id="igL">${cargando()}</div>`;
    try {
      const d = await api('/api/tq/integraciones');
      const grupos = {};
      d.integraciones.forEach(i => (grupos[i.grupo] = grupos[i.grupo] || []).push(i));
      $('igL').innerHTML = Object.entries(grupos).map(([g, l]) => `<div class="eyebrow" style="margin:16px 0 8px">${esc(g)}</div><div class="grid two">${l.map(i => `
        <form class="card" data-prov="${esc(i.proveedor)}"><div class="tq-row" style="justify-content:space-between"><b>${esc(i.nombre)}</b>${badge(i.estado.replace(/_/g, ' '), ESTADO_C[i.estado])}</div>
        <div class="muted" style="margin:6px 0 10px">${esc(i.descripcion)}</div>
        ${i.campos.map(c => `<div class="formrow"><label class="label">${esc(c.etiqueta)}${c.requerido ? '' : ' (opcional)'}${c.secreto && c.guardado ? ` · guardado ${esc(c.mascara)}` : ''}</label>
          ${c.tipo === 'select' ? `<select class="field" name="${esc(c.id)}">${c.opciones.map(o => `<option ${o === c.valor ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`
          : `<input class="field" name="${esc(c.id)}" type="${c.secreto ? 'password' : c.tipo === 'number' ? 'number' : 'text'}" autocomplete="off" ${c.secreto ? `placeholder="${c.guardado ? 'Deja vacío para conservar' : ''}"` : `value="${esc(c.valor || '')}"`}>`}
          ${c.ayuda ? `<small class="muted">${esc(c.ayuda)}</small>` : ''}</div>`).join('')}
        <div class="muted">Última comprobación: ${fecha(i.ultima_prueba_ts)} ${i.resultado ? '· ' + esc(i.resultado) : ''}</div>${i.error ? `<div class="tq-msg err">${esc(i.error)}</div>` : ''}
        <div class="tq-row" style="margin-top:10px">${i.campos.length ? '<button class="btn primary" data-acc="guardar">Guardar</button>' : ''}<button class="btn" data-acc="probar">Probar conexión</button>
          ${i.oauth ? '<button class="btn" data-acc="oauth">Autorizar con cTrader</button>' : ''}
          <button class="btn" data-acc="activar">${i.activa ? 'Desactivar' : 'Activar'}</button>${i.campos.length ? '<button class="btn" data-acc="eliminar">Eliminar credenciales</button>' : ''}</div><div class="tq-m"></div></form>`).join('')}</div>`).join('');
      $('igL').querySelectorAll('form[data-prov]').forEach(f => {
        const prov = f.dataset.prov;
        const m = f.querySelector('.tq-m');
        f.onsubmit = ev => ev.preventDefault();
        f.querySelectorAll('[data-acc]').forEach(b => b.onclick = async ev => {
          ev.preventDefault();
          const acc = b.dataset.acc;
          try {
            if (acc === 'guardar') { const val = {}; new FormData(f).forEach((x, k) => { if (x !== '') val[k] = x; }); await api('/api/tq/integraciones/guardar', { proveedor: prov, valores: val }); }
            else if (acc === 'probar') { msg(m, 'Probando…'); const r = await api('/api/tq/integraciones/probar', { proveedor: prov }); if (r.estado === 'error') throw new Error(r.error); }
            else if (acc === 'activar') await api('/api/tq/integraciones/activar', { proveedor: prov, activa: b.textContent === 'Activar' });
            else if (acc === 'eliminar') { if (!confirm('¿Eliminar de forma segura las credenciales de ' + prov + '?')) return; await api('/api/tq/integraciones/eliminar', { proveedor: prov }); }
            else if (acc === 'oauth') { const r = await api('/api/tq/integraciones/ctrader/autorizar', {}); location.href = r.url; return; }
            RENDER.brokers();
          } catch (e) { msg(m, e.message, 'err'); }
        });
      });
    } catch (e) { $('igL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== BOT OPERADOR (tres cuentas separadas)
  RENDER.operator = async function () {
    const v = $('view-operator');
    const mod = ls.get('tq_op_mod', 'simulacion');
    v.innerHTML = `<div class="head"><div class="eyebrow">TITAN AUTO TRADER</div><h1>Bot operador</h1>
      <div class="muted">Tres cuentas independientes, cada una con su propia base de datos. Solo se comparte el conocimiento del motor de aprendizaje.</div></div><div id="opL">${cargando()}</div>`;
    try {
      const d = await api('/api/tq/operador?modalidad=' + mod);
      const m = d.bots[mod] ? mod : 'simulacion';
      const b = d.bots[m], a = b.ajustes, rs = d.resumen[m], k = d.conocimiento_fusion;
      const inp = (key, et, t) => `<div class="formrow"><label class="label">${et}</label><input class="field" name="${key}" type="${t || 'number'}" step="any" value="${esc(a[key] == null ? '' : a[key])}"></div>`;
      const chk = (key, et) => `<label class="tq-chk"><input type="checkbox" name="${key}" ${a[key] ? 'checked' : ''}> ${et}</label>`;
      const ct = a.broker === 'ctrader';
      const aviso = { simulacion: 'SIMULACIÓN — operaciones ficticias con precios reales. Base: datos/cuentas/simulacion.db',
        demo: 'DEMO — cuenta de práctica del broker (cTrader demo). Base: datos/cuentas/demo.db',
        real: '⚠ REAL LIVE — DINERO REAL en tu cuenta cTrader live. Base: datos/cuentas/real.db' }[m];
      $('opL').innerHTML = `<div class="tq-tabs" id="opMod">${['simulacion', 'demo', 'real'].map(x => `<button data-mod="${x}" class="${x === m ? 'on' : ''}" style="min-width:150px;padding:10px">
          <b>${{ simulacion: '🧪', demo: '🟦', real: '🟥' }[x]} ${NOMBRE_MOD[x]}</b><br><small>${esc(d.bots[x].estado)} · ${d.resumen[x].abiertas} abiertas · ${d.resumen[x].n} cerradas</small></button>`).join('')}</div>
        <div class="tq-mode ${m}" style="margin-bottom:12px;font-size:14px">${esc(aviso)}</div>
        <div class="tq-kpis"><div class="tq-kpi"><small>Estado del bot ${esc(NOMBRE_MOD[m])}</small><b>${esc(b.estado.toUpperCase())}</b><small>hilo ${d.hilo_vivo ? 'vivo' : 'detenido'}</small></div>
        <div class="tq-kpi"><small>Instrumento · estrategia</small><b>${esc(ct ? a.simbolo_broker : a.instrumento)}</b><small>${esc(a.estrategia)} · ${esc(a.horizonte)} · ${ct ? 'cuenta ' + esc(a.cuenta_ctid || '— sin elegir') : esc(a.broker)}</small></div>
        <div class="tq-kpi"><small>Resultado de esta cuenta</small><b class="${rs.neto >= 0 ? 'up' : ''}">${num(rs.neto)} ${esc(rs.moneda || '')}</b><small>${rs.n} cerradas · ${rs.ganadas} ganadas · ${rs.perdidas} perdidas</small></div>
        <div class="tq-kpi"><small>Abiertas / rechazadas</small><b>${rs.abiertas} / ${rs.rechazadas}</b><small>broker ${esc(a.broker)}</small></div></div>
        <div class="card" style="margin-bottom:12px"><div class="tq-row">
          <button class="btn primary" data-est="activo">▶ Iniciar ${esc(NOMBRE_MOD[m])}</button><button class="btn" data-est="pausado">⏸ Pausar</button><button class="btn" data-est="detenido">■ Detener</button>
          <button class="btn" id="opCiclo">Ejecutar un ciclo ahora</button>
          <button class="btn" data-est="emergencia" style="background:#5a1515;border-color:#a33;color:#fff;font-weight:700">⛔ PARADA DE EMERGENCIA</button></div>
          ${m === 'real' ? '<div class="formrow" style="max-width:320px;margin-top:8px"><label class="label">Contraseña de TITAN (obligatoria para iniciar el bot REAL)</label><input class="field" id="opClaveReal" type="password" autocomplete="current-password"></div>' : ''}
          <div id="opM"></div></div>
        <div class="grid two"><form class="card" id="opF"><b>Configuración de la cuenta ${esc(NOMBRE_MOD[m])} (bot pausado o detenido)</b>
          <div class="grid two" style="margin-top:10px"><div>
          <div class="formrow"><label class="label">Broker / plataforma</label><select class="field" name="broker">${d.brokers.filter(x => d.brokers_por_modalidad[m].includes(x.id)).map(x => `<option value="${esc(x.id)}">${esc(x.nombre)}</option>`).join('')}</select></div>
          <div id="opCT" ${ct ? '' : 'hidden'}>
            <div class="formrow"><label class="label">Cuenta cTrader ${m === 'real' ? 'REAL (live)' : 'DEMO'}</label><select class="field" name="cuenta_ctid"><option value="">Cargando cuentas…</option></select></div>
            <div class="formrow"><label class="label">Símbolo del broker</label><input class="field" name="simbolo_broker" list="opSims" value="${esc(a.simbolo_broker || '')}"><datalist id="opSims"></datalist></div>
            <div class="formrow"><label class="label">Velas para el análisis</label><select class="field" name="fuente_datos"><option value="broker">Las del propio broker (recomendado)</option><option value="yahoo">Yahoo Finance</option></select></div>
            ${chk('capital_desde_broker', 'Usar el saldo real de la cuenta como capital')}
            <div id="opCTm" class="muted" style="margin:6px 0"></div></div>
          ${inp('instrumento', 'Instrumento para el análisis (Yahoo)', 'text')}
          <div class="formrow"><label class="label">Mercado</label><input class="field" name="mercado" value="${esc(a.mercado)}"></div>
          <div class="formrow"><label class="label">Horizonte</label><select class="field" name="horizonte">${['scalping', 'intradia', 'corto', 'mediano', 'largo'].map(x => `<option ${x === a.horizonte ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
          <div class="formrow"><label class="label">Tipo</label><select class="field" name="tipo"><option value="margen">Margen/CFD (stop y objetivo)</option><option value="binaria">Opción binaria</option></select></div>
          <div class="formrow"><label class="label">Estrategia</label><select class="field" name="estrategia">${Object.entries(d.estrategias).map(([x, t]) => `<option value="${x}">${esc(t)}</option>`).join('')}</select></div>
          ${inp('payout', 'Payout binarias (0–1)')}${inp('expiracion_min', 'Expiración binarias (min)')}</div><div>
          ${inp('capital', 'Capital de referencia (si no se usa el saldo)')}${inp('riesgo_pct', 'Riesgo máximo por operación (%)')}${inp('perdida_diaria_max_pct', 'Pérdida máxima diaria (%)')}
          ${inp('perdida_semanal_max_pct', 'Pérdida máxima semanal (%)')}${inp('exposicion_max_pct', 'Exposición total máxima (% en riesgo)')}${inp('max_abiertas', 'Máx. operaciones abiertas')}
          ${inp('max_perdidas_consecutivas', 'Máx. pérdidas consecutivas')}${inp('spread_max_pct', 'Spread máximo (%)')}${inp('slippage_max_pct', 'Slippage máximo (%)')}
          ${inp('datos_max_edad_s', 'Antigüedad máxima de datos (s)')}${inp('duplicado_ventana_s', 'Ventana anti-duplicados (s)')}${inp('ciclo_s', 'Frecuencia del ciclo (s)')}
          ${m === 'real' ? chk('exigir_ventaja_real', 'Exigir ventaja demostrada antes de abrir en REAL') + inp('ventaja_min_operaciones', 'Operaciones mínimas de conocimiento') : ''}</div></div>
          <button class="btn primary">Guardar configuración ${esc(NOMBRE_MOD[m])}</button><div id="opFm"></div></form>
          <div><div class="card"><b>🧠 Conocimiento compartido (estrategia fusion)</b>
            <div class="muted" style="margin:6px 0">Lo único que comparten las tres cuentas: el resultado de cada operación medido en R (resultado ÷ riesgo), sin importes, saldos ni números de cuenta.</div>
            <div class="tq-kpis"><div class="tq-kpi"><small>Operaciones aprendidas</small><b>${k.n}</b></div><div class="tq-kpi"><small>Expectativa</small><b>${k.expectativa_r == null ? '—' : num(k.expectativa_r, 3) + ' R'}</b></div>
            <div class="tq-kpi"><small>Acierto</small><b>${k.tasa_acierto == null ? '—' : num(k.tasa_acierto * 100, 1) + ' %'}</b><small>${k.n ? 'IC95 ' + num(k.tasa_ic95[0] * 100, 0) + '–' + num(k.tasa_ic95[1] * 100, 0) + ' %' : ''}</small></div></div>
            <div class="muted">${Object.entries(k.por_origen).map(([o, x]) => `${esc(NOMBRE_MOD[o] || o)}: ${x.n} op · ${num(x.expectativa_r, 3)} R`).join(' · ') || 'Aún sin operaciones cerradas.'}</div></div>
          <div class="card" style="margin-top:12px"><b>Cuenta REAL</b> ${b && d.bots.real.real_habilitado ? badge('habilitada', 'real') : badge('bloqueada', 'warn')}
            <div class="muted">Requisitos:</div><ul>${d.requisitos_real.requisitos.map(r => `<li>${r.ok ? '✅' : '❌'} ${esc(r.requisito)} <span class="muted">(${esc(r.valor == null ? '—' : r.valor)})</span></li>`).join('')}</ul>
            <div class="muted">Recomendaciones:</div><ul>${d.requisitos_real.recomendaciones.map(r => `<li>${r.ok ? '✅' : '⚠️'} ${esc(r.recomendacion)} <span class="muted">(${esc(r.valor)})</span></li>`).join('')}</ul>
            ${d.bots.real.real_habilitado ? '<button class="btn" id="opRealOff">Deshabilitar la cuenta REAL</button>' : `<form id="opRealF"><div class="formrow"><label class="label">Escribe: ${esc(d.frase_real)}</label><input class="field" name="frase" autocomplete="off"></div>
              <div class="formrow"><label class="label">Contraseña de TITAN</label><input class="field" name="clave" type="password" autocomplete="current-password"></div><button class="btn" style="border-color:#a33">Habilitar la cuenta REAL</button></form>`}
            <div id="opRm"></div></div></div></div>
        <div class="card" style="margin-top:12px"><div class="tq-tabs" id="opTabs"><button class="on" data-t="abiertas">Operaciones activas</button><button data-t="todas">Historial de operaciones</button><button data-t="decisiones">Decisiones del bot</button></div><div id="opT"></div></div>`;
      v.querySelectorAll('#opMod [data-mod]').forEach(x => x.onclick = () => { ls.set('tq_op_mod', x.dataset.mod); RENDER.operator(); });
      const f = $('opF');
      ['broker', 'tipo', 'estrategia', 'fuente_datos'].forEach(x => { if (f[x]) f[x].value = a[x]; });
      f.broker.onchange = () => { $('opCT').hidden = f.broker.value !== 'ctrader'; if (f.broker.value === 'ctrader') cargarCuentas(); };
      const cargarSimbolos = async () => {
        if (!f.cuenta_ctid.value) return;
        try { const r = await api(`/api/tq/ctrader/simbolos?modalidad=${m}&cuenta=${encodeURIComponent(f.cuenta_ctid.value)}`);
          if (!r.ok) throw new Error(r.error);
          $('opSims').innerHTML = r.simbolos.map(x => `<option value="${esc(x)}">`).join('');
          $('opCTm').textContent = r.simbolos.length + ' símbolos disponibles en la cuenta.';
        } catch (e) { $('opCTm').textContent = e.message; }
      };
      const cargarCuentas = async () => {
        if (m === 'simulacion') return;
        if (!d.ctrader_autorizado) { f.cuenta_ctid.innerHTML = '<option value="">—</option>'; $('opCTm').innerHTML = 'cTrader no está autorizado: ve a <a href="#" id="opIrInt">Configuración e integraciones → cTrader</a> y pulsa Autorizar.'; $('opIrInt').onclick = ev => { ev.preventDefault(); window.go('brokers'); }; return; }
        try { const r = await api('/api/tq/ctrader/cuentas?modalidad=' + m);
          if (!r.ok) throw new Error(r.error);
          f.cuenta_ctid.innerHTML = '<option value="">— elige la cuenta —</option>' + r.cuentas.map(c => `<option value="${c.ctid}">${esc(c.broker || 'cTrader')} · login ${esc(c.login)} · ${c.real ? 'REAL' : 'DEMO'} (${c.ctid})</option>`).join('');
          if (!r.cuentas.length) $('opCTm').textContent = `El token no tiene cuentas ${m === 'real' ? 'reales (live)' : 'demo'}.`;
          if (!r.trading) $('opCTm').textContent = 'El token es de SOLO LECTURA: vuelve a autorizar cTrader para poder operar.';
          f.cuenta_ctid.value = a.cuenta_ctid || '';
          cargarSimbolos();
        } catch (e) { f.cuenta_ctid.innerHTML = '<option value="">—</option>'; $('opCTm').textContent = e.message; }
      };
      f.cuenta_ctid.onchange = cargarSimbolos;
      f.simbolo_broker.onchange = () => { const s = d.simbolos_sugeridos[f.simbolo_broker.value.toUpperCase()]; if (s && !f.instrumento.dataset.tocado) f.instrumento.value = s; };
      f.instrumento.oninput = () => { f.instrumento.dataset.tocado = 1; };
      if (ct) cargarCuentas();
      f.onsubmit = async ev => { ev.preventDefault(); const aj = {}; new FormData(f).forEach((x, key) => aj[key] = x);
        f.querySelectorAll('input[type=checkbox]').forEach(c => aj[c.name] = c.checked);
        if (f.broker.value !== 'ctrader') { delete aj.cuenta_ctid; }
        try { await api('/api/tq/operador/ajustes', { modalidad: m, ajustes: aj }); msg($('opFm'), 'Configuración guardada.', 'ok'); modoBot(); setTimeout(RENDER.operator, 700); } catch (e) { msg($('opFm'), e.message, 'err'); } };
      v.querySelectorAll('[data-est]').forEach(x => x.onclick = async () => {
        const est = x.dataset.est, datos = { modalidad: m, estado: est };
        if (est === 'emergencia' && !confirm(`¿PARADA DE EMERGENCIA en ${NOMBRE_MOD[m]}? No abrirá operaciones y cerrará sus posiciones.`)) return;
        if (est === 'activo' && m === 'demo' && !confirm('Vas a iniciar el bot en tu cuenta DEMO del broker. ¿Confirmas?')) return;
        if (est === 'activo' && m === 'real') {
          datos.clave = ($('opClaveReal') || {}).value || '';
          if (!datos.clave) return msg($('opM'), 'Escribe tu contraseña para iniciar el bot REAL.', 'err');
          if (!confirm('⚠ Vas a operar con DINERO REAL en tu cuenta cTrader live. ¿Confirmas?')) return;
        }
        try { await api('/api/tq/operador/estado', datos); modoBot(); RENDER.operator(); } catch (e) { msg($('opM'), e.message, 'err'); }
      });
      if ($('opRealF')) $('opRealF').onsubmit = async ev => { ev.preventDefault(); const F = ev.target;
        try { await api('/api/tq/operador/real', { frase: F.frase.value, clave: F.clave.value }); msg($('opRm'), 'Cuenta REAL habilitada.', 'ok'); setTimeout(RENDER.operator, 800); } catch (e) { msg($('opRm'), e.message, 'err'); } };
      if ($('opRealOff')) $('opRealOff').onclick = async () => { try { await api('/api/tq/operador/real', { deshabilitar: true }); RENDER.operator(); } catch (e) { msg($('opRm'), e.message, 'err'); } };
      $('opCiclo').onclick = async () => { msg($('opM'), 'Ejecutando ciclo…'); try { const r = await api('/api/tq/operador/ciclo', { modalidad: m }); msg($('opM'), 'Ciclo: ' + r.ciclo.accion + (r.ciclo.cerradas ? ` · ${r.ciclo.cerradas} cerradas` : '') + (r.ciclo.error ? ' · ' + r.ciclo.error : ''), 'ok'); tabla('decisiones'); sondearAlertas(); } catch (e) { msg($('opM'), e.message, 'err'); } };
      const tabla = async t => {
        $('opTabs').querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.t === t));
        const T = $('opT'); T.innerHTML = cargando();
        if (t === 'decisiones') {
          const r = await api('/api/tq/operador/decisiones?modalidad=' + m);
          T.innerHTML = `<div class="tq-scroll"><table class="tq-table"><tr><th>Fecha</th><th>Cuenta</th><th>Instrumento</th><th>Acción</th><th>Motivo</th><th>Controles</th></tr>${r.decisiones.map(x => `<tr><td>${fecha(x.ts)}</td><td>${badge(NOMBRE_MOD[x.modalidad], x.modalidad === 'simulacion' ? 'sim' : x.modalidad)}</td><td>${esc(x.instrumento || '')}</td><td>${esc(x.accion)}</td><td class="muted">${esc(x.motivo)}</td><td>${x.controles.length ? x.controles.filter(c => !c.ok).map(c => badge(c.control, 'err')).join(' ') || badge('todos OK', 'ok') : ''}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Sin decisiones todavía.</td></tr>'}</table></div>`;
        } else {
          const r = await api('/api/tq/operador/operaciones?modalidad=' + m + (t === 'abiertas' ? '&estado=abierta' : ''));
          T.innerHTML = `<div class="tq-scroll"><table class="tq-table"><tr><th>#</th><th>Cuenta</th><th>Instrumento</th><th>Tipo</th><th>Dir.</th><th>Volumen / monto</th><th>Entrada</th><th>Stop / Obj.</th><th>Riesgo</th><th>Estado</th><th>Resultado</th><th>R</th><th>Motivo</th></tr>${r.operaciones.map(o => `<tr><td>${o.id}</td><td>${badge(NOMBRE_MOD[o.modalidad] + (o.cuenta && o.cuenta !== o.modalidad ? ' ' + o.cuenta : ''), o.modalidad === 'simulacion' ? 'sim' : o.modalidad)}</td><td>${esc(o.simbolo_broker || o.instrumento)}</td><td>${esc(o.tipo)}</td><td>${esc(o.direccion)}</td><td>${o.volumen ? num(o.volumen / 100, 2) + ' u' : num(o.monto)}</td><td>${num(o.precio_entrada, 5)}</td><td>${num(o.stop, 5)} / ${num(o.objetivo, 5)}</td><td>${num(o.riesgo_importe)} ${esc(o.moneda || '')}</td><td>${esc(o.estado)}</td><td class="${(o.resultado || 0) >= 0 ? 'up' : ''}">${num(o.resultado)}</td><td>${num(o.r, 2)}</td><td class="muted">${esc(o.motivo_cierre || '')}</td></tr>`).join('') || '<tr><td colspan="13" class="muted">Sin operaciones en esta cuenta.</td></tr>'}</table></div>`;
        }
      };
      $('opTabs').querySelectorAll('button').forEach(x => x.onclick = () => tabla(x.dataset.t));
      tabla('abiertas');
    } catch (e) { $('opL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== HISTORIAL
  RENDER.history = async function () {
    const v = $('view-history');
    const st = v._s || (v._s = { tipo: 'analisis', ver: 'normal', sel: new Set() });
    st.sel.clear();
    v.innerHTML = `<div class="head"><div class="eyebrow">Registro</div><h1>Historial</h1><div class="muted">Ocultar o archivar NO borra nada ni altera métricas: el registro original se conserva y puede restaurarse.</div></div>
      <div class="card" style="margin-bottom:12px"><div class="tq-tabs" id="hiT"></div><div class="tq-row">
      <select class="field" id="hiVer" style="width:auto"><option value="normal">Vista normal</option><option value="ocultos">Ocultos</option><option value="archivados">Archivados</option><option value="todo">Todo</option></select>
      <button class="btn" data-h="ocultar">Ocultar seleccionados</button><button class="btn" data-h="archivar">Archivar</button><button class="btn" data-h="restaurar">Restaurar visibilidad</button>
      ${TQ.usuario.admin ? '<button class="btn" id="hiDel" style="border-color:#7a3b3b">Eliminar permanentemente…</button>' : ''}</div><div id="hiM"></div></div><div class="card"><div id="hiL">${cargando()}</div></div>`;
    $('hiVer').value = st.ver;
    $('hiVer').onchange = () => { st.ver = $('hiVer').value; RENDER.history(); };
    try {
      const d = await api(`/api/tq/historial?tipo=${st.tipo}&ver=${st.ver}`);
      $('hiT').innerHTML = Object.entries(d.tipos).map(([k, t]) => `<button class="${k === st.tipo ? 'on' : ''}" data-tipo="${k}">${esc(t)}</button>`).join('');
      $('hiT').querySelectorAll('button').forEach(b => b.onclick = () => { st.tipo = b.dataset.tipo; RENDER.history(); });
      const cols = d.filas.length ? Object.keys(d.filas[0]).filter(k => !['usuario_id', 'datos', 'controles', 'motores', 'resultado_json', 'clave_dedupe', 'fuente_datos', 'detalle'].includes(k)).slice(0, 11) : [];
      const val = x => (typeof x === 'number' && x > 1.6e9 && x < 4e9) ? fecha(x) : (x && typeof x === 'object') ? JSON.stringify(x).slice(0, 80) : (typeof x === 'number' ? num(x, 5) : String(x == null ? '' : x).slice(0, 120));
      $('hiL').innerHTML = d.filas.length ? `<div class="tq-scroll"><table class="tq-table"><tr><th></th>${cols.map(c => `<th>${esc(c)}</th>`).join('')}${st.tipo === 'analisis' ? '<th></th>' : ''}</tr>
        ${d.filas.map(f => `<tr><td><input type="checkbox" data-id="${f.id}" style="width:auto"></td>${cols.map(c => `<td>${c === 'modalidad' ? badge(f[c], f[c] === 'simulacion' ? 'sim' : f[c]) : esc(val(f[c]))}</td>`).join('')}
        ${st.tipo === 'analisis' ? `<td><button class="tq-link" data-ver="${f.id}">abrir</button></td>` : ''}</tr>`).join('')}</table></div><div id="hiDet"></div>` : '<div class="muted">Sin registros en esta vista.</div>';
      $('hiL').querySelectorAll('input[data-id]').forEach(c => c.onchange = () => c.checked ? st.sel.add(c.dataset.id) : st.sel.delete(c.dataset.id));
      $('hiL').querySelectorAll('[data-ver]').forEach(b => b.onclick = async () => { const r = await api('/api/tq/analisis?id=' + b.dataset.ver); $('hiDet').innerHTML = '<div style="margin-top:14px">' + pintarAnalisis(r.resultado, r.id) + '</div>'; enlazarAnalisis($('hiDet')); });
      v.querySelectorAll('[data-h]').forEach(b => b.onclick = async () => {
        if (!st.sel.size) return msg($('hiM'), 'Selecciona al menos un registro.', 'err');
        try { const r = await api('/api/tq/historial/' + b.dataset.h, { tipo: st.tipo, ids: Array.from(st.sel) }); msg($('hiM'), r.n + ' registro(s) actualizados. Nada fue borrado.', 'ok'); setTimeout(RENDER.history, 600); } catch (e) { msg($('hiM'), e.message, 'err'); }
      });
      const del = $('hiDel');
      if (del) del.onclick = async () => {
        if (st.tipo !== 'analisis') return msg($('hiM'), 'Solo los análisis archivados pueden eliminarse permanentemente. Operaciones, alertas y auditoría se conservan siempre.', 'err');
        const frase = prompt('Eliminación PERMANENTE de análisis archivados. Escribe: ELIMINAR PERMANENTEMENTE');
        if (!frase) return;
        try { const r = await api('/api/tq/historial/eliminar_permanente', { ids: Array.from(st.sel), frase }); msg($('hiM'), r.n + ' análisis eliminados (queda constancia en auditoría).', 'ok'); setTimeout(RENDER.history, 600); } catch (e) { msg($('hiM'), e.message, 'err'); }
      };
    } catch (e) { $('hiL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== PREFERENCIAS
  RENDER.settings = async function () {
    const v = $('view-settings');
    v.innerHTML = `<div class="head"><div class="eyebrow">Preferencias</div><h1>Preferencias, sonidos y notificaciones</h1></div><div id="seL">${cargando()}</div>`;
    try {
      const { preferencias: p } = await api('/api/cuenta/preferencias');
      const s = p.sonidos;
      $('seL').innerHTML = `<div class="grid two"><form class="card" id="seF1"><b>General</b>
        <div class="formrow" style="margin-top:10px"><label class="label">Zona horaria (IANA)</label><input class="field" name="zona" value="${esc(p.zona)}"></div>
        <div class="formrow"><label class="label">Horizonte por defecto</label><select class="field" name="horizonte">${['scalping', 'intradia', 'corto', 'mediano', 'largo'].map(x => `<option ${x === p.horizonte ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
        <div class="formrow"><label class="label">Capital de referencia (análisis)</label><input class="field" name="capital" type="number" step="any" value="${esc(p.riesgo.capital)}"></div>
        <div class="formrow"><label class="label">Riesgo por operación (%)</label><input class="field" name="riesgo_pct" type="number" step="any" value="${esc(p.riesgo.riesgo_pct)}"></div>
        <label class="tq-chk"><input type="checkbox" name="telegram" ${p.notificaciones.telegram ? 'checked' : ''}> Enviar alertas importantes a Telegram</label>
        <button class="btn primary">Guardar</button><div id="seM1"></div></form>
        <form class="card" id="seF2"><b>Sonidos de alertas</b><p class="muted">El navegador exige un toque antes de reproducir sonido: aparecerá un botón para activarlos.</p>
        <label class="tq-chk"><input type="checkbox" name="activado" ${s.activado ? 'checked' : ''}> Activar sonidos</label>
        <div class="formrow"><label class="label">Volumen</label><input class="field" name="volumen" type="range" min="0" max="1" step="0.05" value="${esc(s.volumen)}"></div>
        ${[['oportunidad', 'Oportunidad nueva'], ['entrada', 'Entrada nueva'], ['operacion', 'Operación cerrada'], ['critica', 'Alertas críticas']].map(([k, t]) => `<label class="tq-chk"><input type="checkbox" name="${k}" ${s[k] ? 'checked' : ''}> ${t}</label>`).join('')}
        <div class="tq-row"><button class="btn primary">Guardar</button><button type="button" class="btn" id="seProbar">Probar sonido</button></div><div id="seM2"></div></form></div>`;
      $('seF1').onsubmit = async ev => { ev.preventDefault(); const f = ev.target;
        try { const r = await api('/api/cuenta/preferencias', { zona: f.zona.value, horizonte: f.horizonte.value, riesgo: { capital: f.capital.value, riesgo_pct: f.riesgo_pct.value }, notificaciones: { telegram: f.telegram.checked } });
          TQ.preferencias = r.preferencias; msg($('seM1'), 'Guardado.', 'ok'); } catch (e) { msg($('seM1'), e.message, 'err'); } };
      $('seF2').onsubmit = async ev => { ev.preventDefault(); const f = ev.target;
        const o = { activado: f.activado.checked, volumen: Number(f.volumen.value) }; ['oportunidad', 'entrada', 'operacion', 'critica'].forEach(k => o[k] = f[k].checked);
        try { const r = await api('/api/cuenta/preferencias', { sonidos: o }); TQ.preferencias = r.preferencias; msg($('seM2'), 'Guardado.', 'ok'); botonSonido(); } catch (e) { msg($('seM2'), e.message, 'err'); } };
      $('seProbar').onclick = () => { try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); audio.resume(); } catch (e) {}
        const prev = TQ.preferencias.sonidos; TQ.preferencias.sonidos = Object.assign({}, prev, { activado: true, volumen: Number($('seF2').volumen.value) }); tono(PATRONES.oportunidad); TQ.preferencias.sonidos = prev; };
    } catch (e) { $('seL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== MI CUENTA
  RENDER.account = async function () {
    const v = $('view-account');
    const u = TQ.usuario;
    v.innerHTML = `<div class="head"><div class="eyebrow">Mi cuenta</div><h1>${esc(u.nombre)}</h1><div class="muted">${esc(u.correo)} · ${esc(u.rol)} · alta ${fecha(u.creado_ts)}</div></div>
      <div class="grid two"><form class="card" id="acP"><b>Perfil</b><div class="formrow" style="margin-top:10px"><label class="label">Nombre</label><input class="field" name="nombre" value="${esc(u.nombre)}" maxlength="80"></div>
        <div class="formrow"><label class="label">Correo</label><input class="field" value="${esc(u.correo)}" disabled></div><button class="btn primary">Guardar</button><div id="acPm"></div></form>
      <form class="card" id="acC"><b>Seguridad · cambiar contraseña</b>
        <div class="formrow" style="margin-top:10px"><label class="label">Contraseña actual</label><input class="field" name="actual" type="password" autocomplete="current-password" required></div>
        <div class="formrow"><label class="label">Nueva contraseña</label><input class="field" name="nueva" type="password" autocomplete="new-password" required minlength="10"></div>
        <div class="formrow"><label class="label">Confirmar</label><input class="field" name="nueva2" type="password" autocomplete="new-password" required></div><button class="btn primary">Cambiar</button><div id="acCm"></div></form></div>
      <div class="grid two" style="margin-top:14px"><div class="card"><div class="tq-row" style="justify-content:space-between"><b>Sesiones activas</b><button class="btn" id="acTodas">Cerrar las demás</button></div><div id="acS">${cargando()}</div></div>
      <div class="card"><b>Registro de seguridad</b><div id="acE" style="max-height:320px;overflow:auto">${cargando()}</div></div></div>
      <div class="card" style="margin-top:14px"><b>Integraciones personales, preferencias y notificaciones</b><div class="tq-row" style="margin-top:8px"><button class="btn" onclick="go('brokers')">Integraciones</button><button class="btn" onclick="go('settings')">Preferencias y sonidos</button><button class="btn" onclick="go('inteligencia')">Nivel de inteligencia</button></div></div>`;
    $('acP').onsubmit = async ev => { ev.preventDefault(); try { const r = await api('/api/cuenta/perfil', { nombre: ev.target.nombre.value }); TQ.usuario = r.usuario; $('tqUser').textContent = r.usuario.nombre; msg($('acPm'), 'Guardado.', 'ok'); } catch (e) { msg($('acPm'), e.message, 'err'); } };
    $('acC').onsubmit = async ev => { ev.preventDefault(); const f = ev.target; try { const r = await api('/api/auth/cambiar_clave', { actual: f.actual.value, nueva: f.nueva.value, nueva2: f.nueva2.value }); f.reset(); msg($('acCm'), r.mensaje, 'ok'); } catch (e) { msg($('acCm'), e.message, 'err'); } };
    const ses = async () => { const d = await api('/api/auth/sesiones');
      $('acS').innerHTML = `<table class="tq-table">${d.sesiones.map(s => `<tr><td>${s.actual ? badge('esta', 'ok') : ''} ${esc((s.agente || '').slice(0, 60))}<br><span class="muted">${esc(s.ip)} · última ${fecha(s.ultimo_ts)}</span></td><td>${s.actual ? '' : `<button class="tq-link" data-ses="${esc(s.id)}">Cerrar</button>`}</td></tr>`).join('')}</table>`;
      $('acS').querySelectorAll('[data-ses]').forEach(b => b.onclick = async () => { await api('/api/auth/sesiones/cerrar', { id: b.dataset.ses }); ses(); }); };
    $('acTodas').onclick = async () => { await api('/api/auth/logout_todas', {}); ses(); };
    ses();
    const ev = await api('/api/cuenta/eventos');
    $('acE').innerHTML = `<table class="tq-table">${ev.eventos.map(e => `<tr><td>${fecha(e.ts)}</td><td>${esc(e.tipo.replace(/_/g, ' '))}</td><td class="muted">${esc(e.ip || '')}</td></tr>`).join('')}</table>`;
  };

  // =========================================================================== ADMINISTRACIÓN
  const ESTADO_U = { activo: ['activo', 'ok'], pendiente_aprobacion: ['pendiente de aprobación', 'warn'], sin_confirmar: ['correo sin confirmar', 'warn'], suspendido: ['suspendido', 'err'] };
  RENDER.admin = async function () {
    const v = $('view-admin');
    if (!v) return;
    v.innerHTML = `<div class="head"><div class="eyebrow">Acceso privilegiado</div><h1>Administración</h1>
      <div class="muted">Solicitudes de cuenta, aprobación con correo de aceptación, suspensión y administradores. Todo queda en auditoría.</div></div><div id="adL">${cargando()}</div>`;
    try {
      const d = await api('/api/admin/usuarios');
      const yo = TQ.usuario;
      const acciones = u => {
        const b = (a, t, c) => `<button class="btn" style="padding:5px 8px;font-size:11.5px;${c || ''}" data-ad="${a}" data-id="${u.id}">${t}</button>`;
        if (u.rol === 'propietario') return '<span class="muted">Propietario (acceso total)</span>';
        if (u.id === yo.id) return '<span class="muted">Tu cuenta</span>';
        const out = [];
        if (u.estado === 'pendiente_aprobacion' || u.estado === 'sin_confirmar') out.push(b('aprobar', '✔ Aprobar y enviar aceptación', 'border-color:#2f6b55'));
        if (u.estado === 'pendiente_aprobacion') out.push(b('rechazar', '✖ Rechazar', 'border-color:#7a3b3b'));
        if (u.estado === 'sin_confirmar') out.push(b('reenviar', 'Reenviar confirmación'));
        if (u.estado === 'activo') out.push(b('suspender', 'Suspender', 'border-color:#7a3b3b'));
        if (u.estado === 'suspendido') out.push(b('reactivar', 'Reactivar'));
        if (yo.rol === 'propietario' && u.estado === 'activo') out.push(u.admin ? b('quitar_admin', 'Quitar administrador') : b('hacer_admin', '★ Hacer administrador'));
        if (u.sesiones) out.push(b('cerrar_sesiones', `Cerrar sesiones (${u.sesiones})`));
        if (u.bloqueo_temporal) out.push(b('desbloquear', 'Quitar bloqueo por intentos'));
        return out.join(' ');
      };
      $('adL').innerHTML = `<div class="tq-kpis"><div class="tq-kpi"><small>Cuentas</small><b>${d.total}</b></div>
        <div class="tq-kpi"><small>Solicitudes pendientes</small><b class="${d.pendientes ? 'up' : ''}">${d.pendientes}</b></div>
        <div class="tq-kpi"><small>Envío de correo</small><b>${d.correo_configurado ? 'Configurado' : 'Sin configurar'}</b></div>
        <div class="tq-kpi"><small>Tu rol</small><b>${yo.rol === 'propietario' ? 'Propietario' : 'Administrador'}</b></div></div>
        <div class="grid two" style="margin-bottom:14px"><div class="card"><b>Registro de cuentas nuevas</b>
          <label class="tq-chk" style="margin-top:10px"><input type="checkbox" id="adApr" ${d.requiere_aprobacion ? 'checked' : ''}> Las cuentas nuevas necesitan mi aprobación</label>
          <div class="muted">Al aprobar, TITAN envía al usuario un correo de aceptación. Las solicitudes nuevas te llegan como alerta (y por Telegram y correo si están configurados).</div><div id="adM1"></div></div>
          <div class="card"><b>Envío de correo</b> ${d.correo_configurado ? badge('configurado', 'ok') : badge('sin configurar', 'warn')}
          <div class="muted" style="margin-top:8px">Hotmail/Outlook.com personal no sirve para ENVIAR (Microsoft desactivó el SMTP con contraseña). Tu correo Hotmail sí puede RECIBIR.
          Opción recomendada: Gmail → activa la verificación en 2 pasos → crea una «contraseña de aplicación» → pégala en Integraciones → Correo (SMTP) con proveedor «gmail».</div>
          <div class="tq-row" style="margin-top:10px"><button class="btn primary" onclick="go('brokers')">Configurar correo</button><button class="btn" id="adPrueba">Enviar correo de prueba a ${esc(yo.correo)}</button></div><div id="adM2"></div></div></div>
        <div class="card"><b>Cuentas y solicitudes</b><div class="tq-scroll"><table class="tq-table"><tr><th>Usuario</th><th>Rol</th><th>Estado</th><th>Alta</th><th>Último acceso</th><th>Acciones</th></tr>
        ${d.usuarios.map(u => `<tr><td><b>${esc(u.nombre)}</b><br><span class="muted">${esc(u.correo)}</span></td>
          <td>${u.rol === 'propietario' ? badge('propietario', 'ok') : u.admin ? badge('administrador', 'ok') : badge('usuario')}</td>
          <td>${badge(ESTADO_U[u.estado][0], ESTADO_U[u.estado][1])}${u.bloqueo_temporal ? ' ' + badge('bloqueo por intentos', 'err') : ''}</td>
          <td>${fecha(u.creado_ts)}</td><td>${fecha(u.ultimo_acceso_ts)}</td><td><div class="tq-row" style="gap:5px">${acciones(u)}</div></td></tr>`).join('')}</table></div><div id="adM3"></div></div>`;
      $('adApr').onchange = async () => { try { await api('/api/admin/config', { requiere_aprobacion: $('adApr').checked }); msg($('adM1'), 'Guardado.', 'ok'); } catch (e) { msg($('adM1'), e.message, 'err'); } };
      $('adPrueba').onclick = async () => { msg($('adM2'), 'Enviando…'); try { const r = await api('/api/admin/correo_prueba', {}); msg($('adM2'), r.mensaje, 'ok'); } catch (e) { msg($('adM2'), e.message, 'err'); } };
      $('adL').querySelectorAll('[data-ad]').forEach(b => b.onclick = async () => {
        const a = b.dataset.ad;
        if (['rechazar', 'suspender', 'hacer_admin'].includes(a) && !confirm('¿Confirmas: ' + b.textContent.trim() + '?')) return;
        b.disabled = true;
        try {
          const r = await api('/api/admin/' + a, { id: Number(b.dataset.id) });
          let t = 'Hecho.';
          if (r.correo === 'smtp') t = 'Hecho. Correo enviado al usuario.';
          else if (r.correo === 'archivo') t = 'Hecho. El correo no está configurado: el mensaje quedó guardado en el dispositivo (bash titan.sh registro).';
          else if (r.correo === 'error') t = 'Hecho, pero el correo falló: ' + (r.aviso_correo || '');
          await RENDER.admin(); msg($('adM3'), t, r.correo === 'error' ? 'err' : 'ok');
        } catch (e) { msg($('adM3'), e.message, 'err'); b.disabled = false; }
      });
    } catch (e) { $('adL').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  };

  // =========================================================================== arranque
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciarAcceso); else iniciarAcceso();
})();
