"""cTrader DEMO y REAL contra un servidor cTrader simulado, y separación estricta de bases por cuenta."""
import json
import shutil
import time

from titan_quant import db, integraciones
from titan_quant.pruebas.base_prueba import Base
from titan_quant.pruebas.ctrader_falso import CTraderFalso
from titan_quant.pruebas.test_operacion import analisis_falso
from titan_quant.seguridad import boveda
from titan_quant.trader import almacen, autotrader
from titan_quant.trader.base import ErrorAdaptador
from titan_quant.trader.ctrader import CTrader
from titan_quant.trader.ctrader_ws import SesionCTrader

DEMO, DEMO_EUR, REAL = 9001, 9002, 7001


class BaseCT(Base):
    def setUp(self):
        super().setUp()
        self.f = CTraderFalso().iniciar()
        self.W = self.f.mundo
        self.u = self.usuario()["id"]
        boveda.guardar(self.u, "ctrader", {"client_id": self.W.client_id, "client_secret": self.W.client_secret,
                                           "redirect_uri": "http://127.0.0.1:8765/api/tq/integraciones/ctrader/callback",
                                           "access_token": "tok-trading", "refresh_token": "ref-1"})

    def tearDown(self):
        self.f.detener()
        super().tearDown()

    def analisis(self, captura=None, **kw):
        base = analisis_falso(**kw)

        def fn(sim, hz, nivel, politica, **k):
            if captura is not None:
                captura.update(k)
            return base(sim, hz, nivel, politica, **k)
        return fn


class TestProtocolo(BaseCT):
    def test_sesion_cuentas_simbolos_cotizacion_y_velas(self):
        with SesionCTrader("demo", self.W.client_id, self.W.client_secret, "tok-trading") as s:
            info = s.cuentas()
            self.assertEqual({c["ctid"] for c in info["cuentas"]}, {DEMO, DEMO_EUR, REAL})
            self.assertEqual({c["ctid"] for c in info["cuentas"] if c["real"]}, {REAL})
            s.autorizar_cuenta(DEMO)
            sims = {x["nombre"]: x for x in s.simbolos()}
            self.assertIn("XAUUSD", sims)
            q = s.cotizacion(sims["XAUUSD"]["id"])
            self.assertAlmostEqual(q["bid"], 2000.00)
            self.assertAlmostEqual(q["spread"], 0.40, places=5)
            v = s.velas(sims["XAUUSD"]["id"], "60m", (time.time() - 30 * 86400) * 1000, time.time() * 1000)
            self.assertGreater(len(v), 300)
            self.assertTrue(all(b[2] >= max(b[1], b[4]) and b[3] <= min(b[1], b[4]) for b in v))     # h ≥ o,c ≥ l
            self.assertEqual(v, sorted(v))

    def test_credenciales_de_app_incorrectas(self):
        with self.assertRaises(Exception):
            SesionCTrader("demo", "otra", "x", "tok-trading").abrir()

    def test_enums_como_texto_tambien_se_entienden(self):
        self.W.enum_como_texto = True
        ad = CTrader(self.u, "demo", DEMO, "XAUUSD")
        ej = ad.abrir({"tipo": "margen", "direccion": "bajista", "stop_dist_pct": 0.01, "obj_dist_pct": 0.015, "riesgo_importe": 100})
        self.assertTrue(ad.verificar(ej))


