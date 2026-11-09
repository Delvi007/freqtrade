import json
import os
import random
import tempfile
import unittest

from titan_quant.binaria_bot.almacen import Almacen
from titan_quant.binaria_bot import escaner as es
from titan_quant.binaria_bot.riesgo import LimitesRiesgo

BASE = 1_700_000_040  # alineado a minuto


def _con():
    d = tempfile.mkdtemp()
    almacen = Almacen(os.path.join(d, "binaria_bot_escaner_prueba.db"))
    es._asegurar_esquema(almacen.con)
    return almacen


def _fila(con, activo, ts_senal, ts_entrada, vence, direccion="CALL", entrada=1.0,
          resultado=None, ejecutada=0, decision=None):
    con.execute(
        "INSERT INTO candidatas (activo, ts_senal, ts_entrada, vence_ts, direccion, entrada, resultado, ejecutada, decision)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (activo, ts_senal, ts_entrada, vence, direccion, entrada, resultado, ejecutada, decision))
    con.commit()


def _historial(con, activo, n, resultado="ganada", vence_base=BASE - 10_000):
    for i in range(n):
        t = vence_base + i * 100  # 40 vencimientos entre BASE-10000 y BASE-6100: todos antes de la prueba
        _fila(con, activo, t - 360, t - 300, t, resultado=resultado, decision="historial")


class ResolucionTests(unittest.TestCase):

    def test_call_gana_si_sube_put_gana_si_baja_empate(self):
        self.assertEqual(es._resultado("CALL", 1.0, 1.1), "ganada")
        self.assertEqual(es._resultado("CALL", 1.0, 0.9), "perdida")
        self.assertEqual(es._resultado("PUT", 1.0, 0.9), "ganada")
        self.assertEqual(es._resultado("PUT", 1.0, 1.1), "perdida")
        self.assertEqual(es._resultado("CALL", 1.0, 1.0), "empate")


class DescubrimientoTests(unittest.TestCase):

    def test_descubre_pares_sin_lista_fija(self):
        d = tempfile.mkdtemp()
        for nombre in ("EURUSD-OTC_5s.json", "GBPUSD-OTC_5s.json", "EURUSD-OTC_60s.json", "notas.txt"):
            with open(os.path.join(d, nombre), "w", encoding="utf-8") as f:
                f.write("{}")
        self.assertEqual(set(es.descubrir_pares(d)), {"EURUSD-OTC", "GBPUSD-OTC"})


class DecisionTests(unittest.TestCase):

    def test_sin_payout_no_opera_y_lo_declara(self):
        a = _con()
        _historial(a.con, "P1", 40)
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, None, LimitesRiesgo())
        dec, cat = a.con.execute("SELECT decision, categoria FROM candidatas WHERE ts_entrada=?", (BASE + 60,)).fetchone()
        self.assertEqual((dec, cat), ("abstener", "payout_desconocido"))
        self.assertEqual(a.con.execute("SELECT COUNT(*) FROM candidatas WHERE ejecutada=1").fetchone()[0], 0)
        a.cerrar()

    def test_muestra_insuficiente_no_opera(self):
        a = _con()
        _historial(a.con, "P1", 10)
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo())
        cat = a.con.execute("SELECT categoria FROM candidatas WHERE ts_entrada=?", (BASE + 60,)).fetchone()[0]
        self.assertEqual(cat, "muestra_insuficiente")
        a.cerrar()

    def test_causal_resultados_futuros_no_cuentan(self):
        a = _con()
        # 40 aciertos, pero todos vencen DESPUÉS de la entrada: no deben contar.
        for i in range(40):
            _fila(a.con, "P1", BASE + i, BASE + 60 + i, BASE + 360 + i, resultado="ganada")
        g, p = es.estadisticas_previas(a.con, "P1", BASE + 60)
        self.assertEqual((g, p), (0, 0))
        a.cerrar()

    def test_opera_con_evidencia_y_respeta_max_abiertas(self):
        a = _con()
        for par in ("P1", "P2", "P3"):
            _historial(a.con, par, 40)
        for par in ("P1", "P2", "P3"):
            _fila(a.con, par, BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), max_abiertas=1, min_resueltas=30)
        ops = a.con.execute("SELECT COUNT(*) FROM candidatas WHERE ejecutada=1").fetchone()[0]
        omit = a.con.execute("SELECT COUNT(*) FROM candidatas WHERE decision='omitida'").fetchone()[0]
        self.assertEqual(ops, 1)
        self.assertEqual(omit, 2)
        a.cerrar()

    def test_no_duplica_operacion_en_el_mismo_par(self):
        a = _con()
        _historial(a.con, "P1", 40)
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360, direccion="CALL")
        _fila(a.con, "P1", BASE + 1, BASE + 60, BASE + 360, direccion="PUT")
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), max_abiertas=5, min_resueltas=30)
        ops = a.con.execute("SELECT COUNT(*) FROM candidatas WHERE ejecutada=1").fetchone()[0]
        self.assertEqual(ops, 1)
        a.cerrar()

    def test_racha_de_perdidas_bloquea_nuevas_operaciones(self):
        a = _con()
        _historial(a.con, "P1", 40)
        for i in range(3):  # tres operaciones ejecutadas y perdidas, ya vencidas
            t = BASE - 5000 + i * 600
            _fila(a.con, "PX", t, t + 60, t + 360, resultado="perdida", ejecutada=1, decision="operar")
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        lim = LimitesRiesgo(racha_perdidas_max=3)
        es.procesar_decisiones(a.con, 0.86, lim, max_abiertas=5, min_resueltas=30)
        dec = a.con.execute("SELECT decision FROM candidatas WHERE ts_entrada=?", (BASE + 60,)).fetchone()[0]
        self.assertEqual(dec, "bloqueada")
        a.cerrar()

    def test_decision_no_se_recalcula(self):
        a = _con()
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, None, LimitesRiesgo())
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), min_resueltas=0)
        dec = a.con.execute("SELECT decision FROM candidatas").fetchone()[0]
        self.assertEqual(dec, "abstener", "una decisión ya tomada no debe cambiar")
        a.cerrar()


