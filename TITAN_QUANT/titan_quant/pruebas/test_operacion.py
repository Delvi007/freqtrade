"""Pruebas del bot operador (sin simulación interna): controles de riesgo, ciclo de vida verificable de las órdenes,
separación de cuentas y de conocimiento, REAL bloqueado, alertas, historial e integraciones.

`Fijo` es un ADAPTADOR DE PRUEBA (no forma parte de la operativa): imita las respuestas de un broker para comprobar que
el bot solo avanza de fase con la confirmación del broker y que nunca inventa un resultado."""
import json
import sqlite3
import time

from titan_quant import alertas, db, historial, integraciones
from titan_quant.pruebas import sintetico
from titan_quant.pruebas.base_prueba import Base
from titan_quant.trader import almacen, autotrader
from titan_quant.trader.base import Adaptador, ErrorAdaptador, OrdenNoConfirmada


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
    """Adaptador de PRUEBA con respuestas de broker controladas."""
    id, nombre = "fijo", "Fijo"

    def __init__(self, precio=100.0, edad=5, conectado=True, falla=False, sin_respuesta=False, confirma=True, resultado=None):
        self.p, self.e, self.c, self.f = precio, edad, conectado, falla
        self.sin_respuesta, self.confirma, self.res = sin_respuesta, confirma, resultado
        self.n = 0

    def conectado(self):
        return self.c

    def cotizacion(self, s):
        return {"precio": self.p, "edad_s": self.e, "bid": None, "ask": None, "spread": None, "proveedor": "prueba", "instrumento": "x"}

    def abrir(self, sol):
        if self.f:
            raise ErrorAdaptador("rechazada por el broker")
        if self.sin_respuesta:
            raise OrdenNoConfirmada("sin respuesta del broker")
        self.n += 1
        return {"id_externo": f"F{self.n}", "precio_entrada": self.p, "costo": 0.1, "fuente_precio": "prueba",
                "evidencia": {"broker": "fijo", "id": f"F{self.n}"}}

    def verificar_apertura(self, op):
        return {"confirmada": self.confirma, "evidencia": {"fuente": "prueba"}}

    def actualizar(self, op, ahora=None):
        return self.res

    def cerrar(self, op, motivo):
        return {"precio_salida": self.p, "resultado": -1.0, "motivo": motivo}


M = "demo"                     # bot cTrader (DEMO); el adaptador real se sustituye por Fijo


