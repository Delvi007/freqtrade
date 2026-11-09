"""C2–C9: matriz y conectores de brokers, centro de brokers, supervisor, cerebro autónomo, laboratorio cuántico y centro de servidores."""
import io
import json
import time
import unittest
from unittest import mock

import numpy as np

from titan_quant import db
from titan_quant.brokers import catalogo, centro
from titan_quant.brokers.base import ErrorBroker
from titan_quant.brokers.conectores import Alpaca, Kraken, OANDA
from titan_quant.pruebas.base_prueba import Base
from titan_quant.seguridad import boveda, interruptores
from titan_quant.trader.base import ErrorAdaptador


class Resp(io.BytesIO):
    status = 200


def servidor_falso(rutas):
    """abrir_url simulado: rutas {('GET','/v3/accounts'): dict | callable(req)}. Registra las peticiones."""
    llamadas = []

    def abrir(req):
        ruta = req.full_url.split("://", 1)[1].split("/", 1)[1]
        ruta = "/" + ruta.split("?")[0]
        llamadas.append((req.get_method(), ruta, dict(req.header_items()), req.data))
        r = rutas.get((req.get_method(), ruta))
        if r is None:
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 404, "no", {}, io.BytesIO(b'{"error":"no"}'))
        r = r(req) if callable(r) else r
        return Resp(json.dumps(r).encode())
    abrir.llamadas = llamadas
    return abrir


class TestCatalogo(unittest.TestCase):
    def test_matriz_completa_y_honesta(self):
        ids = {b["id"] for b in catalogo.B}
        for b in ("ibkr", "tastytrade", "tradestation", "schwab", "alpaca", "tradier", "webull", "ninjatrader", "tradovate", "moomoo", "saxo", "ig",
                  "oanda", "cmc", "xtb", "capital", "swissquote", "fxcm", "trading212", "coinbase", "kraken", "ctrader", "mt4", "mt5"):
            self.assertIn(b, ids)
        for b in catalogo.lista():
            for k in ("apis", "auth", "demo", "docs", "regulacion", "requisitos", "verificado", "conector", "republica_dominicana"):
                self.assertIn(k, b)
            if b["conector"] == "no":
                self.assertTrue(b.get("motivo"), b["id"])                     # si no hay conector, se explica por qué
        self.assertIn("DISCONTINUADA", catalogo.por_id("xtb")["apis"])


