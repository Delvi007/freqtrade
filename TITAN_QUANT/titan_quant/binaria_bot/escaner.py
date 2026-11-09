"""Escáner de binarias sobre DATOS HISTÓRICOS (backtest/replay de archivos de la sonda). No envía órdenes a ningún broker.
Sus «operaciones» son RESULTADOS HISTÓRICOS CALCULADOS, nunca operaciones de IQ Option.

Un ciclo:
  1. Descubre pares en una carpeta (archivos *_5s.json). No usa lista fija.
  2. Genera candidatas con la estrategia Keltner+RCI en cada par, por tramo continuo de M1.
  3. Registra cada candidata una sola vez (clave: par, instante de señal, dirección).
  4. Resuelve las candidatas cuyo vencimiento ya tiene datos.
  5. Decide en orden cronológico usando SOLO resultados vencidos antes de la entrada (sin información futura).
  6. Calcula sobre el histórico las mejores oportunidades que superan el filtro, respetando límites.

Vencimiento: fijo de 5 minutos. El "TITAN SMART EXPIRATION ENGINE" no existe en el código disponible
y no se simula.

Abstención: sin payout fiable, con muestra previa insuficiente, o con límite inferior de Wilson
que no supera el equilibrio, el escáner no opera.
"""
import argparse
import glob
import json
import os
import re
import time
from datetime import datetime, timezone

from titan_quant.binaria_bot.almacen import Almacen
from titan_quant.binaria_bot.capital import (CapitalNoFiable, PoliticaCapital, describir,
                                             leer_capital_practica, monto_para, verificar_coherencia)
from titan_quant.binaria_bot.datos import agregar_m1, cargar_crudas, tramos_continuos
from titan_quant.binaria_bot.estadistica import Z_95, intervalo_wilson, punto_equilibrio
from titan_quant.binaria_bot.niveles import NIVEL_DEFECTO, configurar
from titan_quant.binaria_bot.riesgo import GestorRiesgo, LimitesRiesgo
from titan_quant.estrategias.keltner_rci import senales

ESTRATEGIA = "keltner_rci_m1"
VENCIMIENTO_VELAS = 5
SEG_VELA = 60
MIN_RESUELTAS_DEFECTO = 30
MAX_ABIERTAS_DEFECTO = 3

ESQUEMA = """
CREATE TABLE IF NOT EXISTS candidatas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activo TEXT NOT NULL,
    ts_senal INTEGER NOT NULL,
    ts_entrada INTEGER NOT NULL,
    vence_ts INTEGER NOT NULL,
    direccion TEXT NOT NULL,
    entrada REAL NOT NULL,
    salida REAL,
    resultado TEXT,
    decision TEXT,
    categoria TEXT,
    motivo TEXT,
    calidad REAL,
    ejecutada INTEGER NOT NULL DEFAULT 0,
    payout REAL,
    UNIQUE(activo, ts_senal, direccion)
);
CREATE INDEX IF NOT EXISTS ix_candidatas_activo_venc ON candidatas(activo, vence_ts);
"""


def _asegurar_esquema(con):
    con.executescript(ESQUEMA)
    columnas = [r[1] for r in con.execute("PRAGMA table_info(candidatas)")]
    if "payout" not in columnas:
        con.execute("ALTER TABLE candidatas ADD COLUMN payout REAL")
    if "monto" not in columnas:
        con.execute("ALTER TABLE candidatas ADD COLUMN monto REAL")
    if "capital_ref" not in columnas:
        con.execute("ALTER TABLE candidatas ADD COLUMN capital_ref REAL")
    con.commit()


# Lista cerrada de monedas fiduciarias ISO 4217. Añadir una moneda es una decisión explícita.
MONEDAS_FIAT = frozenset({
    "USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "NOK", "SEK", "ZAR", "HKD", "INR", "SGD",
    "TRY", "MXN", "PLN", "THB", "IDR", "MYR", "PHP", "VND", "ARS", "BDT", "BOB", "BRL", "CLP", "COP",
    "DOP", "AED", "NGN", "SAR",
})
PATRON_PAR_OTC = re.compile(r"^([A-Z]{3})([A-Z]{3})-OTC$")