class PayoutPorParTests(unittest.TestCase):

    def test_par_sin_payout_se_abstiene(self):
        a = _con()
        _historial(a.con, "EURUSD-OTC", 40)
        _fila(a.con, "EURUSD-OTC", BASE, BASE + 60, BASE + 360)
        _historial(a.con, "GBPUSD-OTC", 40)
        _fila(a.con, "GBPUSD-OTC", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, {"EURUSD-OTC": 0.85}, LimitesRiesgo(), min_resueltas=30)
        cat = dict(a.con.execute("SELECT activo, categoria FROM candidatas WHERE decision IS NOT NULL AND ts_entrada=?", (BASE + 60,)).fetchall())
        self.assertEqual(cat["GBPUSD-OTC"], "payout_desconocido")
        a.cerrar()

    def test_riesgo_usa_el_payout_guardado_de_cada_operacion(self):
        a = _con()
        _fila(a.con, "EURUSD-OTC", BASE - 2000, BASE - 1940, BASE - 1640, resultado="ganada", ejecutada=1, decision="operar")
        a.con.execute("UPDATE candidatas SET payout=0.85 WHERE activo='EURUSD-OTC'")
        a.con.commit()
        g, _ = es.estado_riesgo(a.con, BASE, 0.86, LimitesRiesgo())
        self.assertAlmostEqual(g.equity, 0.85, places=6)
        a.cerrar()

    def test_cargar_payouts_valida_el_archivo(self):
        d = tempfile.mkdtemp()
        ok = os.path.join(d, "ok.json")
        with open(ok, "w", encoding="utf-8") as f:
            json.dump({"EURUSD-OTC": 0.85, "AUDCAD-OTC": 0.85}, f)
        self.assertEqual(es.cargar_payouts(ok), {"EURUSD-OTC": 0.85, "AUDCAD-OTC": 0.85})
        malo = os.path.join(d, "malo.json")
        with open(malo, "w", encoding="utf-8") as f:
            json.dump({"EURUSD-OTC": 9}, f)
        with self.assertRaises(ValueError):
            es.cargar_payouts(malo)


