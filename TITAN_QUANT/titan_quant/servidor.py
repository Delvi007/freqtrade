"""Servidor web de TITAN QUANT: cuentas, sesiones, CSRF, límites, los 23 motores, bot operador, alertas e historial.

Extiende el servidor heredado (api_web.Handler): sus rutas siguen funcionando, pero ahora EXIGEN sesión.
Por defecto escucha solo en 127.0.0.1. Para la red local: TITAN_HOST=0.0.0.0 (sigue exigiendo sesión;
sin HTTPS las contraseñas viajan sin cifrar por la Wi-Fi, por eso se avisa al arrancar).
"""
import json
import secrets
import sys
import time
import traceback
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import api_web  # noqa: E402  (módulo heredado)

from . import VERSION, alertas, config, correo, db, historial, integraciones, niveles, recursos  # noqa: E402
from .motores import base as mbase  # noqa: E402
from .motores import nucleo, sistema  # noqa: E402
from .registro import limpiar, log  # noqa: E402
from .seguridad import administracion, boveda, cuentas, limites  # noqa: E402
from .seguridad.cuentas import ErrorCuenta  # noqa: E402
from .trader import autotrader  # noqa: E402

COOKIE = "tq_sesion"
MAX_CUERPO = 64 * 1024

RUTAS_PUBLICAS = {"/api/health", "/api/auth/estado", "/api/auth/verificar"}
POST_PUBLICOS = {"/api/auth/registro", "/api/auth/login", "/api/auth/olvide", "/api/auth/restablecer", "/api/auth/reenviar"}
LEGADO_GET_USUARIO = {"/api/assets", "/api/quotes", "/api/chart", "/api/mtf"}
LEGADO_GET_PROPIETARIO = {"/api/history", "/api/stats", "/api/alerts", "/api/plans"}
LEGADO_POST_USUARIO = {"/api/analyze", "/api/report"}
LEGADO_POST_PROPIETARIO = {"/api/plan", "/api/plan/cancel", "/api/plan/limpiar"}

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; font-src 'self' data:; media-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


class Respuesta(Exception):
    def __init__(self, codigo, datos):
        super().__init__(codigo)
        self.codigo, self.datos = codigo, datos


def _rq(cond, msg="Petición no válida."):
    if not cond:
        raise ValueError(msg)


def _ints(v):
    if not isinstance(v, list):
        v = [v]
    return [int(x) for x in v if str(x).lstrip("-").isdigit()]


# ============================================================================ manejadores GET
def g_estado(h, q):
    return {"ok": True, "hay_usuarios": cuentas.hay_usuarios(), "correo_configurado": correo.configurado(), "version": VERSION,
            "local": cuentas.es_local(h.ip()), "requiere_aprobacion": cuentas.requiere_aprobacion()}


def g_yo(h, q):
    s = h.requerir()
    u = s["usuario"]
    return {"ok": True, "usuario": u, "csrf": s["csrf"], "preferencias": preferencias(u["id"])}


def g_sesiones(h, q):
    s = h.requerir()
    return {"ok": True, "sesiones": cuentas.sesiones(s["usuario"]["id"], s["sesion_id"])}


def g_eventos(h, q):
    return {"ok": True, "eventos": cuentas.eventos(h.requerir()["usuario"]["id"])}


def g_preferencias(h, q):
    return {"ok": True, "preferencias": preferencias(h.requerir()["usuario"]["id"])}


def g_motores(h, q):
    h.requerir()
    est = sistema.estado_sistema(rapido=True)
    fichas = {m.id: m.ficha() for m in mbase.REGISTRO.values()}
    for m in est["motores"]:
        m["ficha"] = fichas[m["id"]]
    return {"ok": True, "motores": est["motores"], "total": len(est["motores"])}


def g_sistema(h, q):
    h.requerir(propietario=True)
    est = sistema.estado_sistema(rapido=False)
    est["autotrader_vivo"] = autotrader.hilo_vivo()
    est["autotrader_error"] = autotrader._HILO["error"]
    return {"ok": True, **est}


def g_hardware(h, q):
    h.requerir()
    d = recursos.diagnostico(red=q.get("red") == "1")
    return {"ok": True, "diagnostico": d, "recomendacion": recursos.recomendar_nivel(d)}


def g_niveles(h, q):
    u = h.requerir()["usuario"]
    return {"ok": True, "niveles": niveles.NIVELES, "orden": niveles.ORDEN, "politicas": niveles.POLITICAS, "horizontes": niveles.HORIZONTES,
            "seleccion": {"nivel": db.cfg_usuario(u["id"], "nivel", "intermedio"), "politica": db.cfg_usuario(u["id"], "politica", "automatico")},
            "recomendacion": recursos.recomendar_nivel()}


def g_analisis(h, q):
    u = h.requerir()["usuario"]
    r = db.q1("SELECT * FROM analisis WHERE id=? AND usuario_id=?", (int(q.get("id") or 0), u["id"]))
    if not r:
        raise Respuesta(404, {"ok": False, "error": "Análisis no encontrado."})
    return {"ok": True, "id": r["id"], "resultado": json.loads(r["resultado"])}


def g_integraciones(h, q):
    u = h.requerir()["usuario"]
    return {"ok": True, "integraciones": integraciones.listar(u["id"]), "estados": integraciones.ESTADOS}


def g_ctrader_callback(h, q):
    u = h.requerir()["usuario"]
    try:
        integraciones.ctrader_intercambiar(u["id"], q.get("code", ""), q.get("state", ""))
        destino = "/#integraciones-ok"
    except Exception as e:
        log().warning("cTrader OAuth: %s", type(e).__name__)
        destino = "/#integraciones-error"
    raise Respuesta(302, destino)


def g_alertas(h, q):
    u = h.requerir()["usuario"]
    return {"ok": True, "alertas": alertas.listar(u["id"], q.get("categoria") or None, q.get("estado") or None, q.get("importancia") or None,
                                                  q.get("buscar") or None, q.get("ver") or "normal", int(q.get("limite") or 100), q.get("desde_id") or None),
            "contadores": alertas.contadores(u["id"])}


def g_alertas_contadores(h, q):
    return {"ok": True, **alertas.contadores(h.requerir()["usuario"]["id"])}


def g_alertas_categorias(h, q):
    u = h.requerir()["usuario"]
    sil = {r["categoria"] for r in db.q("SELECT categoria FROM alertas_silencio WHERE usuario_id=?", (u["id"],))}
    return {"ok": True, "categorias": [{"id": k, "nombre": v, "silenciada": k in sil} for k, v in alertas.CATEGORIAS.items()]}


def g_historial(h, q):
    s = h.requerir()
    u = s["usuario"]
    tipo = q.get("tipo") or "analisis"
    return {"ok": True, "tipo": tipo, "tipos": historial.TIPOS,
            "filas": historial.listar(u["id"], tipo, q.get("ver") or "normal", int(q.get("limite") or 100), administracion.es_admin(u))}


def _modalidad(x):
    m = x.get("modalidad") or "demo"
    _rq(m in autotrader.MODALIDADES, "Modalidad no válida (demo = cTrader DEMO, binaria = IQ Option PRACTICE). La simulación interna se retiró.")
    return m


