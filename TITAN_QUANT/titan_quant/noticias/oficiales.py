"""Datos OFICIALES publicados (fuente primaria): API pública v1 del U.S. Bureau of Labor Statistics (sin clave; límite
oficial 25 consultas/día → TITAN consulta como mucho 4 veces al día). Completa el calendario, que no trae el dato publicado.

Series: IPC general y subyacente (CPI-U, índice → variación mensual e interanual calculadas), tasa de paro, nóminas no
agrícolas (variación mensual en miles) y salario medio por hora.
"""
import json
import ssl
import time
import urllib.request

from . import almacen

URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
SERIES = {"CUUR0000SA0": ("IPC (CPI-U) EE. UU.", "indice"), "CUUR0000SA0L1E": ("IPC subyacente EE. UU.", "indice"),
          "LNS14000000": ("Tasa de paro EE. UU.", "tasa"), "CES0000000001": ("Nóminas no agrícolas EE. UU. (miles)", "nivel"),
          "CES0500000003": ("Salario medio por hora EE. UU.", "nivel")}
CADA_S = 6 * 3600
ESQUEMA = """CREATE TABLE IF NOT EXISTS datos_oficiales(serie TEXT NOT NULL, nombre TEXT, periodo TEXT NOT NULL, valor REAL, var_mensual REAL,
    var_anual REAL, preliminar INTEGER, fuente TEXT, recibido_ts INTEGER, PRIMARY KEY(serie, periodo))"""


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def consultar(abrir=None):
    req = urllib.request.Request(URL, data=json.dumps({"seriesid": list(SERIES)}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "TITAN-QUANT/7.2"})
    r = (abrir or (lambda q: urllib.request.urlopen(q, timeout=30, context=_ctx())))(req)
    d = json.loads(r.read())
    if d.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("BLS: " + "; ".join(d.get("message") or ["respuesta no válida"]))
    return d["Results"]["series"]


def guardar(series, ahora=None):
    ahora = int(ahora or time.time())
    n = 0
    with almacen.tx() as c:
        c.execute(ESQUEMA)
        for s in series:
            sid = s["seriesID"]
            nombre, tipo = SERIES.get(sid, (sid, "nivel"))
            datos = [x for x in s.get("data") or [] if str(x.get("period", "")).startswith("M") and x.get("period") != "M13"]
            por = {(int(x["year"]), int(x["period"][1:])): float(x["value"]) for x in datos if x.get("value") not in (None, "-")}
            for x in datos:
                try:
                    y, m, v = int(x["year"]), int(x["period"][1:]), float(x["value"])
                except (ValueError, KeyError):
                    continue
                prev = por.get((y - 1, 12) if m == 1 else (y, m - 1))
                anio = por.get((y - 1, m))
                if tipo == "indice":
                    vm = (v / prev - 1) * 100 if prev else None
                    va = (v / anio - 1) * 100 if anio else None
                elif tipo == "tasa":
                    vm, va = (v - prev) if prev is not None else None, (v - anio) if anio is not None else None
                else:
                    vm, va = (v - prev) if prev is not None else None, (v / anio - 1) * 100 if anio else None
                pre = int(any((f or {}).get("code") == "P" for f in x.get("footnotes") or []))
                c.execute("""INSERT INTO datos_oficiales(serie,nombre,periodo,valor,var_mensual,var_anual,preliminar,fuente,recibido_ts) VALUES(?,?,?,?,?,?,?,?,?)
                             ON CONFLICT(serie,periodo) DO UPDATE SET valor=excluded.valor, var_mensual=excluded.var_mensual, var_anual=excluded.var_anual,
                             preliminar=excluded.preliminar, recibido_ts=excluded.recibido_ts""",
                          (sid, nombre, f"{y}-{m:02d}", v, vm, va, pre, "U.S. Bureau of Labor Statistics (API pública v1)", ahora))
                n += 1
    return n


def actualizar_si_toca(abrir=None):
    ult = almacen.ajuste("bls_ultima_ts", 0) or 0
    if time.time() - ult < CADA_S:
        return 0
    almacen.guardar_ajuste("bls_ultima_ts", int(time.time()))
    return guardar(consultar(abrir))


def ultimos():
    try:
        filas = almacen.q("""SELECT d.* FROM datos_oficiales d JOIN (SELECT serie, MAX(periodo) p FROM datos_oficiales GROUP BY serie) u
                            ON u.serie=d.serie AND u.p=d.periodo ORDER BY d.serie""")
    except Exception:
        return []
    return filas
