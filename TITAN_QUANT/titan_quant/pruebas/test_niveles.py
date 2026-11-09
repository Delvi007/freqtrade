import os
import tempfile
import unittest
from unittest import mock

from titan_quant.binaria_bot import escaner as es
from titan_quant.binaria_bot.almacen import Almacen
from titan_quant.binaria_bot.capital import CapitalNoFiable
from titan_quant.binaria_bot.niveles import NIVEL_DEFECTO, configurar, z_para
from titan_quant.binaria_bot.riesgo import LimitesRiesgo

BASE = 1_700_000_040


class NivelesTests(unittest.TestCase):

    def test_nivel_basico_es_wilson_95_sin_correccion(self):
        self.assertAlmostEqual(z_para(1, 55), 1.959963984540054, places=9)

    def test_nivel_estricto_corrige_por_pares(self):
        # Bonferroni con 55 pares: z ≈ 3.317 (verificado en la sesión)
        self.assertAlmostEqual(z_para(2, 55), 3.317, places=3)
        self.assertAlmostEqual(z_para(3, 55), 3.317, places=3)

    def test_mas_pares_mas_exigencia(self):
        self.assertLess(z_para(2, 10), z_para(2, 55))

    def test_configurar_usa_el_predeterminado_y_sus_minimos(self):
        cfg = configurar()
        self.assertEqual((cfg["nivel"], cfg["nombre"], cfg["min_resueltas"]), (NIVEL_DEFECTO, "estricto", 100))
        self.assertEqual(configurar(3, 55)["min_resueltas"], 300)

    def test_min_resueltas_manual_anula_el_del_nivel(self):
        self.assertEqual(configurar(2, 55, min_resueltas=50)["min_resueltas"], 50)

    def test_entradas_invalidas_se_rechazan(self):
        with self.assertRaises(ValueError):
            configurar(4)
        with self.assertRaises(ValueError):
            z_para(2, 0)
        with self.assertRaises(ValueError):
            configurar(2, 5, min_resueltas=0)

    def test_nivel_estricto_rechaza_lo_que_el_basico_acepta(self):
        # 70 aciertos de 100: Wilson inferior ~0.605 con z=1.96 (supera 0.5376),
        # ~0.535 con z=3.317 (no supera). Este caso separa los dos niveles.
        ok_basico, *_ = es.decidir(70, 30, 0.86, 30, z=z_para(1, 55))
        ok_estricto, *_ = es.decidir(70, 30, 0.86, 30, z=configurar(2, 55)["z"])
        self.assertTrue(ok_basico)
        self.assertFalse(ok_estricto)


def _con():
    d = tempfile.mkdtemp()
    almacen = Almacen(os.path.join(d, "b.db"))
    es._asegurar_esquema(almacen.con)
    return almacen


def _fila(con, activo, ts_senal, ts_entrada, vence, resultado=None, ejecutada=0, decision=None):
    con.execute("INSERT INTO candidatas (activo, ts_senal, ts_entrada, vence_ts, direccion, entrada, resultado,"
                " ejecutada, decision) VALUES (?,?,?,?,?,?,?,?,?)",
                (activo, ts_senal, ts_entrada, vence, "CALL", 1.0, resultado, ejecutada, decision))
    con.commit()


class NivelEnEscanerTests(unittest.TestCase):

    def test_nivel_estricto_exige_100_resultados_previos(self):
        a = _con()
        for i in range(40):  # 40 aciertos previos: suficiente para el nivel 1, no para el 2
            t = BASE - 10_000 + i * 100
            _fila(a.con, "P1", t - 360, t - 300, t, resultado="ganada", decision="historial")
        _fila(a.con, "P1", BASE, BASE + 60, BASE + 360)
        es.procesar_decisiones(a.con, 0.86, LimitesRiesgo(), min_resueltas=100, z=configurar(2, 55)["z"])
        cat = a.con.execute("SELECT categoria FROM candidatas WHERE ts_entrada=?", (BASE + 60,)).fetchone()[0]
        self.assertEqual(cat, "muestra_insuficiente")
        a.cerrar()


class UniversoDeParesTests(unittest.TestCase):

    def test_bonferroni_usa_el_universo_de_pares_con_payout(self):
        import json
        import random
        carpeta = tempfile.mkdtemp()
        rnd, velas, p, t = random.Random(1), [], 1.30, BASE
        for _ in range(400 * 12):
            o = p
            c = o + rnd.gauss(0, 0.0004)
            velas.append({"from": t, "open": o, "close": c, "max": max(o, c) + 0.0001,
                          "min": min(o, c) - 0.0001, "volume": 0})
            p, t = c, t + 5
        with open(os.path.join(carpeta, "EURUSD-OTC_5s.json"), "w", encoding="utf-8") as f:
            json.dump({"meta": {}, "velas": velas}, f)
        universo = {f"PAR{i:02d}-OTC": 0.86 for i in range(55)}  # 55 pares con payout; solo 1 analizado
        rep = es.ciclo(carpeta, os.path.join(tempfile.mkdtemp(), "b.db"), payout=universo, nivel=2)
        self.assertAlmostEqual(rep["z"], 3.317, places=3)


class SaldoPracticaEnEscanerTests(unittest.TestCase):

    def test_sin_credenciales_no_opera_y_devuelve_2(self):
        carpeta, db = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "b.db")
        with mock.patch.dict(os.environ, {}, clear=True):
            codigo = es.main(["--carpeta", carpeta, "--db", db, "--capital-desde-practica"])
        self.assertEqual(codigo, 2)

    def test_capital_desde_practica_sin_credenciales_falla(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CapitalNoFiable):
                es.capital_desde_practica()

    def test_no_se_pueden_usar_dos_fuentes_de_capital(self):
        carpeta, db = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "b.db")
        with self.assertRaises(SystemExit):
            es.main(["--carpeta", carpeta, "--db", db, "--capital-desde-practica", "--capital-inicial", "1000"])


if __name__ == "__main__":
    unittest.main()