class TestAdaptador(BaseCT):
    def test_tamano_stops_relativos_y_riesgo(self):
        ad = CTrader(self.u, "demo", DEMO, "XAUUSD")
        ej = ad.abrir({"tipo": "margen", "direccion": "alcista", "stop_dist_pct": 0.01, "obj_dist_pct": 0.02, "riesgo_importe": 100.0,
                       "estrategia": "fusion"})
        orden = self.W.ordenes[-1]
        self.assertEqual(orden["entorno"], "demo")
        self.assertEqual(orden["tradeSide"], 1)
        self.assertNotIn("stopLoss", orden)                          # a mercado: solo relativos
        self.assertEqual(orden["relativeStopLoss"] % 1000, 0)        # XAUUSD tiene 2 decimales → múltiplo de 1000
        self.assertEqual(orden["volume"] % 100, 0)
        self.assertEqual(ej["volumen"], 400)                          # 100 USD / (20,004 × 1) = 4,99 oz → 4 oz (hacia abajo)
        self.assertLessEqual(ej["riesgo_importe"], 100.0)
        self.assertAlmostEqual(ej["precio_entrada"], 2000.40)         # compra al ask real
        self.assertAlmostEqual(ej["stop"], 2000.40 - 20.0, places=2)
        self.assertEqual(ej["moneda"], "USD")
        self.assertIn("bid 2000.0 ask 2000.4", ej["fuente_precio"])

    def test_cuenta_en_eur_convierte_el_riesgo(self):
        ad = CTrader(self.u, "demo", DEMO_EUR, "XAUUSD")
        ej = ad.abrir({"tipo": "margen", "direccion": "alcista", "stop_dist_pct": 0.01, "obj_dist_pct": None, "riesgo_importe": 100.0})
        self.assertEqual(ej["moneda"], "EUR")
        self.assertEqual(ej["volumen"], 500)                          # 100 EUR ≈ 108 USD → 5,4 oz → 5 oz
        self.assertLessEqual(ej["riesgo_importe"], 100.0)
        self.assertIsNone(ej["objetivo"])

    def test_volumen_minimo_rechaza_en_vez_de_redondear_arriba(self):
        ad = CTrader(self.u, "demo", DEMO, "XAUUSD")
        with self.assertRaises(ErrorAdaptador) as e:
            ad.abrir({"tipo": "margen", "direccion": "alcista", "stop_dist_pct": 0.01, "riesgo_importe": 5.0})
        self.assertIn("volumen mínimo", str(e.exception))
        self.assertEqual(self.W.ordenes, [])

    def test_no_se_mezclan_cuentas_demo_y_real(self):
        with self.assertRaises(ErrorAdaptador) as e:
            CTrader(self.u, "demo", REAL, "XAUUSD").cotizacion()
        self.assertIn("no se mezclan", str(e.exception))
        with self.assertRaises(ErrorAdaptador):
            CTrader(self.u, "real", DEMO, "XAUUSD").cotizacion()
        self.assertAlmostEqual(CTrader(self.u, "real", REAL, "XAUUSD").cotizacion()["precio"], 2000.20)

    def test_token_caducado_se_renueva_y_se_guarda_cifrado(self):
        del self.W.tokens["tok-trading"]
        self.W.tokens["tok-nuevo-oculto"] = "SCOPE_TRADE"
        self.W.refresh["ref-1"] = "tok-nuevo-oculto"
        q = CTrader(self.u, "demo", DEMO, "XAUUSD").cotizacion()
        self.assertGreater(q["precio"], 0)
        nuevo = boveda.leer(self.u, "ctrader")
        self.assertNotEqual(nuevo["access_token"], "tok-trading")
        self.assertIn(nuevo["access_token"], self.W.tokens)
        self.assertNotIn("ref-1", self.W.refresh)

    def test_token_solo_lectura_no_opera(self):
        boveda.guardar(self.u, "ctrader", {"access_token": "tok-lectura"})
        with self.assertRaises(ErrorAdaptador) as e:
            CTrader(self.u, "demo", DEMO, "XAUUSD").abrir({"tipo": "margen", "direccion": "alcista", "stop_dist_pct": 0.01, "riesgo_importe": 100})
        self.assertIn("lectura", str(e.exception))
        self.assertEqual(self.W.ordenes, [])

    def test_simbolo_inexistente_y_listados(self):
        with self.assertRaises(ErrorAdaptador):
            CTrader(self.u, "demo", DEMO, "NOEXISTE").cotizacion()
        self.assertEqual({x["nombre"] for x in CTrader(self.u, "demo", DEMO).simbolos()}, {"XAUUSD", "EURUSD"})     # XAGUSD deshabilitado
        info = integraciones.ctrader_cuentas(self.u)
        self.assertTrue(info["trading"])
        self.assertEqual(integraciones.probar(self.u, "ctrader")["estado"], "conectada")

    def test_oauth_pide_permiso_de_trading(self):
        self.assertIn("scope=trading", integraciones.ctrader_url_autorizacion(self.u, "E1"))


