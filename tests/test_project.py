from concurrent.futures import ThreadPoolExecutor
import csv
import io
from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from app import REPORT, TriageServer
from business import assumptions, calculate, expected_seconds, sensitivity
from dataset import SPLITS, audit, build_rows, read_rows
from economics import calculate as baseline_economics
from evaluate import evaluate as baseline_evaluate
from experiment import evaluate, wilson
from model import decision, load_predictor, read_json
from storage import Store
from ticket_io import DEMO, csv_messages, message
from triage import normalize

PREDICTOR = None


def predictor():
    global PREDICTOR
    if PREDICTOR is None:
        PREDICTOR = load_predictor()
    return PREDICTOR


class DataAndModelTests(unittest.TestCase):
    def test_unicode_whitespace_and_negation_preserved(self):
        self.assertEqual(normalize("  Ａ\tНЕ\nВХОЖУ, ёж  "), "a не вхожу, еж")

    def test_frozen_data_matches_source_and_has_disjoint_groups(self):
        splits = {split: read_rows(split) for split in SPLITS}
        self.assertTrue(all(build_rows(split) == rows for split, rows in splits.items()))
        self.assertLess(max(pair["jaccard_char4"] for pair in audit(splits)), 0.60)

    def test_audit_rejects_duplicate_across_groups(self):
        data = {split: build_rows(split) for split in ("train", "validation")}
        data["validation"][0]["text"] = data["train"][0]["text"]
        with self.assertRaisesRegex(ValueError, "Близкий повтор"):
            audit(data)

    def test_recommendation_and_unknown(self):
        value = predictor().predict(DEMO[1])
        self.assertEqual(value["route"], "payment")
        self.assertAlmostEqual(sum(value["scores"].values()), 1)
        self.assertEqual(predictor().predict(DEMO[4])["reason"], "other")
        self.assertEqual(predictor().predict(DEMO[5])["reason"], "short")

    def test_threshold_boundary_and_margin(self):
        scores = {"access": .55, "payment": .40, "other": .05}
        self.assertEqual(decision(scores, "не вхожу", .55, .08)["route"], "access")
        self.assertEqual(decision(scores, "не вхожу", .551, .08)["reason"], "low_score")
        self.assertEqual(decision(scores, "не вхожу", .55, .16)["reason"], "close_scores")

    def test_invalid_message(self):
        for invalid in ("   ", None, 3, "a" * 1001, "a\x00"):
            with self.subTest(invalid=repr(invalid)[:40]), self.assertRaises(ValueError):
                message(invalid)
        with self.assertRaises(ValueError):
            predictor().predict(" ")

    def test_policy_metrics_classification_vs_selective(self):
        rows = [{"label": label} for label in ("access", "payment", "other", "other")]
        results = [{"candidate": label, "route": route} for label, route in
                   (("access", "access"), ("payment", "manual"), ("access", "access"), ("other", "manual"))]
        data = evaluate(rows, results)
        self.assertEqual(data["coverage"], .5)
        self.assertEqual(data["precision"], .5)
        self.assertEqual(data["wrong_share"], .25)
        self.assertEqual(data["other_recall"], .5)
        self.assertEqual(data["raw_known_macro_f1"], .5)
        self.assertEqual(data["accuracy"], .5)
        self.assertIsNone(wilson(0, 0))
        self.assertLess(wilson(1, 1)[0], .5)

    def test_report_match_and_fixed_holdout_predictions(self):
        report = read_json(REPORT)
        self.assertEqual(report["release"], predictor().release)
        rows = read_rows("test")
        expected = report["comparison"]["test"][predictor().release["algorithm"]]
        measured = evaluate(rows, [predictor().predict(row["text"]) for row in rows])
        self.assertEqual(measured, expected)

    def test_baseline_unchanged(self):
        metrics = baseline_evaluate()
        self.assertEqual((metrics["auto_correct"], metrics["manual_count"]), (61, 57))
        self.assertAlmostEqual(baseline_economics(.525, 61 / 63, 6000)["net_month_rub"], 21666.6666667, 5)


