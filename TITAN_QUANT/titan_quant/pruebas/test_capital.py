import os
import tempfile
import time
import unittest

from titan_quant.binaria_bot import escaner as es
from titan_quant.binaria_bot.almacen import Almacen
from titan_quant.binaria_bot.capital import (CapitalNoFiable, PoliticaCapital, describir,
                                             leer_capital_practica, monto_para, verificar_coherencia)
from titan_quant.binaria_bot.riesgo import LimitesRiesgo

BASE = 1_700_000_040  # alineado a minuto


class MontoTests(unittest.TestCase):

    def test_uno_por_ciento_del_capital_actual(self):
        p = PoliticaCapital()
        self.assertEqual(monto_para(500.0, p), (5.0, ""))
        self.assertEqual(monto_para(800.0, p), (8.0, ""))

    def test_sin_tope_el_monto_crece_con_el_saldo(self):
        self.assertEqual(monto_para(5000.0, PoliticaCapital()), (50.0, ""))
        self.assertEqual(monto_para(20000.0, PoliticaCapital()), (200.0, ""))

    def test_por_debajo_del_minimo_no_opera(self):
        self.assertEqual(monto_para(50.0, PoliticaCapital()), (None, "capital_insuficiente"))

    def test_capital_cero_o_negativo_no_opera(self):
        self.assertEqual(monto_para(0.0, PoliticaCapital()), (None, "capital_insuficiente"))
        self.assertEqual(monto_para(-20.0, PoliticaCapital()), (None, "capital_insuficiente"))

    def test_capital_no_fiable(self):
        for valor in (None, float("nan"), float("inf"), "1000", True):
            self.assertEqual(monto_para(valor, PoliticaCapital()), (None, "capital_no_fiable"), repr(valor))

    def test_politica_invalida_se_rechaza(self):
        with self.assertRaises(ValueError):
            PoliticaCapital(monto_minimo=0)
        with self.assertRaises(ValueError):
            PoliticaCapital(riesgo_pct=0)
        with self.assertRaises(ValueError):
            PoliticaCapital(riesgo_pct=6)

    def test_describir_resume_la_politica(self):
        self.assertIn("riesgo 1.0%", describir(PoliticaCapital()))


class _FakeIQ:
    def __init__(self, modo="PRACTICE", saldo=1000.0, bloquea=False, error=False):
        self.modo, self.saldo, self.bloquea, self.error = modo, saldo, bloquea, error

    def get_balance_mode(self):
        return self.modo

    def get_balance(self):
        if self.bloquea:
            time.sleep(3)
        if self.error:
            raise RuntimeError("fallo simulado")
        return self.saldo


class LecturaSaldoTests(unittest.TestCase):

    def test_practica_devuelve_el_saldo(self):
        self.assertEqual(leer_capital_practica(_FakeIQ(saldo=1234.5)), 1234.5)

    def test_cuenta_real_se_rechaza(self):
        with self.assertRaises(CapitalNoFiable):
            leer_capital_practica(_FakeIQ(modo="REAL"))

    def test_broker_que_no_responde_se_corta_por_tiempo(self):
        with self.assertRaises(CapitalNoFiable):
            leer_capital_practica(_FakeIQ(bloquea=True), timeout_s=0.2)

    def test_error_del_broker_se_reporta_sin_detener(self):
        with self.assertRaises(CapitalNoFiable):
            leer_capital_practica(_FakeIQ(error=True))

    def test_saldo_invalido_se_rechaza(self):
        for saldo in (0, -5, "100", None, float("nan")):
            with self.assertRaises(CapitalNoFiable, msg=repr(saldo)):
                leer_capital_practica(_FakeIQ(saldo=saldo))


