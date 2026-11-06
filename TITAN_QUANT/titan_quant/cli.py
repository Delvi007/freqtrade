"""Comandos de TITAN QUANT.  Uso:  python3 -m titan_quant.cli COMANDO [opciones]

  servidor                   Arranca la plataforma web (http://127.0.0.1:8765).
  migrar                     Crea/actualiza las bases de datos (con respaldo previo).
  probar                     Ejecuta TODAS las pruebas sobre una copia temporal (no toca tus datos).
  respaldar                  Copia consistente de todas las bases (principal, conocimiento, simulación, demo y real).
  importar-secretos [--borrar-originales] [--ctrader RUTA]
                             Cifra en la bóveda los secretos de .iqoption.env, .telegram_token/.telegram_chat
                             y los JSON de cTrader; con --borrar-originales sobrescribe y elimina los archivos en claro.
  verificar-correo CORREO    Confirma y APRUEBA una cuenta desde la terminal del dispositivo (sin necesidad de correo).
  hacer-admin CORREO         Da privilegios de administrador a una cuenta (acceso desde el propio dispositivo).
  usuarios                   Lista las cuentas y su estado.
  estado                     Resumen de bases, motores, usuarios e integraciones.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from titan_quant import config, db  # noqa: E402


def migrar():
    config.asegurar_directorios()
    db.migrar()
    from titan_quant import servidor
    hechas = servidor.inicializar_bases_heredadas()
    print("Base principal:", config.DB_PRINCIPAL, "· versión de esquema", db.q1("SELECT MAX(version) v FROM esquema_version")["v"])
    print("Bases heredadas listas:", ", ".join(hechas))


def respaldar():
    config.asegurar_directorios()
    sello = time.strftime("%Y%m%d_%H%M%S")
    dest = config.RESPALDOS / sello
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    for ruta in (config.DB_PRINCIPAL, config.DATOS / "conocimiento.db", RAIZ / "titan_activos.db", RAIZ / "titan_planes.db", RAIZ / "titan_lab.db"):
        if ruta.exists():
            r = db.respaldar(dest / ruta.name, ruta)
            print("  ✔", r)
    for m in ("simulacion", "demo", "real"):            # cada cuenta en su propio archivo de respaldo
        ruta = config.DATOS / "cuentas" / f"{m}.db"
        if ruta.exists():
            print("  ✔", db.respaldar(dest / f"cuenta_{m}.db", ruta))
    print("Respaldo en", dest)
    print("Las credenciales van CIFRADAS dentro de titan_quant.db. La clave maestra (datos/.clave_maestra) NO se incluye:")
    print("guárdala aparte en un lugar seguro; sin ella no se pueden descifrar las credenciales del respaldo.")


def _sobrescribir_y_borrar(p):
    try:
        n = p.stat().st_size
        with open(p, "r+b") as f:
            f.write(os.urandom(max(n, 1)))
            f.flush()
            os.fsync(f.fileno())
        p.unlink()
        print("  borrado:", p.name)
    except OSError as e:
        print("  no se pudo borrar", p.name, type(e).__name__)


def importar_secretos(args):
    from titan_quant import integraciones
    dueno = db.q1("SELECT id, correo FROM usuarios WHERE rol='propietario' ORDER BY id LIMIT 1")
    if not dueno:
        print("Primero crea la cuenta propietaria desde la web (la primera cuenta registrada).")
        return 1
    uid = dueno["id"]
    borrar = "--borrar-originales" in args
    if "--ctrader" in args:
        ct_dir = Path(args[args.index("--ctrader") + 1]).expanduser()
    else:
        proot = Path("/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/root")
        candidatos = (RAIZ / "conectores" / "ctrader", RAIZ.parent / "TITAN_CTRADER_CONNECTOR", proot / "TITAN_CTRADER_CONNECTOR",
                      Path.home() / "TITAN_CTRADER_CONNECTOR")
        ct_dir = next((d for d in candidatos if (d / "ctrader_app.json").exists() or (d / "oauth_tokens.json").exists()), candidatos[0])
    hechos, originales = [], []
    env = RAIZ / ".iqoption.env"
    if env.exists():
        vals = {}
        for ln in env.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
        if vals.get("IQOPTION_EMAIL") and vals.get("IQOPTION_PASSWORD"):
            integraciones.guardar(uid, "iqoption", {"correo": vals["IQOPTION_EMAIL"], "clave": vals["IQOPTION_PASSWORD"]})
            hechos.append("IQ Option")
            originales.append(env)
    tt, tc = RAIZ / ".telegram_token", RAIZ / ".telegram_chat"
    if tt.exists() and tc.exists():
        integraciones.guardar(uid, "telegram", {"token": tt.read_text().strip(), "chat_id": tc.read_text().strip()})
        hechos.append("Telegram")
        originales.append(tt)   # el bot heredado lee ahora el token de la bóveda; .telegram_chat (no secreto) se conserva
    app, tok = ct_dir / "ctrader_app.json", ct_dir / "oauth_tokens.json"
    v = _leer_ctrader(ct_dir)
    if v:
        titan_cb = f"http://127.0.0.1:{config.PUERTO}/api/tq/integraciones/ctrader/callback"
        if v.get("redirect_uri") and v["redirect_uri"] != titan_cb:
            print(f"cTrader: tu app usaba la Redirect URI {v['redirect_uri']}. TITAN recibe la autorización en:\n  {titan_cb}\n"
                  "  Añádela en openapi.ctrader.com → tu aplicación → Redirect URIs (puedes dejar también la anterior).")
            v["redirect_uri"] = titan_cb
        integraciones.guardar(uid, "ctrader", v)
        _asignar_cuentas_ctrader(uid, ct_dir / "ctrader_accounts.json")
        hechos.append(f"cTrader ({', '.join(sorted(k for k in v if v[k]))}) desde {ct_dir}")
        originales += [p for p in (app, tok, ct_dir / "oauth_code.json") if p.exists()]
        if not v.get("access_token"):
            print("cTrader: no se encontró token. Autoriza desde la web: Integraciones → cTrader → Autorizar con cTrader.")
    print("Importado y cifrado para", dueno["correo"], ":", ", ".join(hechos) or "nada (no se encontraron archivos)")
    if borrar:
        for p in originales:
            if p.exists():
                _sobrescribir_y_borrar(p)
    elif originales:
        print("Los archivos en claro siguen ahí. Repite con --borrar-originales para eliminarlos de forma segura.")
    print("RECUERDA: esas credenciales viajaron en un backup sin cifrar. Cámbialas/revócalas en cada servicio y guarda las nuevas desde la web.")
    return 0


def _leer_ctrader(d):
    """Lee las credenciales del conector cTrader anterior (JSON y .env), aceptando nombres en snake_case o camelCase."""
    alias = {"client_id": ("client_id", "clientId", "CTRADER_CLIENT_ID", "CLIENT_ID"),
             "client_secret": ("client_secret", "clientSecret", "CTRADER_CLIENT_SECRET", "CLIENT_SECRET"),
             "redirect_uri": ("redirect_uri", "redirectUri", "CTRADER_REDIRECT_URI", "REDIRECT_URI"),
             "access_token": ("access_token", "accessToken", "CTRADER_ACCESS_TOKEN", "ACCESS_TOKEN"),
             "refresh_token": ("refresh_token", "refreshToken", "CTRADER_REFRESH_TOKEN", "REFRESH_TOKEN")}
    plano = {}
    for nombre in ("ctrader_app.json", "oauth_tokens.json", "config.json"):
        p = d / nombre
        if p.exists():
            try:
                x = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            pila = [x]
            while pila:                       # admite JSON anidado ({"tokens": {...}})
                o = pila.pop()
                if isinstance(o, dict):
                    for k, val in o.items():
                        (pila.append(val) if isinstance(val, (dict, list)) else plano.setdefault(k, val))
                elif isinstance(o, list):
                    pila.extend(o)
    for nombre in (".env", "ctrader.env"):
        p = d / nombre
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if "=" in ln and not ln.strip().startswith("#"):
                    k, val = ln.split("=", 1)
                    plano.setdefault(k.strip(), val.strip().strip('"').strip("'"))
    v = {campo: next((str(plano[a]) for a in nombres if plano.get(a)), None) for campo, nombres in alias.items()}
    return {k: x for k, x in v.items() if x} or None


def _asignar_cuentas_ctrader(uid, ruta):
    """Si el conector anterior guardó la lista de cuentas, preasigna la DEMO al bot demo y la LIVE al bot real (sin iniciarlos)."""
    if not ruta.exists():
        return
    try:
        from titan_quant.trader import autotrader
        cuentas = json.loads(ruta.read_text(encoding="utf-8"))
        for c in cuentas if isinstance(cuentas, list) else []:
            ctid = str(c.get("account_id") or c.get("ctidTraderAccountId") or "")
            vivo = c.get("is_live", c.get("isLive"))
            if ctid.isdigit() and vivo is not None:
                m = "real" if vivo else "demo"
                if not autotrader.estado(uid, m)["ajustes"].get("cuenta_ctid"):
                    autotrader.guardar_ajustes(uid, m, {"broker": "ctrader", "cuenta_ctid": int(ctid)})
                    print(f"cTrader: cuenta {'REAL (live)' if vivo else 'DEMO'} {ctid} asignada al bot {m.upper()} (detenido).")
    except Exception as e:
        print("cTrader: no se pudieron asignar las cuentas automáticamente:", type(e).__name__)


def verificar_correo(correo):
    correo = (correo or "").strip().lower()
    with db.tx() as c:
        n = c.execute("UPDATE usuarios SET verificado=1, aprobado=1, suspendido=0, fallos=0, bloqueado_hasta=0 WHERE correo=?", (correo,)).rowcount
    if n:
        from titan_quant.seguridad import cuentas
        u = db.q1("SELECT id FROM usuarios WHERE correo=?", (correo,))
        cuentas.evento(u["id"], "cuenta_activada_terminal", "local")
        db.auditar(None, "cuenta_activada_terminal", "usuario", u["id"])
    print("Cuenta confirmada y aprobada. Ya puede iniciar sesión." if n else "No existe esa cuenta.")


def hacer_admin(correo):
    correo = (correo or "").strip().lower()
    with db.tx() as c:
        n = c.execute("UPDATE usuarios SET admin=1, verificado=1, aprobado=1, suspendido=0 WHERE correo=?", (correo,)).rowcount
    if n:
        db.auditar(None, "admin_concedido_terminal", "usuario", correo)
    print("Ahora es administrador." if n else "No existe esa cuenta.")


def usuarios():
    from titan_quant.seguridad import administracion
    for u in administracion.listar():
        print(f"{u['id']:>3}  {u['correo']:35} {u['rol']:11} {'admin' if u['admin'] else '':6} {u['estado']}")


def estado():
    from titan_quant.motores import nucleo, sistema  # noqa: F401
    s = sistema.estado_sistema(rapido=False)
    print("Bases:")
    for k, v in s["bases"].items():
        print(f"  {k:18} {'%.2f MB' % v['mb'] if v.get('existe') else 'no existe':>10}  {v.get('integridad', '')}")
    print("Usuarios:", db.q1("SELECT COUNT(*) n FROM usuarios")["n"], "· integraciones:", db.q1("SELECT COUNT(*) n FROM integraciones")["n"])
    print("Motores:")
    for m in s["motores"]:
        print(f"  {m['numero']:>2} {m['nombre']:36} {m['estado']:12} ejec {m['ejecuciones']}")
    print("Última batería de pruebas:", db.cfg_sistema("ultima_bateria_pruebas"))


def probar():
    """Copia el proyecto a una carpeta temporal y ejecuta: pruebas nuevas, autoprueba heredada (probar.py) y la del laboratorio."""
    tmp = Path(tempfile.mkdtemp(prefix="titan_pruebas_"))
    copia = tmp / "TITAN"
    shutil.copytree(RAIZ, copia, ignore=shutil.ignore_patterns("__pycache__", "datos", "*.db", "*.db-wal", "*.db-shm", ".telegram*",
                                                                "*.env", ".estado_bot.json", "respaldo*", "archivo_historico", ".git", ".venv"))
    entorno = dict(os.environ, TITAN_DATOS=str(tmp / "datos"), PYTHONDONTWRITEBYTECODE="1")
    entorno.pop("TITAN_CLAVE_MAESTRA", None)
    pasos = [
        ("Sintaxis de todos los módulos", [sys.executable, "-m", "compileall", "-q", "."]),
        ("Pruebas TITAN QUANT (seguridad, 23 motores, bot operador, servidor)", [sys.executable, "-m", "unittest", "discover", "-s", "titan_quant/pruebas", "-t", ".", "-p", "test_*.py"]),
        ("Autoprueba heredada (bot de Telegram, pipeline, escenarios)", [sys.executable, "probar.py"]),
        ("Autoprueba del Laboratorio de Aprendizaje", [sys.executable, "lab_engine.py", "--autoprueba"]),
    ]
    resultados = []
    for nombre, cmd in pasos:
        print(f"\n=== {nombre}", flush=True)
        t0 = time.time()
        r = subprocess.run(cmd, cwd=copia, env=entorno, capture_output=True, text=True, timeout=3600)
        salida = (r.stdout + r.stderr).strip().splitlines()
        lineas = [ln for ln in salida if any(k in ln for k in ("RESULTADO", "Ran ", "OK", "FAIL", "Error", "FALLA", "FALLO"))]
        for ln in (lineas[-6:] if r.returncode == 0 else salida[-25:]):
            print("  " + ln)
        resultados.append({"paso": nombre, "ok": r.returncode == 0, "segundos": round(time.time() - t0, 1)})
        print(f"  → {'CORRECTO' if r.returncode == 0 else 'CON FALLOS'} ({resultados[-1]['segundos']} s)")
    ok = all(x["ok"] for x in resultados)
    resumen = f"{sum(x['ok'] for x in resultados)}/{len(resultados)} baterías correctas"
    try:
        db.set_cfg_sistema("ultima_bateria_pruebas", {"ok": ok, "ts": int(time.time()), "resumen": resumen, "detalle": resultados})
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nRESULTADO GLOBAL: {'CORRECTO' if ok else 'CON FALLOS'} · {resumen}")
    return 0 if ok else 1


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help", "ayuda"):
        print(__doc__)
        return 0
    cmd, resto = a[0], a[1:]
    if cmd == "servidor":
        from titan_quant import servidor
        servidor.main()
    elif cmd == "migrar":
        migrar()
    elif cmd == "probar":
        return probar()
    elif cmd == "respaldar":
        respaldar()
    elif cmd == "importar-secretos":
        return importar_secretos(resto)
    elif cmd == "verificar-correo" and resto:
        verificar_correo(resto[0])
    elif cmd == "hacer-admin" and resto:
        hacer_admin(resto[0])
    elif cmd == "usuarios":
        usuarios()
    elif cmd == "estado":
        estado()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