def g_operador(h, q):
    """Estado de los bots (cTrader DEMO, IQ Option PRACTICE; REAL bloqueada); cada uno lee solo su propia base."""
    u = h.requerir()["usuario"]
    from .trader import almacen
    from .trader.ctrader import CTrader
    from .trader.iqoption import IQOption, disponible
    bots = {m: {**autotrader.estado(u["id"], m), "abiertas": autotrader.abiertas(u["id"], m)} for m in autotrader.MODALIDADES}
    k = {"demo": almacen.conocimiento(origen="demo"), "binaria": almacen.conocimiento(origen="binaria")}
    return {"ok": True, "bots": bots, "modalidad": _modalidad(q), "hilo_vivo": autotrader.hilo_vivo(), "resumen": autotrader.resumen(u["id"]),
            "requisitos_real": autotrader.requisitos_real(u["id"]), "conocimiento": k["demo"], "conocimiento_por_broker": k,
            "conocimiento_fusion": almacen.conocimiento("fusion", origen="demo"), "simulacion_interna": "retirada",
            "estrategias": autotrader.ESTRATEGIAS, "limites": autotrader.LIMITES, "frase_real": autotrader.FRASE_REAL,
            "estrategias_simples": __import__("titan_quant.estrategias.simples", fromlist=["x"]).catalogo_publico(),
            "intervalos_escaner": autotrader.INTERVALOS_ESCANER, "reales": autotrader.REALES,
            "recolector": __import__("titan_quant.recolector_continuo", fromlist=["x"]).estado(),
            "brokers_por_modalidad": autotrader.BROKERS_POR_MODALIDAD, "simbolos_sugeridos": autotrader.SIMBOLOS_SUGERIDOS,
            "brokers": [{**IQOption({}).ficha(), "libreria_instalada": disponible()}, CTrader(cred={}).ficha()],
            "ctrader_autorizado": "access_token" in boveda.mascaras(u["id"], "ctrader"),  # solo se mira si existe, nunca el valor
            "nivel": db.cfg_usuario(u["id"], "nivel", "intermedio")}


def _filas_json(filas):
    for f in filas:
        f["controles"] = json.loads(f.get("controles") or "[]")
        f["motores"] = json.loads(f.get("motores") or "[]")
    return filas


def g_operaciones(h, q):
    u = h.requerir()["usuario"]
    from .trader import almacen
    m = _modalidad(q)
    sql, a = "SELECT * FROM operaciones WHERE usuario_id=?", [u["id"]]
    if q.get("estado") == "vivas":                  # enviadas, aceptadas, abiertas o sin confirmar
        sql += " AND estado IN ('enviada','aceptada','abierta','error')"
    elif q.get("estado"):
        sql += " AND estado=?"
        a.append(q["estado"])
    return {"ok": True, "modalidad": m, "operaciones": _filas_json(almacen.q(m, sql + " ORDER BY id DESC LIMIT 200", a))}


def g_eventos_operacion(h, q):
    """Traza verificable de una operación: cada fase con su hora, id del broker y evidencia."""
    u = h.requerir()["usuario"]
    from .trader import almacen
    m = _modalidad(q)
    _rq(str(q.get("id") or "").isdigit())
    o = almacen.q1(m, "SELECT * FROM operaciones WHERE id=? AND usuario_id=?", (int(q["id"]), u["id"]))
    _rq(o is not None, "Operación no encontrada en esta cuenta.")
    return {"ok": True, "modalidad": m, "operacion": _filas_json([o])[0], "eventos": almacen.eventos(m, o["id"])}


# ============================================================================ backtesting (dos sistemas independientes)
def _bt(mercado):
    _rq(mercado in ("binaria", "ctrader"), "Mercado de backtesting no válido (binaria | ctrader).")
    if mercado == "binaria":
        from .backtest_binaria import almacen, motor, recolector, ETIQUETA
    else:
        from .backtest_ctrader import almacen, motor, recolector, ETIQUETA
    return almacen, motor, recolector, ETIQUETA


def p_op_exploracion(h, d):
    """Aplica el perfil de EXPLORACIÓN (exigencia básica, todas las temporalidades) a un bot de PRÁCTICA."""
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, **autotrader.aplicar_perfil_exploracion(uid, _modalidad(d))}


def g_interruptores(h, q):
    """Estado de la PARADA TOTAL y de los interruptores por broker."""
    h.requerir()
    from .seguridad import interruptores
    return {"ok": True, **interruptores.estado()}


def p_interruptores(h, d):
    """PARADA TOTAL e interruptores por broker. Detener: siempre permitido. Reanudar/desbloquear: contraseña y este dispositivo."""
    u = h.requerir()["usuario"]
    from .seguridad import interruptores
    acc = d.get("accion")
    if acc == "parada_total":
        r = interruptores.parada_total(u["id"], str(d.get("motivo") or "PARADA TOTAL pulsada por el usuario"),
                                       bool(d.get("cerrar_posiciones")))
        return {"ok": True, **r}
    if acc == "bloquear_broker":
        return {"ok": True, **interruptores.bloquear_broker(u["id"], str(d.get("broker")), str(d.get("motivo") or "bloqueo manual"))}
    if acc in ("reanudar", "desbloquear_broker"):
        h.limite("login")
        clave_ok = _clave_ok(u["id"], d.get("clave"))
        if acc == "reanudar":
            return {"ok": True, **interruptores.reanudar(u["id"], clave_ok, api_web_local(h))}
        return {"ok": True, **interruptores.desbloquear_broker(u["id"], str(d.get("broker")), clave_ok, api_web_local(h))}
    _rq(False, "Acción no válida.")


# ============================================================================ centro de noticias
def g_noticias(h, q):
    """Noticias recopiladas y analizadas (titular, resumen breve, enlace a la fuente original y puntuaciones)."""
    h.requerir()
    from .noticias import almacen as na
    horas = max(1, min(24 * 30, int(q.get("horas") or 48)))
    sql = ("SELECT n.*, f.nombre fuente, f.estrellas, f.primaria, f.categoria categoria_fuente, g.n_fuentes, g.fuentes fuentes_grupo, g.contradiccion "
           "FROM noticias n JOIN fuentes f ON f.id=n.fuente_id JOIN grupos g ON g.id=n.grupo_id WHERE n.publicada_ts>=?")
    args = [int(time.time()) - horas * 3600]
    if q.get("categoria"):
        sql += " AND n.categoria=?"
        args.append(q["categoria"])
    if q.get("fuente"):
        sql += " AND n.fuente_id=?"
        args.append(q["fuente"])
    if q.get("urgentes") in ("1", "true"):
        sql += " AND n.urgente=1"
    if q.get("verificadas") in ("1", "true"):
        sql += " AND n.verificada=1"
    if q.get("macro") in ("1", "true"):
        sql += " AND n.categoria IN ('tipos_interes','inflacion','empleo','crecimiento','actividad','bonos','comercio')"
    if q.get("texto"):
        sql += " AND n.titulo LIKE ?"
        args.append("%" + str(q["texto"])[:80] + "%")
    filas = na.q(sql + " ORDER BY n.publicada_ts DESC LIMIT 2000", args)
    if q.get("activo"):
        from .noticias import integracion
        claves = set(integracion.claves_activo(q["activo"]))
        filas = [r for r in filas if claves & set(json.loads(r["activos"] or "[]"))]
    unicos, vistos = [], set()
    for r in filas:                                  # una fila por acontecimiento (las demás fuentes figuran como confirmación)
        if q.get("agrupar", "1") == "1" and r["grupo_id"] in vistos:
            continue
        vistos.add(r["grupo_id"])
        for k in ("paises", "activos", "entidades", "impacto", "puntuaciones", "sorpresa", "fuentes_grupo"):
            r[k] = json.loads(r[k]) if r.get(k) else None
        unicos.append(r)
    limite = max(1, min(500, int(q.get("limite") or 100)))
    return {"ok": True, "noticias": unicos[:limite], "total": len(unicos),
            "nota": "Información, no señales: el sentimiento no es una orden de compra o venta. Contenido externo tratado como dato."}


