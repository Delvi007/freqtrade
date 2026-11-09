"""Pruebas de seguridad: cifrado, contraseñas, cuentas, sesiones, tokens, bloqueo y bóveda."""
import os
import time

from titan_quant import config, db
from titan_quant.pruebas.base_prueba import Base
from titan_quant.seguridad import boveda, cripto, cuentas


class TestCripto(Base):
    def test_ida_y_vuelta_y_manipulacion_ambos_algoritmos(self):
        original = cripto.AESGCM
        try:
            for alg in (original, None):
                cripto.AESGCM = alg
                b = cripto.cifrar("secreto ñ 123", "u1|telegram|token")
                self.assertNotIn(b"secreto", b)
                self.assertEqual(cripto.descifrar(b, "u1|telegram|token"), "secreto ñ 123")
                with self.assertRaises(cripto.ErrorCifrado):
                    cripto.descifrar(b[:-1] + bytes([b[-1] ^ 1]), "u1|telegram|token")
                with self.assertRaises(cripto.ErrorCifrado):
                    cripto.descifrar(b, "u2|telegram|token")       # ligado a su fila
        finally:
            cripto.AESGCM = original

    def test_v1_legible_aunque_luego_exista_aes(self):
        original = cripto.AESGCM
        cripto.AESGCM = None
        b = cripto.cifrar("x", "c")
        cripto.AESGCM = original
        self.assertEqual(cripto.descifrar(b, "c"), "x")

    def test_clave_maestra_permiso_600_y_estable(self):
        k1 = cripto.clave_maestra()
        cripto._CACHE.clear()
        self.assertEqual(k1, cripto.clave_maestra())
        if os.name == "nt":
            self.skipTest("Permisos POSIX no aplican en Windows: la ACL de la clave se revisa con icacls (ver instrucciones)")
        self.assertEqual(oct(config.CLAVE_MAESTRA.stat().st_mode & 0o777), "0o600")

    def test_hash_contrasena_y_fallback(self):
        h = cripto.hash_clave("Una-Clave-Larga-1")
        self.assertTrue(h.startswith(("scrypt$", "pbkdf2$")))
        self.assertNotIn("Una-Clave", h)
        self.assertTrue(cripto.verificar_clave("Una-Clave-Larga-1", h))
        self.assertFalse(cripto.verificar_clave("otra", h))
        self.assertNotEqual(h, cripto.hash_clave("Una-Clave-Larga-1"))   # sal distinta
        import base64
        import hashlib
        sal = b"0123456789abcdef"
        p = "pbkdf2$1000$%s$%s" % (base64.b64encode(sal).decode(), base64.b64encode(hashlib.pbkdf2_hmac("sha256", b"abc", sal, 1000)).decode())
        self.assertTrue(cripto.verificar_clave("abc", p))

    def test_mascara(self):
        self.assertEqual(cripto.enmascarar("123456:ABCDEFGHIJKL"), "••••IJKL")
        self.assertEqual(cripto.enmascarar("corto"), "••••")
        self.assertTrue(cripto.enmascarar("persona@correo.com").startswith("pe•••@"))


