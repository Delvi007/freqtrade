"""Payout IQ Option: una consulta atascada (get_all_profit sin respuesta) no debe bloquear el bot,
ni lanzar consultas en cascada. Sin red: la API se sustituye por una falsa."""
import threading
import time
import unittest
from unittest import mock

from titan_quant.trader import iqoption as iqmod


class _ApiFalsa:
    def __init__(self, espera, valor):
        self.espera = espera
        self.valor = valor
        self.llamadas = 0

    def get_all_profit(self):
        self.llamadas += 1
        self.espera.wait(5)
        return self.valor


class PayoutTests(unittest.TestCase):

    def setUp(self):
        iqmod._PAYOUT_HILO = None
        self.espera = threading.Event()
        self._t = mock.patch.object(iqmod, "PAYOUT_TIMEOUT_S", 0.2)
        self._t.start()

    def tearDown(self):
        self.espera.set()
        if iqmod._PAYOUT_HILO is not None:
            iqmod._PAYOUT_HILO.join(5)
        iqmod._PAYOUT_HILO = None
        self._t.stop()

    def _api(self, api):
        return mock.patch.object(iqmod, "_api", return_value=api)

    def test_consulta_atascada_no_bloquea(self):
        api = _ApiFalsa(self.espera, {})
        t0 = time.time()
        with self._api(api):
            valor = iqmod.IQOption({}).payout("EURGBP-OTC")
        self.assertIsNone(valor)
        self.assertLess(time.time() - t0, 2)

    def test_no_lanza_otra_consulta_mientras_la_anterior_sigue(self):
        api = _ApiFalsa(self.espera, {})
        with self._api(api):
            iqmod.IQOption({}).payout("EURGBP-OTC")
            iqmod.IQOption({}).payout("EURGBP-OTC")
        self.assertEqual(api.llamadas, 1)

    def test_resultado_normal(self):
        api = _ApiFalsa(self.espera, {"EURGBP-OTC": {"turbo": 0.86}})
        self.espera.set()
        with self._api(api):
            valor = iqmod.IQOption({}).payout("EURGBP-OTC")
        self.assertEqual(valor, 0.86)


if __name__ == "__main__":
    unittest.main()