class CoherenciaSaldoTests(unittest.TestCase):

    def test_primera_lectura_se_acepta(self):
        self.assertEqual(verificar_coherencia(1000.0, None, 20.0), "")

    def test_cambio_pequeno_se_acepta(self):
        self.assertEqual(verificar_coherencia(1005.0, 1000.0, 20.0), "")

    def test_cambio_brusco_se_rechaza(self):
        motivo = verificar_coherencia(2000.0, 1000.0, 20.0)
        self.assertIn("cambió 100.0%", motivo)

    def test_caida_brusca_tambien_se_rechaza(self):
        self.assertNotEqual(verificar_coherencia(500.0, 1000.0, 20.0), "")

    def test_umbral_invalido(self):
        with self.assertRaises(ValueError):
            verificar_coherencia(1000.0, 1000.0, 0)

    def test_base_guarda_solo_lecturas_aceptadas(self):
        db = os.path.join(tempfile.mkdtemp(), "saldo.db")
        es._registrar_saldo_coherente(db, 10000.0, 20.0)   # primera: se guarda
        es._registrar_saldo_coherente(db, 10500.0, 20.0)   # 5%: se guarda
        with self.assertRaises(CapitalNoFiable):
            es._registrar_saldo_coherente(db, 30000.0, 20.0)  # brusca: rechazada, no se guarda
        es._registrar_saldo_coherente(db, 10400.0, 20.0)   # se compara contra 10500, no contra 30000
        import sqlite3
        con = sqlite3.connect(db)
        try:
            valores = [r[0] for r in con.execute("SELECT valor FROM lecturas_saldo ORDER BY id")]
        finally:
            con.close()
        self.assertEqual(valores, [10000.0, 10500.0, 10400.0])


def _con():
    d = tempfile.mkdtemp()
    almacen = Almacen(os.path.join(d, "binaria_bot_escaner_capital.db"))
    es._asegurar_esquema(almacen.con)
    return almacen


def _fila(con, activo, ts_senal, ts_entrada, vence, direccion="CALL", entrada=1.0,
          resultado=None, ejecutada=0, decision=None, monto=None, payout=None):
    con.execute(
        "INSERT INTO candidatas (activo, ts_senal, ts_entrada, vence_ts, direccion, entrada, resultado,"
        " ejecutada, decision, monto, payout) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (activo, ts_senal, ts_entrada, vence, direccion, entrada, resultado, ejecutada, decision, monto, payout))
    con.commit()


def _historial(con, activo, n, resultado="ganada", vence_base=BASE - 10_000):
    for i in range(n):
        t = vence_base + i * 100
        _fila(con, activo, t - 360, t - 300, t, resultado=resultado, decision="historial")


class CapitalEnEscanerTests(unittest.TestCase):

    def test_sin_capital_suficiente_abstiene_con_motivo(self):
        a = _con()
        _historial(a.con, "P1", 40)
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), min_resueltas=30, capital_inicial=50.0)
        dec, cat = a.con.execute("SELECT decision, categoria FROM candidatas WHERE ts_entrada=?",
                                 (BASE + 60,)).fetchone()
        self.assertEqual((dec, cat), ("abstener", "capital_insuficiente"))
        a.cerrar()

    def test_al_operar_guarda_monto_y_capital_de_referencia(self):
        a = _con()
        _historial(a.con, "P1", 40)
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), min_resueltas=30, capital_inicial=1000.0)
        dec, monto, cap = a.con.execute(
            "SELECT decision, monto, capital_ref FROM candidatas WHERE ts_entrada=?", (BASE + 60,)).fetchone()
        self.assertEqual(dec, "operar")
        self.assertEqual((monto, cap), (10.0, 1000.0))
        a.cerrar()

    def test_tras_una_perdida_el_monto_baja_y_no_sube(self):
        a = _con()
        _historial(a.con, "P1", 40)
        # Operación previa ya perdida de 10 USD (monto guardado).
        _fila(a.con, "PX", BASE - 2000, BASE - 1940, BASE - 1640, resultado="perdida", ejecutada=1,
              decision="operar", monto=10.0, payout=0.86)
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), min_resueltas=30, capital_inicial=1000.0)
        monto = a.con.execute("SELECT monto FROM candidatas WHERE ts_entrada=? AND activo='P1'",
                              (BASE + 60,)).fetchone()[0]
        self.assertAlmostEqual(monto, 9.9, places=6)  # 1% de 990
        self.assertLess(monto, 10.0)  # no sube para recuperar
        a.cerrar()

    def test_sin_capital_el_comportamiento_legado_no_cambia(self):
        a = _con()
        _historial(a.con, "P1", 40)
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), min_resueltas=30, monto=1.0)
        monto, cap = a.con.execute("SELECT monto, capital_ref FROM candidatas WHERE ts_entrada=?",
                                   (BASE + 60,)).fetchone()
        self.assertEqual((monto, cap), (1.0, None))
        a.cerrar()


if __name__ == "__main__":
    unittest.main()
