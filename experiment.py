"""Сравнение подходов. Выбор модели и порога выполняется до оценки test/challenge."""

from collections import Counter
import csv
import json
import math
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from business import assumptions, calculate, expected_seconds
from dataset import CLASSES, DATA, SPLITS, audit, fingerprint, read_rows
from model import EXPERIMENT, RELEASE, decision, fit_model, read_json, release_info, rules, score_rows
from triage import ROUTE_LABELS, load_model, predict

OUT = Path(__file__).resolve().parent / "docs" / "experiments"


def wilson(success, total):
    if not total:
        return None
    z = 1.959963984540054
    share = success / total
    denominator = 1 + z * z / total
    center = share + z * z / (2 * total)
    radius = z * math.sqrt(share * (1 - share) / total + z * z / (4 * total * total))
    return [max(0, (center - radius) / denominator), min(1, (center + radius) / denominator)]


def evaluate(rows, results):
    labels = [row["label"] for row in rows]
    candidates = [result["candidate"] for result in results]
    routes = [result["route"] for result in results]
    outcomes = [route if route != "manual" else "other" for route in routes]
    n = len(rows)
    covered = sum(route != "manual" for route in routes)
    correct = sum(route != "manual" and route == label for route, label in zip(routes, labels))
    other = labels.count("other")
    other_manual = sum(route == "manual" and label == "other" for route, label in zip(routes, labels))
    known = [index for index, label in enumerate(labels) if label in ROUTE_LABELS]
    coverage, precision = covered / n, correct / covered if covered else None
    raw = classification_report([labels[i] for i in known], [candidates[i] for i in known],
                                labels=ROUTE_LABELS, zero_division=0, output_dict=True)
    report = classification_report(labels, outcomes, labels=CLASSES, output_dict=True, zero_division=0)
    return {
        "n": n, "recommended": covered, "correct": correct, "wrong": covered - correct,
        "manual": n - covered, "coverage": coverage, "precision": precision, "manual_share": 1 - coverage,
        "wrong_share": (covered - correct) / n, "other_manual": other_manual, "other_total": other,
        "other_recall": other_manual / other if other else None,
        "accuracy": accuracy_score(labels, outcomes), "macro_f1": report["macro avg"]["f1-score"],
        "weighted_f1": report["weighted avg"]["f1-score"],
        "raw_known_macro_f1": raw["macro avg"]["f1-score"], "by_class": report,
        "matrix": confusion_matrix(labels, outcomes, labels=CLASSES).tolist(),
        "ci95_coverage": wilson(covered, n), "ci95_precision": wilson(correct, covered),
        "ci95_wrong_share": wilson(covered - correct, n), "ci95_other": wilson(other_manual, other),
        "seconds": expected_seconds(coverage, precision or 0),
    }


def calibration(rows, scores):
    p = np.array([[row[label] for label in CLASSES] for row in scores])
    y = np.array([CLASSES.index(row["label"]) for row in rows])
    truth = np.eye(len(CLASSES))[y]
    confidence = p.max(axis=1)
    correct = p.argmax(axis=1) == y
    ece = 0.0
    bins = []
    for index in range(5):
        low, high = index / 5, (index + 1) / 5
        mask = (confidence >= low) & ((confidence < high) if index < 4 else (confidence <= high))
        if mask.any():
            mean_score, accuracy = float(confidence[mask].mean()), float(correct[mask].mean())
            count = int(mask.sum())
            ece += count / len(rows) * abs(mean_score - accuracy)
            bins.append({"lower": low, "upper": high, "n": count, "score": mean_score, "accuracy": accuracy})
    return {"brier": float(np.mean(np.sum((p - truth) ** 2, axis=1))),
            "ece_top1": ece, "reliability_bins": bins}


def make_results(rows, scores, threshold, margin):
    return [decision(score, row["text"], threshold, margin) for row, score in zip(rows, scores)]


def sweep(rows, scores, config):
    data = []
    for threshold in config["thresholds"]:
        metrics = evaluate(rows, make_results(rows, scores, threshold, config["margin"]))
        allowed = (metrics["wrong_share"] <= config["max_wrong_share"]
                   and metrics["other_recall"] >= config["min_other_recall"])
        inputs = assumptions(metrics["coverage"], metrics["precision"] or 0)["base"]
        data.append({key: metrics[key] for key in ("coverage", "precision", "wrong_share", "manual_share",
                                                   "other_recall", "seconds")} | {
            "threshold": threshold, "allowed": allowed,
            "objective": metrics["seconds"] + config["wrong_risk_seconds"] * metrics["wrong_share"],
            "net_month_rub": calculate(inputs)["net_month_rub"],
        })
    return data