def es_par_otc(nombre):
    """Par OTC de divisas, p. ej. EURUSD-OTC: ambos códigos son monedas fiduciarias de MONEDAS_FIAT.
    Excluye acciones (AMAZON-OTC), ETFs, materias primas (XAUUSD-OTC, USOUSD-OTC), índices y cripto (BCHUSD-OTC)."""
    m = PATRON_PAR_OTC.match(nombre or "")
    if not m:
        return False
    base, cotizada = m.group(1), m.group(2)
    return base != cotizada and base in MONEDAS_FIAT and cotizada in MONEDAS_FIAT


def cargar_payouts(ruta):
    """JSON {"EURUSD-OTC": 0.85, ...}. Valores fuera de (0, 5) se rechazan."""
    with open(ruta, "r", encoding="utf-8") as f:
        datos = json.load(f)
    if not isinstance(datos, dict):
        raise ValueError("el archivo de payouts debe ser un objeto JSON")
    out = {}
    for par, valor in datos.items():
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not (0 < valor < 5):
            raise ValueError(f"payout inválido para {par}: {valor!r}")
        out[str(par)] = float(valor)
    return out


def _payout_de(payout, activo):
    """payout puede ser un float global o un dict por par. Devuelve None si no hay dato."""
    if isinstance(payout, dict):
        return payout.get(activo)
    return payout


def descubrir_pares(carpeta):
    """Devuelve {nombre_par: ruta}. Solo archivos *_5s.json; el nombre es el prefijo del archivo."""
    pares = {}
    for ruta in sorted(glob.glob(os.path.join(carpeta, "*_5s.json"))):
        nombre = os.path.basename(ruta)[: -len("_5s.json")]
        if nombre:
            pares[nombre] = ruta
    return pares


def candidatas_de_par(activo, m1):
    """Señales Keltner+RCI del par. Entrada: apertura de j+1. Vencimiento: cierre de j+5."""
    salida = []
    for tramo in tramos_continuos(m1):
        high = [v.high for v in tramo]
        low = [v.low for v in tramo]
        close = [v.close for v in tramo]
        for e in senales(high, low, close):
            j = e["indice"]
            if j + VENCIMIENTO_VELAS >= len(tramo):
                continue  # sin vela de vencimiento: no se registra
            salida.append({
                "activo": activo,
                "ts_senal": tramo[j].ts,
                "ts_entrada": tramo[j].ts + SEG_VELA,
                "vence_ts": tramo[j + VENCIMIENTO_VELAS].ts + SEG_VELA,
                "direccion": "CALL" if e["direccion"] == "compra" else "PUT",
                "entrada": tramo[j + 1].open,
            })
    return salida


def registrar_candidatas(con, cands):
    nuevas = 0
    for c in cands:
        cur = con.execute(
            "INSERT OR IGNORE INTO candidatas (activo, ts_senal, ts_entrada, vence_ts, direccion, entrada)"
            " VALUES (?,?,?,?,?,?)",
            (c["activo"], c["ts_senal"], c["ts_entrada"], c["vence_ts"], c["direccion"], c["entrada"]))
        nuevas += cur.rowcount
    con.commit()
    return nuevas


def _resultado(direccion, entrada, salida):
    if salida == entrada:
        return "empate"
    if (direccion == "CALL") == (salida > entrada):
        return "ganada"
    return "perdida"


def resolver(con, precios):
    """precios: {activo: {ts_inicio_vela: cierre}}. Solo resuelve con el cierre de la vela de vencimiento."""
    filas = con.execute("SELECT id, activo, direccion, entrada, vence_ts FROM candidatas WHERE resultado IS NULL").fetchall()
    n = 0
    for cid, act, dire, ent, venc in filas:
        salida = precios.get(act, {}).get(venc - SEG_VELA)
        if salida is None:
            continue
        con.execute("UPDATE candidatas SET salida=?, resultado=? WHERE id=?",
                    (salida, _resultado(dire, ent, salida), cid))
        n += 1
    con.commit()
    return n


