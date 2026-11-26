"""Scenario model for the first-line support routing workflow."""

import argparse
import json

from evaluate import evaluate


def calculate(coverage, precision, volume):
    manual_seconds = 90
    accepted_seconds = 30
    correction_seconds = 120
    abstention_seconds = 100
    hours_per_fte = 160
    hourly_cost = 800
    setup_cost = 90_000
    running_cost = 12_000

    assisted_seconds = (
        coverage * (precision * accepted_seconds + (1 - precision) * correction_seconds)
        + (1 - coverage) * abstention_seconds
    )
    current_hours = volume * manual_seconds / 3600
    target_hours = volume * assisted_seconds / 3600
    saved_hours = current_hours - target_hours
    gross_month = saved_hours * hourly_cost
    net_month = gross_month - running_cost
    first_year_cost = setup_cost + 12 * running_cost
    first_year_net = 12 * gross_month - first_year_cost
    precision_drop = min(0.10, precision)
    sensitivity_seconds = coverage * precision_drop * (correction_seconds - accepted_seconds)

    return {
        "volume": volume,
        "coverage": coverage,
        "precision": precision,
        "current_seconds": manual_seconds,
        "assisted_seconds": assisted_seconds,
        "seconds_saved": manual_seconds - assisted_seconds,
        "time_reduction": (manual_seconds - assisted_seconds) / manual_seconds,
        "current_hours": current_hours,
        "target_hours": target_hours,
        "saved_hours": saved_hours,
        "current_fte": current_hours / hours_per_fte,
        "target_fte": target_hours / hours_per_fte,
        "saved_fte": saved_hours / hours_per_fte,
        "gross_month_rub": gross_month,
        "net_month_rub": net_month,
        "setup_rub": setup_cost,
        "running_rub": running_cost,
        "payback_months": setup_cost / net_month if net_month > 0 else None,
        "first_year_net_rub": first_year_net,
        "first_year_roi": first_year_net / first_year_cost,
        "sensitivity_precision_drop": precision_drop,
        "sensitivity_seconds_added": sensitivity_seconds,
        "sensitivity_hours_added": volume * sensitivity_seconds / 3600,
        "sensitivity_rub_lost": volume * sensitivity_seconds / 3600 * hourly_cost,
    }


def share(value):
    fraction = float(value)
    if not 0 <= fraction <= 1:
        raise argparse.ArgumentTypeError("укажите долю от 0 до 1")
    return fraction


def main():
    parser = argparse.ArgumentParser(description="Сценарный расчёт затрат времени и окупаемости")
    parser.add_argument("--coverage", type=share, help="доля обращений с подсказкой")
    parser.add_argument("--precision", type=share, help="доля верных среди подсказок")
    parser.add_argument("--volume", type=int, default=6000, help="обращений в месяц")
    args = parser.parse_args()
    if args.volume <= 0:
        parser.error("--volume должен быть больше нуля")
    if (args.coverage is None) != (args.precision is None):
        parser.error("передайте обе доли или оставьте обе по умолчанию")

    coverage, precision = args.coverage, args.precision
    if coverage is None:
        metrics = evaluate()
        coverage, precision = metrics["coverage"], metrics["auto_precision"] or 0.0
    result = calculate(coverage, precision, args.volume)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