class TestBotsSeparados(BaseCT):
    def preparar(self, mod, ctid, **extra):
        autotrader.guardar_ajustes(self.u, mod, {"broker": "ctrader", "estrategia": "fusion", "cuenta_ctid": ctid, "simbolo_broker": "XAUUSD", "instrumento": "GC=F",
                                                  "riesgo_pct": 1.0, **extra})

    def test_demo_opera_con_velas_del_broker_cierra_y_aprende(self):
        self.preparar("demo", DEMO)
        autotrader.cambiar_estado(self.u, "demo", "activo")
        cap = {}
        r = autotrader.ciclo(self.u, "demo", analizar_fn=self.analisis(cap, precio=2000.20))
        self.assertEqual(r["accion"], "abrir", r)
        self.assertEqual(cap["serie"]["proveedor"], "ctrader-demo")                  # análisis con los precios del broker
        self.assertEqual(cap["riesgo"]["capital"], 10000.0)                          # capital = saldo real de la cuenta demo
        op = almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (r["operacion_id"],))
        self.assertEqual((op["broker"], op["cuenta"], op["moneda"], op["simbolo_broker"]), ("ctrader", str(DEMO), "USD", "XAUUSD"))
        self.assertEqual(op["volumen"], 9900)                                         # 100 USD / 1,0002 de stop → 99,98 oz → 99 oz
        ctl = {c["control"]: c for c in json.loads(op["controles"])}
        self.assertIn("real del broker", ctl["spread"]["detalle"])
        self.assertNotIn("ventaja_demostrada", ctl)                                  # solo se exige en REAL
        self.assertIsNone(almacen.q1("real", "SELECT * FROM operaciones"))
        with self.assertRaises(ValueError):
            almacen.q1("simulacion", "SELECT * FROM operaciones")                   # la simulación interna se retiró
        self.assertEqual((op["estado"], op["fase"]), ("abierta", "abierta_confirmada"))   # confirmada en las posiciones del broker
        self.assertEqual([e["fase"] for e in almacen.eventos("demo", op["id"])], ["orden_enviada", "orden_aceptada", "abierta_confirmada"])
        self.assertTrue(almacen.q1("demo", "SELECT * FROM saldos WHERE cuenta=?", (str(DEMO),)))
        self.assertIsNone(db.q1("SELECT * FROM operaciones"))                        # nada en la base principal
        self.W.mover(41, op["objetivo"] + 0.5, op["objetivo"] + 0.9)                  # el broker toca el objetivo
        self.assertEqual(autotrader.actualizar_abiertas(self.u, "demo"), 1)
        op = almacen.q1("demo", "SELECT * FROM operaciones WHERE id=?", (op["id"],))
        self.assertEqual((op["estado"], op["motivo_cierre"], op["fase"], op["fuente_resultado"]), ("cerrada", "objetivo", "resultado_recibido", "broker"))
        self.assertGreater(op["resultado"], 0)
        self.assertAlmostEqual(op["r"], op["resultado"] / op["riesgo_importe"])
        k = almacen.conocimiento("fusion", "XAUUSD")                              # nombre del símbolo tal como lo publica cTrader
        self.assertEqual((k["n"], list(k["por_origen"])), (1, ["demo"]))
        fila = dict(almacen.con_conocimiento().execute("SELECT * FROM resultados").fetchone())
        self.assertNotIn(str(DEMO), json.dumps(fila))                                # el conocimiento no lleva cuenta ni importes
        self.assertEqual(set(fila), {"id", "ts", "origen", "estrategia", "instrumento", "horizonte", "direccion", "r", "motivo"})

    def test_emergencia_cierra_en_el_broker(self):
        self.preparar("demo", DEMO)
        autotrader.cambiar_estado(self.u, "demo", "activo")
        r = autotrader.ciclo(self.u, "demo", analizar_fn=self.analisis(precio=2000.20))
        self.assertEqual(r["accion"], "abrir")
        self.assertEqual(len(self.W.cuentas[DEMO]["posiciones"]), 1)
        autotrader.cambiar_estado(self.u, "demo", "emergencia")
        self.assertEqual(self.W.cuentas[DEMO]["posiciones"], {})
        self.assertFalse(autotrader.abiertas(self.u, "demo"))
        op = almacen.q1("demo", "SELECT * FROM operaciones")
        self.assertEqual(op["motivo_cierre"], "emergencia")

    def test_real_solo_con_interruptor_live_y_por_el_host_live(self):
        self.preparar("real", REAL)
        with almacen.tx("real") as c:                          # apagado: aunque se fuerce la base, no se envía nada al host LIVE
            c.execute("UPDATE bot_estado SET estado='activo'")
        self.assertEqual(autotrader.ciclo(self.u, "real", analizar_fn=self.analisis(precio=2000.20))["accion"], "bloqueado")
        self.assertEqual([o for o in self.W.ordenes if o["entorno"] == "live"], [])
        autotrader.interruptor_live(self.u, "real", True, clave_ok=True)
        r = autotrader.ciclo(self.u, "real", analizar_fn=self.analisis(precio=2000.20, direccion="bajista"))
        self.assertEqual(r["accion"], "abrir", r)
        vivas = [o for o in self.W.ordenes if o["entorno"] == "live"]
        self.assertEqual((len(vivas), vivas[0]["ctid"]), (1, REAL))
        op = almacen.q1("real", "SELECT * FROM operaciones WHERE estado='abierta'")
        self.assertEqual((op["modalidad"], op["cuenta"], op["instrumento"]), ("real", str(REAL), "XAUUSD"))   # nombre del símbolo de cTrader
        self.assertIsNone(almacen.q1("demo", "SELECT * FROM operaciones"))
        with self.assertRaises(ErrorAdaptador):                # una cuenta DEMO nunca opera por el host live
            CTrader(self.u, "real", DEMO, "XAUUSD").abrir({"tipo": "margen", "direccion": "alcista", "stop_dist_pct": 0.01, "riesgo_importe": 10})
        autotrader.interruptor_live(self.u, "real", False)
        self.assertEqual(autotrader.estado(self.u, "real")["estado"], "detenido")

    def test_broker_caido_no_abre_y_avisa(self):
        self.preparar("demo", DEMO)
        autotrader.cambiar_estado(self.u, "demo", "activo")
        self.f.detener()
        SesionCTrader.URL_PRUEBAS = {"demo": "ws://127.0.0.1:9/", "live": "ws://127.0.0.1:9/"}
        try:
            r = autotrader.ciclo(self.u, "demo", analizar_fn=self.analisis(precio=2000.20))
        finally:
            SesionCTrader.URL_PRUEBAS = None
            self.f = CTraderFalso().iniciar()
        self.assertEqual(r["accion"], "broker_no_disponible")
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE categoria='conexion'"))

    def test_bot_ctrader_exige_cuenta(self):
        autotrader.guardar_ajustes(self.u, "demo", {"broker": "ctrader", "simbolo_broker": "XAUUSD"})
        with self.assertRaises(ValueError):
            autotrader.cambiar_estado(self.u, "demo", "activo")