def estadisticas_previas(con, activo, ts):
    """Aciertos y fallos de candidatas del par YA VENCIDAS antes de `ts`. Nunca usa resultados futuros."""
    g, p = con.execute(
        "SELECT COALESCE(SUM(resultado='ganada'),0), COALESCE(SUM(resultado='perdida'),0)"
        " FROM candidatas WHERE activo=? AND vence_ts<=? AND resultado IN ('ganada','perdida')",
        (activo, ts)).fetchone()
    return int(g), int(p)


def decidir(g, p, payout, min_resueltas, z=Z_95):
    """Devuelve (operar, calidad, categoria, detalle). Calidad = límite inferior de Wilson - equilibrio."""
    if payout is None or not (0 < payout < 5):
        return False, None, "payout_desconocido", "payout no disponible: sin datos fiables, se abstiene"
    n = g + p
    if n < min_resueltas:
        return False, None, "muestra_insuficiente", f"{n} resultados previos; se exigen {min_resueltas}"
    bajo, _ = intervalo_wilson(g, n, z)
    eq = punto_equilibrio(payout)
    calidad = round(bajo - eq, 6)
    if bajo <= eq:
        return False, calidad, "sin_ventaja", f"Wilson inferior {bajo:.3f} no supera equilibrio {eq:.3f} (n={n})"
    return True, calidad, "ventaja", f"Wilson inferior {bajo:.3f} > equilibrio {eq:.3f} (n={n})"


def _neto(resultado, payout, monto=1.0):
    if resultado == "ganada":
        return payout * monto
    if resultado == "perdida":
        return -monto
    return 0.0


