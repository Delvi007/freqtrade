"""Pruebas del bot operador, controles de riesgo, simulador, alertas, historial e integraciones."""
import json
import time

from titan_quant import alertas, db, historial, integraciones
from titan_quant.motores import datos
from titan_quant.pruebas import sintetico
from titan_quant.pruebas.base_prueba import Base
from titan_quant.trader import almacen, autotrader
from titan_quant.trader.base import Adaptador, ErrorAdaptador
from titan_quant.trader.simulador import Simulador


def analisis_falso(direccion="alcista", precio=100.0, calibrada=False, prob=0.5, regimen="tendencia_alcista"):
    sg = 1 if direccion == "alcista" else -1
    esc = {"direccion": direccion, "precio_referencia": precio, "zona_entrada": [precio, precio], "entrada": precio,
           "stop_loss": precio - sg * 1.0, "take_profit": [precio + sg * 1.5, precio + sg * 3], "riesgo_beneficio": 1.5,
           "probabilidad": prob, "metodo_probabilidad": "x", "confirmacion": [], "invalidacion": [], "vigencia_hasta_ts": int(time.time()) + 3600,
           "horizonte": "Intradía", "tamano": None}

    def fn(sim, hz, nivel, politica, **k):
        return {"ts": int(time.time()), "activo": {"simbolo": sim, "nombre": sim, "clase": "metal"}, "horizonte": hz,
                "hay_oportunidad": True, "escenario": esc, "fusion": {"justificacion": ["prueba"], "motivo_sin_oportunidad": []},
                "fuente_datos": {"tipo": "futuro"},
                "motores": [{"motor": "regime", "estado": "completado", "salida": {"regimen": regimen}},
                            {"motor": "ml", "estado": "completado", "salida": {"calibrada": calibrada, "probabilidad_alcista": prob}},
                            {"motor": "microstructure", "estado": "simplificado", "salida": {"spread_estimado_pct": {"corwin_schultz": 0.01}}},
                            {"motor": "fusion", "estado": "completado", "salida": {}}]}
    return fn


class Fijo(Adaptador):
    """Adaptador de prueba con precio y antigüedad controlados."""
    id, nombre = "fijo", "Fijo"

    def __init__(self, precio=100.0, edad=5, conectado=True, falla=False):
        self.p, self.e, self.c, self.f = precio, edad, conectado, falla

    def conectado(self):
        return self.c

    def cotizacion(self, s):
        return {"precio": self.p, "edad_s": self.e, "bid": None, "ask": None, "spread": None, "proveedor": "prueba", "instrumento": "x"}

    def abrir(self, sol):
        if self.f:
            raise ErrorAdaptador("rechazada por el broker")
        return {"id_externo": "F1", "precio_entrada": self.p, "costo": 0.1, "fuente_precio": "prueba"}

    def actualizar(self, op, ahora=None):
        return None


S = "simulacion"