class CicloTests(unittest.TestCase):

    def _crudas(self, carpeta, nombre, minutos=400, seed=1):
        rnd = random.Random(seed)
        velas, p, t = [], 1.30, BASE
        for _ in range(minutos * 12):
            o = p
            c = o + rnd.gauss(0, 0.0004)
            velas.append({"from": t, "open": o, "close": c, "max": max(o, c) + 0.0001,
                          "min": min(o, c) - 0.0001, "volume": 0})
            p, t = c, t + 5
        with open(os.path.join(carpeta, nombre), "w", encoding="utf-8") as f:
            json.dump({"meta": {}, "velas": velas}, f)

    def test_ciclo_idempotente_sin_duplicar_candidatas(self):
        carpeta = tempfile.mkdtemp()
        self._crudas(carpeta, "EURUSD-OTC_5s.json", seed=1)
        self._crudas(carpeta, "GBPUSD-OTC_5s.json", seed=2)
        db = os.path.join(tempfile.mkdtemp(), "b.db")
        r1 = es.ciclo(carpeta, db, payout=0.86)
        r2 = es.ciclo(carpeta, db, payout=0.86)
        self.assertGreater(r1["candidatas_nuevas"], 0)
        self.assertEqual(r2["candidatas_nuevas"], 0)
        self.assertEqual(set(r1["pares"]), {"EURUSD-OTC", "GBPUSD-OTC"})

    def test_sin_payout_el_ciclo_no_simula_operaciones(self):
        carpeta = tempfile.mkdtemp()
        self._crudas(carpeta, "EURUSD-OTC_5s.json", seed=3)
        db = os.path.join(tempfile.mkdtemp(), "b.db")
        rep = es.ciclo(carpeta, db, payout=None)
        self.assertEqual(rep["resumen"]["operaciones_calculadas"], [])
        self.assertNotIn("operar", rep["resumen"]["decisiones"])

    def test_excluye_etfs_y_acciones_por_defecto(self):
        carpeta = tempfile.mkdtemp()
        self._crudas(carpeta, "EURUSD-OTC_5s.json", seed=5)
        self._crudas(carpeta, "SPY_5s.json", seed=6)
        self._crudas(carpeta, "AMAZON-OTC_5s.json", seed=8)
        db = os.path.join(tempfile.mkdtemp(), "b.db")
        rep = es.ciclo(carpeta, db, payout=0.86)
        self.assertEqual(rep["pares"]["SPY"]["estado"], "excluido")
        self.assertEqual(rep["pares"]["AMAZON-OTC"]["estado"], "excluido")
        self.assertEqual(rep["pares"]["EURUSD-OTC"]["estado"], "analizado")

    def test_incluye_no_otc_si_se_pide(self):
        carpeta = tempfile.mkdtemp()
        self._crudas(carpeta, "SPY_5s.json", seed=7)
        db = os.path.join(tempfile.mkdtemp(), "b.db")
        rep = es.ciclo(carpeta, db, payout=0.86, solo_otc=False)
        self.assertEqual(rep["pares"]["SPY"]["estado"], "analizado")

    def test_es_par_otc(self):
        self.assertTrue(es.es_par_otc("EURUSD-OTC"))
        self.assertFalse(es.es_par_otc("SPY"))
        self.assertFalse(es.es_par_otc("DIA"))
        self.assertTrue(es.es_par_otc("USDZAR-OTC"))
        self.assertTrue(es.es_par_otc("EURGBP-OTC"))
        for no_divisa in ("AMAZON-OTC", "GOOGLE-OTC", "KLARNA-OTC", "COFFEE-OTC", "BCHUSD-OTC",
                          "XAUUSD-OTC", "USOUSD-OTC", "ETHBTC-OTC", "ZZZUSD-OTC", "USDUSD-OTC"):
            self.assertFalse(es.es_par_otc(no_divisa), no_divisa)
        self.assertFalse(es.es_par_otc("EURUSD"))  # sin sufijo OTC
        self.assertFalse(es.es_par_otc(None))

    def test_archivo_roto_se_descarta_sin_detener(self):
        carpeta = tempfile.mkdtemp()
        with open(os.path.join(carpeta, "NZDUSD-OTC_5s.json"), "w", encoding="utf-8") as f:
            f.write("{no es json")
        self._crudas(carpeta, "AUDUSD-OTC_5s.json", seed=4)
        db = os.path.join(tempfile.mkdtemp(), "b.db")
        rep = es.ciclo(carpeta, db, payout=0.86)
        self.assertEqual(rep["pares"]["NZDUSD-OTC"]["estado"], "descartado")
        self.assertEqual(rep["pares"]["AUDUSD-OTC"]["estado"], "analizado")


if __name__ == "__main__":
    unittest.main()
