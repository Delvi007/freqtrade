"""Pruebas HTTP de extremo a extremo: autenticación, CSRF, origen, permisos, límites, cabeceras y conexiones con módulos heredados."""
import glob
import re
import threading
import time

from titan_quant import config, servidor
from titan_quant.pruebas.base_prueba import Base
from titan_quant.pruebas.cliente import Cliente
from titan_quant.seguridad import limites

CLAVE = "Titan-Quant-2026!"


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


class TestServidor(Base):
    def setUp(self):
        super().setUp()
        self.srv = servidor.crear("127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def entrar(self, correo="dueno@ejemplo.com"):
        """La primera cuenta (desde 127.0.0.1) es el administrador y queda activa al instante.
        Las siguientes confirman el correo y las aprueba el administrador (self.admin)."""
        c = Cliente(self.base)
        code, d, _ = c.post("/api/auth/registro", {"nombre": "Persona", "correo": correo, "clave": CLAVE, "clave2": CLAVE, "acepta": True, "t": (time.time() - 5) * 1000})
        self.assertEqual(code, 200, d)
        if not d.get("activado"):
            f = [x for x in glob.glob(str(config.SALIDA_CORREO) + "/*") if correo.replace("@", "_at_") in x and "confirma" in leer(x)]
            with open(sorted(f)[-1], encoding="utf-8") as fh:
                tok = re.search(r"token=([\w-]+)", fh.read()).group(1)
            code, _, h = c.get("/api/auth/verificar?token=" + tok)
            self.assertEqual((code, h.get("Location")), (302, "/#verificado"))
            code, d, _ = c.post("/api/auth/login", {"correo": correo, "clave": CLAVE})
            self.assertEqual(code, 400)
            self.assertIn("pendiente de aprobación", d["error"])
            uid = next(u["id"] for u in self.admin.get("/api/admin/usuarios")[1]["usuarios"] if u["correo"] == correo)
            code, d, _ = self.admin.post("/api/admin/aprobar", {"id": uid})
            self.assertEqual((code, d["correo"]), (200, "archivo"), d)
        code, d, h = c.post("/api/auth/login", {"correo": correo, "clave": CLAVE})
        self.assertEqual(code, 200, d)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        self.assertIn("SameSite=Lax", h["Set-Cookie"])
        c.csrf = d["csrf"]
        if not hasattr(self, "admin"):
            self.admin = c
        return c

    def test_todo_exige_sesion(self):
        c = Cliente(self.base)
        for r in ("/api/tq/motores", "/api/tq/alertas", "/api/tq/operador", "/api/tq/integraciones", "/api/assets", "/api/history",
                  "/api/lab/estado", "/api/plans", "/api/chart?symbol=GC=F"):
            self.assertEqual(c.get(r)[0], 401, r)
        for r in ("/api/tq/analizar", "/api/plan/cancel", "/api/lab/motor", "/api/analyze"):
            self.assertEqual(c.post(r, {})[0], 401, r)
        self.assertEqual(c.get("/api/health")[0], 200)
        self.assertEqual(c.get("/")[0], 200)

    def test_csrf_y_origen(self):
        c = self.entrar()
        tok = c.csrf
        c.csrf = None
        self.assertEqual(c.post("/api/tq/nivel", {"nivel": "basico"})[0], 403)
        c.csrf = tok
        self.assertEqual(c.pedir("POST", "/api/tq/nivel", {"nivel": "basico"}, {"Origin": "http://malo.example"})[0], 403)
        self.assertEqual(c.post("/api/tq/nivel", {"nivel": "basico"})[0], 200)

    def test_cabeceras_de_seguridad_y_archivos_ocultos(self):
        c = Cliente(self.base)
        _, _, h = c.get("/")
        for k in ("Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"):
            self.assertIn(k, h)
        for r in ("/.clave_maestra", "/../datos/titan_quant.db", "/titan_quant.db"):
            self.assertIn(c.get(r)[0], (404,), r)

    def test_flujo_completo_y_conexiones_heredadas(self):
        c = self.entrar()
        code, d, _ = c.post("/api/tq/analizar", {"simbolo": "GC=F", "horizonte": "intradia"})
        self.assertEqual(code, 200, d)
        self.assertEqual(len(d["resultado"]["motores"]), 23)
        self.assertEqual(c.get(f"/api/tq/analisis?id={d['id']}")[0], 200)
        for r in ("/api/tq/motores", "/api/tq/sistema", "/api/tq/hardware", "/api/tq/niveles", "/api/tq/alertas", "/api/tq/alertas/categorias",
                  "/api/tq/historial?tipo=analisis", "/api/tq/historial?tipo=plan", "/api/tq/historial?tipo=lab", "/api/tq/operador",
                  "/api/tq/operador/operaciones", "/api/tq/operador/decisiones", "/api/tq/integraciones", "/api/tq/diagnostico",
                  "/api/auth/sesiones", "/api/cuenta/eventos", "/api/cuenta/preferencias",
                  "/api/assets", "/api/history", "/api/stats", "/api/alerts", "/api/plans", "/api/quotes?symbols=GC=F",
                  "/api/chart?symbol=GC=F&tf=15m", "/api/mtf?symbol=GC=F", "/api/lab/estado", "/api/lab/metricas"):
            code, d, _ = c.get(r)
            self.assertEqual(code, 200, f"{r}: {d}")
        self.assertEqual(c.post("/api/analyze", {"simbolo": "GC=F"})[0], 200)
        self.assertEqual(c.post("/api/plan", {"simbolo": "GC=F", "modo": "intradia"})[0], 200)
        self.assertEqual(c.post("/api/tq/operador/estado", {"estado": "activo"})[0], 200)
        code, d, _ = c.post("/api/tq/operador/ciclo")
        self.assertEqual(code, 200, d)
        self.assertEqual(c.post("/api/tq/operador/estado", {"estado": "emergencia"})[0], 200)
        self.assertEqual(c.post("/api/cuenta/preferencias", {"sonidos": {"activado": True, "volumen": 0.4}})[0], 200)
        self.assertEqual(c.post("/api/cuenta/preferencias", {"riesgo": {"capital": 1000, "riesgo_pct": 9}})[0], 400)
        self.assertEqual(c.post("/api/tq/operador/real", {"frase": "x", "clave": CLAVE})[0], 400)

    def test_ctrader_demo_y_real_por_separado_desde_la_api(self):
        from titan_quant.pruebas.ctrader_falso import CTraderFalso
        from titan_quant.seguridad import boveda
        c = self.entrar()
        uid = c.get("/api/auth/yo")[1]["usuario"]["id"]
        with CTraderFalso() as f:
            boveda.guardar(uid, "ctrader", {"client_id": f.mundo.client_id, "client_secret": f.mundo.client_secret, "redirect_uri": "http://x/cb",
                                            "access_token": "tok-trading", "refresh_token": "ref-1"})
            code, d, _ = c.get("/api/tq/ctrader/cuentas?modalidad=demo")
            self.assertEqual((code, sorted(x["ctid"] for x in d["cuentas"])), (200, [9001, 9002]), d)
            code, d, _ = c.get("/api/tq/ctrader/cuentas?modalidad=real")
            self.assertEqual([x["ctid"] for x in d["cuentas"]], [7001])
            self.assertNotIn("tok-trading", str(d))
            code, d, _ = c.get("/api/tq/ctrader/simbolos?modalidad=demo&cuenta=9001")
            self.assertIn("XAUUSD", d["simbolos"])
            self.assertFalse(c.get("/api/tq/ctrader/simbolos?modalidad=demo&cuenta=7001")[1]["ok"])      # cuenta real en demo: no
            code, d, _ = c.post("/api/tq/operador/ajustes", {"modalidad": "demo", "ajustes": {"broker": "ctrader", "cuenta_ctid": 9001, "simbolo_broker": "xauusd"}})
            self.assertEqual((code, d["ajustes"]["simbolo_broker"]), (200, "XAUUSD"), d)
            code, d, _ = c.post("/api/tq/operador/ajustes", {"modalidad": "real", "ajustes": {"broker": "ctrader", "cuenta_ctid": 7001}})
            self.assertEqual(code, 200, d)
            code, d, _ = c.get("/api/tq/operador?modalidad=demo")
            self.assertEqual((d["bots"]["demo"]["ajustes"]["cuenta_ctid"], d["bots"]["real"]["ajustes"]["cuenta_ctid"]), (9001, 7001))
            self.assertTrue(d["ctrader_autorizado"])
            self.assertEqual(c.post("/api/tq/operador/estado", {"modalidad": "real", "estado": "activo"})[0], 403)          # sin contraseña
            self.assertEqual(c.post("/api/tq/operador/estado", {"modalidad": "real", "estado": "activo", "clave": CLAVE})[0], 403)   # no habilitado
            self.assertEqual(c.post("/api/tq/operador/estado", {"modalidad": "mixta", "estado": "activo"})[0], 400)
            self.assertEqual(c.post("/api/tq/operador/estado", {"modalidad": "demo", "estado": "pausado"})[0], 200)
            self.assertEqual(c.get("/api/tq/operador/decisiones?modalidad=real")[1]["decisiones"], [])
            self.assertEqual(len(c.get("/api/tq/operador/decisiones?modalidad=demo")[1]["decisiones"]), 1)
            self.assertEqual(c.get("/api/tq/historial?tipo=decision_demo")[0], 200)

    def test_secretos_nunca_salen_por_la_api(self):
        c = self.entrar()
        self.assertEqual(c.post("/api/tq/integraciones/guardar", {"proveedor": "telegram", "valores": {"token": "999:SECRETO-TELEGRAM-XYZ", "chat_id": "1234567"}})[0], 200)
        for r in ("/api/tq/integraciones", "/api/tq/diagnostico", "/api/tq/sistema", "/api/cuenta/eventos"):
            _, d, _ = c.get(r)
            self.assertNotIn("SECRETO-TELEGRAM", str(d), r)
        self.assertNotIn(b"SECRETO-TELEGRAM", open(config.REGISTRO, "rb").read() if config.REGISTRO.exists() else b"")

    def test_permisos_propietario_y_privacidad(self):
        self.entrar()
        otro = self.entrar("otro@ejemplo.com")
        for r in ("/api/history", "/api/lab/estado", "/api/plans", "/api/tq/diagnostico", "/api/tq/sistema", "/api/admin/usuarios"):
            self.assertEqual(otro.get(r)[0], 403, r)
        self.assertEqual(otro.post("/api/plan/cancel", {"id": 1})[0], 403)
        self.assertEqual(otro.get("/api/tq/analisis?id=1")[0], 404)
        self.assertEqual(otro.get("/api/assets")[0], 200)

    def test_limite_de_intentos_de_login(self):
        limites.reiniciar()
        c = Cliente(self.base)
        codigos = [c.post("/api/auth/login", {"correo": "x@ejemplo.com", "clave": "x"})[0] for _ in range(12)]
        self.assertIn(429, codigos)

    def test_enumeracion_y_cierre_de_sesion(self):
        c = self.entrar()
        _, d1, _ = Cliente(self.base).post("/api/auth/olvide", {"correo": "dueno@ejemplo.com"})
        _, d2, _ = Cliente(self.base).post("/api/auth/olvide", {"correo": "nadie@ejemplo.com"})
        self.assertEqual(d1["mensaje"], d2["mensaje"])
        self.assertEqual(c.post("/api/auth/logout")[0], 200)
        self.assertEqual(c.get("/api/tq/motores")[0], 401)

    def test_error_interno_no_revela_detalles(self):
        c = self.entrar()
        import titan_quant.servidor as s
        orig = s.RUTAS_GET["/api/tq/niveles"]
        s.RUTAS_GET["/api/tq/niveles"] = lambda h, q: 1 / 0
        try:
            code, d, _ = c.get("/api/tq/niveles")
        finally:
            s.RUTAS_GET["/api/tq/niveles"] = orig
        self.assertEqual(code, 500)
        self.assertNotIn("ZeroDivision", d["error"])
        self.assertIn("referencia", d["error"])


    def test_administracion_completa(self):
        adm = self.entrar()
        _, d, _ = adm.get("/api/auth/yo")
        self.assertTrue(d["usuario"]["admin"])
        self.assertEqual(d["usuario"]["rol"], "propietario")
        otro = self.entrar("otro@ejemplo.com")
        uid = next(u["id"] for u in adm.get("/api/admin/usuarios")[1]["usuarios"] if u["correo"] == "otro@ejemplo.com")
        aceptacion = [x for x in glob.glob(str(config.SALIDA_CORREO) + "/*") if "otro_at_" in x and "aceptada" in leer(x)]
        self.assertTrue(aceptacion, "correo de aceptación generado")
        self.assertEqual(otro.post("/api/admin/aprobar", {"id": 1})[0], 403)          # un usuario normal no administra
        self.assertEqual(adm.post("/api/admin/suspender", {"id": 1})[0], 400)          # el propietario no se suspende
        self.assertEqual(adm.post("/api/admin/hacer_admin", {"id": uid})[0], 200)
        self.assertEqual(otro.get("/api/admin/usuarios")[0], 200)                      # ahora es administrador
        self.assertEqual(otro.post("/api/admin/suspender", {"id": 1})[0], 400)
        self.assertEqual(adm.post("/api/admin/quitar_admin", {"id": uid})[0], 200)
        self.assertEqual(adm.post("/api/admin/suspender", {"id": uid})[0], 200)
        self.assertEqual(otro.get("/api/tq/motores")[0], 401)                          # sesión cortada
        code, d, _ = Cliente(self.base).post("/api/auth/login", {"correo": "otro@ejemplo.com", "clave": CLAVE})
        self.assertIn("suspendida", d["error"])
        self.assertEqual(adm.post("/api/admin/reactivar", {"id": uid})[0], 200)
        self.assertEqual(Cliente(self.base).post("/api/auth/login", {"correo": "otro@ejemplo.com", "clave": CLAVE})[0], 200)
        code, d, _ = adm.post("/api/admin/correo_prueba")
        self.assertEqual(code, 400)
        self.assertIn("no está configurado", d["error"])
        self.assertEqual(adm.post("/api/admin/config", {"requiere_aprobacion": False})[0], 200)
        _, d, _ = Cliente(self.base).get("/api/auth/estado")
        self.assertFalse(d["requiere_aprobacion"])

    def test_estado_inicial_indica_configuracion(self):
        _, d, _ = Cliente(self.base).get("/api/auth/estado")
        self.assertFalse(d["hay_usuarios"])
        self.assertTrue(d["local"])
