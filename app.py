"""Local web demo for routing Russian-language support requests."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from triage import load_model, predict


STATIC = Path(__file__).resolve().parent / "static"
MAX_TEXT_LENGTH = 1000
MAX_REQUEST_BYTES = 16000
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class TriageServer(ThreadingHTTPServer):
    def __init__(self, address, model):
        super().__init__(address, TriageHandler)
        self.model = model


class TriageHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def do_GET(self):
        asset = STATIC_ROUTES.get(urlsplit(self.path).path)
        if asset is None:
            self._json(404, {"error": "Страница не найдена."})
            return
        name, content_type = asset
        self._send(200, content_type, (STATIC / name).read_bytes())

    def do_POST(self):
        if urlsplit(self.path).path != "/api/predict":
            self._json(404, {"error": "Страница не найдена."})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "Ожидается запрос в формате JSON."})
            return

        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(400, {"error": "Укажите длину запроса."})
            return
        if not 0 < size <= MAX_REQUEST_BYTES:
            self._json(413, {"error": "Запрос пуст или слишком велик."})
            return

        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "Не удалось прочитать запрос."})
            return

        message = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(message, str) or not message.strip():
            self._json(400, {"error": "Введите текст обращения."})
            return
        if len(message) > MAX_TEXT_LENGTH:
            self._json(400, {"error": f"Допустимо до {MAX_TEXT_LENGTH} символов."})
            return

        self._json(200, predict(self.server.model, message.strip()))


def main():
    parser = argparse.ArgumentParser(description="Запуск локального демо «Первый ответ»")
    parser.add_argument("--port", type=int, default=8000, help="Локальный порт (по умолчанию 8000)")
    args = parser.parse_args()

    model = load_model()
    with TriageServer(("127.0.0.1", args.port), model) as server:
        print(f"Первый ответ · http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
