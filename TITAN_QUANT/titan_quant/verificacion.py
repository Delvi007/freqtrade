"""Verificación REAL y trazable de los dos conectores. Solo cuentas PRACTICE (IQ Option) y DEMO (cTrader).

    python -m titan_quant.cli verificar-brokers --iq                                  lectura: conexión, cuenta, saldo, velas, payout
    python -m titan_quant.cli verificar-brokers --ctrader CUENTA_DEMO XAUUSD          lectura: cuenta DEMO, saldo, cotización, velas
    … --iq --activo PAR-OTC   par a verificar (por defecto EURGBP-OTC)
    … --enviar   además envía UNA orden mínima por el MISMO flujo de fases que el bot (autotrader._enviar) y sigue su ciclo
                 hasta el resultado del broker:
                   IQ Option: binaria de 1 USD, 5 min, en la cuenta PRACTICE; se espera al vencimiento y se lee el resultado.
                   cTrader:   orden a mercado con el volumen mínimo del símbolo en la cuenta DEMO; se confirma la posición,
                              se cierra y se lee el deal de cierre.
Las órdenes quedan registradas en la base de su cuenta (binaria.db / demo.db) con estrategia 'verificacion_conector'
y la traza completa de fases en operacion_eventos. Si el broker no confirma algo, la verificación lo dice: no se da por buena.
"""
import json
import time

from . import db
from .trader import almacen, autotrader
from .trader.base import ErrorAdaptador

ESTRATEGIA = "verificacion_conector"


def _uid():
    fila = db.q1("SELECT id FROM usuarios ORDER BY id LIMIT 1")
    if not fila:
        raise SystemExit("No hay usuarios en TITAN.")
    return fila["id"]


def _paso(informe, nombre, ok, detalle):
    informe["pasos"].append({"paso": nombre, "ok": bool(ok), "detalle": detalle})
    print(f"  [{'OK' if ok else 'FALLO'}] {nombre}: {detalle}", flush=True)
    return ok


def _traza(modalidad, oid):
    op = almacen.q1(modalidad, "SELECT id, estado, fase, id_externo, precio_entrada, precio_salida, resultado, fuente_resultado, motivo_cierre FROM operaciones WHERE id=?", (oid,))
    return {"operacion": op, "eventos": [{"fase": e["fase"], "id_broker": e["id_broker"], "detalle": (e["detalle"] or "")[:300]}
                                          for e in almacen.eventos(modalidad, oid)]}


def _an(horizonte, texto):
    return {"ts": int(time.time()), "horizonte": horizonte, "fusion": {"justificacion": [texto]}}