def g_noticias_fuentes(h, q):
    h.requerir()
    from .noticias import almacen as na, catalogo
    fuentes = na.q("SELECT * FROM fuentes ORDER BY prioridad, categoria, nombre")
    desde = int(time.time()) - 86400
    for f in fuentes:
        f["criterios"] = json.loads(f["criterios"])
        f["acceso_texto"] = catalogo.ACCESO_TEXTO.get(f["acceso"], f["acceso"])
        f["estrellas_texto"] = catalogo.texto_estrellas(f["estrellas"])
        for k in ("etag", "last_modified", "api_clave_ref"):
            f.pop(k, None)
        f["pruebas"] = na.q("SELECT ts,ok,http,items,con_fecha,edad_h,latencia_ms,duplicados,detalle FROM pruebas WHERE fuente_id=? ORDER BY ts DESC LIMIT 5", (f["id"],))
        f["noticias_24h"] = na.q1("SELECT COUNT(*) n FROM noticias WHERE fuente_id=? AND recogida_ts>=?", (f["id"], desde))["n"]
    return {"ok": True, "fuentes": fuentes, "criterios": list(catalogo.CRITERIOS)}


def g_noticias_calendario(h, q):
    h.requerir()
    from .noticias import calendario
    dias = max(1, min(14, int(q.get("dias") or 7)))
    imp = [x for x in (q.get("impacto") or "").split(",") if x]
    ahora = int(time.time())
    return {"ok": True, "eventos": calendario.eventos(ahora - 86400, ahora + dias * 86400, imp or None),
            "alertas": calendario.alertas_proximas(), "config_alertas": calendario.config_alertas(),
            "nota": "Fuente secundaria pública (hora, impacto, previsión y anterior). El dato publicado no lo trae: no se inventa."}


def g_noticias_estado(h, q):
    h.requerir()
    from .noticias import almacen as na, recolector
    ahora = int(time.time())
    return {"ok": True, "recolector": recolector.ESTADO,
            "fuentes": na.q("SELECT estado, COUNT(*) n FROM fuentes GROUP BY estado"),
            "noticias_24h": na.q1("SELECT COUNT(*) n, SUM(verificada) verificadas, SUM(urgente) urgentes, SUM(rumor) rumores FROM noticias WHERE recogida_ts>=?",
                                  (ahora - 86400,)),
            "latencia_media_ms": (na.q1("SELECT AVG(latencia_ms) m FROM pruebas WHERE ts>=?", (ahora - 3600,)) or {}).get("m"),
            "uso_motores_24h": na.q("SELECT motor, COUNT(*) n FROM uso_motor WHERE ts>=? GROUP BY motor", (ahora - 86400,))}


def p_noticias_fuente(h, d):
    """Administración de fuentes (solo propietario): crear, editar, eliminar, activar/desactivar y probar."""
    h.requerir(propietario=True)
    import re as _re
    from .noticias import almacen as na, catalogo, recolector
    acc = d.get("accion")
    fid = str(d.get("id") or "").strip()[:40]
    if acc == "crear":
        fid = _re.sub(r"[^a-z0-9_]", "_", (fid or str(d.get("nombre") or "")).lower())[:40].strip("_")
        _rq(fid and not na.q1("SELECT 1 FROM fuentes WHERE id=?", (fid,)), "Identificador vacío o ya existente.")
        ok, motivo = recolector.url_permitida(d.get("url"))
        _rq(ok, "URL no válida: " + motivo)
        crit = {k: max(0, min(5, int((d.get("criterios") or {}).get(k, 3)))) for k in catalogo.CRITERIOS}
        prim = bool(d.get("primaria"))
        cal = d.get("tipo") == "calendario"
        with na.tx() as c:
            c.execute("""INSERT INTO fuentes(id,nombre,categoria,url,tipo,acceso,primaria,idioma,frecuencia_min,prioridad,activo,criterios,estrellas,
                         palabras_clave,limite_hora,nota,personalizada,creada_ts,estado) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,1,?,'sin_probar')""",
                      (fid, str(d.get("nombre") or fid)[:120], str(d.get("categoria") or "medio")[:30], d["url"].strip(),
                       "calendario" if cal else "rss", "json_publico" if cal else "rss_publico", int(prim), str(d.get("idioma") or "en")[:5],
                       max(5, int(d.get("frecuencia_min") or 15)), max(1, min(5, int(d.get("prioridad") or 3))), json.dumps(crit),
                       catalogo.estrellas(crit, prim), str(d.get("palabras_clave") or "")[:500], max(1, min(60, int(d.get("limite_hora") or 12))),
                       str(d.get("nota") or "")[:300], int(time.time())))
    else:
        f = na.q1("SELECT * FROM fuentes WHERE id=?", (fid,))
        _rq(f, "Fuente desconocida.")
        if acc == "eliminar":
            with na.tx() as c:
                c.execute("DELETE FROM fuentes WHERE id=?", (fid,))
            return {"ok": True, "eliminada": fid}
        if acc in ("activar", "desactivar"):
            _rq(acc == "desactivar" or f["acceso"] not in ("sin_rss_publico", "bloqueado"), "Esta fuente no ofrece acceso gratuito autorizado.")
            with na.tx() as c:
                c.execute("UPDATE fuentes SET activo=? WHERE id=?", (int(acc == "activar"), fid))
        elif acc == "editar":
            cambios = {}
            if "url" in d:
                ok, motivo = recolector.url_permitida(d["url"])
                _rq(ok, "URL no válida: " + motivo)
                cambios.update(url=d["url"].strip(), etag=None, last_modified=None, estado="sin_probar")
            for k, lim in (("frecuencia_min", (5, 1440)), ("prioridad", (1, 5)), ("limite_hora", (1, 60))):
                if k in d:
                    cambios[k] = max(lim[0], min(lim[1], int(d[k])))
            for k, n in (("nombre", 120), ("idioma", 5), ("palabras_clave", 500), ("nota", 300), ("categoria", 30)):
                if k in d:
                    cambios[k] = str(d[k] or "")[:n]
            if "criterios" in d or "primaria" in d:
                crit = {**json.loads(f["criterios"]),
                        **{k: max(0, min(5, int(v))) for k, v in (d.get("criterios") or {}).items() if k in catalogo.CRITERIOS}}
                prim = bool(d.get("primaria", f["primaria"]))
                cambios.update(criterios=json.dumps(crit), primaria=int(prim), estrellas=catalogo.estrellas(crit, prim))
            if cambios:
                with na.tx() as c:
                    c.execute("UPDATE fuentes SET " + ",".join(f"{k}=?" for k in cambios) + " WHERE id=?", list(cambios.values()) + [fid])
        elif acc != "probar":
            _rq(False, "Acción no válida.")
    if acc in ("crear", "probar") or (acc == "editar" and "url" in d):
        f = na.q1("SELECT * FROM fuentes WHERE id=?", (fid,))
        return {"ok": True, "prueba": recolector.recoger(f, forzar=True), "fuente": fid}
    return {"ok": True, "fuente": fid}


