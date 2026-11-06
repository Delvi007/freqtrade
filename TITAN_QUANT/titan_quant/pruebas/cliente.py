"""Cliente HTTP mínimo con cookies y CSRF para pruebas de extremo a extremo."""
import http.cookiejar
import json
import urllib.error
import urllib.request


class Cliente:
    def __init__(self, base, origen=True):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), _SinRedireccion())
        self.csrf = None
        self.origen = origen

    def pedir(self, metodo, ruta, datos=None, cabeceras=None):
        h = {"Content-Type": "application/json"}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if self.origen and metodo == "POST":
            h["Origin"] = self.base
        h.update(cabeceras or {})
        req = urllib.request.Request(self.base + ruta, data=json.dumps(datos).encode() if datos is not None else (b"{}" if metodo == "POST" else None),
                                     method=metodo, headers=h)
        try:
            with self.op.open(req, timeout=300) as r:
                cuerpo, codigo, hdr = r.read(), r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            cuerpo, codigo, hdr = e.read(), e.code, dict(e.headers)
        try:
            d = json.loads(cuerpo)
        except ValueError:
            d = {"_texto": cuerpo[:200].decode("utf-8", "replace")}
        return codigo, d, hdr

    def get(self, ruta):
        return self.pedir("GET", ruta)

    def post(self, ruta, datos=None):
        return self.pedir("POST", ruta, datos or {})


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