class TestConectores(unittest.TestCase):
    def test_oanda_flujo_demo(self):
        f = servidor_falso({
            ("GET", "/v3/accounts"): {"accounts": [{"id": "101-001-1"}]},
            ("GET", "/v3/accounts/101-001-1/summary"): {"account": {"balance": "100000.0", "NAV": "100050.5", "currency": "USD", "marginUsed": "20", "unrealizedPL": "50.5"}},
            ("GET", "/v3/accounts/101-001-1/openTrades"): {"trades": [{"id": "77", "instrument": "EUR_USD", "price": "1.1000", "currentUnits": "-1000",
                                                                        "unrealizedPL": "3.2", "openTime": "1794240000.000000000", "financing": "-0.12",
                                                                        "stopLossOrder": {"price": "1.1050"}, "takeProfitOrder": {"price": "1.0900"}}]},
            ("POST", "/v3/accounts/101-001-1/orders"): {"orderFillTransaction": {"id": "90", "price": "1.1001", "commission": "0.0", "tradeOpened": {"tradeID": "91"}}},
            ("GET", "/v3/accounts/101-001-1/transactions/sinceid"): {"transactions": [
                {"id": "90", "type": "ORDER_FILL", "orderID": "89", "instrument": "EUR_USD", "units": "1000", "price": "1.1001", "commission": "0.5",
                 "financing": "-0.1", "pl": "0.0", "time": "1794240000.0"}, {"id": "92", "type": "MARKET_ORDER"}]},
        })
        o = OANDA({"token": "tok-secreto-123"}, "demo", abrir_url=f)
        self.assertEqual(o.probar()["ok"], True)
        p = o.posiciones()[0]
        self.assertEqual((p["lado"], p["cantidad"], p["stop"], p["objetivo"], p["swap"]), ("venta", 1000, 1.105, 1.09, -0.12))
        r = o.abrir("EURUSD", "compra", 1000, stop=1.09, objetivo=1.12)
        self.assertEqual(r["id_externo"], "91")
        cuerpo = json.loads(f.llamadas[-1][3])
        self.assertEqual(cuerpo["order"]["instrument"], "EUR_USD")
        self.assertEqual(cuerpo["order"]["stopLossOnFill"]["price"], "1.09000")
        self.assertIn("Bearer tok-secreto-123", f.llamadas[-1][2]["Authorization"])
        ej = o.ejecuciones()
        self.assertEqual(len(ej), 1)                                              # solo ORDER_FILL
        self.assertEqual((ej[0]["comision"], ej[0]["swap"]), (0.5, -0.1))

    def test_real_solo_lectura(self):
        o = OANDA({"token": "x"}, "real", abrir_url=servidor_falso({}))
        with self.assertRaises(ErrorAdaptador):
            o.abrir("EURUSD", "compra", 1000)
        with self.assertRaises(ErrorAdaptador):
            Kraken().abrir("BTCUSD", "compra", 0.1)                                 # sin demo de spot: nunca ejecuta

    def test_alpaca_cabeceras_y_bracket(self):
        f = servidor_falso({("POST", "/v2/orders"): {"id": "ord-1", "status": "accepted"}, ("GET", "/v2/account"): {"cash": "1000", "equity": "1000", "currency": "USD"}})
        a = Alpaca({"clave": "K1", "secreto": "S1"}, "demo", abrir_url=f)
        a.abrir("aapl", "compra", 2, stop=180.0, objetivo=200.0)
        met, ruta, cab, datos = f.llamadas[-1]
        self.assertEqual((cab.get("Apca-api-key-id"), cab.get("Apca-api-secret-key")), ("K1", "S1"))
        c = json.loads(datos)
        self.assertEqual((c["symbol"], c["side"], c["order_class"], c["stop_loss"]["stop_price"]), ("AAPL", "buy", "bracket", 180.0))
        self.assertIn("paper-api.alpaca.markets", Alpaca.ENTORNOS["demo"])

    def test_errores_no_revelan_credenciales(self):
        import urllib.error

        def abrir(req):
            raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b'{"error":"bad token tok-secreto-123"}'))
        with self.assertRaises(ErrorBroker) as cm:
            OANDA({"token": "tok-secreto-123", "cuenta": "1"}, "demo", abrir_url=abrir).cuenta()
        self.assertNotIn("tok-secreto-123", str(cm.exception))

    def test_firma_kraken_vector_oficial(self):
        k = Kraken({"clave": "x", "secreto": "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="})
        firma = k.firma("/0/private/AddOrder", b"nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25")
        self.assertEqual(firma, "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ==")