class TestBasesSeparadas(Base):
    def test_una_base_no_puede_usarse_como_otra(self):
        almacen.q("demo", "SELECT 1")
        almacen.q("real", "SELECT 1")
        almacen.reiniciar_para_pruebas()
        shutil.copy(almacen.ruta("demo"), almacen.ruta("real"))
        with self.assertRaises(RuntimeError):
            almacen.q("real", "SELECT 1")

    def test_migracion_desde_v71_reparte_por_modalidad(self):
        u = self.usuario()["id"]
        with db.tx() as c:
            for m in ("simulacion", "demo"):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,abierta_ts)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""", (u, m, "simulador" if m == "simulacion" else "iqoption", "GC=F", "x", "margen", "alcista", 10, "abierta", 1))
            c.execute("INSERT INTO bot_estado(usuario_id,estado,ajustes,actualizado_ts) VALUES(?,?,?,?)", (u, "activo", json.dumps({"modalidad": "simulacion"}), 1))
        self.assertEqual(almacen.q1("demo", "SELECT COUNT(*) n FROM operaciones")["n"], 1)
        # sin id del broker no hay prueba de ejecución: la fila antigua queda como 'error' (pendiente de conciliar), no como abierta
        self.assertEqual(almacen.q1("demo", "SELECT estado, fase FROM operaciones"), {"estado": "error", "fase": "error_broker"})
        self.assertEqual(almacen.q1("real", "SELECT COUNT(*) n FROM operaciones")["n"], 0)
        self.assertEqual(almacen.q1("binaria", "SELECT COUNT(*) n FROM operaciones")["n"], 0)   # la simulación no se copia a ninguna cuenta
        with self.assertRaises(ValueError):
            autotrader.estado(u, "simulacion")
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM operaciones")["n"], 2)          # la copia histórica no se borra
        self.assertTrue(db.cfg_sistema("cuentas_separadas_v72"))