class TestOperador(Base):
    def setUp(self):
        super().setUp()
        self.u = self.usuario()["id"]
        autotrader.guardar_ajustes(self.u, M, {"estrategia": "fusion", "simbolo_broker": "XAUUSD", "instrumento": "GC=F", "ciclo_s": 60,
                                               "cuenta_ctid": 9001, "capital_desde_broker": False})

    def _ciclo(self, ad=None, **kw):
        return autotrader.ciclo(self.u, M, analizar_fn=analisis_falso(**kw), adaptador=ad or Fijo())

    def _op(self, oid):
        return almacen.q1(M, "SELECT * FROM operaciones WHERE id=?", (oid,))

    def _ultima(self):
        return almacen.q1(M, "SELECT * FROM operaciones ORDER BY id DESC LIMIT 1")

    def test_inactivo_no_opera(self):
        self.assertEqual(self._ciclo()["accion"], "inactivo")

    def test_orden_aceptada_y_confirmada_por_el_broker_con_traza(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        r = self._ciclo()
        self.assertEqual((r["accion"], r["confirmada"], r["id_broker"]), ("abrir", True, "F1"), r)
        op = self._op(r["operacion_id"])
        self.assertEqual((op["estado"], op["fase"], op["id_externo"]), ("abierta", "abierta_confirmada", "F1"))
        self.assertIsNone(op["resultado"])                                                   # aceptada no es resultado
        fases = [e["fase"] for e in almacen.eventos(M, op["id"])]
        self.assertEqual(fases, ["orden_enviada", "orden_aceptada", "abierta_confirmada"])
        self.assertTrue(all(c["ok"] for c in json.loads(op["controles"])))
        self.assertTrue(almacen.q1(M, "SELECT * FROM decisiones_bot WHERE accion='abrir'"))
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE categoria='entrada'"))
        self.assertIsNone(almacen.q1("binaria", "SELECT * FROM operaciones"))                 # IQ Option no ve las de cTrader
        self.assertIsNone(almacen.q1("real", "SELECT * FROM decisiones_bot WHERE accion='abrir'"))

    def test_sin_confirmacion_de_apertura_queda_pendiente(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        r = self._ciclo(Fijo(confirma=False))
        op = self._op(r["operacion_id"])
        self.assertEqual((op["estado"], op["fase"], r["confirmada"]), ("aceptada", "orden_aceptada", False))
        self.assertEqual(autotrader.resumen(self.u)[M]["pendientes"], 1)

    def test_resultado_solo_del_broker_y_nunca_inventado(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        oid = self._ciclo()["operacion_id"]
        self.assertEqual(autotrader.actualizar_abiertas(self.u, M, Fijo(resultado=None)), 0)     # el broker no da resultado
        self.assertEqual(self._op(oid)["estado"], "abierta")
        self.assertEqual(autotrader.resumen(self.u)[M]["n"], 0)
        res = {"precio_salida": 101.0, "resultado": 7.5, "motivo": "objetivo", "evidencia": {"fuente": "prueba"}}
        self.assertEqual(autotrader.actualizar_abiertas(self.u, M, Fijo(resultado=res)), 1)
        op = self._op(oid)
        self.assertEqual((op["estado"], op["fase"], op["fuente_resultado"], op["resultado"]), ("cerrada", "resultado_recibido", "broker", 7.5))
        self.assertEqual([e["fase"] for e in almacen.eventos(M, oid)][-2:], ["cerrada_confirmada", "resultado_recibido"])
        self.assertEqual(autotrader.resumen(self.u)[M]["n"], 1)
        k = almacen.conocimiento(origen=M)
        self.assertEqual((k["n"], list(k["por_origen"])), (1, [M]))
        self.assertEqual(almacen.conocimiento(origen="binaria")["n"], 0)                      # mercados separados

    def test_oportunidad_descartada_no_es_operacion(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        self.assertEqual(self._ciclo(Fijo(edad=99999))["accion"], "rechazar")
        op = self._ultima()
        self.assertEqual((op["estado"], op["fase"], op["id_externo"]), ("rechazada", "oportunidad_detectada", None))
        self.assertEqual(autotrader.resumen(self.u)[M]["n"], 0)

    def test_rechazo_del_broker(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        r = self._ciclo(Fijo(falla=True))
        self.assertEqual(r["accion"], "rechazar")
        op = self._op(r["operacion_id"])
        self.assertEqual((op["estado"], op["fase"]), ("rechazada", "error_broker"))
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE categoria='integracion'"))

    def test_orden_sin_confirmar_bloquea_hasta_conciliar(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        r = self._ciclo(Fijo(sin_respuesta=True))
        self.assertEqual(r["accion"], "sin_confirmar")
        op = self._op(r["operacion_id"])
        self.assertEqual((op["estado"], op["fase"]), ("error", "error_broker"))
        r2 = self._ciclo(direccion="bajista")
        self.assertFalse(next(c for c in r2["controles"] if c["control"] == "ordenes_conciliadas")["ok"])
        with self.assertRaises(ValueError):
            autotrader.conciliar(self.u, M, op["id"], "no_ejecutada", "")                     # exige nota
        autotrader.conciliar(self.u, M, op["id"], "no_ejecutada", "revisado en la cuenta DEMO: no existe")
        self.assertEqual(self._op(op["id"])["estado"], "rechazada")
        self.assertEqual(self._ciclo(direccion="alcista", precio=100.0)["accion"], "abrir")

    def test_duplicado_bloqueado(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        self.assertEqual(self._ciclo()["accion"], "abrir")
        r = self._ciclo()
        self.assertEqual(r["accion"], "rechazar")
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "duplicados")["ok"])

    def test_datos_obsoletos_y_desconexion_bloquean(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        r = self._ciclo(Fijo(edad=99999))
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "datos_frescos")["ok"])
        r = self._ciclo(Fijo(conectado=False), direccion="bajista")
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "conexion")["ok"])

    def test_volatilidad_y_slippage(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        r = self._ciclo(regimen="alta_volatilidad")
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "volatilidad")["ok"])
        r = self._ciclo(Fijo(precio=100.5), direccion="bajista", precio=100.0)
        self.assertFalse(next(c for c in r["controles"] if c["control"] == "slippage")["ok"])

    def test_perdida_diaria_y_racha_solo_con_resultados_del_broker(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        ahora = int(time.time())
        with almacen.tx(M) as c:
            for i in range(3):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,fase,fuente_resultado,
                             id_externo,abierta_ts,cerrada_ts,resultado) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (self.u, M, "ctrader", f"X{i}", "x", "margen", "alcista", 100, "cerrada", "resultado_recibido", "broker", f"P{i}",
                           ahora - 100, ahora - 50 + i, -10))
        r = self._ciclo()
        fallos = {c["control"] for c in r["controles"] if not c["ok"]}
        self.assertIn("perdida_diaria", fallos)
        self.assertIn("perdidas_consecutivas", fallos)

    def test_racha_de_perdidas_pausa_y_luego_libera(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        hace = int(time.time()) - 2 * 3600                     # 3 pérdidas hace 2 horas; pausa por defecto 60 min
        with almacen.tx(M) as c:
            for i in range(3):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,fase,fuente_resultado,
                             id_externo,abierta_ts,cerrada_ts,resultado) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (self.u, M, "ctrader", f"Y{i}", "x", "margen", "alcista", 100, "cerrada", "resultado_recibido", "broker", f"Q{i}",
                           hace - 100, hace + i, -1))
        r = self._ciclo()
        self.assertEqual(r["accion"], "abrir", r)                # la pausa ya se cumplió: vuelve a operar

    def test_filas_sin_resultado_del_broker_no_cuentan(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        ahora = int(time.time())
        with almacen.tx(M) as c:                       # resultados sin verificación del broker: no cuentan en límites
            for i in range(3):
                c.execute("""INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,fase,abierta_ts,cerrada_ts,resultado)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (self.u, M, "ctrader", f"X{i}", "x", "margen", "alcista", 100, "rechazada",
                                                                  "oportunidad_detectada", ahora - 100, ahora - 50 + i, -10))
        self.assertEqual(self._ciclo()["accion"], "abrir")

    def test_interruptor_live_de_la_cuenta_real(self):
        autotrader.guardar_ajustes(self.u, "real", {"estrategia": "fusion", "simbolo_broker": "XAUUSD", "cuenta_ctid": 7001,
                                                    "capital_desde_broker": False})
        # Apagado: no arranca ni opera, aunque se fuerce el estado.
        with self.assertRaises(PermissionError):
            autotrader.cambiar_estado(self.u, "real", "activo", confirmado_real=True)
        with almacen.tx("real") as c:
            c.execute("UPDATE bot_estado SET estado='activo'")
        self.assertEqual(autotrader.ciclo(self.u, "real", analizar_fn=analisis_falso(), adaptador=Fijo())["accion"], "bloqueado")
        self.assertIsNone(almacen.q1("real", "SELECT * FROM operaciones"))
        # Encender exige contraseña y hacerlo en el propio dispositivo.
        with self.assertRaises(PermissionError):
            autotrader.interruptor_live(self.u, "real", True, clave_ok=False)
        with self.assertRaises(PermissionError):
            autotrader.interruptor_live(self.u, "real", True, clave_ok=True, local=False)
        with self.assertRaises(ValueError):
            autotrader.interruptor_live(self.u, M, True, clave_ok=True)                 # la DEMO no tiene interruptor LIVE
        e = autotrader.interruptor_live(self.u, "real", True, clave_ok=True)
        self.assertEqual((e["live"], e["estado"]), (True, "activo"))
        r = autotrader.ciclo(self.u, "real", analizar_fn=analisis_falso(), adaptador=Fijo())
        self.assertEqual(r["accion"], "abrir", r)                                       # demo y real pueden ir a la vez
        self.assertEqual(almacen.q1("real", "SELECT modalidad FROM operaciones")["modalidad"], "real")
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE categoria='riesgo' AND importancia='critica'"))
        # Apagar: deja de abrir.
        e = autotrader.interruptor_live(self.u, "real", False)
        self.assertEqual((e["live"], e["estado"]), (False, "detenido"))
        self.assertEqual(autotrader.ciclo(self.u, "real", analizar_fn=analisis_falso(direccion="bajista"), adaptador=Fijo())["accion"], "bloqueado")
        with self.assertRaises(ValueError):
            autotrader.guardar_ajustes(self.u, M, {"broker": "iqoption"})            # el bot cTrader solo usa cTrader
        with self.assertRaises(ValueError):
            autotrader.guardar_ajustes(self.u, M, {"riesgo_pct": 50})
        for m in ("simulacion", "mixta"):
            with self.assertRaises(ValueError):
                autotrader.estado(self.u, m)

    def test_no_hay_simulador_interno(self):
        import importlib
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("titan_quant.trader.simulador")
        self.assertNotIn("simulacion", autotrader.MODALIDADES)
        self.assertNotIn("simulador", [b for v in autotrader.BROKERS_POR_MODALIDAD.values() for b in v])
        with self.assertRaises(ValueError):
            autotrader.adaptador_para(self.u, {"broker": "simulador", "modalidad": M})

    def test_emergencia_pide_el_cierre_al_broker(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        oid = self._ciclo()["operacion_id"]
        orig = autotrader.adaptador_para
        autotrader.adaptador_para = lambda *a, **k: Fijo()
        try:
            autotrader.cambiar_estado(self.u, M, "emergencia")
        finally:
            autotrader.adaptador_para = orig
        op = self._op(oid)
        self.assertEqual((op["estado"], op["fuente_resultado"]), ("cerrada", "broker"))
        self.assertEqual(self._ciclo()["accion"], "emergencia")
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE importancia='critica'"))

    def test_no_se_cambia_config_con_bot_activo(self):
        autotrader.cambiar_estado(self.u, M, "activo")
        with self.assertRaises(ValueError):
            autotrader.guardar_ajustes(self.u, M, {"riesgo_pct": 2})
        autotrader.guardar_ajustes(self.u, "binaria", {"riesgo_pct": 2})               # otra cuenta: independiente

    def test_migra_base_antigua_sin_inventar_verificaciones(self):
        almacen.reiniciar_para_pruebas()
        ruta = almacen.ruta("binaria")
        for extra in ("", "-wal", "-shm"):
            ruta.with_name(ruta.name + extra).unlink(missing_ok=True)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(ruta))
        c.executescript("""CREATE TABLE operaciones(id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL, modalidad TEXT NOT NULL,
            broker TEXT NOT NULL, cuenta TEXT, instrumento TEXT NOT NULL, simbolo_broker TEXT, mercado TEXT NOT NULL, tipo TEXT NOT NULL,
            direccion TEXT NOT NULL, monto REAL NOT NULL, riesgo_importe REAL, volumen INTEGER, moneda TEXT, precio_entrada REAL, stop REAL,
            objetivo REAL, payout REAL, expira_ts INTEGER, costo REAL NOT NULL DEFAULT 0,
            estado TEXT NOT NULL CHECK(estado IN ('abierta','cerrada','rechazada')), abierta_ts INTEGER NOT NULL, cerrada_ts INTEGER,
            precio_salida REAL, resultado REAL, r REAL, motivo_cierre TEXT, id_externo TEXT, fuente_precio TEXT, estrategia TEXT, horizonte TEXT,
            motores TEXT, controles TEXT, clave_dedupe TEXT);
            INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,abierta_ts,cerrada_ts,resultado,id_externo)
              VALUES(1,'binaria','iqoption','EURGBP-OTC','binarias','binaria','alcista',1,'cerrada',1,2,0.86,'123');
            INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,abierta_ts,cerrada_ts,resultado)
              VALUES(1,'binaria','iqoption','EURGBP-OTC','binarias','binaria','alcista',1,'cerrada',1,2,5.0);
            INSERT INTO operaciones(usuario_id,modalidad,broker,instrumento,mercado,tipo,direccion,monto,estado,abierta_ts)
              VALUES(1,'binaria','iqoption','EURGBP-OTC','binarias','binaria','alcista',1,'rechazada',1);""")
        c.commit()
        c.close()
        filas = almacen.q("binaria", "SELECT estado, fase, fuente_resultado FROM operaciones ORDER BY id")
        self.assertEqual([(f["estado"], f["fase"], f["fuente_resultado"]) for f in filas],
                         [("cerrada", "resultado_recibido", "broker"), ("error", "error_broker", None), ("rechazada", "oportunidad_detectada", None)])
        self.assertEqual(autotrader.resumen(1)["binaria"]["n"], 1)


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
        integraciones.guardar(u, "telegram", {"token": "CLAVE-SUPER-SECRETA-99", "chat_id": "42424242"})
        orig = integraciones._probar
        integraciones._probar = lambda uid, p: (_ for _ in ()).throw(RuntimeError("fallo con CLAVE-SUPER-SECRETA-99 en la URL"))
        try:
            r = integraciones.probar(u, "telegram")
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
