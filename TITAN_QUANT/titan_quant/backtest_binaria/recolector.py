"""Recolección del histórico del mercado binario (solo lectura; no envía órdenes).

    recopilar_iqoption(activo, velas=…)  velas M1 CERRADAS de IQ Option, incremental desde la última guardada
    registrar_payout(activo, payout)     payout observado en IQ Option (para backtests con payout real)
    importar_sonda(ruta, activo)         archivo *_5s.json de la sonda → velas M1 completas
    importar_csv(ruta, activo, fuente)   CSV exportado por el usuario (titan_quant.binaria.datos_csv)
"""
import time

from . import INTERVALO, almacen

PROVEEDOR_IQ = "iqoption"
LOTE = 1000                       # IQ Option devuelve lotes de hasta 1000 velas


def _api_iq(sesion=None):
    if sesion is not None:
        return sesion
    import iqoption_data
    return iqoption_data._api()


def recopilar_iqoption(activo, velas=3000, sesion=None, resolver=None, ahora=None, intervalo=INTERVALO):
    """Descarga hasta `velas` velas CERRADAS de la temporalidad indicada, sin repetir las ya guardadas. Solo lectura."""
    from ..historico import SEG
    paso = SEG[intervalo]
    activo = str(activo).upper()
    api = _api_iq(sesion)
    if resolver is None:
        import iqoption_data
        resolver = iqoption_data.resolve
    nombre, _, _ = resolver(activo)
    alm = almacen()
    ultimo = alm.ultimo_ts(PROVEEDOR_IQ, activo, intervalo)
    ahora = int(ahora or (api.get_server_timestamp() if hasattr(api, "get_server_timestamp") else 0) or time.time())
    fin = ahora - ahora % paso               # inicio de la vela en formación: solo se guardan velas anteriores (cerradas)
    pedir = int(velas)
    filas, peticiones, end = {}, 0, fin - 1
    while pedir > 0 and peticiones < 50:
        n = min(LOTE, pedir)
        lote = api.get_candles(nombre, paso, n, end) or []
        peticiones += 1
        limpias = []
        for x in lote:
            try:
                ts = int(x.get("from", x.get("at")))
                limpias.append([ts, float(x["open"]), float(x.get("max", x.get("high"))), float(x.get("min", x.get("low"))),
                                float(x["close"]), float(x.get("volume") or 0)])
            except (TypeError, ValueError, KeyError):
                continue
        limpias = [f for f in limpias if f[0] + paso <= fin]
        if not limpias:
            break
        for f in limpias:
            filas[f[0]] = f
        mas_antigua = min(f[0] for f in limpias)
        if ultimo is not None and mas_antigua <= ultimo:
            break                            # ya enlazamos con lo guardado
        end = mas_antigua - 1
        pedir -= len(limpias)
        if len(limpias) < n:
            break
    nuevas = [f for t, f in sorted(filas.items()) if ultimo is None or t > ultimo]
    r = alm.guardar(PROVEEDOR_IQ, activo, intervalo, nuevas) if nuevas else {"guardadas": 0, "rechazadas": 0}
    return {"activo": activo, "proveedor": PROVEEDOR_IQ, "intervalo": intervalo, "peticiones": peticiones, "recibidas": len(filas), **r,
            "huecos": len(alm.huecos(PROVEEDOR_IQ, activo, intervalo))}


def registrar_payout(activo, payout, fuente="iqoption get_all_profit (turbo)", ts=None):
    if payout is None or not (0 < float(payout) < 1.5):
        return False
    alm = almacen()
    with alm.tx() as c:
        c.execute("INSERT OR REPLACE INTO payouts(activo,ts,payout,fuente) VALUES(?,?,?,?)",
                  (str(activo).upper(), int(ts or time.time()), float(payout), fuente))
    return True


def payout_observado(activo):
    """Mediana de los payouts observados en IQ Option para el par, o None si no hay ninguno."""
    filas = [r["payout"] for r in almacen().q("SELECT payout FROM payouts WHERE activo=? ORDER BY payout", (str(activo).upper(),))]
    if not filas:
        return None, 0
    m = len(filas) // 2
    med = filas[m] if len(filas) % 2 else (filas[m - 1] + filas[m]) / 2
    return med, len(filas)


def importar_sonda(ruta, activo):
    from ..binaria_bot.datos import agregar_m1, cargar_crudas
    m1 = agregar_m1(cargar_crudas(ruta))
    filas = [[v.ts, v.open, v.high, v.low, v.close, 0.0] for v in m1]
    return {"activo": str(activo).upper(), "proveedor": "sonda", **almacen().guardar("sonda", str(activo).upper(), INTERVALO, filas)}


def importar_csv(ruta, activo, fuente):
    from ..binaria import datos_csv
    velas, _ = datos_csv.leer(ruta, activo, fuente)
    filas = [[v[0], v[1], v[2], v[3], v[4], 0.0] for v in velas]
    prov = "csv:" + str(fuente)
    return {"activo": str(activo).upper(), "proveedor": prov, **almacen().guardar(prov, str(activo).upper(), INTERVALO, filas)}
