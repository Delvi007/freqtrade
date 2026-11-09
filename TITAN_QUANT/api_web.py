
import json
from contextlib import closing
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from http.server import SimpleHTTPRequestHandler

import activos
import agente

ROOT = Path(__file__).resolve().parent
# v7: la interfaz vive DENTRO del proyecto (web/). Antes apuntaba a una ruta fija de Termux fuera del backup.
HTML_DIR = ROOT / "web"
DB = ROOT / "titan_activos.db"
STATE_FILE = ROOT / ".estado_bot.json"

HOST = "127.0.0.1"   # v7: solo este dispositivo por defecto (antes 0.0.0.0 sin autenticación)
PORT = 8765
MAX_BODY = 4096


def leer_estado():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def json_seguro(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): json_seguro(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_seguro(v) for v in obj]
    return str(obj)


def conectar_solo_lectura():
    uri = DB.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def obtener_activos():
    estado = leer_estado()
    personalizados = estado.get("personalizados", [])
    seleccion = estado.get("seleccion", [])

    resultado = []
    for a in activos.CATALOGO:
        resultado.append({
            "categoria": a["categoria"],
            "nombre": a["nombre"],
            "simbolo": a["simbolo"],
            "clase": a["clase"],
            "seleccionado": a["simbolo"] in seleccion
        })

    for simbolo in personalizados:
        try:
            a = activos.personalizado(simbolo)
            resultado.append({
                "categoria": a["categoria"],
                "nombre": a["nombre"],
                "simbolo": a["simbolo"],
                "clase": a["clase"],
                "seleccionado": a["simbolo"] in seleccion
            })
        except Exception:
            continue

    return resultado


def obtener_historial():
    with closing(conectar_solo_lectura()) as c:   # v7: el 'with' de sqlite3 no cierra la conexión
        c.row_factory = sqlite3.Row
        filas = c.execute("""
            SELECT id, simbolo, creado_en, precio, total,
                   direccion, confianza, horizonte_h, resultado
            FROM analisis
            ORDER BY id DESC
            LIMIT 30
        """).fetchall()

    return [dict(f) for f in filas]


