from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json
import os

BASE = Path(__file__).resolve().parent
TOKEN_FILE = BASE / "oauth_code.json"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]

        if error:
            self.respond(400, "cTrader rechazó la autorización.")
            print("ERROR OAUTH:", error)
            return

        if not code:
            self.respond(400, "No se recibió el código OAuth.")
            return

        TOKEN_FILE.write_text(json.dumps({
            "code": code,
            "received": True
        }))
        os.chmod(TOKEN_FILE, 0o600)

        self.respond(200, "Autorización recibida. Puedes cerrar esta ventana.")
        print("AUTORIZACIÓN RECIBIDA CORRECTAMENTE.")
        print("Código guardado localmente. No se mostrará.")

    def respond(self, status, message):
        body = f"<html><body><h2>{message}</h2></body></html>".encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

server = HTTPServer(("127.0.0.1", 443), Handler)
print("Receptor OAuth activo en https://localhost/callback")
print("Esperando autorización de cTrader...")
server.serve_forever()