def p_noticias_alertas(h, d):
    h.requerir()
    from .noticias import calendario
    return {"ok": True, "config": calendario.guardar_alertas(d)}


def g_escaner(h, q):
    """Ranking del escáner multiactivo (resultados de backtest por activo y estrategia; no son operaciones)."""
    h.requerir()
    if q.get("mercado") == "binaria":
        from .backtest_binaria import escaner as e
        filas = e.ranking(int(q.get("limite") or 100))
    else:
        from .backtest_ctrader import escaner as e
        filas = e.ranking(q.get("entorno") if q.get("entorno") in ("demo", "live") else None, q.get("intervalo"), int(q.get("limite") or 100))
    return {"ok": True, "ranking": filas, "nota": "Resultados históricos calculados (backtest); no son operaciones del broker."}


def g_backtest(h, q):
    h.requerir()
    alm, motor, _, etiqueta = _bt(q.get("mercado"))
    return {"ok": True, "mercado": q.get("mercado"), "etiqueta": etiqueta, "inventario": alm().inventario(),
            "informes": motor.informes(int(q.get("limite") or 20))}


def g_backtest_informe(h, q):
    h.requerir()
    alm, _, _, _ = _bt(q.get("mercado"))
    _rq(str(q.get("id") or "").isdigit())
    f = alm().q("SELECT resultado FROM informes WHERE id=?", (int(q["id"]),))
    _rq(bool(f), "Informe no encontrado.")
    return {"ok": True, "informe": json.loads(f[0]["resultado"])}


def p_backtest_recopilar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("integracion")
    _, _, rec, _ = _bt(d.get("mercado"))
    try:
        if d["mercado"] == "binaria":
            from .trader.iqoption import IQOption
            ad = IQOption(integraciones._config(uid, "iqoption"))
            ad._sesion()
            activo = str(d.get("activo") or "EURGBP-OTC").upper()
            r = rec.recopilar_iqoption(activo, int(d.get("velas") or 3000))
            p = ad.payout(activo)
            r["payout_observado"] = p
            r["payout_registrado"] = rec.registrar_payout(activo, p)
        else:
            aj = autotrader.estado(uid, "demo")["ajustes"]
            ctid = int(d.get("cuenta") or aj.get("cuenta_ctid") or 0)
            _rq(ctid > 0, "Indica la cuenta cTrader DEMO.")
            r = rec.recopilar(uid, ctid, str(d.get("simbolo") or aj.get("simbolo_broker") or "XAUUSD"), str(d.get("intervalo") or "15m"),
                              int(d.get("dias") or 60))
    except (RuntimeError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:                      # errores del broker: se muestran, no se inventa nada
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
    return {"ok": True, "recopilacion": r}


def p_backtest_ejecutar(h, d):
    h.requerir()
    h.limite("analizar")
    _, motor, _, _ = _bt(d.get("mercado"))
    try:
        if d["mercado"] == "binaria":
            r = motor.ejecutar(str(d.get("activo") or "EURGBP-OTC"), proveedor=str(d.get("proveedor") or "iqoption"),
                               payout=float(d["payout"]) if d.get("payout") not in (None, "") else None, k=int(d.get("k") or 4))
        else:
            r = motor.ejecutar(str(d.get("simbolo") or "XAUUSD"), intervalo=str(d.get("intervalo") or "15m"),
                               estrategia=str(d.get("estrategia") or "ema_rsi_atr"), horizonte=str(d.get("horizonte") or "intradia"),
                               costo_por_lado_pct=float(d["costo"]) if d.get("costo") not in (None, "") else None)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "resultado": r}


def g_decisiones(h, q):
    u = h.requerir()["usuario"]
    from .trader import almacen
    m = _modalidad(q)
    return {"ok": True, "modalidad": m,
            "decisiones": _filas_json(almacen.q(m, "SELECT * FROM decisiones_bot WHERE usuario_id=? ORDER BY id DESC LIMIT 200", (u["id"],)))}