class TestCentroBrokers(Base):
    def setUp(self):
        super().setUp()
        centro.cerrar()
        self.addCleanup(centro.cerrar)
        self.u = self.usuario()["id"]

    def test_interruptor_credenciales_y_sincronizacion(self):
        centro.guardar(self.u, "oanda", habilitado=True, credenciales={"token": "tok-abc-123456", "cuenta": "101-1"})
        self.assertEqual(boveda.leer(self.u, "broker_oanda")["token"], "tok-abc-123456")
        panel = {b["id"]: b for b in centro.panel(self.u)}
        self.assertTrue(panel["oanda"]["habilitado"])
        self.assertNotIn("tok-abc-123456", json.dumps(panel))                     # la interfaz solo ve máscaras
        self.assertFalse(panel["ibkr"]["tiene_conector"])
        falso = mock.MagicMock()
        falso.cuenta.return_value = {"balance": 1.0}
        falso.posiciones.return_value = [{"id_externo": "7", "simbolo": "EUR_USD", "lado": "compra", "cantidad": 1, "precio_entrada": 1.1,
                                          "pnl_no_realizado": 0, "stop": None, "objetivo": None, "swap": 0, "abierta_ts": 1}]
        falso.ordenes.return_value = []
        falso.ejecuciones.return_value = [{"id_externo": "e1", "orden_id": "o1", "simbolo": "EUR_USD", "lado": "compra", "cantidad": 1, "precio": 1.1,
                                           "comision": 0.2, "swap": -0.1, "pnl": None, "ts": int(time.time())}]
        with mock.patch.object(centro, "conector", return_value=falso):
            r1 = centro.sincronizar(self.u, "oanda")
            r2 = centro.sincronizar(self.u, "oanda")
        self.assertEqual((r1["posiciones"], r1["ejecuciones_nuevas"], r2["ejecuciones_nuevas"]), (1, 1, 0))   # sin duplicados
        self.assertEqual(centro.q1("SELECT comision, swap FROM ejecuciones")["comision"], 0.2)

    def test_orden_prueba_solo_demo_y_con_seguridad(self):
        with self.assertRaises(PermissionError):
            centro.orden_prueba_demo(self.u, "oanda", "EURUSD", "compra", 1)       # apagado
        centro.guardar(self.u, "oanda", habilitado=True, entorno="real")
        with self.assertRaises(PermissionError):
            centro.orden_prueba_demo(self.u, "oanda", "EURUSD", "compra", 1)       # REAL
        centro.guardar(self.u, "oanda", entorno="demo")
        interruptores.parada_total(self.u, "prueba")
        with self.assertRaises(PermissionError):
            centro.orden_prueba_demo(self.u, "oanda", "EURUSD", "compra", 1)       # PARADA TOTAL

    def test_diagnostico_no_marca_conectado_sin_respuesta(self):
        centro.guardar(self.u, "alpaca", habilitado=True)
        r = centro.diagnosticar(self.u, "alpaca")                                    # sin credenciales
        self.assertFalse(r["ok"])
        self.assertFalse({b["id"]: b for b in centro.panel(self.u)}["alpaca"]["conectado"])


class TestSupervisor(Base):
    def test_recupera_proceso_caido_y_controles(self):
        from titan_quant import supervisor
        estado = {"vivo": False, "arranques": 0}
        falso = {"nombre": "Prueba", "prioridad": 3, "prefijos": ("x-",), "depende": (), "funcion": "prueba",
                 "f": lambda: {"iniciar": lambda: estado.update(vivo=True, arranques=estado["arranques"] + 1), "detener": lambda: estado.update(vivo=False),
                               "vivo": lambda: estado["vivo"], "error": lambda: None}}
        carga_normal = {"cpu_sistema": 20.0, "ram_sistema": 40.0, "por_proceso": {}}
        with mock.patch.dict(supervisor.PROCESOS, {"prueba": falso}, clear=True), mock.patch.object(supervisor, "metricas", return_value=carga_normal):
            supervisor._REINICIOS.clear()
            supervisor.ESTADO["pausa_por_carga"] = False
            supervisor.vigilar()
            self.assertTrue(estado["vivo"])                                            # caído → reiniciado
            self.assertEqual(supervisor.estado()["procesos"][0]["reinicios"], 1)
            supervisor.controlar("prueba", "detener")
            supervisor.vigilar()
            self.assertFalse(estado["vivo"])                                           # detenido a propósito: no se reinicia
            supervisor.controlar("prueba", "pausar")
            self.assertFalse(supervisor.permitido("prueba"))
            supervisor.controlar("prueba", "reanudar")
            self.assertTrue(supervisor.permitido("prueba"))
            supervisor.ESTADO["pausa_por_carga"] = True
            self.assertFalse(supervisor.permitido("prueba"))                           # investigación en pausa por carga
            supervisor.ESTADO["pausa_por_carga"] = False
        m = supervisor.metricas()
        self.assertIn("cpu_sistema", m)