def verificar_iq(uid, enviar=False, activo="EURGBP-OTC", espera_max_s=600):
    from . import integraciones
    from .trader.iqoption import IQOption
    inf = {"broker": "IQ Option", "cuenta": "PRACTICE", "pasos": []}
    print("IQ Option (PRACTICE)")
    ad = IQOption(integraciones._config(uid, "iqoption"))
    try:
        api = ad._sesion()
    except Exception as e:
        _paso(inf, "conexión", False, f"{type(e).__name__}: {e}")
        return inf
    _paso(inf, "conexión", ad.conectado(), "check_connect()")
    modo = api.get_balance_mode()
    if not _paso(inf, "cuenta PRACTICE", modo == "PRACTICE", f"get_balance_mode() = {modo}"):
        return inf
    try:
        _paso(inf, "saldo PRACTICE", True, ad.saldo())
    except Exception as e:
        _paso(inf, "saldo PRACTICE", False, f"{type(e).__name__}: {e}")
    try:
        velas = ad.velas_m1(activo, 120)
        _paso(inf, f"velas M1 cerradas de {activo}", len(velas) >= 30, f"{len(velas)} velas, última {velas[-1]['ts'] if velas else None}")
    except Exception as e:
        _paso(inf, f"velas M1 de {activo}", False, f"{type(e).__name__}: {e}")
    import iqoption_data
    try:
        nombre, grupo, abierto = iqoption_data.resolve(activo)
        _paso(inf, f"estado de {activo} en IQ Option (get_all_init_v2)", abierto is not None,
              f"{'ABIERTO' if abierto else 'CERRADO/suspendido' if abierto is False else 'desconocido'} ({grupo})")
    except Exception as e:
        _paso(inf, f"estado de {activo}", False, f"{type(e).__name__}: {e}")
    p = ad.payout(activo)
    _paso(inf, f"payout turbo de {activo}", p is not None, p)
    if p is not None:
        from .backtest_binaria.recolector import registrar_payout
        registrar_payout(activo, p)
    if not enviar:
        return inf
    autotrader.estado(uid, "binaria")
    sol = {"instrumento": activo, "direccion": "alcista", "tipo": "binaria", "monto": 1.0, "riesgo_importe": 1.0, "stop": None,
           "objetivo": None, "stop_dist_pct": None, "obj_dist_pct": None, "precio_ref": None, "expira_ts": int(time.time()) + 300,
           "payout": p, "modalidad": "binaria", "estrategia": ESTRATEGIA, "clase": "binaria"}
    aj = {**autotrader.estado(uid, "binaria")["ajustes"], "estrategia": ESTRATEGIA, "duplicado_ventana_s": 60}
    ctl = [{"control": "verificacion_manual_del_conector", "ok": True, "detalle": "orden mínima de verificación (1 USD, PRACTICE)"}]
    out = autotrader._enviar(uid, "binaria", aj, sol, _an("scalping", "verificación del conector IQ Option"), ad, ctl, [], "binarias",
                             {"modalidad": "binaria"})
    oid = out.get("operacion_id")
    _paso(inf, "orden enviada → respuesta del broker", out.get("accion") == "abrir", {k: out.get(k) for k in ("accion", "id_broker", "confirmada", "error")})
    if not oid or out.get("accion") != "abrir":
        inf["traza"] = _traza("binaria", oid) if oid else None
        return inf
    o = almacen.q1("binaria", "SELECT * FROM operaciones WHERE id=?", (oid,))
    print(f"  … esperando el vencimiento y el resultado de IQ Option (id {o['id_externo']})", flush=True)
    fin = time.time() + espera_max_s
    while time.time() < fin:
        time.sleep(15)
        autotrader.actualizar_abiertas(uid, "binaria", adaptador=ad)
        o = almacen.q1("binaria", "SELECT * FROM operaciones WHERE id=?", (oid,))
        if o["estado"] == "cerrada":
            break
    _paso(inf, "resultado recibido del broker", o["estado"] == "cerrada" and o["fuente_resultado"] == "broker",
          {"estado": o["estado"], "fase": o["fase"], "resultado": o["resultado"], "motivo": o["motivo_cierre"]})
    inf["traza"] = _traza("binaria", oid)
    return inf