def best_policy(sweep_rows):
    return min((row for row in sweep_rows if row["allowed"]),
               key=lambda row: (row["objective"], row["wrong_share"], -row["threshold"]))


def error_rows(split, rows, results):
    records = []
    for row, result in zip(rows, results):
        route, label = result["route"], row["label"]
        expected = "manual" if label == "other" else label
        if route == expected:
            continue
        records.append({"split": split, "id": row["id"], "tag": row["tag"], "expected": expected,
                        "route": route, "candidate": result["candidate"], "score": result["confidence"],
                        "reason": result["reason"] or "wrong_suggestion", "text": row["text"]})
    return sorted(records, key=lambda row: (row["route"] == "manual", -row["score"]))


def measure(model, rows, thresholds, margin):
    texts = [row["text"] for row in rows]
    score_rows(model, texts[:1])
    times = []
    for _ in range(3):
        for text in texts:
            start = perf_counter()
            decision(score_rows(model, [text])[0], text, thresholds, margin)
            times.append((perf_counter() - start) * 1000)
    return {"median_ms": median(times), "p95_ms": quantiles(times, n=20, method="inclusive")[18],
            "n": len(times)}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    config = read_json(EXPERIMENT)
    validation = read_rows("validation")
    models, policies, sweeps, fit_seconds = {}, {}, {}, {}
    for name in config["algorithms"]:
        start = perf_counter()
        models[name] = fit_model(name, config)
        fit_seconds[name] = perf_counter() - start
        sweeps[name] = sweep(validation, score_rows(models[name], [row["text"] for row in validation]), config)
        policies[name] = best_policy(sweeps[name])
    selected = min(policies, key=lambda name: (policies[name]["objective"], policies[name]["wrong_share"], name))
    release = release_info(selected, policies[selected]["threshold"], config)

    # Итоговые наборы читаются только после фиксации всех параметров.
    splits = {split: read_rows(split) for split in SPLITS}
    closest = audit(splits)
    original = load_model()
    raw_models = {name: fit_model(name, config, calibrated=False) for name in ("logistic", "naive_bayes")}
    report = {
        "release": release, "rules": config, "labels": list(CLASSES), "validation_policies": policies,
        "datasets": {name: {"n": len(rows), "counts": dict(Counter(row["label"] for row in rows)),
                            "sha256": fingerprint(DATA / f"{name}.csv")} for name, rows in splits.items()},
        "nearest_pairs": closest, "curves": sweeps[selected], "comparison": {}, "calibration": {},
        "challenge_by_tag": {}, "fit_seconds": fit_seconds,
    }
    errors = []
    for split in ("validation", "benchmark", "test", "challenge"):
        rows = splits[split]
        texts = [row["text"] for row in rows]
        sets = {"v1": [predict(original, text) for text in texts]}
        sets["rules"] = [{"candidate": label, "route": "manual" if label == "other" else label}
                         for label in map(rules, texts)]
        report["calibration"][split] = {}
        for name, model in models.items():
            scores = score_rows(model, texts)
            sets[name] = make_results(rows, scores, policies[name]["threshold"], config["margin"])
            results = {"calibrated": calibration(rows, scores)}
            if name in raw_models:
                results["raw"] = calibration(rows, score_rows(raw_models[name], texts))
            report["calibration"][split][name] = results
        report["comparison"][split] = {name: evaluate(rows, results) for name, results in sets.items()}
        if split in ("test", "challenge"):
            errors.extend(error_rows(split, rows, sets[selected]))
        if split == "challenge":
            for tag in sorted({row["tag"] for row in rows}):
                pairs = [(row, result) for row, result in zip(rows, sets[selected]) if row["tag"] == tag]
                report["challenge_by_tag"][tag] = evaluate(*map(list, zip(*pairs)))

    report["timing"] = measure(models[selected], splits["test"], release["threshold"], config["margin"])
    final = report["comparison"]["test"][selected]
    scenarios = assumptions(final["coverage"], final["precision"] or 0)
    report["economics"] = {key: {"inputs": value, "results": calculate(value)} for key, value in scenarios.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    dump(RELEASE, release)
    dump(OUT / "v2.json", report)
    sweep_records = [{"model": name, **row} for name in sweeps for row in sweeps[name]]
    error_fields = ("split", "id", "tag", "expected", "route", "candidate", "score", "reason", "text")
    for path, rows, fields in ((OUT / "thresholds.csv", sweep_records, list(sweep_records[0])),
                               (OUT / "errors.csv", errors, error_fields)):
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print(f"{release['version']}: порог {release['threshold']}, test {final['correct']}/{final['recommended']}, "
          f"охват {final['coverage']:.1%}, ошибка в потоке {final['wrong_share']:.1%}")


if __name__ == "__main__":
    main()
