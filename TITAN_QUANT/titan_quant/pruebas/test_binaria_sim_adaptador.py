import io
import logging
import time
import unittest

from titan_quant.binaria_sim.adaptador_practica import (
    AdaptadorPractica, CUENTA_PERMITIDA, DURACION_MIN,
)


class FakeAPI:
    """Imita iq.api: el websocket deja el dato en get_options_v2_data al llegar la respuesta."""

    def __init__(self, iq):
        self._iq = iq
        self.get_options_v2_data = None

    def get_options_v2(self, limit, tipo):
        cerradas = self._iq._cerradas
        if isinstance(cerradas, Exception):
            raise cerradas
        if cerradas is None:
            return  # nunca llega respuesta
        if self._iq._retardo:
            import threading
            threading.Timer(self._iq._retardo, lambda: setattr(self, "get_options_v2_data", cerradas)).start()
        else:
            self.get_options_v2_data = cerradas


class FakeIQ:
    """Cliente falso: solo las llamadas que usa el adaptador."""

    def __init__(self, modo="PRACTICE", buy=None, modo_error=False, cerradas=None, retardo_s=0.0):
        self.modo = modo
        self.modo_error = modo_error
        self._buy = buy if buy is not None else (True, 1001)
        self._cerradas = cerradas
        self._retardo = retardo_s
        self.llamadas_buy = []
        self.api = FakeAPI(self)

    def get_balance_mode(self):
        if self.modo_error:
            raise ConnectionError("sin conexión")
        return self.modo

    def buy(self, monto, activo, direccion, duracion):
        self.llamadas_buy.append((monto, activo, direccion, duracion))
        if isinstance(self._buy, Exception):
            raise self._buy
        return self._buy

    def get_optioninfo_v2(self, limit):
        if self._retardo:
            time.sleep(self._retardo)
        if isinstance(self._cerradas, Exception):
            raise self._cerradas
        return self._cerradas


def _cerrada(id_op, win, monto=1.0, neto=None):
    return {"id": [id_op], "win": win, "amount": monto,
            "win_amount": (monto + (neto if neto is not None else 0.8)) if win == "win" else (0 if win == "loose" else monto)}