def estado_riesgo(con, ts, payout, limites):
    """Estado de riesgo reconstruido SOLO con operaciones ya vencidas en `ts`."""
    g = GestorRiesgo(limites)
    dia = ts // 86400
    filas = con.execute(
        "SELECT vence_ts, resultado, payout, monto FROM candidatas WHERE ejecutada=1 AND resultado IS NOT NULL"
        " AND vence_ts<=? ORDER BY vence_ts", (ts,)).fetchall()
    for venc, res, pay, mon in filas:
        neto = _neto(res, pay if pay is not None else payout, mon if mon is not None else 1.0)
        g.equity += neto
        g.pico = max(g.pico, g.equity)
        if venc // 86400 == dia:
            g.pnl_dia += neto
        if neto < 0:
            g.racha += 1
        elif neto > 0:
            g.racha = 0
    entradas = [r[0] for r in con.execute("SELECT ts_entrada FROM candidatas WHERE ejecutada=1 AND ts_entrada<=?", (ts,))]
    g.ops_dia = sum(1 for t in entradas if t // 86400 == dia)
    abiertas = [r[0] for r in con.execute(
        "SELECT activo FROM candidatas WHERE ejecutada=1 AND ts_entrada<=? AND vence_ts>?", (ts, ts))]
    return g, abiertas


def _gestor_del_momento(gestor, capital_inicial, politica, monto, base):
    """Gestor con límites recalculados desde el capital del instante (porcentajes del capital de referencia).
    El monto queda fijado para esta decisión. Estado de riesgo copiado sin modificar el original."""
    cap = capital_inicial + gestor.equity
    inicio_dia = cap - gestor.pnl_dia
    lim = LimitesRiesgo(
        monto_base=monto, monto_max=monto,
        perdida_diaria_max=politica.perdida_diaria_pct / 100.0 * inicio_dia,
        drawdown_max=politica.drawdown_pct / 100.0 * (capital_inicial + gestor.pico),
        racha_perdidas_max=base.racha_perdidas_max, ops_diarias_max=base.ops_diarias_max)
    g = GestorRiesgo(lim)
    g.equity, g.pico, g.pnl_dia = gestor.equity, gestor.pico, gestor.pnl_dia
    g.ops_dia, g.racha = gestor.ops_dia, gestor.racha
    return g


def procesar_decisiones(con, payout, limites, max_abiertas=MAX_ABIERTAS_DEFECTO,
                        min_resueltas=MIN_RESUELTAS_DEFECTO, monto=1.0,
                        capital_inicial=None, politica=None, z=Z_95):
    """Decide cada candidata en orden cronológico. Una decisión, una vez tomada, no se recalcula.
    Con capital_inicial, el monto se recalcula en cada instante desde el capital actual (sin martingala)."""
    filas = con.execute(
        "SELECT id, activo, ts_entrada FROM candidatas WHERE decision IS NULL ORDER BY ts_entrada, activo, direccion"
    ).fetchall()
    por_ts = {}
    for cid, act, ts in filas:
        por_ts.setdefault(ts, []).append((cid, act))
    for ts in sorted(por_ts):
        evaluadas = []
        for cid, act in por_ts[ts]:
            g, p = estadisticas_previas(con, act, ts)
            ok, cal, cat, det = decidir(g, p, _payout_de(payout, act), min_resueltas, z)
            evaluadas.append({"id": cid, "activo": act, "ok": ok, "cal": cal, "cat": cat, "det": det})
        evaluadas.sort(key=lambda x: (not x["ok"], -(x["cal"] if x["cal"] is not None else 0.0)))
        gestor, abiertas = estado_riesgo(con, ts, payout, limites)
        abiertas = list(abiertas)
        monto_usado = monto
        if capital_inicial is not None:
            pol = politica or PoliticaCapital()
            monto_ts, motivo_cap = monto_para(capital_inicial + gestor.equity, pol)
            if monto_ts is not None and (capital_inicial + gestor.equity - gestor.pnl_dia) <= 0:
                monto_ts, motivo_cap = None, "capital_insuficiente"
            if monto_ts is None:
                for e in evaluadas:
                    if e["ok"]:
                        e["ok"], e["cat"], e["det"] = False, motivo_cap, f"capital: {motivo_cap}"
            else:
                gestor = _gestor_del_momento(gestor, capital_inicial, pol, monto_ts, limites)
                monto_usado = monto_ts
        for e in evaluadas:
            if not e["ok"]:
                dec, mot = "abstener", e["det"]
            elif e["activo"] in abiertas:
                dec, mot = "omitida", "ya hay una operación abierta en el par"
            elif len(abiertas) >= max_abiertas:
                dec, mot = "omitida", "límite de posiciones abiertas"
            else:
                ok2, m2 = gestor.puede_operar(monto_usado)
                if not ok2:
                    dec, mot = "bloqueada", m2
                else:
                    dec, mot = "operar", e["det"]
                    abiertas.append(e["activo"])
                    gestor.ops_dia += 1
                    con.execute("UPDATE candidatas SET ejecutada=1, payout=?, monto=?, capital_ref=? WHERE id=?",
                                (_payout_de(payout, e["activo"]), monto_usado,
                                 (capital_inicial + gestor.equity) if capital_inicial is not None else None,
                                 e["id"]))
            cat = e["cat"] if not e["ok"] else ("ventaja" if dec == "operar" else dec)
            con.execute("UPDATE candidatas SET decision=?, categoria=?, motivo=?, calidad=? WHERE id=?",
                        (dec, cat, mot, e["cal"], e["id"]))
        con.commit()


def resumen_db(con):
    decisiones = dict(con.execute(
        "SELECT decision, COUNT(*) FROM candidatas WHERE decision IS NOT NULL GROUP BY decision").fetchall())
    abstenciones = con.execute(
        "SELECT categoria, COUNT(*) FROM candidatas WHERE decision='abstener' GROUP BY categoria ORDER BY COUNT(*) DESC"
    ).fetchall()
    ops = con.execute(
        "SELECT activo, direccion, ts_entrada, vence_ts, entrada, salida, resultado, calidad, monto, capital_ref"
        " FROM candidatas WHERE ejecutada=1 ORDER BY ts_entrada, activo").fetchall()
    return {
        "decisiones": decisiones,
        "abstenciones_por_categoria": abstenciones,
        "operaciones_calculadas": [
            {"activo": a, "direccion": d, "ts_entrada": te, "vence_ts": tv, "entrada": e,
             "salida": s, "resultado": r, "calidad": c, "monto": mo, "capital_ref": cr}
            for a, d, te, tv, e, s, r, c, mo, cr in ops],
    }


def ciclo(carpeta, ruta_db, payout=None, limites=None, max_abiertas=MAX_ABIERTAS_DEFECTO,
          min_resueltas=None, monto=1.0, solo_otc=True,
          capital_inicial=None, politica=None, nivel=None, capital_fuente="manual"):
    limites = limites or LimitesRiesgo()
    almacen = Almacen(ruta_db)
    con = almacen.con
    try:
        _asegurar_esquema(con)
        rep = {"carpeta": carpeta, "payout": payout, "candidatas_nuevas": 0, "resueltas": 0, "pares": {},
               "instante_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
               "capital_inicial": capital_inicial, "capital_fuente": capital_fuente,
               "politica": describir(politica or PoliticaCapital()) if capital_inicial is not None else None,
               "nivel": None, "z": None, "min_resueltas": None}
        precios = {}
        for nombre, ruta in descubrir_pares(carpeta).items():
            if solo_otc and not es_par_otc(nombre):
                rep["pares"][nombre] = {"estado": "excluido",
                                        "motivo": "no es par OTC de divisas (exclusión decidida por el operador)"}
                continue
            try:
                m1 = agregar_m1(cargar_crudas(ruta))
            except (OSError, ValueError, KeyError, TypeError) as e:
                rep["pares"][nombre] = {"estado": "descartado", "motivo": f"no legible ({type(e).__name__})"}
                continue
            if not m1:
                rep["pares"][nombre] = {"estado": "descartado", "motivo": "sin velas M1 completas"}
                continue
            precios[nombre] = {v.ts: v.close for v in m1}
            cands = candidatas_de_par(nombre, m1)
            nuevas = registrar_candidatas(con, cands)
            rep["candidatas_nuevas"] += nuevas
            rep["pares"][nombre] = {"estado": "analizado", "velas_m1": len(m1),
                                    "candidatas": len(cands), "nuevas": nuevas}
        k = sum(1 for v in rep["pares"].values() if v["estado"] == "analizado")
        if nivel is None:
            exig = {"nombre": None, "z": Z_95, "min_resueltas": min_resueltas or MIN_RESUELTAS_DEFECTO}
        else:
            # Corrección de Bonferroni sobre el universo de pares evaluables (los que tienen payout).
            universo = max(k, len(payout) if isinstance(payout, dict) else 0)
            exig = configurar(nivel, max(1, universo), min_resueltas)
        rep["nivel"], rep["z"], rep["min_resueltas"] = exig["nombre"], exig["z"], exig["min_resueltas"]
        rep["resueltas"] = resolver(con, precios)
        procesar_decisiones(con, payout, limites, max_abiertas, exig["min_resueltas"], monto,
                            capital_inicial=capital_inicial, politica=politica, z=exig["z"])
        rep["resumen"] = resumen_db(con)
        return rep
    finally:
        almacen.cerrar()


def texto_reporte(rep):
    def fecha(ts):
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pay = rep['payout']
    pay_txt = f"por par ({len(pay)} pares)" if isinstance(pay, dict) else str(pay)
    L = [f"Ciclo {rep['instante_utc']} | carpeta: {rep['carpeta']} | payout: {pay_txt}",
         f"Candidatas nuevas: {rep['candidatas_nuevas']} | resultados resueltos en este ciclo: {rep['resueltas']}",
         "", "PARES DESCUBIERTOS"]
    if not rep["pares"]:
        L.append("  ninguno (no hay archivos *_5s.json en la carpeta)")
    for n, info in sorted(rep["pares"].items()):
        if info["estado"] == "analizado":
            L.append(f"  {n}: velas M1 {info['velas_m1']}, candidatas {info['candidatas']} (nuevas {info['nuevas']})")
        else:
            L.append(f"  {n}: {info['estado'].upper()} - {info['motivo']}")
    if rep.get("capital_inicial") is not None:
        L.insert(1, f"Capital de referencia del backtest: {rep['capital_inicial']:.2f} ({rep['capital_fuente']}) | {rep['politica']}")
    if rep.get("nivel"):
        L.insert(2, f"Exigencia: nivel {rep['nivel']} | z={rep['z']:.3f} | mínimo {rep['min_resueltas']} resultados previos")
    r = rep["resumen"]
    L += ["", "DECISIONES (acumuladas en la base)"]
    for k, v in sorted(r["decisiones"].items()):
        L.append(f"  {k}: {v}")
    L += ["", "ABSTENCIONES POR CATEGORÍA"]
    for cat, n in r["abstenciones_por_categoria"]:
        L.append(f"  {cat}: {n}")
    L += ["", "OPERACIONES CALCULADAS SOBRE EL HISTÓRICO (backtest, no son operaciones de broker)"]
    if not r["operaciones_calculadas"]:
        L.append("  ninguna: ninguna candidata superó los filtros con la evidencia disponible")
    for o in r["operaciones_calculadas"]:
        extra = ""
        if o["monto"] is not None:
            extra = f" | monto {o['monto']:.2f} | capital ref {o['capital_ref']:.2f}" if o["capital_ref"] is not None \
                else f" | monto {o['monto']:.2f}"
        L.append(f"  {o['activo']} {o['direccion']} entrada {fecha(o['ts_entrada'])} "
                 f"vence {fecha(o['vence_ts'])} -> {o['resultado'] or 'pendiente'}{extra}")
    L += ["", "Resultado histórico calculado: no se envió ninguna orden a ningún broker."]
    return "\n".join(L)


def _registrar_saldo_coherente(ruta_db, valor, umbral_pct):
    """Compara el saldo con la última lectura ACEPTADA. Si cambió más de umbral_pct %, lanza CapitalNoFiable
    y NO guarda la lectura: la siguiente se compara contra la última válida."""
    almacen = Almacen(ruta_db)
    try:
        con = almacen.con
        con.execute("CREATE TABLE IF NOT EXISTS lecturas_saldo (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "ts INTEGER NOT NULL, valor REAL NOT NULL)")
        fila = con.execute("SELECT valor FROM lecturas_saldo ORDER BY id DESC LIMIT 1").fetchone()
        motivo = verificar_coherencia(valor, fila[0] if fila else None, umbral_pct)
        if motivo:
            raise CapitalNoFiable(motivo)
        con.execute("INSERT INTO lecturas_saldo (ts, valor) VALUES (?, ?)", (int(time.time()), float(valor)))
        con.commit()
    finally:
        almacen.cerrar()


def capital_desde_practica():
    """Saldo de la cuenta PRACTICE. Solo lectura: no envía órdenes ni cambia de cuenta.
    Credenciales desde variables de entorno de la ventana actual (IQOPTION_EMAIL, IQOPTION_PASSWORD)."""
    email = os.environ.get("IQOPTION_EMAIL", "")
    clave = os.environ.get("IQOPTION_PASSWORD", "")
    if not email or not clave:
        raise CapitalNoFiable("faltan credenciales en esta ventana")
    from iqoptionapi.stable_api import IQ_Option
    try:
        iq = IQ_Option(email, clave)
        ok, motivo = iq.connect()
    except Exception as e:  # noqa: BLE001
        raise CapitalNoFiable(f"error al conectar ({type(e).__name__})") from None
    if not ok:
        raise CapitalNoFiable(f"no se conectó: {motivo}")
    return leer_capital_practica(iq)


def main(argv=None):
    p = argparse.ArgumentParser(description="Escáner de binarias en simulación (sin órdenes reales)")
    p.add_argument("--carpeta", required=True, help="carpeta con archivos *_5s.json")
    p.add_argument("--db", required=True, help="base SQLite independiente (.db)")
    p.add_argument("--payout", type=float, default=None, help="payout global (p. ej. 0.86)")
    p.add_argument("--payouts", default=None, help="JSON con payout por par; los pares sin dato se abstienen")
    p.add_argument("--max-abiertas", type=int, default=MAX_ABIERTAS_DEFECTO)
    p.add_argument("--min-resueltas", type=int, default=None, help="anula el mínimo del nivel elegido")
    p.add_argument("--nivel", type=int, choices=[1, 2, 3], default=NIVEL_DEFECTO,
                   help="1 básico, 2 estricto (predeterminado), 3 exigente")
    p.add_argument("--capital-desde-practica", action="store_true",
                   help="tomar el capital inicial del saldo PRACTICE (solo lectura)")
    p.add_argument("--umbral-saldo-pct", type=float, default=20.0,
                   help="%% máximo de cambio del saldo entre lecturas; si se supera, no opera")
    p.add_argument("--monto", type=float, default=1.0)
    p.add_argument("--ciclos", type=int, default=1, help="0 = continuo hasta interrumpir")
    p.add_argument("--espera-s", type=float, default=300.0)
    p.add_argument("--informe", default=None)
    p.add_argument("--incluir-no-otc", action="store_true", help="incluir ETFs, acciones e índices")
    p.add_argument("--capital-inicial", type=float, default=None,
                   help="capital de la simulación; si se indica, el monto se recalcula desde el capital actual")
    p.add_argument("--riesgo-pct", type=float, default=1.0, help="%% del capital actual por operación")
    p.add_argument("--monto-minimo", type=float, default=1.0, help="mínimo del broker (verificar en la plataforma)")
    p.add_argument("--perdida-diaria-pct", type=float, default=3.0, help="%% del capital al inicio del día")
    p.add_argument("--drawdown-pct", type=float, default=5.0, help="%% del pico de capital")
    a = p.parse_args(argv)
    if a.capital_desde_practica and a.capital_inicial is not None:
        p.error("use --capital-inicial o --capital-desde-practica, no ambos")
    capital_inicial, capital_fuente = a.capital_inicial, "manual"
    if a.capital_desde_practica:
        if not (0 < a.umbral_saldo_pct <= 100):
            p.error("--umbral-saldo-pct debe estar en (0, 100]")
        try:
            capital_inicial = capital_desde_practica()
            _registrar_saldo_coherente(a.db, capital_inicial, a.umbral_saldo_pct)
        except CapitalNoFiable as e:
            print(f"NO OPERA: capital no fiable: {e}")
            return 2
        capital_fuente = "saldo PRACTICE"
    payout_arg = cargar_payouts(a.payouts) if a.payouts else a.payout
    politica = PoliticaCapital(riesgo_pct=a.riesgo_pct, monto_minimo=a.monto_minimo,
                               perdida_diaria_pct=a.perdida_diaria_pct, drawdown_pct=a.drawdown_pct)
    i = 0
    while a.ciclos == 0 or i < a.ciclos:
        rep = ciclo(a.carpeta, a.db, payout_arg, None, a.max_abiertas, a.min_resueltas, a.monto,
                    solo_otc=not a.incluir_no_otc, capital_inicial=capital_inicial, politica=politica,
                    nivel=a.nivel, capital_fuente=capital_fuente)
        texto = texto_reporte(rep)
        print(texto)
        if a.informe:
            with open(a.informe, "w", encoding="utf-8") as f:
                f.write(texto + "\n")
        i += 1
        if a.ciclos == 0 or i < a.ciclos:
            time.sleep(a.espera_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
