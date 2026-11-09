"""Estados de una orden de IQ Option según la respuesta REAL de la librería (stable_api.buy / get_options_v2).
Se usa una sesión FALSA que reproduce las formas de respuesta de la librería; no hay red ni dinero.
Lo que se comprueba: el adaptador nunca convierte una respuesta ambigua en 'aceptada' ni inventa un resultado."""
import json
import threading
import time
import unittest
from unittest import mock

from titan_quant.trader.base import ErrorAdaptador, OrdenNoConfirmada
from titan_quant.trader.iqoption import IQOption, resultado_de_cerrada


class Canal:
    def __init__(self, cerradas=None, responde=True):
        self.buy_multi_option = {}
        self.get_options_v2_data = None
        self.socket_option_opened = {}
        self._cerradas, self._responde = cerradas, responde

    def get_options_v2(self, limite, tipos):
        if self._responde:
            def _r():
                time.sleep(0.05)
                self.get_options_v2_data = {"msg": {"closed_options": self._cerradas or []}}
            threading.Thread(target=_r, daemon=True).start()


class SesionFalsa:
    def __init__(self, modo="PRACTICE", buy=(True, 777), cerradas=None, responde=True, msg_creacion=True):
        self.modo, self._buy = modo, buy
        self.api = Canal(cerradas, responde)
        self.msg_creacion = msg_creacion
        self.compras = []

    def get_balance_mode(self):
        return self.modo

    def check_connect(self):
        return True

    def buy(self, monto, activo, accion, minutos):
        self.compras.append((monto, activo, accion, minutos))
        if isinstance(self._buy, Exception):
            raise self._buy
        ok, oid = self._buy
        if ok is True and oid is not None and self.msg_creacion:
            self.api.buy_multi_option = {"42": {"id": oid, "created": 1793000000, "exp": 1793000300, "value": 0.8701, "profit_income": 186}}
        return ok, oid


SOL = {"modalidad": "binaria", "tipo": "binaria", "instrumento": "EURGBP-OTC", "direccion": "alcista", "monto": 1.0}


