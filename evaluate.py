"""Проверка маршрутизации на отдельной контрольной выборке."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from triage import load_model, predict


TEST_PATH = Path(__file__).resolve().parent / "data" / "test.csv"
ROUTES = ("access", "payment", "schedule", "materials")
LABELS = (*ROUTES, "other")
DECISIONS = (*ROUTES, "manual")


def read_test_rows():
    with TEST_PATH.open(encoding="utf-8-sig", newline="") as file:
        rows = [(row["text"].strip(), row["label"]) for row in csv.DictReader(file)]
    if set(label for _, label in rows) != set(LABELS):
        raise ValueError("В тестовой выборке должны присутствовать все пять классов.")
    normalized = {" ".join(text.casefold().split()) for text, _ in rows}
    if "" in normalized or len(normalized) != len(rows):
        raise ValueError("В тестовой выборке есть пустые сообщения или дубли.")
    return rows


def evaluate():
    rows = read_test_rows()
    model = load_model()
    confusion = {label: dict.fromkeys(DECISIONS, 0) for label in LABELS}
    raw_counts = Counter()
    auto_errors = []
    for message, label in rows:
        result = predict(model, message)
        route = result["route"]
        confusion[label][route] += 1
        if label != "other":
            raw_counts[label, result["candidate"]] += 1
        if route != "manual" and route != label:
            auto_errors.append({
                "text": message,
                "expected": label,
                "route": route,
                "confidence": float(result["confidence"]),
            })

    raw_f1 = {}
    for route in ROUTES:
        true_positives = raw_counts[route, route]
        predicted = sum(raw_counts[label, route] for label in ROUTES)
        expected = sum(raw_counts[route, candidate] for candidate in ROUTES)
        raw_f1[route] = 2 * true_positives / (predicted + expected)

    n = len(rows)
    manual_count = sum(counts["manual"] for counts in confusion.values())
    auto_count = n - manual_count
    auto_correct = sum(confusion[route][route] for route in ROUTES)
    support = {label: sum(confusion[label].values()) for label in LABELS}
    return {
        "n": n,
        "support": support,
        "auto_count": auto_count,
        "auto_correct": auto_correct,
        "auto_wrong": auto_count - auto_correct,
        "manual_count": manual_count,
        "coverage": auto_count / n,
        "auto_precision": auto_correct / auto_count if auto_count else None,
        "correct_auto_share": auto_correct / n,
        "raw_macro_f1": sum(raw_f1.values()) / len(ROUTES),
        "raw_f1_by_route": raw_f1,
        "out_of_scope_manual_recall": confusion["other"]["manual"] / support["other"],
        "confusion": confusion,
        "auto_error_examples": auto_errors,
    }


def print_summary(result):
    print(f"Контрольная выборка · {result['n']} сообщений")
    for title, key in (
        ("Доля рекомендаций", "coverage"),
        ("Точность рекомендаций", "auto_precision"),
        ("Верные рекомендации среди всех сообщений", "correct_auto_share"),
        ("Macro F1 кандидата на четырёх маршрутах", "raw_macro_f1"),
        ("Обращения вне маршрутов, переданные на ручной разбор", "out_of_scope_manual_recall"),
    ):
        value = result[key]
        displayed = "н/д" if value is None else f"{value:.1%}"
        print(f"{title:<56} {displayed}")

    print(
        f"\nВерная рекомендация · {result['auto_correct']}"
        f"   Ошибочная · {result['auto_wrong']}"
        f"   Ручной разбор · {result['manual_count']}"
    )
    print("\nСтроки — истинные классы, столбцы — решение системы")
    print(f"{'':12}" + "".join(f"{route:>11}" for route in DECISIONS))
    for label in LABELS:
        print(f"{label:12}" + "".join(f"{result['confusion'][label][route]:>11}" for route in DECISIONS))

    if result["auto_error_examples"]:
        print("\nПервые ошибочные рекомендации")
        for example in result["auto_error_examples"][:5]:
            print(f"  {example['expected']} → {example['route']} · {example['text']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="вывести метрики в формате JSON")
    args = parser.parse_args()
    result = evaluate()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_summary(result)


if __name__ == "__main__":
    main()