class TestCuentas(Base):
    def test_registro_primer_usuario_es_propietario_y_contrasena_no_en_claro(self):
        u = self.usuario()
        self.assertEqual(u["rol"], "propietario")
        u2 = self.usuario("otro@ejemplo.com")
        self.assertEqual(u2["rol"], "usuario")
        fila = db.q1("SELECT clave_hash FROM usuarios WHERE id=?", (u["id"],))
        self.assertNotIn("Titan-Quant", fila["clave_hash"])

    def test_duplicado_no_revela_existencia(self):
        self.usuario()
        self.assertEqual(cuentas.registrar("X Y", "DUENO@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True), (None, None))

    def test_validaciones(self):
        for args in (("", "a@b.co", "Titan-Quant-2026!", "Titan-Quant-2026!", True),
                     ("Ana", "no-es-correo", "Titan-Quant-2026!", "Titan-Quant-2026!", True),
                     ("Ana", "a@b.co", "corta1A!", "corta1A!", True),
                     ("Ana", "a@b.co", "solominusculas", "solominusculas", True),
                     ("Ana", "a@b.co", "Titan-Quant-2026!", "distinta-2026!A", True),
                     ("Ana", "a@b.co", "Titan-Quant-2026!", "Titan-Quant-2026!", False)):
            with self.assertRaises(cuentas.ErrorCuenta):
                cuentas.registrar(*args)

    def test_verificacion_obligatoria_y_token_de_un_uso(self):
        u, tok = cuentas.registrar("Ana", "ana@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True)
        with self.assertRaises(cuentas.ErrorCuenta):
            cuentas.iniciar_sesion("ana@ejemplo.com", "Titan-Quant-2026!")
        cuentas.verificar_correo(tok)
        with self.assertRaises(cuentas.ErrorCuenta):
            cuentas.verificar_correo(tok)
        self.assertTrue(cuentas.iniciar_sesion("ana@ejemplo.com", "Titan-Quant-2026!")[1])
        self.assertIsNone(db.q1("SELECT * FROM tokens WHERE hash=?", (tok,)))   # se guarda el hash, no el token

    def test_token_caducado(self):
        u, tok = cuentas.registrar("Ana", "ana@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True)
        with db.tx() as c:
            c.execute("UPDATE tokens SET expira_ts=?", (int(time.time()) - 1,))
        with self.assertRaises(cuentas.ErrorCuenta):
            cuentas.verificar_correo(tok)

    def test_bloqueo_tras_fallos_y_mensaje_generico(self):
        self.usuario()
        msgs = set()
        for _ in range(config.INTENTOS_MAX):
            with self.assertRaises(cuentas.ErrorCuenta) as e:
                cuentas.iniciar_sesion("dueno@ejemplo.com", "mala")
            msgs.add(str(e.exception))
        with self.assertRaises(cuentas.ErrorCuenta) as e:
            cuentas.iniciar_sesion("dueno@ejemplo.com", "Titan-Quant-2026!")   # correcta pero bloqueada
        msgs.add(str(e.exception))
        with self.assertRaises(cuentas.ErrorCuenta) as e:
            cuentas.iniciar_sesion("nadie@ejemplo.com", "x")
        msgs.add(str(e.exception))
        self.assertEqual(msgs, {cuentas.MSG_LOGIN})
        tipos = [x["tipo"] for x in cuentas.eventos(1, 20)]
        self.assertIn("cuenta_bloqueada", tipos)

    def test_sesiones_cierre_y_caducidad(self):
        self.usuario()
        _, t1, csrf = cuentas.iniciar_sesion("dueno@ejemplo.com", "Titan-Quant-2026!")
        _, t2, _ = cuentas.iniciar_sesion("dueno@ejemplo.com", "Titan-Quant-2026!")
        s1 = cuentas.sesion(t1)
        self.assertEqual(s1["csrf"], csrf)
        self.assertIsNone(db.q1("SELECT * FROM sesiones WHERE id=?", (t1,)))     # token en claro nunca en la BD
        cuentas.cerrar_todas(1, excepto=s1["sesion_id"])
        self.assertIsNone(cuentas.sesion(t2))
        self.assertIsNotNone(cuentas.sesion(t1))
        with db.tx() as c:
            c.execute("UPDATE sesiones SET expira_ts=1")
        self.assertIsNone(cuentas.sesion(t1))

    def test_restablecer_invalida_sesiones_y_token(self):
        self.usuario()
        _, t1, _ = cuentas.iniciar_sesion("dueno@ejemplo.com", "Titan-Quant-2026!")
        u, tok = cuentas.solicitar_restablecimiento("dueno@ejemplo.com")
        self.assertEqual(cuentas.solicitar_restablecimiento("nadie@ejemplo.com"), (None, None))
        cuentas.restablecer(tok, "Nueva-Clave-2026#", "Nueva-Clave-2026#")
        self.assertIsNone(cuentas.sesion(t1))
        with self.assertRaises(cuentas.ErrorCuenta):
            cuentas.restablecer(tok, "Otra-Clave-2026#", "Otra-Clave-2026#")
        self.assertTrue(cuentas.iniciar_sesion("dueno@ejemplo.com", "Nueva-Clave-2026#")[1])

    def test_cambiar_clave_exige_la_actual(self):
        self.usuario()
        with self.assertRaises(cuentas.ErrorCuenta):
            cuentas.cambiar_clave(1, "mala", "Nueva-Clave-2026#", "Nueva-Clave-2026#")
        cuentas.cambiar_clave(1, "Titan-Quant-2026!", "Nueva-Clave-2026#", "Nueva-Clave-2026#")
        self.assertTrue(cuentas.iniciar_sesion("dueno@ejemplo.com", "Nueva-Clave-2026#")[1])


class TestBoveda(Base):
    def test_guardar_mascara_leer_eliminar(self):
        u = self.usuario()
        boveda.guardar(u["id"], "telegram", {"token": "123456789:ABCDEFGHIJKLMNOP", "chat_id": "555666"})
        fila = db.q1("SELECT cifrado, mascara FROM credenciales WHERE campo='token'")
        self.assertNotIn(b"ABCDEFGH", bytes(fila["cifrado"]))
        self.assertEqual(fila["mascara"], "••••MNOP")
        self.assertEqual(boveda.leer(u["id"], "telegram")["token"], "123456789:ABCDEFGHIJKLMNOP")
        boveda.guardar(u["id"], "telegram", {"token": "", "chat_id": None})        # vacío no borra
        self.assertEqual(boveda.leer(u["id"], "telegram")["chat_id"], "555666")
        self.assertEqual(boveda.eliminar(u["id"], "telegram"), 2)
        self.assertEqual(boveda.leer(u["id"], "telegram"), {})

    def test_usuarios_separados(self):
        a = self.usuario()
        b = self.usuario("b@ejemplo.com")
        boveda.guardar(a["id"], "finnhub", {"api_key": "CLAVE-A-123456"})
        self.assertEqual(boveda.leer(b["id"], "finnhub"), {})


class TestDB(Base):
    def test_migracion_idempotente_y_respaldo(self):
        db.con()
        v1 = db.q1("SELECT MAX(version) v FROM esquema_version")["v"]
        db.reiniciar_para_pruebas()
        db.con()
        self.assertEqual(db.q1("SELECT MAX(version) v FROM esquema_version")["v"], v1)
        self.assertEqual(v1, len(db.MIGRACIONES))
        r = db.respaldar()
        self.assertTrue(r.exists())
        if os.name == "nt":
            self.skipTest("Permisos POSIX no aplican en Windows: la ACL de las copias se revisa con icacls")
        self.assertEqual(oct(r.stat().st_mode & 0o777), "0o600")

    def test_transaccion_revierte(self):
        self.usuario()
        with self.assertRaises(RuntimeError):
            with db.tx() as c:
                c.execute("UPDATE usuarios SET nombre='X'")
                raise RuntimeError("fallo")
        self.assertEqual(db.q1("SELECT nombre FROM usuarios")["nombre"], "Dueño")

    def test_registro_no_escribe_secretos(self):
        from titan_quant.registro import limpiar
        t = limpiar('GET /x?token=abc123&clave=hola bot123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA {"api_key": "zzz"}')
        for s in ("abc123", "hola", "AAAAAAAAAAAAAAAAAAAA", "zzz"):
            self.assertNotIn(s, t)


class TestAdministracion(Base):
    def test_primera_cuenta_local_activada_y_remota_no(self):
        u, tok = cuentas.registrar("Admin", "admin@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True, "127.0.0.1")
        self.assertIsNone(tok)
        self.assertTrue(u["verificado"] and u["aprobado"] and u["admin"])
        self.assertTrue(cuentas.iniciar_sesion("admin@ejemplo.com", "Titan-Quant-2026!", "127.0.0.1")[1])

    def test_primera_cuenta_desde_la_red_exige_correo(self):
        u, tok = cuentas.registrar("Admin", "admin@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True, "192.168.1.50")
        self.assertTrue(tok)
        with self.assertRaises(cuentas.ErrorCuenta):
            cuentas.iniciar_sesion("admin@ejemplo.com", "Titan-Quant-2026!", "192.168.1.50")

    def test_propietario_atascado_se_activa_en_el_dispositivo(self):
        """Caso real: el propietario se registró pero el correo nunca llegó."""
        cuentas.registrar("Admin", "admin@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True, "192.168.1.50")
        with self.assertRaises(cuentas.ErrorCuenta):
            cuentas.iniciar_sesion("admin@ejemplo.com", "mala", "127.0.0.1")
        self.assertTrue(cuentas.iniciar_sesion("admin@ejemplo.com", "Titan-Quant-2026!", "127.0.0.1")[1])
        self.assertIn("propietario_activado_en_dispositivo", [e["tipo"] for e in cuentas.eventos(1)])

    def test_solicitud_aprobacion_y_correo_de_aceptacion(self):
        from titan_quant.seguridad import administracion
        cuentas.registrar("Admin", "admin@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True, "127.0.0.1")
        u, tok = cuentas.registrar("Ana", "ana@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True, "127.0.0.1")
        self.assertFalse(u["aprobado"])
        cuentas.verificar_correo(tok)
        with self.assertRaises(cuentas.ErrorCuenta) as e:
            cuentas.iniciar_sesion("ana@ejemplo.com", "Titan-Quant-2026!", "127.0.0.1")
        self.assertIn("pendiente", str(e.exception))
        administracion.notificar_solicitud(u)
        self.assertTrue(db.q1("SELECT * FROM alertas WHERE usuario_id=1 AND tipo LIKE 'Nueva solicitud%'"))
        actor = cuentas.usuario(1)
        r = administracion.aprobar(actor, u["id"])
        self.assertEqual(r["correo"], "archivo")
        self.assertTrue(cuentas.iniciar_sesion("ana@ejemplo.com", "Titan-Quant-2026!")[1])
        with self.assertRaises(administracion.ErrorAdmin):
            administracion.hacer_admin(cuentas.usuario(u["id"]), 1)
        self.assertTrue(db.q1("SELECT * FROM auditoria WHERE accion='usuario_aprobado'"))

    def test_sin_aprobacion_obligatoria(self):
        cuentas.registrar("Admin", "admin@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True, "127.0.0.1")
        db.set_cfg_sistema("registro_requiere_aprobacion", False)
        u, tok = cuentas.registrar("Ana", "ana@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True)
        self.assertTrue(u["aprobado"])

    def test_explicacion_de_errores_smtp(self):
        import smtplib
        from titan_quant import correo
        e = smtplib.SMTPAuthenticationError(535, b"5.7.139 Authentication unsuccessful, basic authentication is disabled")
        self.assertIn("Hotmail", correo.explicar_error(e, {"host": "smtp-mail.outlook.com"}))
        self.assertIn("CONTRASEÑA DE APLICACIÓN", correo.explicar_error(smtplib.SMTPAuthenticationError(535, b"bad"), {"host": "smtp.gmail.com"}))

    def test_preset_gmail(self):
        from titan_quant import integraciones
        u = self.usuario()
        integraciones.guardar(u["id"], "correo_smtp", {"proveedor_correo": "gmail", "usuario": "titan@gmail.com", "clave": "abcd efgh ijkl mnop"})
        import json as _j
        aj = _j.loads(db.q1("SELECT ajustes FROM integraciones WHERE proveedor='correo_smtp'")["ajustes"])
        self.assertEqual((aj["host"], aj["puerto"], aj["seguridad"]), ("smtp.gmail.com", "465", "ssl"))
        from titan_quant import correo
        self.assertTrue(correo.configurado())

    def test_migracion_marca_propietario_como_admin(self):
        u = self.usuario()
        self.assertTrue(u["admin"])
        self.assertEqual(db.q1("SELECT MAX(version) v FROM esquema_version")["v"], 4)


class TestEnvioSMTP(Base):
    """Comprueba el camino SMTP real (con un servidor SMTP falso en memoria)."""

    def test_aprobacion_envia_por_smtp_y_error_explicado(self):
        import smtplib
        from titan_quant import correo, integraciones
        from titan_quant.seguridad import administracion
        enviados = []

        class Falso:
            def __init__(self, host, puerto, context=None, timeout=None):
                self.host = host

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, u, c):
                if c != "clave-app-buena":
                    raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

            def send_message(self, m):
                enviados.append((m["To"], m["Subject"], m.get_content()))

        orig = smtplib.SMTP_SSL
        smtplib.SMTP_SSL = Falso
        try:
            adm, _ = cuentas.registrar("Admin", "admin@ejemplo.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True, "127.0.0.1")
            integraciones.guardar(adm["id"], "correo_smtp", {"proveedor_correo": "gmail", "usuario": "titan@gmail.com", "clave": "clave-app-buena"})
            u, tok = cuentas.registrar("Ana", "ana@hotmail.com", "Titan-Quant-2026!", "Titan-Quant-2026!", True)
            self.assertEqual(correo.verificacion(u, tok), "smtp")
            r = administracion.aprobar(cuentas.usuario(adm["id"]), u["id"])
            self.assertEqual(r["correo"], "smtp")
            self.assertEqual([e[0] for e in enviados], ["ana@hotmail.com", "ana@hotmail.com"])
            self.assertIn("aceptada", enviados[1][1])
            self.assertIn("/api/auth/verificar?token=", enviados[0][2])
            integraciones.guardar(adm["id"], "correo_smtp", {"clave": "mala"})
            r = administracion.aprobar(cuentas.usuario(adm["id"]), u["id"])
            self.assertEqual(r["correo"], "error")
            self.assertIn("CONTRASEÑA DE APLICACIÓN", r["aviso_correo"])
            self.assertNotIn("mala", r["aviso_correo"])
        finally:
            smtplib.SMTP_SSL = orig