class AdaptadorPracticaTests(unittest.TestCase):

    def setUp(self):
        self.logs = io.StringIO()
        self.log = logging.getLogger("binaria_sim.practica")
        self.handler = logging.StreamHandler(self.logs)
        self.log.addHandler(self.handler)
        self.log.setLevel(logging.DEBUG)

    def tearDown(self):
        self.log.removeHandler(self.handler)

    # --- cuenta ---
    def test_envia_en_practice(self):
        iq = FakeIQ(modo=CUENTA_PERMITIDA)
        r = AdaptadorPractica(iq).enviar("EURUSD", "CALL", 1.0)
        self.assertEqual(r.estado, "enviada")
        self.assertEqual(r.orden_id, "1001")
        self.assertEqual(iq.llamadas_buy, [(1.0, "EURUSD", "call", DURACION_MIN)])

    def test_bloquea_cuenta_real_sin_enviar(self):
        iq = FakeIQ(modo="REAL")
        r = AdaptadorPractica(iq).enviar("EURUSD", "CALL", 1.0)
        self.assertEqual(r.estado, "rechazada")
        self.assertIn("REAL", r.motivo)
        self.assertEqual(iq.llamadas_buy, [])

    def test_verifica_cuenta_antes_de_cada_orden(self):
        iq = FakeIQ(modo="PRACTICE")
        ad = AdaptadorPractica(iq)
        ad.enviar("EURUSD", "CALL", 1.0)
        iq.modo = "REAL"
        self.assertEqual(ad.enviar("EURUSD", "PUT", 1.0).estado, "rechazada")
        self.assertEqual(len(iq.llamadas_buy), 1)

    def test_no_puede_verificar_cuenta_no_envia(self):
        iq = FakeIQ(modo_error=True)
        self.assertEqual(AdaptadorPractica(iq).enviar("EURUSD", "CALL", 1.0).estado, "rechazada")
        self.assertEqual(iq.llamadas_buy, [])

    # --- validación ---
    def test_interruptor_bloquea(self):
        iq = FakeIQ()
        ad = AdaptadorPractica(iq)
        ad.apagar_nuevas()
        self.assertEqual(ad.enviar("EURUSD", "CALL", 1.0).estado, "rechazada")
        self.assertEqual(iq.llamadas_buy, [])
        ad.reactivar()
        self.assertEqual(ad.enviar("EURUSD", "CALL", 1.0).estado, "enviada")

    def test_monto_fuera_de_limite(self):
        iq = FakeIQ()
        for m in (0, -1, 1.5, "1", None, True):
            self.assertEqual(AdaptadorPractica(iq, monto_max=1.0).enviar("EURUSD", "CALL", m).estado,
                             "rechazada", f"monto {m!r}")
        self.assertEqual(iq.llamadas_buy, [])

    def test_direccion_invalida(self):
        iq = FakeIQ()
        for d in ("call", "BUY", "", None):
            self.assertEqual(AdaptadorPractica(iq).enviar("EURUSD", d, 1.0).estado, "rechazada")
        self.assertEqual(iq.llamadas_buy, [])

    def test_activo_invalido(self):
        iq = FakeIQ()
        self.assertEqual(AdaptadorPractica(iq).enviar("", "CALL", 1.0).estado, "rechazada")
        self.assertEqual(AdaptadorPractica(iq).enviar(None, "CALL", 1.0).estado, "rechazada")

    def test_sin_sesion_no_construye(self):
        with self.assertRaises(ValueError):
            AdaptadorPractica(None)

    # --- respuestas de buy() ---
    def test_rechazo_con_mensaje_es_rechazada(self):
        r = AdaptadorPractica(FakeIQ(buy=(False, "saldo insuficiente"))).enviar("EURUSD", "CALL", 1.0)
        self.assertEqual(r.estado, "rechazada")
        self.assertIn("saldo insuficiente", r.motivo)

    def test_timeout_de_buy_es_desconocida_no_rechazada(self):
        iq = FakeIQ(buy=(False, None))
        self.assertEqual(AdaptadorPractica(iq).enviar("EURUSD", "CALL", 1.0).estado, "desconocida")
        self.assertEqual(len(iq.llamadas_buy), 1, "no debe reintentarse")

    def test_excepcion_tras_envio_es_desconocida(self):
        iq = FakeIQ(buy=ConnectionError("cayó el websocket"))
        self.assertEqual(AdaptadorPractica(iq).enviar("EURUSD", "CALL", 1.0).estado, "desconocida")
        self.assertEqual(len(iq.llamadas_buy), 1)

    def test_ok_true_sin_id_es_desconocida(self):
        self.assertEqual(AdaptadorPractica(FakeIQ(buy=(True, None))).enviar("EURUSD", "CALL", 1.0).estado,
                         "desconocida")

    # --- liquidación ---
    def test_liquidar_ganada_perdida_empate(self):
        iq = FakeIQ(cerradas={"msg": {"closed_options": [
            _cerrada(1001, "win", 1.0, 0.8),
            _cerrada(1002, "loose", 1.0),
            _cerrada(1003, "equal", 1.0),
        ]}})
        ad = AdaptadorPractica(iq)
        est, neto = ad.liquidar("1001")
        self.assertEqual(est, "ganada")
        self.assertAlmostEqual(neto, 0.8, places=6)
        est, neto = ad.liquidar("1002")
        self.assertEqual(est, "perdida")
        self.assertAlmostEqual(neto, -1.0, places=6)
        self.assertEqual(ad.liquidar("1003"), ("empate", 0.0))

    def test_liquidar_orden_aun_no_cerrada_devuelve_none(self):
        iq = FakeIQ(cerradas={"msg": {"closed_options": [_cerrada(9999, "win")]}})
        self.assertIsNone(AdaptadorPractica(iq).liquidar("1001"))

    def test_liquidar_consulta_colgada_no_bloquea(self):
        iq = FakeIQ(cerradas={"msg": {"closed_options": []}}, retardo_s=2.0)
        ad = AdaptadorPractica(iq, timeout_consulta_s=0.2)
        inicio = time.time()
        self.assertIsNone(ad.liquidar("1001"))
        self.assertLess(time.time() - inicio, 1.5, "debe volver por el tiempo máximo, no esperar la consulta")

    def test_liquidar_error_de_consulta_devuelve_none(self):
        iq = FakeIQ(cerradas=ConnectionError("x"))
        self.assertIsNone(AdaptadorPractica(iq).liquidar("1001"))

    def test_liquidar_forma_inesperada_devuelve_none(self):
        self.assertIsNone(AdaptadorPractica(FakeIQ(cerradas={"otra": 1})).liquidar("1001"))

    # --- registros ---
    def test_logs_no_contienen_secretos(self):
        secreto = "CLAVE_SECRETA_XYZ_987"
        AdaptadorPractica(FakeIQ(buy=ConnectionError(secreto))).enviar("EURUSD", "CALL", 1.0)
        self.assertNotIn(secreto, self.logs.getvalue())


if __name__ == "__main__":
    unittest.main()
