/* TITAN QUANT v7 — sesión y CSRF para TODA la página (se carga antes que el resto).
   - La cookie de sesión es HttpOnly: JavaScript no puede leerla.
   - El token CSRF se pide a /api/auth/yo y se añade a cada POST del mismo origen. */
(function () {
  'use strict';
  const nativo = window.fetch.bind(window);
  const TQ = window.TQ = window.TQ || {};
  TQ.csrf = null;
  TQ.usuario = null;
  TQ.cargarSesion = function () {
    if (!TQ._promesa) {
      TQ._promesa = nativo('/api/auth/yo', { credentials: 'same-origin', cache: 'no-store' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d && d.ok) { TQ.csrf = d.csrf; TQ.usuario = d.usuario; TQ.preferencias = d.preferencias; } return d; })
        .catch(() => null);
    }
    return TQ._promesa;
  };
  function mismoOrigen(u) {
    try { return new URL(u, location.href).origin === location.origin; } catch (e) { return false; }
  }
  window.fetch = async function (recurso, opciones) {
    opciones = Object.assign({}, opciones || {});
    const url = typeof recurso === 'string' ? recurso : (recurso && recurso.url) || '';
    const metodo = (opciones.method || (recurso && recurso.method) || 'GET').toUpperCase();
    if (mismoOrigen(url)) {
      opciones.credentials = 'same-origin';
      if (metodo !== 'GET' && metodo !== 'HEAD') {
        if (!TQ.csrf) await TQ.cargarSesion();
        const h = new Headers(opciones.headers || {});
        if (TQ.csrf) h.set('X-CSRF-Token', TQ.csrf);
        opciones.headers = h;
      }
    }
    const r = await nativo(recurso, opciones);
    if (r.status === 401 && mismoOrigen(url) && TQ.alCaducar && TQ.usuario) TQ.alCaducar();
    return r;
  };
  TQ.cargarSesion();
})();