class BusinessAndCSVTests(unittest.TestCase):
    def test_economics_matches_hand_calculation(self):
        a = assumptions(.525, 61 / 63)["base"]
        r = calculate({**a, "monetized": 1})
        self.assertAlmostEqual(r["assisted_seconds"], 64.75)
        self.assertAlmostEqual(r["net_month_rub"], 21666.6666667, 5)
        self.assertAlmostEqual(r["first_year_net_rub"], 170000)
        self.assertAlmostEqual(r["payback_months"], 4.1538461538)
        self.assertEqual(calculate({**a, "monetized": 0})["net_month_rub"], -12000)
        self.assertTrue(all(row["value"] <= 1 for row in sensitivity({**a, "coverage": 1})))

    def test_economics_boundaries(self):
        a = assumptions(0, 0)["base"]
        self.assertEqual(expected_seconds(0, 0), 100)
        self.assertEqual(expected_seconds(1, 1), 30)
        r = calculate(a)
        self.assertLess(r["saved_hours"], 0)
        self.assertIsNone(r["break_even_volume"])
        self.assertIsNone(r["payback_months"])
        self.assertEqual(calculate({**a, "volume": 0})["saved_hours"], 0)
        for key, invalid in (("manual_seconds", 0), ("volume", 1.5), ("precision", float("nan")),
                             ("setup_cost", True), ("hourly_cost", -1), ("coverage", 1.1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                calculate({**a, key: invalid})

    def test_csv_dialects_and_multiline(self):
        self.assertEqual(csv_messages('\ufefftext;kind\r\n"строка; 1\nстрока 2";a\r\n'),
                         ["строка; 1\nстрока 2"])
        self.assertEqual(csv_messages('text\n"цена, пожалуйста"\n'), ["цена, пожалуйста"])

    def test_csv_invalid_and_limits(self):
        for invalid in ("label\naccess\n", 'text\n"broken\n', "text,text\nx,y\n", "text\na,b\n",
                        "text,label\na\n", "text\n   \n", "text\n" + "a\n" * 101):
            with self.subTest(invalid=invalid[:30]), self.assertRaises(ValueError):
                csv_messages(invalid)


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "tickets.sqlite3"
        self.opener = build_opener(ProxyHandler({}))
        self.start_server()

    def start_server(self):
        self.server = TriageServer(("127.0.0.1", 0), predictor(), Store(self.path), read_json(REPORT))
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.03}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server, self.server, self.thread)

    @staticmethod
    def stop_server(server, thread):
        if thread.is_alive():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def send(self, path, body=None, *, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = Request(self.url + path, data, headers or ({"Content-Type": "application/json"} if data is not None else {}))
        try:
            response = self.opener.open(request, timeout=4)
        except HTTPError as error:
            response = error
        with response:
            payload = response.read()
            if response.headers.get_content_type() == "application/json":
                payload = json.loads(payload)
            return response.status, payload

    def test_end_to_end_restart_and_history(self):
        status, item = self.send("/api/tickets", {"text": DEMO[1]})
        self.assertEqual(status, 201)
        path = f"/api/tickets/{item['id']}"
        self.assertEqual(item["status"], "new")
        self.assertEqual(item["prediction"]["route"], "payment")
        status, routed = self.send(path + "/decision", {"route": "confirm", "revision": item["revision"]})
        self.assertEqual(status, 200)
        self.assertEqual((routed["status"], routed["operator_route"], routed["changed"]), ("resolved", "payment", False))
        self.assertEqual(self.send(path + "/decision", {"route": "manual", "revision": item["revision"]})[0], 409)
        self.stop_server(self.server, self.thread)
        self.start_server()
        self.assertEqual(self.send(path)[1], routed)
        status, review = self.send(path + "/decision", {"route": "manual", "revision": routed["revision"]})
        self.assertEqual((status, review["status"], review["changed"]), (200, "review", True))
        status, changed = self.send(path + "/decision", {"route": "materials", "revision": review["revision"]})
        self.assertEqual((status, changed["operator_route"], changed["changed"]), (200, "materials", True))
        _, feedback = self.send(path + "/feedback", {"kind": "wrong", "note": "Проверка"})
        self.assertEqual([event["kind"] for event in feedback["events"]],
                         ["feedback", "rerouted", "reviewed", "confirmed", "analyzed", "created"])
        self.assertEqual(feedback["feedback"][0]["note"], "Проверка")
        self.assertEqual(self.send("/api/tickets?" + urlencode({"history": 1, "queue": "materials", "q": "ДВА"}))[1]["total"], 1)
        stats = self.send("/api/analytics?scope=work")[1]
        self.assertEqual((stats["processed"], stats["changed"], stats["queues"]["materials"]), (1, 1, 1))
        self.assertEqual(sum(row["processed"] for row in stats["daily"]), 1)
        self.assertIsNotNone(stats["median_seconds"])

    def test_predict_does_not_create_and_unknown_requires_review(self):
        self.assertEqual(self.send("/api/predict", {"text": DEMO[4]})[1]["route"], "manual")
        self.assertEqual(self.send("/api/tickets")[1]["total"], 0)
        _, item = self.send("/api/tickets", {"text": DEMO[4]})
        path = f"/api/tickets/{item['id']}/decision"
        self.assertEqual(self.send(path, {"route": "confirm", "revision": 1})[0], 400)
        self.assertEqual(self.send(path, {"route": "manual", "revision": 1})[1]["status"], "review")

    def test_idempotency_and_concurrent_revision(self):
        body = {"text": DEMO[1], "request_key": "12345678"}
        with ThreadPoolExecutor(2) as threads:
            submissions = list(threads.map(lambda _: self.send("/api/tickets", body), range(2)))
        self.assertEqual(sorted(status for status, _ in submissions), [200, 201])
        self.assertEqual(len({ticket["id"] for _, ticket in submissions}), 1)
        self.assertEqual(self.send("/api/tickets", {**body, "text": DEMO[3]})[0], 409)
        path = f"/api/tickets/{submissions[0][1]['id']}/decision"
        with ThreadPoolExecutor(2) as threads:
            changes = list(threads.map(lambda route: self.send(path, {"route": route, "revision": 1}),
                                       ("manual", "confirm")))
        self.assertEqual(sorted(status for status, _ in changes), [200, 409])

    def test_demo_is_idempotent_and_scoped(self):
        first = self.send("/api/demo", {})
        again = self.send("/api/demo", {})
        self.assertEqual((first[0], again[0]), (201, 200))
        self.assertEqual(first[1]["ids"], again[1]["ids"])
        self.assertEqual(self.send("/api/analytics?scope=work")[1]["received"], 0)
        self.assertEqual(self.send("/api/analytics?scope=demo")[1]["received"], len(DEMO))
        self.assertEqual(len(self.send("/api/tickets?limit=2&offset=1")[1]["items"]), 2)

    def test_atomic_csv_and_export(self):
        self.assertEqual(self.send("/api/import", {"csv": 'text\nfirst\n"broken\n'})[0], 400)
        self.assertEqual(self.send("/api/tickets")[1]["total"], 0)
        status, response = self.send("/api/import", {"csv": 'text\n"=2+2"\n"Нужен файл"\n'})
        self.assertEqual((status, response["count"]), (201, 2))
        _, raw = self.send("/api/export")
        self.assertEqual(self.send("/api/template"), (200, b"text\r\n"))
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual(rows[1]["text"], "'=2+2")
        self.assertEqual(rows[0]["source"], "csv")

    def test_api_rejects_invalid_inputs(self):
        for path, status in (("/missing", 404), ("/api/tickets/999", 404), ("/api/tickets?offset=-1", 400),
                             ("/api/tickets?limit=200", 400), ("/api/tickets?queue=missing", 400)):
            self.assertEqual(self.send(path)[0], status)
        self.assertEqual(self.send("/api/predict", raw=b"{x")[0], 400)
        self.assertEqual(self.send("/api/predict", body={"text": " "})[0], 400)
        self.assertEqual(self.send("/api/predict", raw=b"[]")[0], 400)
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        try:
            connection.putrequest("POST", "/api/predict")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", "700001")
            connection.endheaders()
            self.assertEqual(connection.getresponse().status, 413)
        finally:
            connection.close()
        self.assertEqual(self.send("/api/predict", raw=b"x", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.send("/api/predict", {"text": "demo"},
                                   headers={"Content-Type": "application/json", "Origin": "https://example.invalid"})[0], 403)

    def test_economics_api(self):
        self.assertEqual(self.send("/api/economics", {"inputs": {}})[0], 400)
        a = assumptions(.7, .9)["base"]
        status, payload = self.send("/api/economics", {"inputs": a})
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"], calculate(a))
        self.assertEqual(len(payload["sensitivity"]), 6)


if __name__ == "__main__":
    unittest.main()