def g_ctrader_cuentas(h, q):
    u = h.requerir()["usuario"]
    h.limite("integracion")
    try:
        info = integraciones.ctrader_cuentas(u["id"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    m = q.get("modalidad")
    if m in ("demo", "real"):
        info["cuentas"] = [c for c in info["cuentas"] if c["real"] == (m == "real")]
    return {"ok": True, **info}


def g_ctrader_simbolos(h, q):
    u = h.requerir()["usuario"]
    h.limite("integracion")
    m = q.get("modalidad")
    _rq(m in ("demo", "real") and str(q.get("cuenta") or "").isdigit())
    try:
        sims = integraciones.ctrader_simbolos(u["id"], m, int(q["cuenta"]))
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "simbolos": sorted((x["nombre"] for x in sims if x.get("nombre")), key=str)}


def g_diagnostico(h, q):
    h.requerir(propietario=True)
    from .seguridad import cripto
    return {"ok": True, "version": VERSION, "cifrado": cripto.algoritmo(), "host": config.HOST, "puerto": config.PUERTO,
            "https": config.HTTPS, "correo_configurado": correo.configurado(), "sistema": sistema.estado_sistema(rapido=False),
            "pruebas": db.cfg_sistema("ultima_bateria_pruebas"), "autotrader": {"vivo": autotrader.hilo_vivo(), "error": autotrader._HILO["error"]},
            "errores_motores": db.q("SELECT motor, error, ts FROM estado_motores WHERE error IS NOT NULL ORDER BY ts DESC LIMIT 20")}


RUTAS_GET = {
    "/api/auth/estado": g_estado, "/api/auth/yo": g_yo, "/api/auth/sesiones": g_sesiones,
    "/api/cuenta/eventos": g_eventos, "/api/cuenta/preferencias": g_preferencias,
    "/api/tq/motores": g_motores, "/api/tq/sistema": g_sistema, "/api/tq/hardware": g_hardware, "/api/tq/niveles": g_niveles,
    "/api/tq/analisis": g_analisis, "/api/tq/integraciones": g_integraciones,
    "/api/tq/integraciones/ctrader/callback": g_ctrader_callback,
    "/api/tq/alertas": g_alertas, "/api/tq/alertas/contadores": g_alertas_contadores, "/api/tq/alertas/categorias": g_alertas_categorias,
    "/api/tq/historial": g_historial, "/api/tq/operador": g_operador, "/api/tq/operador/operaciones": g_operaciones,
    "/api/tq/operador/eventos": g_eventos_operacion,
    "/api/tq/backtest": g_backtest, "/api/tq/escaner": g_escaner, "/api/tq/backtest/informe": g_backtest_informe,
    "/api/tq/noticias": g_noticias, "/api/tq/noticias/fuentes": g_noticias_fuentes, "/api/tq/noticias/calendario": g_noticias_calendario,
    "/api/tq/noticias/estado": g_noticias_estado, "/api/tq/seguridad/interruptores": g_interruptores,
    "/api/tq/operador/decisiones": g_decisiones,
    "/api/tq/ctrader/cuentas": g_ctrader_cuentas, "/api/tq/ctrader/simbolos": g_ctrader_simbolos, "/api/tq/diagnostico": g_diagnostico,
}


# ============================================================================ preferencias
PREF_DEF = {"zona": "America/Santo_Domingo", "nivel": "intermedio", "politica": "automatico", "horizonte": "corto",
            "sonidos": alertas.SONIDO_POR_DEFECTO, "notificaciones": {"telegram": True}, "riesgo": {"capital": 1000.0, "riesgo_pct": 1.0}}


def preferencias(uid):
    return {k: db.cfg_usuario(uid, k, v) for k, v in PREF_DEF.items()}


def _validar_pref(k, v):
    if k == "zona":
        from zoneinfo import ZoneInfo
        ZoneInfo(str(v))
        return str(v)
    if k == "nivel":
        niveles.parametros(v)
        return v
    if k == "politica":
        return niveles.validar_politica(v)
    if k == "horizonte":
        return niveles.validar_horizonte(v)
    if k == "sonidos":
        _rq(isinstance(v, dict))
        out = dict(alertas.SONIDO_POR_DEFECTO)
        for kk in out:
            if kk in v:
                out[kk] = max(0.0, min(1.0, float(v[kk]))) if kk == "volumen" else bool(v[kk])
        return out
    if k == "notificaciones":
        _rq(isinstance(v, dict))
        return {"telegram": bool(v.get("telegram", True))}
    if k == "riesgo":
        cap, pct = float(v.get("capital")), float(v.get("riesgo_pct"))
        _rq(10 <= cap <= 1e9, "Capital fuera de rango.")
        _rq(0.05 <= pct <= 5, "El riesgo por operación debe estar entre 0,05 % y 5 %.")
        return {"capital": cap, "riesgo_pct": pct}
    raise ValueError("Preferencia desconocida")


# ============================================================================ manejadores POST
def _enviar_seguro(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log().error("correo: %s", limpiar(str(e)))
        return "error"


def p_registro(h, d):
    h.limite("registro")
    generico = "Solicitud recibida. Si los datos son válidos, recibirás un correo para confirmar tu dirección."
    if d.get("web"):                         # campo trampa: los humanos no lo ven
        return {"ok": True, "mensaje": generico}
    if time.time() - float(d.get("t") or 0) / 1000 < 2:
        raise ValueError("Formulario enviado demasiado rápido. Inténtalo de nuevo.")
    u, tok = cuentas.registrar(d.get("nombre"), d.get("correo"), d.get("clave", ""), d.get("clave2", ""), bool(d.get("acepta")), h.ip())
    if u and tok is None:                    # primera cuenta creada en el propio dispositivo
        return {"ok": True, "activado": True,
                "mensaje": "Cuenta de ADMINISTRADOR creada y activada en este dispositivo. Ya puedes iniciar sesión."}
    if u:
        _enviar_seguro(correo.verificacion, u, tok)
        if not u["aprobado"]:
            try:
                administracion.notificar_solicitud(u)
            except Exception as e:
                log().error("aviso de solicitud: %s", type(e).__name__)
    extra = ""
    if cuentas.requiere_aprobacion():
        extra = " Después, el administrador debe aprobar la solicitud; te avisaremos por correo."
    if not correo.configurado():
        extra += " (El envío de correo aún no está configurado: el administrador puede aprobar tu cuenta directamente.)"
    return {"ok": True, "mensaje": generico + extra}


def p_reenviar(h, d):
    h.limite("olvide")
    u, tok = cuentas.reenviar_verificacion(d.get("correo"))
    if u and tok:
        _enviar_seguro(correo.verificacion, u, tok)
    return {"ok": True, "mensaje": "Si la cuenta existe y no está confirmada, te enviamos un enlace nuevo."}


def p_login(h, d):
    h.limite("login")
    u, tok, csrf = cuentas.iniciar_sesion(d.get("correo"), d.get("clave"), h.ip(), h.headers.get("User-Agent"), bool(d.get("recordar")))
    dur = config.SESION_RECORDAR_DIAS * 86400 if d.get("recordar") else None
    h.cookie_nueva = (tok, dur)
    return {"ok": True, "usuario": u, "csrf": csrf}


def p_logout(h, d):
    s = h.requerir()
    cuentas.cerrar_sesion(h.token_cookie(), s["usuario"]["id"], h.ip())
    h.cookie_nueva = ("", 0)
    return {"ok": True}


def p_logout_todas(h, d):
    s = h.requerir()
    cuentas.cerrar_todas(s["usuario"]["id"], s["sesion_id"], h.ip())
    return {"ok": True}


def p_cerrar_sesion(h, d):
    s = h.requerir()
    cuentas.cerrar_sesion_id(s["usuario"]["id"], d.get("id"), h.ip())
    return {"ok": True}


def p_olvide(h, d):
    h.limite("olvide")
    u, tok = cuentas.solicitar_restablecimiento(d.get("correo"), h.ip())
    if u and tok:
        _enviar_seguro(correo.recuperacion, u, tok)
    return {"ok": True, "mensaje": "Si el correo está registrado, recibirás un enlace para restablecer la contraseña."}


def p_restablecer(h, d):
    h.limite("restablecer")
    cuentas.restablecer(d.get("token"), d.get("clave", ""), d.get("clave2", ""), h.ip())
    return {"ok": True, "mensaje": "Contraseña actualizada. Ya puedes iniciar sesión."}


def p_cambiar_clave(h, d):
    s = h.requerir()
    h.limite("login")
    cuentas.cambiar_clave(s["usuario"]["id"], d.get("actual"), d.get("nueva", ""), d.get("nueva2", ""), s["sesion_id"], h.ip())
    return {"ok": True, "mensaje": "Contraseña cambiada. Se cerraron tus otras sesiones."}


def p_perfil(h, d):
    s = h.requerir()
    return {"ok": True, "usuario": cuentas.actualizar_perfil(s["usuario"]["id"], d.get("nombre"))}


def p_preferencias(h, d):
    uid = h.requerir()["usuario"]["id"]
    _rq(isinstance(d, dict) and d, "Sin cambios.")
    for k, v in d.items():
        db.set_cfg_usuario(uid, k, _validar_pref(k, v))
    return {"ok": True, "preferencias": preferencias(uid)}


def p_nivel(h, d):
    uid = h.requerir()["usuario"]["id"]
    if "nivel" in d:
        db.set_cfg_usuario(uid, "nivel", _validar_pref("nivel", d["nivel"]))
    if "politica" in d:
        db.set_cfg_usuario(uid, "politica", _validar_pref("politica", d["politica"]))
    return {"ok": True, "nivel": db.cfg_usuario(uid, "nivel", "intermedio"), "politica": db.cfg_usuario(uid, "politica", "automatico")}


def p_analizar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("analizar")
    hz = niveles.validar_horizonte(d.get("horizonte") or db.cfg_usuario(uid, "horizonte", "corto"))
    res = nucleo.analizar(d.get("simbolo"), hz, db.cfg_usuario(uid, "nivel", "intermedio"), db.cfg_usuario(uid, "politica", "automatico"),
                          usuario_id=uid, riesgo=db.cfg_usuario(uid, "riesgo", PREF_DEF["riesgo"]))
    aid = nucleo.guardar(uid, res)
    alertas.desde_analisis(uid, res, aid)
    return {"ok": True, "id": aid, "resultado": res}


def p_integ_guardar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("integracion")
    _rq(isinstance(d.get("valores"), dict))
    return {"ok": True, "estado": integraciones.guardar(uid, d.get("proveedor"), d["valores"])}


def p_integ_probar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("integracion")
    return {"ok": True, **integraciones.probar(uid, d.get("proveedor"))}


def p_integ_activar(h, d):
    uid = h.requerir()["usuario"]["id"]
    integraciones.activar(uid, d.get("proveedor"), bool(d.get("activa")))
    return {"ok": True}


def p_integ_eliminar(h, d):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "secretos_borrados": integraciones.eliminar(uid, d.get("proveedor"))}


def p_ctrader_autorizar(h, d):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "url": integraciones.ctrader_url_autorizacion(uid, secrets.token_urlsafe(24))}