class TestCerebro(Base):
    def setUp(self):
        super().setUp()
        from titan_quant.ia import cerebro
        self.c = cerebro
        cerebro.cerrar()
        self.addCleanup(cerebro.cerrar)
        self.u = self.usuario()["id"]

    def ops(self, m, n, resultado, inst="EURGBP-OTC", est="cruce_ema"):
        from titan_quant.trader import almacen
        ahora = int(time.time()) - 86400
        with almacen.tx(m) as c:
            for i in range(n):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,riesgo_importe,payout,estado,fase,
                             fuente_resultado,id_externo,abierta_ts,cerrada_ts,resultado,estrategia) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (self.u, m, "iqoption", inst, "binarias", "binaria", "alcista", 10, 10, 0.83, "cerrada", "resultado_recibido", "broker",
                           f"{m}{inst}{i}", ahora + i * 60, ahora + i * 60 + 300, resultado if i % 10 else 8.3, est))

    def test_bloquea_en_practica_recomienda_en_real_y_es_reversible(self):
        from titan_quant.trader import autotrader
        self.ops("binaria", 12, -10.0)
        self.ops("binaria_real", 12, -10.0)
        r = self.c.ciclo()
        self.assertEqual(r["cuentas"]["binaria"]["operaciones"], 12)
        dec = {d["cuenta"]: d for d in self.c.informe()["decisiones"]}
        self.assertEqual(dec["binaria"]["estado"], "aplicada")
        self.assertEqual(dec["binaria_real"]["estado"], "propuesta")                 # REAL: solo recomienda
        aj = autotrader.estado(self.u, "binaria")["ajustes"]
        self.assertFalse(autotrader._control_aprendizaje("binaria", aj, "cruce_ema", "EURGBP-OTC")["ok"])
        self.assertTrue(self.c.revertir(dec["binaria"]["id"], self.u))
        self.assertIsNone(self.c.bloqueado("binaria", "cruce_ema", "EURGBP-OTC"))
        self.c.ciclo()                                                               # una decisión revertida no se vuelve a imponer
        self.assertIsNone(self.c.bloqueado("binaria", "cruce_ema", "EURGBP-OTC"))

    def test_poca_muestra_no_decide(self):
        self.ops("binaria", 4, -10.0)
        self.c.ciclo()
        self.assertEqual(self.c.informe()["decisiones"], [])

    def test_el_cerebro_no_puede_tocar_protecciones(self):
        from titan_quant.trader import autotrader
        with self.assertRaises(PermissionError):
            autotrader.guardar_ajustes(self.u, "binaria", {"riesgo_pct": 5.0}, origen="ia")
        with self.assertRaises(PermissionError):
            interruptores.reanudar(self.u, True, True, origen="ia")


class TestCuantico(unittest.TestCase):
    def test_qaoa_vqe_y_qae(self):
        from titan_quant.cuantico import qaoa, qmc, vqe
        rnd = np.random.default_rng(3)
        A = rnd.normal(0, 1, (5, 5))
        S = A @ A.T / 5 + np.eye(5) * 0.1
        mu = rnd.normal(0.3, 0.3, 5)
        r = qaoa.resolver(mu, S, 2, p=3, reinicios=4)
        self.assertGreater(r["amplificacion"], 1.5)                                  # mejor que elegir al azar
        self.assertEqual(sum(r["optimo_clasico"]), 2)
        coste, _ = qaoa.qubo_cartera(mu, S, 2)
        self.assertTrue(vqe.resolver(coste, 5, capas=2)["acierta"])
        q = qmc.estimar(np.ones(32), (np.arange(32) > 24).astype(float), m=8)
        self.assertLess(q["error_qae"], 0.02)


class TestCentroServidores(Base):
    def test_estados_reales(self):
        from titan_quant import servidores
        u = self.usuario()["id"]
        c = servidores.centro(u)
        motores = [s for s in c["servidores"] if s["tipo"] == "motor"]
        self.assertEqual(len(motores), 23)
        self.assertTrue(all(len(s["leds"]) == 5 for s in c["servidores"]))
        self.assertTrue(all(m["leds"][0]["estado"] == "espera" for m in motores))     # nada ejecutado: espera, no actividad ficticia
        d = servidores.detalle(u, "motor:fusion")
        self.assertEqual(d["ficha"]["id"], "fusion")


if __name__ == "__main__":
    unittest.main()
