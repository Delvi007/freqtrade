/* TITAN QUANT — Centro de servidores (C8), Centro universal de brokers (C3/C4), Inteligencia autónoma (C6) y laboratorio
   cuántico (C7), más el INTERRUPTOR universal de la plataforma: cada casilla de activar/desactivar se convierte en un switch
   pequeño (verde ON / rojo OFF) con su indicación ON/OFF encima. Todo texto externo se escapa con esc(). */
(function () {
  'use strict';
  let H;
  const T = {};

  // =========================================================================== INTERRUPTOR UNIVERSAL
  function mejorar(raiz) {
    (raiz || document).querySelectorAll('input[type=checkbox]:not([data-sw])').forEach(inp => {
      inp.dataset.sw = '1';
      const caja = document.createElement('span');
      caja.className = 'tq-sw';
      const txt = document.createElement('small');
      txt.className = 'tq-sw-t';
      inp.parentNode.insertBefore(caja, inp);
      caja.appendChild(txt);
      caja.appendChild(inp);
      const pinta = () => { txt.textContent = inp.checked ? 'ON' : 'OFF'; caja.classList.toggle('on', inp.checked); caja.classList.toggle('dis', inp.disabled); };
      inp.addEventListener('change', pinta);
      const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'checked');
      Object.defineProperty(inp, 'checked', { get() { return desc.get.call(this); }, set(v) { desc.set.call(this, v); pinta(); }, configurable: true });
      pinta();
    });
  }
  const obs = new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) mejorar(n); });
  document.addEventListener('DOMContentLoaded', () => { mejorar(document); obs.observe(document.body, { childList: true, subtree: true }); });
  if (document.body) { mejorar(document); obs.observe(document.body, { childList: true, subtree: true }); }
  const sw = (attrs, on, dis) => `<input type="checkbox" ${attrs} ${on ? 'checked' : ''} ${dis ? 'disabled' : ''}>`;

  function modal(html, alCerrar) {
    const f = document.createElement('div');
    f.className = 'tq-modal';
    f.innerHTML = `<div class="card tq-modal-c tqc-modal">${html}<div style="text-align:right;margin-top:12px"><button class="btn" data-cerrar>Cerrar</button></div></div>`;
    document.body.appendChild(f);
    const cerrar = () => { f.remove(); alCerrar && alCerrar(); };
    f.onclick = e => { if (e.target === f || e.target.dataset.cerrar !== undefined) cerrar(); };
    return f;
  }
  const hace = ts => { if (!ts) return '—'; const s = Date.now() / 1000 - ts; return s < 60 ? Math.round(s) + ' s' : s < 3600 ? Math.round(s / 60) + ' min' : s < 86400 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' d'; };
  const LED_N = ['Ejecución', 'Datos', 'Inteligencia', 'Conectividad', 'Aprendizaje'];

  // =========================================================================== CENTRO DE SERVIDORES (C8)
  let filtroTipo = 'todos', filtroEstado = 'todos', filtroEv = '', tServ = null;
  T.servidores = async function (v) {
    const { esc } = H;
    v.innerHTML = `<div class="head"><div class="eyebrow">TITAN QUANT ENGINE SERVER CENTER</div><h1>Centro de servidores</h1>
      <div class="muted">Cada motor, proceso y broker como un servidor. Las 5 luces muestran estados REALES: ${LED_N.map((n, i) => `<b>${i + 1}</b> ${n}`).join(' · ')}.
      Verde = funcionando · verde parpadeando = procesando ahora · ámbar = en espera/aviso · rojo = error · gris = no aplica. Doble clic en un servidor para su panel técnico.</div></div>
      <div id="tqcSis"></div>
      <div class="tq-row" style="margin:8px 0 12px;gap:8px;flex-wrap:wrap">
        <select class="field" id="tqcFT" style="width:auto">${[['todos', 'Todos'], ['proceso', 'Procesos'], ['motor', 'Motores (23)'], ['broker', 'Brokers']].map(([k, t]) => `<option value="${k}" ${k === filtroTipo ? 'selected' : ''}>${t}</option>`).join('')}</select>
        <select class="field" id="tqcFE" style="width:auto">${[['todos', 'Cualquier estado'], ['error', 'Con error'], ['advertencia', 'Con aviso'], ['actividad', 'Procesando ahora']].map(([k, t]) => `<option value="${k}" ${k === filtroEstado ? 'selected' : ''}>${t}</option>`).join('')}</select>
      </div>
      <div class="tqc-racks" id="tqcRacks">${H.cargando('Leyendo el estado real de los servidores…')}</div>
      <div class="card" style="margin-top:14px"><div class="tq-row" style="justify-content:space-between"><b>Registro de eventos en tiempo real</b>
        <input class="field" id="tqcEvF" placeholder="filtrar (proceso, tipo, texto)" value="${esc(filtroEv)}" style="max-width:260px"></div><div id="tqcEv" class="tqc-ev"></div></div>`;
    v.querySelector('#tqcFT').onchange = e => { filtroTipo = e.target.value; cargarServ(); };
    v.querySelector('#tqcFE').onchange = e => { filtroEstado = e.target.value; cargarServ(); };
    v.querySelector('#tqcEvF').oninput = e => { filtroEv = e.target.value.toLowerCase(); cargarServ(); };
    clearInterval(tServ);
    tServ = setInterval(() => { if (!document.getElementById('tqcRacks')) return clearInterval(tServ); if (!document.hidden) cargarServ(); }, 3000);
    cargarServ();
  };

  async function cargarServ() {
    const { api, esc, num } = H;
    const el = document.getElementById('tqcRacks'); if (!el) return;
    let d;
    try { d = await api('/api/tq/servidores'); } catch (e) { el.innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; return; }
    const s = d.sistema || {};
    document.getElementById('tqcSis').innerHTML = `<div class="tq-kpis">
      <div class="tq-kpi"><small>CPU del equipo</small><b>${s.cpu_sistema == null ? '—' : num(s.cpu_sistema, 0) + ' %'}</b><small>${s.nucleos || '—'} núcleos lógicos</small></div>
      <div class="tq-kpi"><small>RAM del equipo</small><b>${s.ram_sistema == null ? '—' : num(s.ram_sistema, 0) + ' %'}</b><small>TITAN usa ${s.ram_proceso_mb == null ? '—' : num(s.ram_proceso_mb, 0) + ' MB'}</small></div>
      <div class="tq-kpi"><small>Hilos de TITAN</small><b>${s.hilos || '—'}</b><small>activo desde hace ${hace(d.inicio_ts)}</small></div>
      <div class="tq-kpi"><small>Gestión de carga</small><b>${d.pausa_por_carga ? 'investigación en pausa' : 'normal'}</b><small>${d.pausa_por_carga ? 'CPU/RAM altas: se protege lo crítico' : 'prioridad: riesgo y ejecución primero'}</small></div></div>`;
    let lista = d.servidores.filter(x => filtroTipo === 'todos' || x.tipo === filtroTipo);
    if (filtroEstado !== 'todos') lista = lista.filter(x => x.leds.some(l => l.estado === filtroEstado));
    el.innerHTML = lista.map(x => `<div class="tqc-rack" data-id="${esc(x.id)}" title="Doble clic: panel técnico">
      <div class="tqc-cab"><span class="tqc-tipo">${x.tipo === 'motor' ? '#' + x.numero : x.tipo === 'proceso' ? 'P' + x.prioridad : 'BRK'}</span><b>${esc(x.nombre)}</b><small>v${esc(x.version)}</small></div>
      <div class="tqc-leds">${x.leds.map((l, i) => `<span class="tqc-led ${esc(l.estado)}" title="${LED_N[i]}: ${esc(l.texto)}"></span>`).join('')}</div>
      <div class="tqc-pie">${x.tipo === 'proceso' ? `${sw(`data-proc="${esc(x.id.split(':')[1])}"`, x.deseado && x.vivo)}<small>${x.resumen.cpu_pct == null ? '' : 'CPU ' + num(x.resumen.cpu_pct, 1) + ' %'}</small>`
        : x.tipo === 'motor' ? `<small>${x.resumen.ejecuciones} ejec · ${x.resumen.duracion_ms == null ? '—' : x.resumen.duracion_ms + ' ms'} · ${hace(x.resumen.ultimo_ts)}</small>`
        : `<small>${esc(x.resumen.conector)} · ${esc(x.resumen.entorno || '')}</small>`}</div>
      <div class="tqc-rejilla"></div></div>`).join('') || '<div class="muted">Ningún servidor con ese filtro.</div>';
    el.querySelectorAll('.tqc-rack').forEach(r => r.ondblclick = () => detalleServ(r.dataset.id));
    el.querySelectorAll('input[data-proc]').forEach(i => i.onchange = async () => {
      try { await api('/api/tq/servidores', { proceso: i.dataset.proc, accion: i.checked ? 'iniciar' : 'detener' }); } catch (e) { alert(e.message); }
      cargarServ();
    });
    const ev = (d.eventos || []).filter(e => !filtroEv || JSON.stringify(e).toLowerCase().includes(filtroEv));
    document.getElementById('tqcEv').innerHTML = ev.map(e => `<div><span class="muted">${new Date(e.ts * 1000).toLocaleTimeString('es')}</span> <b>${esc(e.proceso)}</b> <span class="tq-b ${e.tipo === 'error' ? 'err' : e.tipo === 'reinicio' || e.tipo === 'carga_alta' ? 'warn' : ''}">${esc(e.tipo)}</span> ${esc(e.detalle)}</div>`).join('') || '<div class="muted">Sin eventos todavía.</div>';
  }

  async function detalleServ(id) {
    const { api, esc, num } = H;
    let d;
    try { d = (await api('/api/tq/servidores?id=' + encodeURIComponent(id))).detalle; } catch (e) { alert(e.message); return; }
    let html = '';
    if (d.tipo === 'motor') {
      const f = d.ficha, e = d.estado || {};
      html = `<b style="font-size:16px">#${f.numero} ${esc(f.nombre)}</b> <span class="muted">v${esc(d.identidad.version)} · ${esc(f.id)}</span>
        <table class="tq-table" style="margin-top:10px"><tr><td>Función</td><td>${esc(f.objetivo)}</td></tr><tr><td>Algoritmos</td><td>${esc(f.metodos)}</td></tr>
        <tr><td>Entradas</td><td>${esc((f.entradas || []).join(', '))}</td></tr><tr><td>Salidas</td><td>${esc((f.salidas || []).join(', '))}</td></tr>
        <tr><td>Se comunica con</td><td>${esc((f.dependencias || []).join(', ') || '—')}</td></tr><tr><td>Archivo</td><td><code>${esc(d.archivo || '')}</code></td></tr>
        <tr><td>Consumo</td><td>${esc(f.consumo)} · ${esc(d.recursos)}</td></tr><tr><td>Ejecuciones / errores</td><td>${num(e.ejecuciones || 0, 0)} / ${num(e.errores || 0, 0)}</td></tr>
        <tr><td>Última ejecución</td><td>${e.ts ? new Date(e.ts * 1000).toLocaleString('es') + ' · ' + esc(e.estado) + ' · ' + (e.duracion_ms ?? '—') + ' ms (latencia)' : 'aún no'}</td></tr>
        <tr><td>Último error</td><td>${esc(e.error || '—')}</td></tr><tr><td>Tiempo activo</td><td>${hace(Date.now() / 1000 - d.tiempo_activo_s)}</td></tr></table>`;
    } else if (d.tipo === 'proceso') {
      const p = d.estado;
      html = `<b style="font-size:16px">${esc(p.nombre)}</b> <span class="muted">prioridad ${p.prioridad} (${p.prioridad === 1 ? 'crítico' : p.prioridad === 2 ? 'datos' : 'investigación'})</span>
        <p class="muted">${esc(p.funcion)}</p>
        <div class="tq-row" style="gap:8px;margin:8px 0">${sw(`data-pd="${esc(p.id)}"`, p.deseado && p.vivo)}<span class="muted">encendido</span>
          <button class="btn" data-pa="pausar">⏸ Pausar</button><button class="btn" data-pa="reanudar">▶ Reanudar</button></div>
        <table class="tq-table"><tr><td>Estado</td><td>${p.vivo ? 'en marcha' : 'detenido'}${p.pausado ? ' · pausado' : ''}</td></tr><tr><td>CPU</td><td>${p.cpu_pct == null ? '—' : num(p.cpu_pct, 1) + ' %'} · ${p.hilos || 0} hilos</td></tr>
        <tr><td>RAM del proceso TITAN</td><td>${d.sistema.ram_proceso_mb == null ? '—' : num(d.sistema.ram_proceso_mb, 0) + ' MB'}</td></tr><tr><td>GPU</td><td>no usada (sin GPU CUDA compatible)</td></tr>
        <tr><td>Reinicios automáticos</td><td>${p.reinicios}</td></tr><tr><td>Error</td><td>${esc(p.error || '—')}</td></tr></table>
        <b style="display:block;margin-top:10px">Eventos</b><div class="tqc-ev">${(d.eventos || []).map(e => `<div><span class="muted">${new Date(e.ts * 1000).toLocaleString('es')}</span> ${esc(e.tipo)} · ${esc(e.detalle)}</div>`).join('') || '<div class="muted">Sin eventos.</div>'}</div>`;
    } else {
      const b = d.identidad || {};
      html = `<b style="font-size:16px">${esc(b.nombre)}</b><table class="tq-table" style="margin-top:10px"><tr><td>APIs</td><td>${esc(b.apis)}</td></tr><tr><td>Autenticación</td><td>${esc(b.auth)}</td></tr>
        <tr><td>Verificado</td><td>${esc(b.verificado)}</td></tr></table><b style="display:block;margin-top:10px">Actividad (sin credenciales)</b>
        <div class="tqc-ev">${(d.actividad || []).map(a => `<div><span class="muted">${new Date(a.ts * 1000).toLocaleString('es')}</span> ${a.ok ? '✔' : '✖'} ${esc(a.accion)} · ${esc(a.detalle)} · ${a.ms} ms</div>`).join('') || '<div class="muted">Sin actividad registrada.</div>'}</div>`;
    }
    const m = modal(html, cargarServ);
    m.querySelectorAll('input[data-pd]').forEach(i => i.onchange = async () => { try { await api('/api/tq/servidores', { proceso: i.dataset.pd, accion: i.checked ? 'iniciar' : 'detener' }); } catch (e) { alert(e.message); i.checked = !i.checked; } });
    m.querySelectorAll('[data-pa]').forEach(b => b.onclick = async () => { try { await api('/api/tq/servidores', { proceso: d.identidad.id, accion: b.dataset.pa }); b.textContent = '✔ ' + b.textContent; } catch (e) { alert(e.message); } });
  }

  // =========================================================================== CENTRO UNIVERSAL DE BROKERS (C2/C3/C4)
  T.brokers_centro = async function (v) {
    const { api, esc, badge, cargando } = H;
    v.innerHTML = `<div class="head"><div class="eyebrow">TITAN UNIVERSAL BROKER CONNECTIVITY CENTER</div><h1>Centro de brokers</h1>
      <div class="muted">Matriz de brokers y plataformas verificada en vivo. Cada broker tiene su interruptor (verde ON / rojo OFF), entorno DEMO/REAL, credenciales cifradas,
      diagnóstico, actividad y sincronización (el broker es la fuente de verdad). En REAL los conectores solo LEEN: TITAN no opera dinero real automáticamente.</div></div><div id="tqcBk">${cargando()}</div>`;
    let d;
    try { d = await api('/api/tq/brokers'); } catch (e) { document.getElementById('tqcBk').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; return; }
    const EUROPA = ['saxo', 'ig', 'oanda', 'cmc', 'xtb', 'capital', 'swissquote', 'fxcm', 'trading212'];
    const PLATAF = ['ctrader', 'iqoption', 'mt4', 'mt5'];
    const grupoDe = b => PLATAF.includes(b.id) ? 'Plataformas' : ['coinbase', 'kraken'].includes(b.id) ? 'Criptomonedas' : EUROPA.includes(b.id) ? 'Europa y Reino Unido' : 'Estados Unidos';
    const grupos = {};
    d.brokers.forEach(b => (grupos[grupoDe(b)] = grupos[grupoDe(b)] || []).push(b));
    const CON = { implementado: ['conector implementado', 'warn'], datos_publicos: ['datos públicos verificados', 'ok'], activo: ['en producción', 'ok'], no: ['sin conector', ''] };
    document.getElementById('tqcBk').innerHTML = `<div class="muted" style="margin-bottom:10px">${d.brokers.length} brokers y plataformas · ${d.brokers.filter(x => x.tiene_conector).length} con conector TITAN · ${esc(d.nota)}</div>` + ['Estados Unidos', 'Europa y Reino Unido', 'Criptomonedas', 'Plataformas'].filter(g => grupos[g]).map(g => `<div class="card" style="margin-bottom:12px"><b>${g}</b>
      ${grupos[g].map(b => { const c = CON[b.conector] || ['', ''];
        return `<div class="tqc-bk" data-b="${esc(b.id)}"><div class="tqc-bk-cab">
          ${b.tiene_conector ? sw(`data-on="${esc(b.id)}"`, b.habilitado) : b.conector === 'activo' ? sw('', true, true) : sw('', false, true)}
          <div style="flex:1"><b>${esc(b.nombre)}</b> ${badge(c[0], c[1])} ${b.tiene_conector ? (b.conectado ? badge('conectado', 'ok') : b.ultimo_error ? badge('desconectado', 'err') : badge('sin probar', '')) : ''}
            <div class="muted" style="font-size:11.5px">${esc(b.mercados)} · ${esc(b.apis)}</div></div>
          ${b.tiene_conector ? `<select class="field" data-ent="${esc(b.id)}" style="width:auto"><option value="demo" ${b.entorno === 'demo' ? 'selected' : ''}>DEMO</option><option value="real" ${b.entorno === 'real' ? 'selected' : ''}>REAL (solo lectura)</option></select>
            <button class="btn" data-acc="probar">Probar</button><button class="btn" data-acc="sincronizar">Sincronizar</button>` : ''}<button class="btn" data-acc="ver">Ficha</button></div>
          ${b.tiene_conector ? `<div class="muted" style="font-size:11.5px;margin-top:4px">${b.ultimo_ok_ts ? 'última conexión hace ' + hace(b.ultimo_ok_ts) + (b.latencia_ms != null ? ' · ' + b.latencia_ms + ' ms' : '') + ' · ' : ''}${esc(b.detalle_estado || b.ultimo_error || '')}
            ${b.ultima_sync_ts ? ' · sincronizado hace ' + hace(b.ultima_sync_ts) + ' · ' + b.posiciones + ' posiciones · ' + b.ejecuciones + ' ejecuciones' : ''}</div>` : `<div class="muted" style="font-size:11.5px;margin-top:4px">${esc(b.motivo || '')}</div>`}</div>`; }).join('')}</div>`).join('');
    const raiz = document.getElementById('tqcBk');
    raiz.querySelectorAll('input[data-on]').forEach(i => i.onchange = async () => {
      try { const r = await api('/api/tq/brokers', { accion: 'guardar', broker: i.dataset.on, habilitado: i.checked }); if (r.prueba && !r.prueba.ok) alert('Encendido, pero la prueba falló: ' + r.prueba.detalle); } catch (e) { alert(e.message); }
      T.brokers_centro(v);
    });
    raiz.querySelectorAll('select[data-ent]').forEach(s => s.onchange = async () => { try { await api('/api/tq/brokers', { accion: 'guardar', broker: s.dataset.ent, entorno: s.value }); } catch (e) { alert(e.message); } T.brokers_centro(v); });
    raiz.querySelectorAll('[data-acc]').forEach(btn => btn.onclick = async () => {
      const id = btn.closest('[data-b]').dataset.b, b = d.brokers.find(x => x.id === id);
      if (btn.dataset.acc === 'ver') return fichaBroker(b, v);
      btn.disabled = true; const t0 = btn.textContent; btn.textContent = '…';
      try { const r = await api('/api/tq/brokers', { accion: btn.dataset.acc, broker: id });
        alert(btn.dataset.acc === 'probar' ? (r.prueba.ok ? '✔ ' : '✖ ') + r.prueba.detalle : `Sincronización: ${r.sync.ok ? 'OK' : 'con errores'} · ${r.sync.posiciones || 0} posiciones · ${r.sync.ordenes || 0} órdenes · ${r.sync.ejecuciones_nuevas || 0} ejecuciones nuevas${(r.sync.errores || []).length ? '\n' + r.sync.errores.join('\n') : ''}${r.sync.detalle ? '\n' + r.sync.detalle : ''}`);
      } catch (e) { alert(e.message); }
      btn.disabled = false; btn.textContent = t0; T.brokers_centro(v);
    });
  };

  function fichaBroker(b, v) {
    const { api, esc } = H;
    const filas = [['Región', b.region], ['Mercados', b.mercados], ['APIs', b.apis], ['Autenticación', b.auth], ['Cuenta DEMO', b.demo], ['Regulación (declarada)', b.regulacion],
      ['República Dominicana', b.republica_dominicana], ['Requisitos', b.requisitos], ['Verificación ' + b.verificacion, b.verificado], ['Conector TITAN', b.conector + (b.motivo ? ' — ' + b.motivo : '')]];
    let docs = '';
    try { const u = new URL(b.docs); docs = `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(u.href)}</a>`; } catch (e) { docs = esc(b.docs); }
    const m = modal(`<b style="font-size:16px">${esc(b.nombre)}</b><table class="tq-table" style="margin-top:10px">${filas.map(([k, x]) => `<tr><td>${esc(k)}</td><td>${esc(x || '—')}</td></tr>`).join('')}
      <tr><td>Documentación oficial</td><td>${docs}</td></tr></table>
      ${b.tiene_conector ? `<form id="tqcCred" class="tq-form" style="margin-top:12px"><b>Credenciales (se guardan cifradas; nunca se muestran)</b>
        ${b.campos.map(c => `<div class="formrow"><label class="label">${esc(c.etiqueta)} ${b.credenciales[c.id] ? `<span class="muted">(guardada: ${esc(b.credenciales[c.id].mascara)})</span>` : ''}</label>
        ${c.id === 'clave_privada' ? `<textarea class="field" name="${esc(c.id)}" rows="3" autocomplete="off"></textarea>` : `<input class="field" name="${esc(c.id)}" type="password" autocomplete="off">`}</div>`).join('')}
        <button class="btn primary">Guardar y probar</button><div id="tqcCredM"></div></form>
        <div class="muted" style="margin-top:8px">Las credenciales DEMO permiten verificar autenticación, lectura, sincronización y una orden de prueba en DEMO. Sin ellas el conector queda «implementado» pero no se marca como conectado.</div>` : ''}`, () => T.brokers_centro(v));
    const f = m.querySelector('#tqcCred');
    if (f) f.onsubmit = async ev => { ev.preventDefault(); const cred = {}; b.campos.forEach(c => { if (f[c.id].value.trim()) cred[c.id] = f[c.id].value.trim(); });
      const out = m.querySelector('#tqcCredM'); out.innerHTML = H.cargando('Guardando y probando…');
      try { const r = await api('/api/tq/brokers', { accion: 'guardar', broker: b.id, credenciales: cred }); f.reset();
        out.innerHTML = r.prueba ? H.badge((r.prueba.ok ? 'conectado: ' : 'la prueba falló: ') + r.prueba.detalle, r.prueba.ok ? 'ok' : 'err') : H.badge('guardado', 'ok');
      } catch (e) { out.innerHTML = H.badge(e.message, 'err'); } };
  }

  // =========================================================================== IA AUTÓNOMA (C6) + LABORATORIO CUÁNTICO (C7)
  T.cerebro = async function (v) {
    const { api, esc, num, badge, cargando } = H;
    v.innerHTML = `<div class="head"><div class="eyebrow">TITAN AUTONOMOUS INTELLIGENCE · QUANTUM LAB</div><h1>Inteligencia autónoma</h1>
      <div class="muted">Inferencia bayesiana sobre operaciones VERIFICADAS por el broker, detección de deterioro, patrones de pérdida y estado del mercado (HMM, GARCH, Hurst, entropía).
      En práctica puede bloquear combinaciones perdedoras (reversible); en REAL solo recomienda. Nunca toca límites de riesgo, el MODO LIVE ni la PARADA TOTAL.</div></div>
      <div id="tqcCe">${cargando()}</div><div id="tqcQ" style="margin-top:14px"></div>`;
    try {
      const d = await api('/api/tq/cerebro');
      const e = d.ejecucion;
      const cuentas = e ? Object.entries(e.resumen.cuentas) : [];
      document.getElementById('tqcCe').innerHTML = `<div class="tq-row" style="margin-bottom:10px;gap:8px"><button class="btn primary" id="tqcRun">▶ Ejecutar análisis ahora</button>
        <span class="muted">${e ? 'último ciclo ' + new Date(e.ts * 1000).toLocaleString('es') + ' · ' + e.duracion_ms + ' ms · modelo v' + esc(d.version) : 'aún sin ciclos (el primero corre 1 min después de arrancar)'}</span></div>
        ${e ? `<div class="tq-kpis">${cuentas.map(([m, c]) => `<div class="tq-kpi"><small>Cuenta ${esc(m)}</small><b>${c.operaciones} verificadas</b>
          <small>${c.global ? esc(c.global.detalle) + (c.global.deterioro ? ' · ⚠ deterioro' : '') : 'sin operaciones cerradas'}</small></div>`).join('')}</div>
        <div class="grid two"><div class="card"><b>Estado del mercado (velas reales de cTrader, 1h)</b><table class="tq-table"><tr><th>Activo</th><th>Régimen (HMM)</th><th>Vol. GARCH</th><th>Hurst</th><th>Entropía</th></tr>
          ${Object.entries(d.mercado || {}).map(([s, x]) => x.error ? `<tr><td>${esc(s)}</td><td colspan="4">${esc(x.error)}</td></tr>` : `<tr><td><b>${esc(s)}</b></td>
            <td>${esc(x.regimen.regimen_actual)} (${num(x.regimen.prob_actual * 100, 0)} %)</td><td>${num(x.garch.vol_siguiente * 100, 3)} % · pers. ${num(x.garch.persistencia, 2)}</td>
            <td>${num(x.hurst, 2)} ${x.hurst > 0.55 ? '(tendencia)' : x.hurst < 0.45 ? '(reversión)' : '(aleatorio)'}</td><td>${num(x.entropia_permutacion, 3)}</td></tr>`).join('')}</table></div>
          <div class="card"><b>Patrones de pérdida (P(ganar) &lt; 20 %)</b><table class="tq-table"><tr><th>Cuenta</th><th>Dimensión</th><th>Valor</th><th>n</th><th>R medio</th></tr>
          ${(d.patrones || []).map(p => `<tr><td>${esc(p.cuenta)}</td><td>${esc(p.dimension)}</td><td>${esc(p.valor)}</td><td>${p.n}</td><td>${num(p.media_r, 2)}</td></tr>`).join('') || '<tr><td colspan="5" class="muted">Sin patrones con evidencia suficiente.</td></tr>'}</table></div></div>
        <div class="card" style="margin-top:12px"><b>Decisiones del cerebro (trazables y reversibles)</b><table class="tq-table"><tr><th>Fecha</th><th>Cuenta</th><th>Decisión</th><th>Estrategia · activo</th><th>Evidencia</th><th>Estado</th><th></th></tr>
          ${(d.decisiones || []).map(x => { const ev = JSON.parse(x.evidencia || '{}'); return `<tr><td>${new Date(x.ts * 1000).toLocaleString('es')}</td><td>${esc(x.cuenta)}</td><td>${esc(x.tipo)}</td>
            <td>${esc(x.estrategia)} · ${esc(x.instrumento)}</td><td>${esc(ev.detalle || '')}</td><td>${badge(x.estado, x.estado === 'aplicada' ? 'warn' : x.estado === 'revertida' ? '' : 'ok')}</td>
            <td>${x.estado !== 'revertida' ? `<button class="btn" data-rev="${x.id}">Revertir</button>` : ''}</td></tr>`; }).join('') || '<tr><td colspan="7" class="muted">Sin decisiones: ninguna combinación tiene aún evidencia suficiente (≥ 6 operaciones y P(ventaja) &lt; 10 %).</td></tr>'}</table></div>
        <details class="card" style="margin-top:12px"><summary><b>Evaluación bayesiana por estrategia y activo</b></summary><table class="tq-table"><tr><th>Cuenta</th><th>Combinación</th><th>n</th><th>R medio</th><th>P(ventaja)</th><th>Detalle</th></tr>
          ${(d.evaluaciones || []).map(x => `<tr><td>${esc(x.cuenta)}</td><td>${esc(x.clave)}</td><td>${x.n}</td><td>${num(x.media_r, 2)}</td><td>${num(x.p_ventaja * 100, 0)} %</td><td>${esc(x.detalle)}${x.deterioro ? ' · ⚠ deterioro' : ''}</td></tr>`).join('')}</table></details>` : ''}`;
      const run = document.getElementById('tqcRun');
      if (run) run.onclick = async () => { run.disabled = true; run.textContent = 'Analizando…'; try { await api('/api/tq/cerebro', { accion: 'ejecutar' }); } catch (e) { alert(e.message); } T.cerebro(v); };
      v.querySelectorAll('[data-rev]').forEach(b => b.onclick = async () => { if (!confirm('¿Revertir esta decisión del cerebro?')) return; try { await api('/api/tq/cerebro', { accion: 'revertir', id: +b.dataset.rev }); } catch (e) { alert(e.message); } T.cerebro(v); });
    } catch (e) { document.getElementById('tqcCe').innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
    cuantico();
  };

  async function cuantico() {
    const { api, esc, num, cargando } = H;
    const el = document.getElementById('tqcQ'); if (!el) return;
    el.innerHTML = cargando('Laboratorio cuántico…');
    try {
      const d = await api('/api/tq/cuantico');
      el.innerHTML = `<div class="card"><b>⚛ Laboratorio cuántico experimental</b> <span class="muted">${esc(d.nota)}</span>
        <div class="tq-row" style="margin:10px 0;gap:8px;flex-wrap:wrap"><button class="btn primary" data-q="cartera">QAOA + VQE: cartera óptima con datos reales</button><button class="btn" data-q="amplitud">Estimación de amplitud cuántica (QAE) vs Monte Carlo</button></div>
        <div id="tqcQr"></div><b style="display:block;margin-top:10px">Historial</b><table class="tq-table"><tr><th>Fecha</th><th>Experimento</th><th>Resultado</th><th>ms</th></tr>
        ${d.historial.map(x => `<tr><td>${new Date(x.ts * 1000).toLocaleString('es')}</td><td>${esc(x.tipo)}</td><td>${x.tipo === 'cartera_qaoa_vqe'
          ? `QAOA ${esc(x.resultado.seleccion_qaoa.join(', '))} · óptimo clásico ${esc(x.resultado.seleccion_optima.join(', '))} · ${x.resultado.qaoa.acierta ? '✔ coincide' : '✖ no coincide'} · P(óptimo) ${num(x.resultado.qaoa.p_optimo * 100, 1)} % (×${num(x.resultado.qaoa.amplificacion, 1)} sobre azar)`
          : `real ${num(x.resultado.valor_real, 4)} · QAE ${num(x.resultado.estimacion_qae, 4)} (error ${num(x.resultado.error_qae, 4)}) · MC clásico ${num(x.resultado.estimacion_mc_clasico, 4)} (error ${num(x.resultado.error_mc_clasico, 4)})`}</td><td>${x.ms}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">Sin experimentos.</td></tr>'}</table></div>`;
      el.querySelectorAll('[data-q]').forEach(b => b.onclick = async () => { b.disabled = true; b.textContent = 'Calculando…';
        try { await api('/api/tq/cuantico', { experimento: b.dataset.q, k: 3, capas: 3 }); } catch (e) { alert(e.message); } cuantico(); });
    } catch (e) { el.innerHTML = `<div class="tq-msg err">${esc(e.message)}</div>`; }
  }

  window.TQCentro = { render(nombre, v, helpers) { H = helpers; if (T[nombre]) return T[nombre](v); }, mejorar };
})();