class TestOperador(Base):
    def setUp(self):
        super().setUp()
        self.u = self.usuario()["id"]
        autotrader.guardar_ajustes(self.u, S, {"instrumento": "GC=F", "ciclo_s": 60})

    def _ciclo(self, ad=None, **kw):
        return autotrader.ciclo(self.u, S, analizar_fn=analisis_falso(**kw), adaptador=ad or Fijo())

    def test_inactivo_no_opera(self):
        self.assertEqual(self._ciclo()["accion"], "inactivo")

    def test_abre_en_simulacion_y_registra_todo(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        r = self._ciclo()
        self.assertEqual(r["accion"], "abrir")
        op = almacen.q1(S, "SELECT * FROM operaciones WHERE id=?", (r["operacion_id"],))
        self.assertEqual(op["modalidad"], "simulacion")
        self.assertTrue(all(c["ok"] for c in json.loads(op["controles"])))
        self.assertAlmostEqual(op["monto"] * abs(op["precio_entrada"] - op["stop"]) / op["precio_entrada"], 10.0, places=1)  # 1 % de 1000
        self.assertTrue(almacen.q1(S, "SELECT * FROM decisiones_bot WHERE accion='abrir'"))
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE categoria='entrada'"))
        self.assertIsNone(almacen.q1("demo", "SELECT * FROM operaciones"))            # la demo no ve la simulación
        self.assertIsNone(almacen.q1("real", "SELECT * FROM decisiones_bot WHERE accion='abrir'"))

    def test_duplicado_bloqueado(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        self.assertEqual(self._ciclo()["accion"], "abrir")
        r = self._ciclo()
        self.assertEqual(r["accion"], "rechazar")
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "duplicados")["ok"])

    def test_datos_obsoletos_y_desconexion_bloquean(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        r = self._ciclo(Fijo(edad=99999))
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "datos_frescos")["ok"])
        r = self._ciclo(Fijo(conectado=False), direccion="bajista")
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "conexion")["ok"])

    def test_volatilidad_y_slippage(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        r = self._ciclo(regimen="alta_volatilidad")
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "volatilidad")["ok"])
        r = self._ciclo(Fijo(precio=100.5), direccion="bajista", precio=100.0)
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "slippage")["ok"])

    def test_perdida_diaria_y_racha(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        ahora = int(time.time())
        with almacen.tx(S) as c:
            for i in range(3):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,abierta_ts,cerrada_ts,resultado)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (self.u, S, "simulador", f"X{i}", "x", "margen", "alcista", 100, "cerrada", ahora - 100, ahora - 50 + i, -10))
        r = self._ciclo()
        fallos = {c["control"] for c in r["controles"] if not c["ok"]}
        self.assertIn("perdida_diaria", fallos)
        self.assertIn("perdidas_consecutivas", fallos)
        # las pérdidas de la simulación NO cuentan para la demo: cada cuenta tiene sus propios límites
        autotrader.guardar_ajustes(self.u, "demo", {"broker": "iqoption", "tipo": "binaria", "instrumento": "GC=F"})
        autotrader.cambiar_estado(self.u, "demo", "activo")
        r = autotrader.ciclo(self.u, "demo", analizar_fn=analisis_falso(calibrada=True, prob=0.9), adaptador=Fijo())
        self.assertEqual(r["accion"], "abrir", r)

    def test_binaria_exige_probabilidad_calibrada(self):
        autotrader.guardar_ajustes(self.u, S, {"tipo": "binaria"})
        autotrader.cambiar_estado(self.u, S, "activo")
        r = self._ciclo(calibrada=False, prob=0.9)
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "probabilidad_calibrada")["ok"])
        r = self._ciclo(calibrada=True, prob=0.62, direccion="bajista")
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "probabilidad_calibrada")["ok"])
        r = self._ciclo(calibrada=True, prob=0.30, direccion="bajista")     # P(baja)=0.70 > 1/1.8+0.02
        self.assertEqual(r["accion"], "abrir")

    def test_emergencia_detiene_y_cierra_simuladas_y_alimenta_conocimiento(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        sim = Simulador({"GC=F": "metal"})
        r = autotrader.ciclo(self.u, S, analizar_fn=analisis_falso(precio=sim.cotizacion("GC=F")["precio"]), adaptador=sim)
        self.assertEqual(r["accion"], "abrir", r)
        autotrader.cambiar_estado(self.u, S, "emergencia")
        self.assertFalse(autotrader.abiertas(self.u, S))
        self.assertEqual(self._ciclo()["accion"], "emergencia")
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE importancia='critica'"))
        k = almacen.conocimiento("fusion", "GC=F")
        self.assertEqual(k["n"], 1)
        self.assertIn("simulacion", k["por_origen"])

    def test_broker_rechaza(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        self.assertEqual(self._ciclo(Fijo(falla=True))["accion"], "rechazar")
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE categoria='integracion'"))

    def test_modo_real_bloqueado(self):
        with self.assertRaises(ValueError):
            autotrader.guardar_ajustes(self.u, "real", {"broker": "simulador"})     # en real solo cTrader
        with self.assertRaises(PermissionError):
            autotrader.habilitar_real(self.u, autotrader.FRASE_REAL, True)
        with self.assertRaises(PermissionError):
            autotrader.habilitar_real(self.u, autotrader.FRASE_REAL, True, local=False)
        with self.assertRaises(PermissionError):
            autotrader.cambiar_estado(self.u, "real", "activo")
        self.assertFalse(autotrader.requisitos_real(self.u)["cumple"])
        with self.assertRaises(ValueError):
            autotrader.guardar_ajustes(self.u, "demo", {"broker": "simulador"})
        with self.assertRaises(ValueError):
            autotrader.guardar_ajustes(self.u, S, {"riesgo_pct": 50})
        with self.assertRaises(ValueError):
            autotrader.estado(self.u, "mixta")

    def test_no_se_cambia_config_con_bot_activo(self):
        autotrader.cambiar_estado(self.u, S, "activo")
        with self.assertRaises(ValueError):
            autotrader.guardar_ajustes(self.u, S, {"riesgo_pct": 2})
        autotrader.guardar_ajustes(self.u, "demo", {"riesgo_pct": 2})                # otra cuenta: independiente


class TestSimulador(Base):
    def test_cierra_por_objetivo_y_stop_con_velas_reales(self):
        sim = Simulador({"T": "accion"})
        s = datos.obtener("T", "5d", "1m")
        t0 = s["t"][-50]
        maximo = max(s["h"][-50:])
        minimo = min(s["l"][-50:])
        if s["l"][-50] <= minimo:       # la vela de entrada no debe ser la del mínimo
            minimo = min(s["l"][-49:])
        op = {"instrumento": "T", "direccion": "alcista", "tipo": "margen", "monto": 1000, "precio_entrada": s["c"][-50],
              "stop": minimo * 0.5, "objetivo": maximo - 1e-9, "abierta_ts": t0, "costo": 1.0, "expira_ts": None}
        r = sim.actualizar(op)
        self.assertEqual(r["motivo"], "objetivo")
        self.assertGreater(r["resultado"], 0)
        op.update(stop=minimo + 1e-9, objetivo=maximo + 100)
        self.assertEqual(sim.actualizar(op)["motivo"], "stop")

    def test_binaria_resuelve_al_vencimiento(self):
        sim = Simulador()
        s = datos.obtener("B", "5d", "1m")
        op = {"instrumento": "B", "direccion": "alcista", "tipo": "binaria", "monto": 10, "precio_entrada": s["c"][-30], "payout": 0.8,
              "abierta_ts": s["t"][-30], "expira_ts": s["t"][-10]}
        r = sim.actualizar(op, ahora=s["t"][-10] + 1)
        self.assertIn(r["resultado"], (8.0, -10.0, 0.0))


class TestAlertasHistorial(Base):
    def test_dedupe_marcar_silenciar_ocultar_sin_borrar(self):
        u = self.usuario()["id"]
        a = alertas.crear(u, "oportunidad", "Prueba", "media", "GC=F", clave_dedupe="k1")
        self.assertIsNone(alertas.crear(u, "oportunidad", "Prueba", "media", "GC=F", clave_dedupe="k1"))
        self.assertEqual(alertas.contadores(u)["nuevas"], 1)
        alertas.marcar(u, [a], True)
        self.assertEqual(alertas.contadores(u)["nuevas"], 0)
        alertas.silenciar(u, "oportunidad", True)
        self.assertTrue(alertas.silenciada(u, "oportunidad"))
        alertas.ocultar(u, [a])
        self.assertEqual(alertas.listar(u), [])
        self.assertEqual(len(alertas.listar(u, ver="ocultos")), 1)
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM alertas")["n"], 1)         # el registro sigue
        with self.assertRaises(ValueError):
            alertas.crear(u, "inventada", "x")

    def test_historial_archivar_restaurar_y_eliminacion_permanente(self):
        u = self.usuario()["id"]
        otro = self.usuario("b@ejemplo.com")["id"]
        with db.tx() as c:
            for i in range(3):
                c.execute("INSERT INTO analisis(ts,usuario_id,simbolo,horizonte,nivel,politica,resultado) VALUES(?,?,?,?,?,?,?)",
                          (int(time.time()), u, "GC=F", "corto", "basico", "automatico", "{}"))
        historial.cambiar_visibilidad(u, "analisis", [1], "oculto")
        historial.cambiar_visibilidad(u, "analisis", [2], "archivado")
        self.assertEqual([f["id"] for f in historial.listar(u, "analisis")], [3])
        self.assertEqual([f["id"] for f in historial.listar(u, "analisis", "archivados")], [2])
        with self.assertRaises(ValueError):
            historial.eliminar_permanente(u, [1], historial.FRASE_ELIMINAR, True)     # no archivado
        with self.assertRaises(ValueError):
            historial.eliminar_permanente(u, [2], "borrar", True)
        with self.assertRaises(PermissionError):
            historial.eliminar_permanente(u, [2], historial.FRASE_ELIMINAR, False)
        self.assertEqual(historial.eliminar_permanente(u, [2], historial.FRASE_ELIMINAR, True), 1)
        self.assertTrue(db.q1("SELECT * FROM auditoria WHERE accion='eliminacion_permanente'"))
        historial.cambiar_visibilidad(u, "analisis", [1], "visible")
        self.assertEqual(len(historial.listar(u, "analisis")), 2)
        self.assertEqual(historial.listar(otro, "analisis"), [])                     # datos privados por usuario


class TestIntegraciones(Base):
    def test_guardar_no_expone_secretos_y_estados(self):
        u = self.usuario()["id"]
        self.assertEqual(next(i for i in integraciones.listar(u) if i["proveedor"] == "telegram")["estado"], "no_configurada")
        integraciones.guardar(u, "telegram", {"token": "123456789:SECRETOSECRETOSECRETO", "chat_id": "42424242"})
        txt = json.dumps(integraciones.listar(u))
        self.assertNotIn("SECRETOSECRETO", txt)
        self.assertNotIn("42424242", txt)
        self.assertEqual(next(i for i in integraciones.listar(u) if i["proveedor"] == "telegram")["estado"], "configurada")
        self.assertEqual(next(i for i in integraciones.listar(u) if i["proveedor"] == "ctrader")["estado"], "no_configurada")
        integraciones.activar(u, "telegram", False)
        self.assertEqual(integraciones.probar(u, "telegram")["estado"], "deshabilitada")

    def test_error_de_prueba_no_filtra_secretos_y_no_marca_conectada(self):
        u = self.usuario()["id"]
        integraciones.guardar(u, "finnhub", {"api_key": "CLAVE-SUPER-SECRETA-99"})
        orig = integraciones._probar
        integraciones._probar = lambda uid, p: (_ for _ in ()).throw(RuntimeError("fallo con CLAVE-SUPER-SECRETA-99 en la URL"))
        try:
            r = integraciones.probar(u, "finnhub")
        finally:
            integraciones._probar = orig
        self.assertEqual(r["estado"], "error")
        self.assertNotIn("CLAVE-SUPER-SECRETA-99", r["error"])
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE categoria='integracion'"))

    def test_ctrader_oauth_exige_state(self):
        u = self.usuario()["id"]
        integraciones.guardar(u, "ctrader", {"client_id": "id1", "client_secret": "sec", "redirect_uri": "http://localhost:5000/callback"})
        self.assertEqual(next(i for i in integraciones.listar(u) if i["proveedor"] == "ctrader")["estado"], "pendiente_autorizacion")
        url = integraciones.ctrader_url_autorizacion(u, "ESTADO123")
        self.assertIn("state=ESTADO123", url)
        with self.assertRaises(ValueError):
            integraciones.ctrader_intercambiar(u, "code", "OTRO")
        sintetico.instalar()