def obtener_estadisticas():
    with closing(conectar_solo_lectura()) as c:   # v7: el 'with' de sqlite3 no cierra la conexión
        fila = c.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN resultado='acierto' THEN 1 ELSE 0 END)
                    AS aciertos,
                SUM(CASE WHEN resultado='fallo' THEN 1 ELSE 0 END)
                    AS fallos,
                SUM(CASE WHEN resultado IS NULL OR resultado=''
                    THEN 1 ELSE 0 END) AS pendientes
            FROM analisis
        """).fetchone()

    total, aciertos, fallos, pendientes = fila
    aciertos = aciertos or 0
    fallos = fallos or 0
    evaluados = aciertos + fallos

    tasa = round(aciertos * 100 / evaluados, 2) if evaluados else None

    return {
        "registros": total or 0,
        "aciertos": aciertos,
        "fallos": fallos,
        "pendientes": pendientes or 0,
        "tasa_acierto_pct": tasa,
        "advertencia": (
            "Estadística descriptiva de resultados registrados; "
            "no demuestra rentabilidad ni capacidad predictiva."
        )
    }



def obtener_alertas():
    try:
        with closing(conectar_solo_lectura()) as c:   # v7: el 'with' de sqlite3 no cierra la conexión
            c.row_factory = sqlite3.Row
            filas = c.execute("""SELECT creado_en, simbolo, tipo, direccion, estado, nivel
                                 FROM escenarios ORDER BY creado_en DESC LIMIT 30""").fetchall()
        return [dict(f) for f in filas]
    except sqlite3.Error:
        return []


def obtener_cotizaciones(parametro):
    import quotes_web
    pedidos = [s.strip().upper() for s in str(parametro or "").split(",") if s.strip()][:8]
    if not pedidos:
        raise ValueError("Indica al menos un símbolo.")
    personalizados = leer_estado().get("personalizados", [])
    lista = []
    for s in pedidos:
        a = activos.buscar(s, personalizados)
        if a is None:
            raise ValueError("Símbolo no permitido: " + s[:30])
        lista.append(a)
    return quotes_web.cotizar_varios(lista)


# CHART_V1
# CHART_V2
def resolver_activo_libre(simbolo):
    import re
    s = str(simbolo or "").strip().upper()
    a = activos.buscar(s, leer_estado().get("personalizados", []))
    if a is None:
        if not re.fullmatch(r"[A-Z0-9.^=\-]{1,15}", s):
            raise ValueError("Símbolo no válido: " + s[:30])
        a = activos.personalizado(s)
    return a

def obtener_grafico(simbolo, tf, reciente=False):
    import chart_web
    return chart_web.grafico(resolver_activo_libre(simbolo), str(tf or "15m"), bool(reciente))

def obtener_mtf(simbolo):
    import chart_web
    return chart_web.mapa_temporalidades(resolver_activo_libre(simbolo))


def analizar_simbolo(simbolo):
    simbolo = str(simbolo or "").strip().upper()

    if not simbolo or len(simbolo) > 30:
        raise ValueError("Símbolo vacío o demasiado largo.")

    estado = leer_estado()
    personalizados = estado.get("personalizados", [])

    activo = activos.buscar(simbolo, personalizados)

    if activo is None:
        raise ValueError("El símbolo no está en el catálogo ni en personalizados.")

    zona = ZoneInfo(estado.get("zona") or "America/Santo_Domingo")

    # Importante: guardar=False evita insertar el análisis
    # y evita que esta consulta modifique la base de datos.
    resultado = agente.analizar(
        activo,
        zona,
        guardar=False
    )

    if not isinstance(resultado, dict):
        raise RuntimeError("El motor devolvió un resultado inesperado.")

    campos = (
        "activo", "error", "notas", "precio", "rsi",
        "ema20", "ema50", "macd", "punt_t", "punt_n",
        "total", "direccion", "confianza", "atr",
        "noticias", "soporte", "resistencia", "ventana",
        "pocas", "est", "diaria"
    )

    salida = {
        k: resultado.get(k)
        for k in campos
        if k in resultado
    }

    # Limitar el tamaño de la respuesta.
    if isinstance(salida.get("noticias"), list):
        salida["noticias"] = salida["noticias"][:8]

    salida["simbolo_solicitado"] = simbolo
    salida["temporalidad_motor"] = "60m"
    salida["guardado_en_bd"] = False

    return json_seguro(salida)


class Handler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HTML_DIR), **kwargs)

    def enviar_json(self, codigo, datos):
        cuerpo = json.dumps(
            json_seguro(datos),
            ensure_ascii=False,
            allow_nan=False
        ).encode("utf-8")

        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = urlparse(self.path).path

        try:
            if ruta.startswith("/api/lab/"):  # LAB_V1
                import lab_engine
                if lab_engine.manejar_get(self, ruta):
                    return

            if ruta == "/api/health":
                self.enviar_json(200, {
                    "ok": True,
                    "servicio": "TITAN_QUANT_API",
                    "host": HOST,
                    "port": PORT,
                    "base_datos": DB.exists(),
                    "html": (HTML_DIR / "index.html").is_file()
                })
                return

            if ruta == "/api/assets":
                self.enviar_json(200, {
                    "ok": True,
                    "activos": obtener_activos()
                })
                return

            if ruta == "/api/history":
                self.enviar_json(200, {
                    "ok": True,
                    "historial": obtener_historial()
                })
                return

            if ruta == "/api/stats":
                self.enviar_json(200, {
                    "ok": True,
                    "estadisticas": obtener_estadisticas()
                })
                return

            if ruta == "/api/alerts":
                self.enviar_json(200, {"ok": True, "alertas": obtener_alertas()})
                return

            if ruta == "/api/quotes":
                from urllib.parse import parse_qs
                q = parse_qs(urlparse(self.path).query)
                try:
                    cot = obtener_cotizaciones((q.get("symbols") or [""])[0])
                except ValueError as e:
                    self.enviar_json(400, {"ok": False, "error": str(e)})
                    return
                self.enviar_json(200, {"ok": True, "cotizaciones": cot})
                return

            if ruta == "/api/chart":
                from urllib.parse import parse_qs
                q = parse_qs(urlparse(self.path).query)
                try:
                    g = obtener_grafico((q.get("symbol") or [""])[0], (q.get("tf") or ["15m"])[0],
                                        (q.get("recent") or ["0"])[0] == "1")
                except ValueError as e:
                    self.enviar_json(400, {"ok": False, "error": str(e)})
                    return
                except RuntimeError as e:
                    self.enviar_json(503, {"ok": False, "error": "Datos de mercado no disponibles: " + str(e)})
                    return
                g["ok"] = True
                self.enviar_json(200, g)
                return

            if ruta == "/api/mtf":
                from urllib.parse import parse_qs
                q = parse_qs(urlparse(self.path).query)
                try:
                    g = obtener_mtf((q.get("symbol") or [""])[0])
                except ValueError as e:
                    self.enviar_json(400, {"ok": False, "error": str(e)})
                    return
                except RuntimeError as e:
                    self.enviar_json(503, {"ok": False, "error": "Datos de mercado no disponibles: " + str(e)})
                    return
                g["ok"] = True
                self.enviar_json(200, g)
                return

            if ruta == "/api/plans":
                from urllib.parse import parse_qs
                import plan_web
                q = parse_qs(urlparse(self.path).query)
                try:
                    res = plan_web.listar((q.get("symbol") or [""])[0], int((q.get("limit") or ["20"])[0]),
                                          leer_estado().get("zona") or "America/Santo_Domingo")
                except ValueError as e:
                    self.enviar_json(400, {"ok": False, "error": str(e)})
                    return
                res["ok"] = True
                self.enviar_json(200, res)
                return

            if ruta.startswith("/api/"):
                self.enviar_json(404, {"ok": False, "error": "Endpoint desconocido."})
                return

            super().do_GET()

        except Exception as e:
            self.enviar_json(500, {
                "ok": False,
                "error": str(e)
            })

    def do_POST(self):
        ruta = urlparse(self.path).path

        if ruta.startswith("/api/lab/"):  # LAB_V1
            import lab_engine
            lab_engine.manejar_post(self, ruta)
            return

        if ruta not in ("/api/analyze", "/api/report", "/api/plan", "/api/plan/cancel", "/api/plan/limpiar"):
            self.enviar_json(404, {"ok": False, "error": "Endpoint desconocido."})
            return

        try:
            longitud = int(self.headers.get("Content-Length", "0"))

            if longitud <= 0 or longitud > MAX_BODY:
                self.enviar_json(413, {
                    "ok": False,
                    "error": "Tamaño de solicitud no permitido."
                })
                return

            datos = json.loads(self.rfile.read(longitud).decode("utf-8"))

            if ruta == "/api/report":
                import informe_web
                estado = leer_estado()
                res = informe_web.generar(
                    datos.get("simbolo"),
                    datos.get("hora"),
                    estado.get("zona", "America/Santo_Domingo"),
                    estado.get("personalizados", [])
                )
                res["ok"] = True
                self.enviar_json(200, res)
                return

            if ruta == "/api/plan":
                import plan_web
                estado = leer_estado()
                res = plan_web.crear(
                    datos.get("simbolo"),
                    datos.get("modo"),
                    estado.get("zona") or "America/Santo_Domingo",
                    estado.get("personalizados", [])
                )
                res["ok"] = True
                self.enviar_json(200, res)
                return

            if ruta == "/api/plan/limpiar":
                import plan_web
                pid = datos.get("id")
                res = plan_web.eliminar_cancelados(int(pid) if pid is not None else None)
                res["ok"] = True
                self.enviar_json(200, res)
                return

            if ruta == "/api/plan/cancel":
                import plan_web
                res = plan_web.cancelar(datos.get("id"))
                res["ok"] = True
                self.enviar_json(200, res)
                return

            simbolo = datos.get("simbolo")
            resultado = analizar_simbolo(simbolo)

            self.enviar_json(200, {
                "ok": True,
                "resultado": resultado
            })

        except ValueError as e:
            self.enviar_json(400, {
                "ok": False,
                "error": str(e)
            })

        except Exception as e:
            self.enviar_json(500, {
                "ok": False,
                "error": str(e)
            })


if __name__ == "__main__":
    # v7: este servidor ya no se ejecuta solo (no tenía autenticación). Arranca el servidor seguro de TITAN QUANT,
    # que reutiliza todas las rutas de este módulo exigiendo sesión.
    from titan_quant import servidor
    servidor.main()
