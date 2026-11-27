"""Локальное рабочее пространство «Первый ответ»."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

from business import calculate, sensitivity
from model import load_predictor, read_json
from storage import Conflict, Missing, STATUSES, Store
from ticket_io import DEMO, REQUEST_KEY, csv_messages, export_csv, message
from triage import ROUTE_LABELS

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
REPORT = ROOT / "docs" / "experiments" / "v2.json"
MAX_REQUEST_BYTES = 700_000
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
QUEUES = (*ROUTE_LABELS, "manual")
SCOPES = ("work", "demo", "all")
FEEDBACK = ("helpful", "unclear", "wrong")
TICKET = re.compile(r"/api/tickets/([1-9][0-9]{0,17})(?:/(decision|feedback))?\Z")
LOG = logging.getLogger("first_reply")


class HTTPError(ValueError):
    def __init__(self, status, description):
        super().__init__(description)
        self.status = status


class TriageServer(ThreadingHTTPServer):
    def __init__(self, address, predictor, store, report):
        self.predictor = predictor
        self.store = store
        self.report = report
        super().__init__(address, TriageHandler)


class TriageHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_request(self, code="-", size="-"):
        # Журнал содержит только тип операции и HTTP-статус.
        path = getattr(self, "path", "").split("?", 1)[0]
        match = TICKET.fullmatch(path)
        if match:
            path = "/api/tickets/:id" + (f"/{match[2]}" if match[2] else "")
        elif path not in STATIC_ROUTES and path not in {
            "/api/tickets", "/api/template", "/api/export", "/api/analytics", "/api/quality",
            "/api/health", "/api/predict", "/api/import", "/api/demo", "/api/economics",
        }:
            path = "unknown"
        command = getattr(self, "command", None)
        LOG.info("%s %s %s", command if command in {"GET", "POST"} else "other", path, code)

    def log_error(self, _format, *_args):
        LOG.info("Ошибка HTTP-запроса")

    def _send(self, status, content_type, body, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def _body(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if origin and origin != f"http://{host}":
            raise HTTPError(403, "Разрешены запросы из локального приложения.")
        if self.headers.get_content_type() != "application/json":
            raise HTTPError(415, "Ожидается запрос в формате JSON.")
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise HTTPError(400, "Укажите длину запроса.") from error
        if not 0 < size <= MAX_REQUEST_BYTES:
            raise HTTPError(413, "Запрос пуст или слишком велик.")
        try:
            value = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            raise HTTPError(400, "Не удалось прочитать JSON.") from error
        if not isinstance(value, dict):
            raise HTTPError(400, "Ожидается JSON-объект.")
        return value

    @staticmethod
    def _filters(query):
        filters = {key: values[-1] for key, values in query.items()}
        for key, allowed in (("status", STATUSES), ("queue", QUEUES), ("scope", SCOPES)):
            if filters.get(key) and filters[key] not in allowed:
                raise ValueError(f"Недопустимое значение фильтра {key}.")
        if len(filters.get("q", "")) > 200:
            raise ValueError("Поисковый запрос должен быть не длиннее 200 символов.")
        if filters.get("history") not in (None, "1", "0"):
            raise ValueError("Некорректный фильтр истории.")
        filters["history"] = filters.get("history") == "1"
        return filters

    def do_GET(self):
        self._handle(self._get)

    def do_POST(self):
        self._handle(self._post)

    def _handle(self, action):
        try:
            local_hosts = {f"{name}:{self.server.server_port}" for name in ("127.0.0.1", "localhost")}
            if self.headers.get("Host") not in local_hosts:
                raise HTTPError(403, "Разрешены запросы из локального приложения.")
            parsed = urlsplit(self.path)
            action(parsed.path, parse_qs(parsed.query, max_num_fields=15))
        except (BrokenPipeError, ConnectionResetError):
            LOG.info("Клиент закрыл соединение")
        except HTTPError as error:
            self._json(error.status, {"error": str(error)})
        except Missing as error:
            self._json(404, {"error": str(error)})
        except Conflict as error:
            self._json(409, {"error": str(error)})
        except (ValueError, UnicodeError) as error:
            self._json(400, {"error": str(error)})
        except TimeoutError:
            self._json(408, {"error": "Время ожидания запроса истекло."})
        except sqlite3.OperationalError as error:
            LOG.error("Ошибка SQLite: %s", error.sqlite_errorname)
            self._json(503, {"error": "Хранилище временно недоступно. Повторите запрос."})
        except Exception as error:
            LOG.error("Ошибка запроса: %s", type(error).__name__)
            self._json(500, {"error": "Не удалось выполнить запрос."})

    def _get(self, path, query):
        store = self.server.store
        if path in STATIC_ROUTES:
            name, content_type = STATIC_ROUTES[path]
            self._send(200, content_type, (STATIC / name).read_bytes())
        elif path == "/api/tickets":
            filters = self._filters(query)
            try:
                offset, limit = int(filters.get("offset", 0)), int(filters.get("limit", 20))
            except ValueError as error:
                raise ValueError("Некорректные параметры страницы.") from error
            if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 100:
                raise ValueError("Некорректные параметры страницы.")
            self._json(200, store.listing(filters, limit, offset))
        elif path == "/api/template":
            self._send(200, "text/csv; charset=utf-8", b"text\r\n",
                       {"Content-Disposition": 'attachment; filename="template.csv"'})
        elif path == "/api/export":
            items = store.listing(self._filters(query))["items"]
            self._send(200, "text/csv; charset=utf-8", export_csv(items),
                       {"Content-Disposition": 'attachment; filename="tickets.csv"'})
        elif path == "/api/analytics":
            self._json(200, store.analytics(self._filters(query).get("scope") or "work"))
        elif path == "/api/quality":
            self._json(200, self.server.report)
        elif path == "/api/health":
            self._json(200, {"model_version": self.server.predictor.release["version"]})
        elif (match := TICKET.fullmatch(path)) and match[2] is None:
            self._json(200, store.detail(int(match[1])))
        else:
            raise Missing("Страница не найдена.")

    def _create(self, texts, source, key):
        entries = [(text, self.server.predictor.predict(text)) for text in texts]
        return self.server.store.create(entries, source, key)

    @staticmethod
    def _key(body):
        key = body.get("request_key")
        if key is not None and (not isinstance(key, str) or not REQUEST_KEY.fullmatch(key)):
            raise ValueError("Некорректный ключ запроса.")
        return key

    def _post(self, path, _query):
        store = self.server.store
        body = self._body()
        if path == "/api/predict":
            self._json(200, self.server.predictor.predict(message(body.get("text"))))
        elif path == "/api/tickets":
            ids, created = self._create([message(body.get("text"))], "manual", self._key(body))
            self._json(201 if created else 200, store.detail(ids[0]))
        elif path == "/api/import":
            ids, created = self._create(csv_messages(body.get("csv")), "csv", self._key(body))
            self._json(201 if created else 200, {"ids": ids, "count": len(ids)})
        elif path == "/api/demo":
            ids, created = self._create(DEMO, "demo", "de000002")
            self._json(201 if created else 200, {"ids": ids, "count": len(ids), "created": created})
        elif path == "/api/economics":
            inputs = body.get("inputs")
            self._json(200, {"results": calculate(inputs), "sensitivity": sensitivity(inputs)})
        elif match := TICKET.fullmatch(path):
            ticket_id, action = int(match[1]), match[2]
            if action == "decision":
                route, revision = body.get("route"), body.get("revision")
                if route not in (*QUEUES, "confirm") or type(revision) is not int or revision < 1:
                    raise ValueError("Выберите очередь и проверьте версию обращения.")
                store.decide(ticket_id, route, revision)
            elif action == "feedback":
                kind, note = body.get("kind"), body.get("note", "")
                if kind not in FEEDBACK or not isinstance(note, str) or len(note) > 500 or "\x00" in note:
                    raise ValueError("Укажите вид обратной связи и комментарий до 500 символов.")
                store.add_feedback(ticket_id, kind, note.strip())
            else:
                raise Missing("Страница не найдена.")
            self._json(200, store.detail(ticket_id))
        else:
            raise Missing("Страница не найдена.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=ROOT / "var" / "tickets.sqlite3")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    predictor = load_predictor()
    report = read_json(REPORT)
    if report["release"] != predictor.release:
        parser.error("Артефакт эксперимента относится к другой версии модели.")
    with TriageServer(("127.0.0.1", args.port), predictor, Store(args.db), report) as server:
        print(f"Первый ответ · http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