class TestEstadosIQOption(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch("iqoption_data.resolve", return_value=("EURGBP-OTC", "turbo", True))
        self.p.start()
        self.addCleanup(self.p.stop)

    def _sol(self):
        return {**SOL, "expira_ts": int(time.time()) + 300}

    def test_aceptada_con_evidencia_del_broker(self):
        ad = IQOption({}, api=SesionFalsa())
        r = ad.abrir(self._sol())
        self.assertEqual((r["id_externo"], r["precio_entrada"], r["payout"]), ("777", 0.8701, 0.86))
        self.assertEqual(r["evidencia"]["cuenta"], "PRACTICE")
        v = ad.verificar_apertura({"id_externo": "777", "evidencia": json.dumps(r["evidencia"])})
        self.assertTrue(v["confirmada"])

    def test_sin_mensaje_de_creacion_no_se_confirma_la_apertura(self):
        ad = IQOption({}, api=SesionFalsa(msg_creacion=False))
        r = ad.abrir(self._sol())
        self.assertIsNone(r["precio_entrada"])                                   # no se inventa el precio
        self.assertFalse(ad.verificar_apertura({"id_externo": "777", "evidencia": json.dumps(r["evidencia"])})["confirmada"])

    def test_rechazo_del_broker(self):
        with self.assertRaises(ErrorAdaptador):
            IQOption({}, api=SesionFalsa(buy=(False, "Not enough money"))).abrir(self._sol())

    def test_respuesta_ambigua_o_excepcion_no_es_rechazo(self):
        for buy in ((False, None), (True, None), ConnectionError("caída")):
            with self.subTest(buy=buy):
                with self.assertRaises(OrdenNoConfirmada):
                    IQOption({}, api=SesionFalsa(buy=buy)).abrir(self._sol())

    def test_cuenta_real_bloqueada_antes_de_enviar(self):
        s = SesionFalsa(modo="REAL")
        with self.assertRaises(ErrorAdaptador):
            IQOption({}, api=s).abrir(self._sol())
        self.assertEqual(s.compras, [])

    def test_mercado_de_estado_desconocido_no_se_opera(self):
        self.p.stop()
        with mock.patch("iqoption_data.resolve", return_value=("EURGBP-OTC", "estatico", None)):
            s = SesionFalsa()
            with self.assertRaises(ErrorAdaptador):
                IQOption({}, api=s).abrir(self._sol())
            self.assertEqual(s.compras, [])
        self.p.start()

    def test_resultado_solo_desde_el_registro_de_cerradas(self):
        op = {"id_externo": "777", "monto": 1.0, "expira_ts": int(time.time()) - 10}
        self.assertIsNone(IQOption({}, api=SesionFalsa(cerradas=[])).actualizar(op))                     # aún no consta
        self.assertIsNone(IQOption({}, api=SesionFalsa(responde=False)).actualizar(op))                  # sin respuesta
        ganada = [{"id": [777], "win": "win", "amount": 1.0, "win_amount": 1.86}]
        r = IQOption({}, api=SesionFalsa(cerradas=ganada)).actualizar(op)
        self.assertAlmostEqual(r["resultado"], 0.86)
        self.assertEqual(r["evidencia"]["fuente"], "IQ Option closed_options")
        perdida = [{"id": [777], "win": "loose", "amount": 1.0, "win_amount": 0}]
        self.assertAlmostEqual(IQOption({}, api=SesionFalsa(cerradas=perdida)).actualizar(op)["resultado"], -1.0)
        self.assertIsNone(IQOption({}, api=SesionFalsa(cerradas=[{"id": [777], "win": "raro"}])).actualizar(op))
        self.assertIsNone(IQOption({}, api=SesionFalsa(cerradas=ganada)).actualizar({**op, "expira_ts": int(time.time()) + 60}))

    def test_resultado_de_cerrada(self):
        self.assertEqual(resultado_de_cerrada({"win": "equal"}), ("empate", 0.0))
        self.assertIsNone(resultado_de_cerrada({"win": "win", "amount": None, "win_amount": 2}))

    def test_activo_sin_id_conocido_no_se_envia(self):
        s = SesionFalsa()
        with mock.patch("iqoption_data.id_activo", return_value=None):
            with self.assertRaises(ErrorAdaptador):
                IQOption({}, api=s).abrir(self._sol())
        self.assertEqual(s.compras, [])


class InitV2:
    """Imita get_all_init_v2: activos de binarias/turbo con enabled / is_suspended (forma verificada el 09/11/2026)."""
    def __init__(self, v2=None, espera=0):
        self.v2, self.espera = v2, espera

    def get_all_init_v2(self):
        time.sleep(self.espera)
        return self.v2


V2 = {"turbo": {"actives": {"77": {"name": "front.EURGBP-OTC", "enabled": True, "is_suspended": True},
                            "999001": {"name": "front.USDXYZ-OTC", "enabled": True, "is_suspended": False},
                            "1862": {"name": "front.EURGBP-op", "enabled": False, "is_suspended": False}}},
      "binary": {"actives": {}}}


class TestEstadoBinarias(unittest.TestCase):
    def setUp(self):
        import iqoption_data
        self.d = iqoption_data
        self.d._BIN.update(ts=0.0, estado=None, hilo=None)
        self.addCleanup(self.d._BIN.update, ts=0.0, estado=None, hilo=None)

    def test_abierto_solo_si_habilitado_y_no_suspendido(self):
        e = self.d.estado_binarias(InitV2(V2))
        self.assertEqual(e["EURGBP-OTC"]["turbo"], False)          # suspendido
        self.assertEqual(e["USDXYZ-OTC"]["turbo"], True)
        self.assertEqual(e["EURGBP-op"]["turbo"], False)
        self.assertEqual(e["USDXYZ-OTC"]["id"], 999001)

    def test_sin_respuesta_es_estado_desconocido(self):
        self.assertIsNone(self.d.estado_binarias(InitV2(None)))
        self.assertIsNone(self.d.estado_binarias(InitV2(V2, espera=2), timeout=0.2))

    def test_consulta_en_curso_se_espera_y_no_devuelve_none(self):
        import threading
        api, res = InitV2(V2, espera=0.5), []
        hilos = [threading.Thread(target=lambda: res.append(self.d.estado_binarias(api, timeout=3))) for _ in range(3)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(len(res), 3)
        self.assertTrue(all(r and r["USDXYZ-OTC"]["turbo"] for r in res))      # todos reciben el estado real

    def test_ultimo_estado_real_si_iq_option_tarda(self):
        self.d.estado_binarias(InitV2(V2))
        self.d._BIN["ts"] -= 120                                                 # caducado (TTL) pero reciente
        self.assertIsNotNone(self.d.estado_binarias(InitV2(None)))
        self.d._BIN["ts"] -= 600                                                 # demasiado antiguo: desconocido
        self.assertIsNone(self.d.estado_binarias(InitV2(None)))

    def test_otc_con_estado_conocido_no_usa_get_instruments(self):
        with mock.patch.object(self.d, "_api", return_value=object()), \
             mock.patch.object(self.d, "estado_binarias", return_value={"USDXYZ-OTC": {"turbo": True}}), \
             mock.patch.object(self.d, "_catalogo_grupo", side_effect=AssertionError("no debe llamarse")):
            with self.assertRaises(LookupError):
                self.d.resolve("COFFEE-OTC")

    def test_id_del_activo_desde_iq_option_si_falta_en_la_tabla(self):
        from iqoptionapi import constants as OP
        self.d.estado_binarias(InitV2(V2))
        self.addCleanup(OP.ACTIVES.pop, "USDXYZ-OTC", None)
        self.assertNotIn("USDXYZ-OTC", OP.ACTIVES)
        self.assertEqual(self.d.id_activo("USDXYZ-OTC"), 999001)
        self.assertEqual(OP.ACTIVES["USDXYZ-OTC"], 999001)
        self.assertIsNone(self.d.id_activo("NOEXISTE-OTC"))
        self.assertEqual(self.d.id_activo("EURGBP-OTC"), OP.ACTIVES["EURGBP-OTC"])   # la tabla estática manda


if __name__ == "__main__":
    unittest.main()


class CanalHistorial(Canal):
    """Imita portfolio.get-history-positions (forma real observada el 09/11/2026)."""
    def __init__(self, posiciones):
        super().__init__(responde=False)
        self.position_history_v2 = None
        self._pos = posiciones

    def get_position_history_v2(self, tipo, limite, offset, inicio, fin):
        self.position_history_v2 = {"name": "history-positions", "status": 2000,
                                    "msg": {"positions": [p for p in self._pos if p["instrument_type"] == tipo]}}


class TestHistorialBroker(unittest.TestCase):
    def test_resultado_desde_el_historial_de_posiciones(self):
        s = SesionFalsa()
        s.api = CanalHistorial([{"external_id": 14433471986, "instrument_type": "turbo-option", "status": "closed", "close_reason": "loose",
                                 "open_quote": 18.434495, "close_quote": 18.420905, "pnl_net": -1, "invest": 1}])
        op = {"id_externo": "14433471986", "monto": 1.0, "expira_ts": int(time.time()) - 10}
        r = IQOption({}, api=s).actualizar(op)
        self.assertEqual((r["resultado"], r["precio_salida"], r["motivo"]), (-1.0, 18.420905, "vencimiento (perdida)"))
        self.assertEqual(r["evidencia"]["fuente"], "IQ Option portfolio.get-history-positions")

    def test_abierta_en_historial_no_da_resultado(self):
        s = SesionFalsa()
        s.api = CanalHistorial([{"external_id": 5, "instrument_type": "turbo-option", "status": "open", "pnl_net": 0}])
        self.assertIsNone(IQOption({}, api=s).actualizar({"id_externo": "5", "monto": 1.0, "expira_ts": int(time.time()) - 10}))

    def test_payout_desde_profit_income(self):
        from titan_quant.trader.iqoption import _payout_de_profit_income
        self.assertEqual(_payout_de_profit_income(183), 0.83)
        self.assertIsNone(_payout_de_profit_income(83))