def verificar_ctrader(uid, ctid, simbolo, enviar=False):
    from .trader.ctrader import CTrader
    inf = {"broker": "cTrader", "cuenta": f"DEMO {ctid}", "pasos": []}
    print(f"cTrader (DEMO {ctid}, {simbolo})")
    ad = CTrader(uid, "demo", ctid, simbolo)
    try:
        info = ad.cuentas()
    except Exception as e:
        _paso(inf, "autorización OAuth", False, f"{type(e).__name__}: {e}")
        return inf
    c = next((x for x in info["cuentas"] if x["ctid"] == int(ctid)), None)
    _paso(inf, "autorización OAuth", True, f"{len(info['cuentas'])} cuenta(s), permiso {info.get('permiso')}")
    if not _paso(inf, "cuenta DEMO vinculada", bool(c) and not c["real"], c):
        return inf
    try:
        _paso(inf, "saldo DEMO", True, ad.saldo())
        q = ad.cotizacion(simbolo)
        _paso(inf, f"cotización {simbolo}", q.get("bid") is not None, {k: q.get(k) for k in ("bid", "ask", "spread", "edad_s")})
        s = ad.serie(simbolo, "15m", 7 * 86400)
        _paso(inf, f"velas 15m de {simbolo}", len(s["c"]) >= 60, f"{len(s['c'])} velas")
    except Exception as e:
        _paso(inf, "lectura de cuenta/mercado", False, f"{type(e).__name__}: {e}")
        return inf
    if not enviar:
        return inf
    # Riesgo para el volumen MÍNIMO del símbolo (stop 0,3 %, objetivo 0,6 %): la orden más pequeña posible.
    ses = ad._abrir()
    try:
        sim, cat = ad._simbolo(ses, None)
        det = ses.simbolo(sim["id"])
        t = ses.trader()
        conv, moneda = ad._conversion(ses, sim, cat, t["depositAssetId"], q["precio"])
    finally:
        ses.cerrar()
    stop_pct, obj_pct = 0.003, 0.006
    riesgo = (det["vol_min"] or 1) / 100 * (q["ask"] * stop_pct) * conv * 1.02
    sol = {"instrumento": simbolo, "direccion": "alcista", "tipo": "margen", "monto": round(riesgo / stop_pct, 2), "riesgo_importe": riesgo,
           "stop": q["ask"] * (1 - stop_pct), "objetivo": q["ask"] * (1 + obj_pct), "stop_dist_pct": stop_pct, "obj_dist_pct": obj_pct,
           "precio_ref": q["precio"], "expira_ts": None, "payout": None, "modalidad": "demo", "estrategia": ESTRATEGIA, "clase": None}
    aj = {**autotrader.estado(uid, "demo")["ajustes"], "broker": "ctrader", "cuenta_ctid": int(ctid), "simbolo_broker": simbolo,
          "instrumento": simbolo, "estrategia": ESTRATEGIA, "duplicado_ventana_s": 60}
    ctl = [{"control": "verificacion_manual_del_conector", "ok": True,
            "detalle": f"orden mínima de verificación ({det['vol_min'] / 100:g} unidades, DEMO, riesgo {riesgo:.2f} {moneda})"}]
    out = autotrader._enviar(uid, "demo", aj, sol, _an("intradia", "verificación del conector cTrader"), ad, ctl, [], "cfd", {"modalidad": "demo"})
    oid = out.get("operacion_id")
    _paso(inf, "orden enviada → respuesta del broker", out.get("accion") == "abrir", {k: out.get(k) for k in ("accion", "id_broker", "confirmada", "error")})
    if not oid or out.get("accion") != "abrir":
        inf["traza"] = _traza("demo", oid) if oid else None
        return inf
    _paso(inf, "apertura confirmada en las posiciones del broker", bool(out.get("confirmada")), out.get("id_broker"))
    time.sleep(3)
    o = almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (oid,))
    r = None
    for intento in range(6):
        try:
            r = ad.cerrar(o, "cierre de verificación") if intento == 0 else ad.actualizar(o)
            if r:
                break
        except ErrorAdaptador as e:
            print(f"  … {e}", flush=True)
        time.sleep(5)
    if r:
        autotrader._cerrar(uid, "demo", o, r)
    o = almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (oid,))
    _paso(inf, "cierre confirmado y resultado recibido del broker", o["estado"] == "cerrada" and o["fuente_resultado"] == "broker",
          {"estado": o["estado"], "fase": o["fase"], "resultado": o["resultado"], "precio_salida": o["precio_salida"]})
    inf["traza"] = _traza("demo", oid)
    return inf


def main(args):
    args = list(args)
    enviar = "--enviar" in args
    uid = _uid()
    informes = []
    if "--iq" in args:
        activo = args[args.index("--activo") + 1].upper() if "--activo" in args else "EURGBP-OTC"
        informes.append(verificar_iq(uid, enviar, activo))
    if "--ctrader" in args:
        i = args.index("--ctrader")
        informes.append(verificar_ctrader(uid, int(args[i + 1]), args[i + 2].upper(), enviar))
    if not informes:
        print(__doc__)
        return 2
    ok = all(p["ok"] for inf in informes for p in inf["pasos"])
    print(json.dumps({"ok": ok, "informes": informes}, ensure_ascii=False, indent=1, default=str))
    db.set_cfg_sistema("ultima_verificacion_brokers", {"ts": int(time.time()), "ok": ok, "enviar": enviar,
                                                       "resumen": [{"broker": x["broker"], "ok": all(p["ok"] for p in x["pasos"])} for x in informes]})
    return 0 if ok else 1
