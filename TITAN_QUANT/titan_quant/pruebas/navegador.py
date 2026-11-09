"""Prueba de extremo a extremo en un navegador real (Chromium + Playwright), si está disponible.
Uso: python3 -m titan_quant.pruebas.navegador URL CARPETA_CORREO CARPETA_CAPTURAS"""
import glob
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL, CORREO, CAPT = sys.argv[1], sys.argv[2], sys.argv[3]
errores, fallos = [], []


def ok(c, m):
    print(("  OK     " if c else "  FALLA  ") + m, flush=True)
    if not c:
        fallos.append(m)


with sync_playwright() as p:
    b = p.chromium.launch()
    for ancho, nombre in ((1366, "pc"), (390, "movil")):
        ctx = b.new_context(viewport={"width": ancho, "height": 900})
        pg = ctx.new_page()
        # Los 401 previos al inicio de sesión son esperados (scripts heredados piden datos antes de entrar).
        pg.on("console", lambda m: m.type == "error" and "status of 401" not in m.text and "status of 400" not in m.text and errores.append(m.text))
        pg.on("pageerror", lambda e: errores.append(str(e)))
        pg.on("response", lambda r: r.status >= 400 and r.status != 401 and not r.url.endswith("/api/auth/login") and errores.append(f"HTTP {r.status} {r.request.method} {r.url.split('?')[0]}"))
        pg.goto(URL)
        pg.wait_for_selector("#tqGate:not([hidden])")
        ok(pg.is_visible("#tqGate button:has-text('CREAR CUENTA')"), f"[{nombre}] pantalla de bienvenida con CREAR CUENTA")
        if nombre == "pc":
            ok(pg.is_visible("#tqGate button:has-text('CREAR CUENTA DE ADMINISTRADOR')"), "configuración inicial ofrece crear la cuenta de administrador")
        pg.screenshot(path=f"{CAPT}/01_bienvenida_{nombre}.png", full_page=True)
        correo = f"usuario_{nombre}@ejemplo.com"
        if nombre == "pc":
            pg.click("#tqGate button:has-text('CREAR CUENTA')")
            pg.fill("#tqGate input[name=nombre]", "Janio Prueba")
            pg.fill("#tqGate input[name=correo]", correo)
            pg.fill("#tqGate input[name=clave]", "Titan-Quant-2026!")
            pg.fill("#tqGate input[name=clave2]", "Titan-Quant-2026!")
            pg.check("#tqGate input[name=acepta]")
            time.sleep(2.2)
            pg.click("#tqGate button.primary")
            pg.wait_for_selector("#tqGate .tq-msg.ok")
            ok("ADMINISTRADOR" in pg.inner_text("#tqGate"), "primera cuenta en el dispositivo: administrador activado sin correo")
            pg.screenshot(path=f"{CAPT}/02_registro.png", full_page=True)
        else:
            pg.click("#tqGate button:has-text('INICIAR SESIÓN')")
        if nombre == "movil":
            correo = "usuario_pc@ejemplo.com"
        pg.fill("#tqGate input[name=correo]", correo)
        pg.fill("#tqGate input[name=clave]", "contraseña-mala-1A")
        pg.click("#tqGate button.primary")
        pg.wait_for_selector(".tq-msg.err")
        ok("incorrectos" in pg.inner_text("#tqGm"), f"[{nombre}] contraseña incorrecta: mensaje genérico")
        pg.fill("#tqGate input[name=clave]", "Titan-Quant-2026!")
        pg.click("#tqGate button.primary")
        pg.wait_for_selector("#tqGate", state="hidden", timeout=20000)
        pg.wait_for_selector("#tqModoTop")
        ok(pg.is_visible("#tqModoTop"), f"[{nombre}] panel central tras iniciar sesión, con indicador de modalidad")
        time.sleep(1.5)
        pg.screenshot(path=f"{CAPT}/03_panel_{nombre}.png", full_page=False)
        vistas = ["analysis", "motores", "inteligencia", "hardware", "alerts", "history", "brokers", "operator", "settings", "account", "diagnostico", "admin", "lab"]
        for v in vistas:
            pg.evaluate(f"go('{v}')")
            if v == "analysis":
                pg.wait_for_selector("#anGo")
                pg.select_option("#anHz", "corto")
                pg.click("#anGo")
                pg.wait_for_selector("text=Estado de los motores en este análisis", timeout=180000)
                filas = pg.locator("#anOut table.tq-table tr").count()
                ok(filas >= 23, f"[{nombre}] ANALIZAR MERCADO muestra los motores ({filas // 2} filas)")
            else:
                time.sleep(1.4)
            txt = pg.inner_text(f"#view-{v}")
            ok("Error interno" not in txt and len(txt) > 40, f"[{nombre}] vista {v} renderiza sin error")
            pg.screenshot(path=f"{CAPT}/v_{v}_{nombre}.png", full_page=(nombre == "pc"))
        if nombre == "pc":
            pg.evaluate("go('operator')")
            pg.wait_for_selector("#opCiclo")
            pg.click("button[data-est='activo']")
            time.sleep(1)
            pg.click("#opCiclo")
            for _ in range(360):
                if "Ciclo:" in pg.inner_text("#opM") or pg.locator("#opM .err").count():
                    break
                time.sleep(0.5)
            ok("Ciclo:" in pg.inner_text("#opM"), "bot operador ejecuta un ciclo desde la interfaz: " + pg.inner_text("#opM")[:60])
            pg.click("button[data-est='detenido']")
            time.sleep(0.8)
            # --- cuentas separadas: la DEMO no ve nada de la simulación
            pg.on("dialog", lambda dlg: dlg.accept())
            pg.click("#opMod button[data-mod='demo']")
            pg.wait_for_selector("#opF select[name=cuenta_ctid]")
            time.sleep(1)
            ok("DEMO" in pg.inner_text("#opL .tq-mode") and "demo.db" in pg.inner_text("#opL .tq-mode"), "selector de cuenta: vista DEMO con su propia base")
            pg.click("#opTabs button[data-t='decisiones']")
            time.sleep(1)
            ok("Sin decisiones" in pg.inner_text("#opT"), "la DEMO no muestra decisiones de otras cuentas")
            ok("no está autorizado" in pg.inner_text("#opCTm"), "sin token, la DEMO pide autorizar cTrader")
            # --- cTrader (servidor simulado): guardar credenciales, elegir cuenta demo y símbolo, ejecutar un ciclo
            pg.evaluate("go('brokers')")
            pg.wait_for_selector("form[data-prov='ctrader']")
            for k, v in (("client_id", "app-prueba"), ("client_secret", "secreto-app"), ("redirect_uri", "http://127.0.0.1:8799/api/tq/integraciones/ctrader/callback"),
                         ("access_token", "tok-trading"), ("refresh_token", "ref-1")):
                pg.fill(f"form[data-prov='ctrader'] input[name='ctrader__{k}']", v)
            pg.click("form[data-prov='ctrader'] button[data-acc='guardar']")
            time.sleep(1.5)
            ok("tok-trading" not in pg.inner_html("form[data-prov='ctrader']"), "token de cTrader solo enmascarado")
            pg.evaluate("go('operator')")
            pg.wait_for_selector("#opF select[name=cuenta_ctid] option[value='9001']", timeout=20000, state="attached")
            opciones = pg.inner_text("#opF select[name=cuenta_ctid]")
            ok("9001" in opciones and "7001" not in opciones, "en DEMO solo se ofrecen cuentas demo: " + opciones.replace("\n", " | ")[:90])
            pg.select_option("#opF select[name=cuenta_ctid]", "9001")
            pg.fill("#opF input[name=simbolo_broker]", "XAUUSD")
            pg.click("#opF button.primary")
            time.sleep(1.5)
            pg.wait_for_selector("#opCiclo")
            pg.click("button[data-est='activo']")
            time.sleep(1)
            pg.click("#opCiclo")
            for _ in range(360):
                if "Ciclo:" in pg.inner_text("#opM") or pg.locator("#opM .err").count():
                    break
                time.sleep(0.5)
            ok("Ciclo:" in pg.inner_text("#opM") and "broker_no_disponible" not in pg.inner_text("#opM"),
               "bot DEMO cTrader ejecuta un ciclo contra el broker: " + pg.inner_text("#opM")[:70])
            pg.screenshot(path=f"{CAPT}/v_operador_demo_ctrader.png", full_page=True)
            pg.click("button[data-est='detenido']")
            time.sleep(0.8)
            pg.click("#opMod button[data-mod='real']")
            time.sleep(1)
            ok("BLOQUEADA" in pg.inner_text("#opL .tq-mode") and pg.locator("#opRealF").count() == 0, "vista REAL bloqueada por código, sin formulario de habilitación")
            pg.click("button[data-est='activo']")
            time.sleep(0.6)
            ok("dinero real" in pg.inner_text("#opM").lower(), "el bot REAL no arranca: órdenes con dinero real deshabilitadas")
            pg.screenshot(path=f"{CAPT}/v_operador_real.png", full_page=True)
            ok(pg.locator("#opMod button[data-mod='simulacion']").count() == 0, "no existe la pestaña de simulación interna")
            pg.click("#opMod button[data-mod='binaria']")
            time.sleep(1)
            ok("RESULTADOS HISTÓRICOS CALCULADOS" in pg.inner_text("#btC"), "panel de backtesting binario etiquetado como histórico")
            pg.evaluate("go('brokers')")
            pg.wait_for_selector("form[data-prov='telegram']")
            pg.fill("form[data-prov='telegram'] input[name='telegram__token']", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
            pg.fill("form[data-prov='telegram'] input[name='telegram__chat_id']", "987654321")
            pg.click("form[data-prov='telegram'] button[data-acc='guardar']")
            time.sleep(1.5)
            html = pg.inner_html("form[data-prov='telegram']")
            ok("AAAAAAAAAAAAAAAAAAAA" not in html and "••••" in html, "credencial guardada solo se muestra enmascarada")
            pg.screenshot(path=f"{CAPT}/v_brokers_guardado.png", full_page=True)
            # --- solicitud de un segundo usuario y aprobación por el administrador
            c2 = b.new_context(viewport={"width": 1366, "height": 900})
            p2 = c2.new_page()
            p2.goto(URL)
            p2.wait_for_selector("#tqGate:not([hidden])")
            p2.click("#tqGate button:has-text('CREAR CUENTA')")
            p2.fill("#tqGate input[name=nombre]", "Ana Solicitante")
            p2.fill("#tqGate input[name=correo]", "ana@hotmail.com")
            p2.fill("#tqGate input[name=clave]", "Otra-Clave-2026!")
            p2.fill("#tqGate input[name=clave2]", "Otra-Clave-2026!")
            p2.check("#tqGate input[name=acepta]")
            time.sleep(2.2)
            p2.click("#tqGate button.primary")
            p2.wait_for_selector("#tqGate .tq-msg.ok")
            ok("administrador debe aprobar" in p2.inner_text("#tqGm"), "solicitud de cuenta: avisa de confirmación y aprobación")
            f = [x for x in sorted(glob.glob(CORREO + "/*")) if "ana_at_" in x][-1]
            with open(f, encoding="utf-8") as fh:
                tok = re.search(r"token=([\w-]+)", fh.read()).group(1)
            p2.goto(URL + "/api/auth/verificar?token=" + tok)
            p2.wait_for_selector("#tqGate >> text=Correo verificado")
            p2.fill("#tqGate input[name=correo]", "ana@hotmail.com")
            p2.fill("#tqGate input[name=clave]", "Otra-Clave-2026!")
            p2.click("#tqGate button.primary")
            p2.wait_for_selector("#tqGate .tq-msg.err")
            ok("pendiente de aprobación" in p2.inner_text("#tqGm"), "sin aprobación no se puede entrar")
            pg.evaluate("go('admin')")
            pg.wait_for_selector("button[data-ad='aprobar']")
            pg.screenshot(path=f"{CAPT}/v_admin_solicitud.png", full_page=True)
            pg.click("button[data-ad='aprobar']")
            pg.wait_for_selector("#adM3 .tq-msg")
            ok("Hecho" in pg.inner_text("#adM3"), "administrador aprueba la solicitud: " + pg.inner_text("#adM3")[:70])
            aceptado = [x for x in glob.glob(CORREO + "/*") if "ana_at_" in x and "aceptada" in open(x, encoding="utf-8").read()]
            ok(bool(aceptado), "se genera el correo de aceptación")
            p2.click("#tqGate button.primary")
            p2.wait_for_selector("#tqGate", state="hidden", timeout=20000)
            ok(not p2.locator(".nav [data-view='admin']").count(), "el usuario normal NO ve Administración")
            c2.close()
            pg.click("#tqSalir")
            pg.wait_for_selector("#tqGate:not([hidden])")
            ok(True, "cerrar sesión vuelve a la bienvenida")
        ctx.close()
    b.close()
ok(not errores, "sin errores de JavaScript en consola" + ("" if not errores else ": " + " | ".join(errores[:5])))
print("RESULTADO NAVEGADOR:", "CORRECTO" if not fallos else f"{len(fallos)} FALLOS")
sys.exit(1 if fallos else 0)
