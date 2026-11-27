"""SQLite-хранилище обращений, решений и событий."""

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from statistics import mean, median

from triage import ROUTE_LABELS

STATUSES = ("new", "review", "resolved")
SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('manual', 'csv', 'demo')),
    import_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('new', 'review', 'resolved')),
    recommendation TEXT NOT NULL,
    prediction TEXT NOT NULL,
    model_version TEXT NOT NULL,
    score REAL NOT NULL,
    operator_route TEXT,
    changed INTEGER,
    first_resolved_at TEXT,
    elapsed_seconds REAL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    occurred_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    route TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    occurred_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    note TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_ticket ON events(ticket_id, id);
CREATE INDEX IF NOT EXISTS feedback_by_ticket ON feedback(ticket_id, id);
CREATE INDEX IF NOT EXISTS tickets_by_status ON tickets(status, id);
"""


class Conflict(ValueError):
    pass


class Missing(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def elapsed(start, end):
    return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.create_function("casefold", 1, str.casefold, deterministic=True)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _event(db, ticket_id, at, kind, before, after, route):
        db.execute("INSERT INTO events(ticket_id, occurred_at, kind, from_status, to_status, route) "
                   "VALUES (?, ?, ?, ?, ?, ?)", (ticket_id, at, kind, before, after, route))

    @staticmethod
    def _ticket(db, ticket_id):
        ticket = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if ticket is None:
            raise Missing("Обращение не найдено.")
        return ticket

    @staticmethod
    def _public(row):
        result = dict(row)
        result["prediction"] = json.loads(result["prediction"])
        result["changed"] = None if result["changed"] is None else bool(result["changed"])
        del result["import_key"]
        return result

    def create(self, entries, source, request_key=None):
        timestamp = now()
        ids = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_key is not None:
                prefix = f"{source}:{request_key}:"
                existing = db.execute("SELECT id, text FROM tickets WHERE import_key GLOB ? ORDER BY id",
                                      (f"{prefix}*",)).fetchall()
                if existing:
                    if [row["text"] for row in existing] != [text for text, _ in entries]:
                        raise Conflict("Этот ключ запроса уже применён к другим обращениям.")
                    return [row["id"] for row in existing], False
            for index, (text, prediction) in enumerate(entries):
                key = f"{source}:{request_key}:{index}" if request_key is not None else None
                cursor = db.execute(
                    "INSERT INTO tickets(text, source, import_key, created_at, updated_at, status, "
                    "recommendation, prediction, model_version, score) VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)",
                    (text, source, key, timestamp, timestamp, prediction["route"],
                     json.dumps(prediction, ensure_ascii=False), prediction["model_version"], prediction["confidence"]),
                )
                ticket_id = cursor.lastrowid
                self._event(db, ticket_id, timestamp, "created", None, "new", None)
                self._event(db, ticket_id, timestamp, "analyzed", "new", "new", prediction["route"])
                ids.append(ticket_id)
        return ids, True

    def detail(self, ticket_id):
        with self.connect() as db:
            db.execute("BEGIN")
            ticket = self._public(self._ticket(db, ticket_id))
            ticket["events"] = [dict(row) for row in db.execute(
                "SELECT * FROM events WHERE ticket_id=? ORDER BY id DESC", (ticket_id,)
            )]
            ticket["feedback"] = [dict(row) for row in db.execute(
                "SELECT * FROM feedback WHERE ticket_id=? ORDER BY id DESC", (ticket_id,)
            )]
        return ticket

    def decide(self, ticket_id, route, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ticket = self._ticket(db, ticket_id)
            if revision != ticket["revision"]:
                raise Conflict("Обращение уже обновилось. Откройте актуальную карточку и проверьте решение.")
            if route == "confirm":
                route = ticket["recommendation"]
                if route == "manual":
                    raise ValueError("У этого обращения нет очереди для подтверждения.")
            status = "review" if route == "manual" else "resolved"
            if ticket["status"] == status and ticket["operator_route"] == route:
                return
            stamp = now()
            resolved_at, duration = ticket["first_resolved_at"], ticket["elapsed_seconds"]
            if status == "resolved" and resolved_at is None:
                resolved_at, duration = stamp, elapsed(ticket["created_at"], stamp)
            changed = route != ticket["recommendation"] if ticket["recommendation"] != "manual" else None
            db.execute("UPDATE tickets SET status=?, operator_route=?, changed=?, updated_at=?, "
                       "first_resolved_at=?, elapsed_seconds=?, revision=revision+1 WHERE id=?",
                       (status, route, changed, stamp, resolved_at, duration, ticket_id))
            kind = "reviewed" if route == "manual" else "confirmed" if route == ticket["recommendation"] else "rerouted"
            self._event(db, ticket_id, stamp, kind, ticket["status"], status, route)

    def add_feedback(self, ticket_id, kind, note):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ticket = self._ticket(db, ticket_id)
            stamp = now()
            db.execute("INSERT INTO feedback(ticket_id, occurred_at, kind, note) VALUES (?, ?, ?, ?)",
                       (ticket_id, stamp, kind, note))
            self._event(db, ticket_id, stamp, "feedback", ticket["status"], ticket["status"], None)

    @staticmethod
    def _filters(filters):
        conditions, values = [], []
        if filters.get("scope") == "work":
            conditions.append("source != 'demo'")
        elif filters.get("scope") == "demo":
            conditions.append("source = 'demo'")
        if query := filters.get("q"):
            conditions.append("(instr(casefold(text), ?) > 0 OR CAST(id AS TEXT) = ?)")
            values.extend([query.casefold(), query.removeprefix("#")])
        if status := filters.get("status"):
            conditions.append("status=?")
            values.append(status)
        if route := filters.get("queue"):
            conditions.append("COALESCE(operator_route, recommendation)=?")
            values.append(route)
        if filters.get("history"):
            conditions.append("status != 'new'")
        clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        return clause, values

    def listing(self, filters, limit=None, offset=0):
        clause, params = self._filters(filters)
        base = f" FROM tickets{clause}"
        paging = " LIMIT ? OFFSET ?" if limit is not None else ""
        with self.connect() as db:
            db.execute("BEGIN")
            rows = db.execute(f"SELECT *{base} ORDER BY id DESC{paging}",
                              [*params, limit, offset] if paging else params).fetchall()
            total = db.execute(f"SELECT COUNT(*){base}", params).fetchone()[0]
        return {"items": [self._public(row) for row in rows], "total": total}

    def analytics(self, scope):
        clause, params = self._filters({"scope": scope})
        with self.connect() as db:
            rows = db.execute("SELECT source, created_at, status, recommendation, operator_route, "
                              f"first_resolved_at, elapsed_seconds FROM tickets{clause}", params).fetchall()
        counts = Counter(row["status"] for row in rows)
        queues = dict.fromkeys(ROUTE_LABELS, 0)
        days = defaultdict(lambda: {"received": 0, "processed": 0})
        suggestions = confirmed = changed = handled = 0
        durations = []
        for row in rows:
            days[row["created_at"][:10]]["received"] += 1
            if row["first_resolved_at"] is not None:
                days[row["first_resolved_at"][:10]]["processed"] += 1
                durations.append(row["elapsed_seconds"])
            if row["status"] == "resolved":
                queues[row["operator_route"]] += 1
            if row["recommendation"] != "manual":
                suggestions += 1
                if row["operator_route"] is not None:
                    handled += 1
                    confirmed += row["operator_route"] == row["recommendation"]
                    changed += row["operator_route"] in ROUTE_LABELS and row["operator_route"] != row["recommendation"]
        return {
            "received": len(rows), "processed": len(durations), "resolved": counts["resolved"], "new": counts["new"],
            "review": counts["review"], "manual_suggested": len(rows) - suggestions,
            "suggestions": suggestions, "reviewed_suggestions": handled, "confirmed": confirmed, "changed": changed,
            "queues": queues, "mean_seconds": mean(durations) if durations else None,
            "median_seconds": median(durations) if durations else None,
            "daily": [{"date": day, **days[day]} for day in sorted(days)],
        }