def p_alertas_marcar(h, d, leida):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "n": alertas.marcar(uid, _ints(d.get("ids", [])), leida)}


def p_alertas_vis(h, d, estado):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "n": historial.cambiar_visibilidad(uid, "alerta", _ints(d.get("ids", [])), estado)}


def p_alertas_silenciar(h, d):
    uid = h.requerir()["usuario"]["id"]
    alertas.silenciar(uid, d.get("categoria"), bool(d.get("silenciar", True)))
    return {"ok": True}


def p_historial(h, d, estado):
    uid = h.requerir()["usuario"]["id"]
    return {"ok": True, "n": historial.cambiar_visibilidad(uid, d.get("tipo"), _ints(d.get("ids", [])), estado)}


def p_historial_eliminar(h, d):
    s = h.requerir()
    u = s["usuario"]
    return {"ok": True, "n": historial.eliminar_permanente(u["id"], _ints(d.get("ids", [])), d.get("frase"), administracion.es_admin(u))}


def _clave_ok(uid, clave):
    from .seguridad import cripto
    fila = db.q1("SELECT clave_hash FROM usuarios WHERE id=?", (uid,))
    return cripto.verificar_clave(clave or "", fila["clave_hash"])


def p_op_ajustes(h, d):
    uid = h.requerir()["usuario"]["id"]
    _rq(isinstance(d.get("ajustes"), dict))
    return {"ok": True, "ajustes": autotrader.guardar_ajustes(uid, _modalidad(d), d["ajustes"])}


def p_op_estado(h, d):
    uid = h.requerir()["usuario"]["id"]
    m = _modalidad(d)
    confirmado = False
    if m in autotrader.REALES and d.get("estado") == "activo":
        h.limite("login")
        confirmado = _clave_ok(uid, d.get("clave"))
        if not confirmado:
            raise PermissionError("Contraseña incorrecta: el bot REAL no se ha iniciado.")
        if not api_web_local(h):
            raise PermissionError("El bot REAL solo se inicia desde el propio dispositivo donde corre TITAN.")
    e = autotrader.cambiar_estado(uid, m, d.get("estado"), confirmado_real=confirmado)
    if e["estado"] == "activo":
        autotrader.iniciar_hilo()
    return {"ok": True, **e}


def p_op_restablecer(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("login")
    e = autotrader.restablecer(uid, _modalidad(d))
    return {"ok": True, **e}


def p_op_ciclo(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("analizar")
    return {"ok": True, "ciclo": autotrader.ciclo(uid, _modalidad(d))}


def p_op_conciliar(h, d):
    uid = h.requerir()["usuario"]["id"]
    h.limite("login")
    _rq(str(d.get("id") or "").isdigit())
    o = autotrader.conciliar(uid, _modalidad(d), int(d["id"]), d.get("resultado_broker"), d.get("nota"))
    return {"ok": True, "operacion": _filas_json([o])[0]}


def p_op_live(h, d):
    """Interruptor MODO LIVE de una cuenta real (cTrader REAL o IQ Option REAL). Encender exige la contraseña."""
    u = h.requerir()["usuario"]
    m = _modalidad(d)
    encender = d.get("encender") in (True, 1, "1", "true", "on")
    clave_ok = False
    if encender:
        h.limite("login")
        clave_ok = _clave_ok(u["id"], d.get("clave"))
    e = autotrader.interruptor_live(u["id"], m, encender, clave_ok, api_web_local(h))
    if e["estado"] == "activo":
        autotrader.iniciar_hilo()
    return {"ok": True, **e}


def p_op_real(h, d):
    u = h.requerir()["usuario"]
    if d.get("deshabilitar"):
        autotrader.deshabilitar_real(u["id"])
        return {"ok": True}
    h.limite("login")
    autotrader.habilitar_real(u["id"], d.get("frase"), _clave_ok(u["id"], d.get("clave")), api_web_local(h))
    return {"ok": True}


def api_web_local(h):
    from .seguridad import cuentas as _c
    return _c.es_local(h.ip())


# ============================================================================ administración
def _admin(h):
    return h.requerir(propietario=True)["usuario"]


def g_admin_usuarios(h, q):
    _admin(h)
    return {"ok": True, "usuarios": administracion.listar(), **administracion.resumen()}


def p_admin(h, d, accion):
    actor = _admin(h)
    uid = int(d.get("id") or 0)
    if accion == "aprobar":
        r = administracion.aprobar(actor, uid, h.ip())
    elif accion == "rechazar":
        r = administracion.rechazar(actor, uid, h.ip())
    elif accion == "suspender":
        r = administracion.suspender(actor, uid, True, h.ip())
    elif accion == "reactivar":
        r = administracion.suspender(actor, uid, False, h.ip())
    elif accion == "hacer_admin":
        r = administracion.hacer_admin(actor, uid, True)
    elif accion == "quitar_admin":
        r = administracion.hacer_admin(actor, uid, False)
    elif accion == "cerrar_sesiones":
        r = administracion.cerrar_sesiones(actor, uid)
    elif accion == "desbloquear":
        r = administracion.desbloquear(actor, uid)
    elif accion == "reenviar":
        r = administracion.reenviar_verificacion(actor, uid)
    else:
        raise ValueError("Acción desconocida")
    return {"ok": True, **r}


def p_admin_config(h, d):
    return {"ok": True, **administracion.configurar(_admin(h), bool(d.get("requiere_aprobacion")))}


def p_admin_correo_prueba(h, d):
    actor = _admin(h)
    h.limite("integracion")
    if not correo.configurado():
        raise ValueError("El correo no está configurado. Ve a Configuración e integraciones → Correo (SMTP).")
    try:
        correo.prueba(actor["correo"])
    except RuntimeError as e:
        raise ValueError(str(e))
    return {"ok": True, "mensaje": f"Correo de prueba enviado a {actor['correo']}. Revisa también la carpeta de spam."}


RUTAS_GET["/api/admin/usuarios"] = g_admin_usuarios


RUTAS_POST = {
    "/api/auth/registro": p_registro, "/api/auth/reenviar": p_reenviar, "/api/auth/login": p_login, "/api/auth/logout": p_logout,
    "/api/auth/logout_todas": p_logout_todas, "/api/auth/sesiones/cerrar": p_cerrar_sesion, "/api/auth/olvide": p_olvide,
    "/api/auth/restablecer": p_restablecer, "/api/auth/cambiar_clave": p_cambiar_clave,
    "/api/cuenta/perfil": p_perfil, "/api/cuenta/preferencias": p_preferencias,
    "/api/tq/nivel": p_nivel, "/api/tq/analizar": p_analizar,
    "/api/tq/integraciones/guardar": p_integ_guardar, "/api/tq/integraciones/probar": p_integ_probar,
    "/api/tq/integraciones/activar": p_integ_activar, "/api/tq/integraciones/eliminar": p_integ_eliminar,
    "/api/tq/integraciones/ctrader/autorizar": p_ctrader_autorizar,
    "/api/tq/alertas/leer": lambda h, d: p_alertas_marcar(h, d, True), "/api/tq/alertas/noleer": lambda h, d: p_alertas_marcar(h, d, False),
    "/api/tq/alertas/ocultar": lambda h, d: p_alertas_vis(h, d, "oculto"), "/api/tq/alertas/restaurar": lambda h, d: p_alertas_vis(h, d, "visible"),
    "/api/tq/alertas/silenciar": p_alertas_silenciar,
    "/api/tq/historial/ocultar": lambda h, d: p_historial(h, d, "oculto"), "/api/tq/historial/archivar": lambda h, d: p_historial(h, d, "archivado"),
    "/api/tq/historial/restaurar": lambda h, d: p_historial(h, d, "visible"), "/api/tq/historial/eliminar_permanente": p_historial_eliminar,
    "/api/tq/operador/ajustes": p_op_ajustes, "/api/tq/operador/estado": p_op_estado, "/api/tq/operador/ciclo": p_op_ciclo,
    "/api/tq/operador/real": p_op_real, "/api/tq/operador/restablecer": p_op_restablecer, "/api/tq/operador/conciliar": p_op_conciliar, "/api/tq/operador/live": p_op_live, "/api/tq/operador/exploracion": p_op_exploracion,
    "/api/tq/noticias/fuente": p_noticias_fuente, "/api/tq/seguridad/interruptores": p_interruptores, "/api/tq/noticias/alertas": p_noticias_alertas,
    "/api/tq/backtest/recopilar": p_backtest_recopilar, "/api/tq/backtest/ejecutar": p_backtest_ejecutar,
    "/api/admin/config": p_admin_config, "/api/admin/correo_prueba": p_admin_correo_prueba,
    **{f"/api/admin/{a}": (lambda h, d, a=a: p_admin(h, d, a)) for a in
       ("aprobar", "rechazar", "suspender", "reactivar", "hacer_admin", "quitar_admin", "cerrar_sesiones", "desbloquear", "reenviar")},
}


# ============================================================================ handler
class Handler(api_web.Handler):
    server_version = "TITAN"
    sys_version = ""

    def __init__(self, *a, **k):
        self._sesion = None
        self.cookie_nueva = None
        super(api_web.Handler, self).__init__(*a, directory=str(config.WEB), **k)

    def finish(self):
        try:
            super().finish()
        finally:
            db.cerrar_hilo()          # cada petición corre en su hilo: cerrar su conexión SQLite
            from .trader import almacen
            almacen.cerrar_hilo()

    # ---------------------------------------------------------------- utilidades
    def ip(self):
        return self.client_address[0] if self.client_address else "?"

    def limite(self, accion):
        if not limites.permitir(accion, self.ip()):
            cuentas.evento(None, "limite_superado", self.ip(), accion)
            raise Respuesta(429, {"ok": False, "error": "Demasiadas solicitudes. Espera unos minutos."})

    def token_cookie(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        return c[COOKIE].value if COOKIE in c else None

    def sesion(self):
        if self._sesion is None:
            self._sesion = cuentas.sesion(self.token_cookie()) or False
        return self._sesion or None

    def requerir(self, propietario=False):
        s = self.sesion()
        if not s:
            raise Respuesta(401, {"ok": False, "error": "Inicia sesión.", "auth": True})
        if propietario and not administracion.es_admin(s["usuario"]):
            raise Respuesta(403, {"ok": False, "error": "Solo administradores."})
        return s

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", CSP)
        ruta = (self.path or "").split("?")[0]
        if ruta in ("/", "/index.html") or ruta.endswith((".js", ".css", ".html")):
            self.send_header("Cache-Control", "no-cache")      # el navegador revalida: tras actualizar TITAN ve la interfaz nueva
        if config.HTTPS:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if self.cookie_nueva is not None:
            tok, dur = self.cookie_nueva
            partes = [f"{COOKIE}={tok}", "Path=/", "HttpOnly", "SameSite=Lax"]
            if config.HTTPS:
                partes.append("Secure")
            if dur is not None:
                partes.append(f"Max-Age={dur}")
            self.send_header("Set-Cookie", "; ".join(partes))
            self.cookie_nueva = None
        super().end_headers()

    def log_message(self, fmt, *args):
        try:
            log().info("%s %s", self.ip(), limpiar(fmt % args).split("?")[0])
        except Exception:
            pass

    def enviar_json(self, codigo, datos):
        if codigo >= 500 and isinstance(datos, dict) and "error" in datos:
            ref = secrets.token_hex(4)
            log().error("500 [%s] %s", ref, limpiar(datos.get("error")))
            datos = {"ok": False, "error": f"Error interno (referencia {ref}). Consulta el registro del servidor."}
        try:
            super().enviar_json(codigo, datos)
        except DESCONEXIONES:
            self.close_connection = True        # el cliente ya no escucha: no hay a quién responder

    def redirigir(self, destino):
        self.send_response(302)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _origen_ok(self):
        o = self.headers.get("Origin") or self.headers.get("Referer")
        if not o:
            return True
        host = self.headers.get("Host", "")
        return urlparse(o).netloc == host

    def _leer_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > MAX_CUERPO:
            raise Respuesta(413, {"ok": False, "error": "Solicitud demasiado grande."})
        if not n:
            return {}
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Respuesta(400, {"ok": False, "error": "JSON no válido."})
        if not isinstance(d, dict):
            raise Respuesta(400, {"ok": False, "error": "Se esperaba un objeto JSON."})
        return d

    def _ejecutar(self, fn, *args):
        try:
            res = fn(self, *args)
            self.enviar_json(200, res)
        except Respuesta as r:
            if r.codigo == 302:
                self.redirigir(r.datos)
            else:
                self.enviar_json(r.codigo, r.datos)
        except (ErrorCuenta, ValueError, KeyError, TypeError) as e:
            msg = str(e) if isinstance(e, (ErrorCuenta, ValueError)) else "Petición no válida."
            self.enviar_json(400, {"ok": False, "error": msg[:300]})
        except PermissionError as e:
            self.enviar_json(403, {"ok": False, "error": str(e)[:300]})
        except Exception as e:
            ref = secrets.token_hex(4)
            log().error("500 [%s] %s %s", ref, type(e).__name__, limpiar(traceback.format_exc(limit=4)))
            self.enviar_json(500, {"ok": False, "error": f"Error interno (referencia {ref})."})

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        ruta = u.path
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if ruta.startswith("/api/") and not limites.permitir("api", self.ip()):
            return self.enviar_json(429, {"ok": False, "error": "Demasiadas solicitudes."})
        if ruta == "/api/auth/verificar":
            try:
                cuentas.verificar_correo(q.get("token"), self.ip())
                return self.redirigir("/#verificado")
            except ErrorCuenta:
                return self.redirigir("/#verificacion-fallida")
        if ruta in RUTAS_GET:
            return self._ejecutar(lambda h: RUTAS_GET[ruta](h, q))
        if ruta == "/api/health":
            return self.enviar_json(200, {"ok": True, "servicio": "TITAN_QUANT_API", "version": VERSION})
        if ruta.startswith("/api/"):
            try:
                if ruta.startswith("/api/lab/") or ruta in LEGADO_GET_PROPIETARIO:
                    self.requerir(propietario=True)
                elif ruta in LEGADO_GET_USUARIO:
                    self.requerir()
                else:
                    return self.enviar_json(404, {"ok": False, "error": "Endpoint desconocido."})
            except Respuesta as r:
                return self.enviar_json(r.codigo, r.datos)
            return super().do_GET()
        if ruta.endswith(".db") or "/." in ruta:
            return self.enviar_json(404, {"ok": False, "error": "No encontrado."})
        return super().do_GET()

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        ruta = urlparse(self.path).path
        if not limites.permitir("api", self.ip()):
            return self.enviar_json(429, {"ok": False, "error": "Demasiadas solicitudes."})
        if not self._origen_ok():
            cuentas.evento(None, "origen_rechazado", self.ip(), ruta)
            return self.enviar_json(403, {"ok": False, "error": "Origen no permitido."})
        if ruta not in POST_PUBLICOS:
            s = self.sesion()
            if not s:
                return self.enviar_json(401, {"ok": False, "error": "Inicia sesión.", "auth": True})
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), s["csrf"]):
                cuentas.evento(s["usuario"]["id"], "csrf_rechazado", self.ip(), ruta)
                return self.enviar_json(403, {"ok": False, "error": "Token CSRF no válido. Recarga la página."})
        if ruta in RUTAS_POST:
            try:
                d = self._leer_json()
            except Respuesta as r:
                return self.enviar_json(r.codigo, r.datos)
            return self._ejecutar(lambda h: RUTAS_POST[ruta](h, d))
        try:
            if ruta.startswith("/api/lab/") or ruta in LEGADO_POST_PROPIETARIO:
                self.requerir(propietario=True)
            elif ruta not in LEGADO_POST_USUARIO:
                return self.enviar_json(404, {"ok": False, "error": "Endpoint desconocido."})
        except Respuesta as r:
            return self.enviar_json(r.codigo, r.datos)
        return super().do_POST()


DESCONEXIONES = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """El navegador cerró la conexión antes de recibir la respuesta (recarga, cambio de vista, WinError 10053):
        es normal y no afecta a los datos ni a los bots. Se ignora en silencio; cualquier otro error se muestra."""
        import sys as _sys
        if isinstance(_sys.exc_info()[1], DESCONEXIONES):
            return
        super().handle_error(request, client_address)


def inicializar_bases_heredadas():
    """Crea (si faltan) las tablas de las bases heredadas para que una instalación nueva funcione desde cero."""
    hechas = []
    for nombre, fn in (("titan_activos.db", lambda: __import__("escenarios").conectar().close()),
                       ("titan_planes.db", lambda: __import__("plan_web")._con().close()),
                       ("titan_lab.db", lambda: __import__("lab_engine").init_db())):
        try:
            fn()
            hechas.append(nombre)
        except Exception as e:
            log().error("inicializar %s: %s", nombre, type(e).__name__)
    return hechas


def crear(host=None, puerto=None):
    config.asegurar_directorios()
    db.migrar()
    inicializar_bases_heredadas()
    api_web.HTML_DIR = config.WEB
    return Servidor((host or config.HOST, config.PUERTO if puerto is None else puerto), Handler)


def iniciar_fondo():
    try:
        import plan_web
        plan_web.iniciar_vigilante()
        print("  · Vigilante de planes: activo")
    except Exception as e:
        print("  · Vigilante de planes no iniciado:", type(e).__name__)
    try:
        import lab_engine
        lab_engine.iniciar()
        print("  · Laboratorio de Aprendizaje: activo")
    except Exception as e:
        print("  · Laboratorio no iniciado:", type(e).__name__)
    autotrader.iniciar_hilo()
    print("  · Bot operador (hilo): activo — solo opera si lo inicias desde la web")


def main():
    srv = crear()
    print(f"TITAN QUANT {VERSION}")
    print(f"  Abre en el navegador:  http://{'127.0.0.1' if config.HOST in ('0.0.0.0', '::') else config.HOST}:{config.PUERTO}")
    print(f"  Datos: {config.DATOS}")
    if config.HOST not in ("127.0.0.1", "localhost", "::1"):
        print("  AVISO: escuchando en la red local. Se exige sesión, pero sin HTTPS las contraseñas viajan sin cifrar por la Wi-Fi.")
    if not correo.configurado():
        print("  Correo SMTP no configurado: los enlaces de verificación y recuperación se mostrarán AQUÍ.")
    iniciar_fondo()
    try:
        from . import recolector_continuo
        recolector_continuo.iniciar()
        print("  · Recolector continuo de velas (cTrader e IQ Option, todas las temporalidades): activo")
    except Exception as e:
        print("  · Recolector continuo no iniciado:", type(e).__name__)
    try:
        from .noticias import recolector as rec_noticias
        rec_noticias.iniciar()
        print("  · Centro de noticias (fuentes oficiales, medios, cripto y calendario): activo")
    except Exception as e:
        print("  · Centro de noticias no iniciado:", type(e).__name__)
    print("  Ctrl+C para detener.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")


if __name__ == "__main__":
    main()
