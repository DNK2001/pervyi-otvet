"""Сценарная модель маршрутизации с проверяемыми допущениями."""

import math

LIMITS = {
    "volume": (0, 1_000_000),
    "manual_seconds": (1, 86_400),
    "accepted_seconds": (0, 86_400),
    "correction_seconds": (0, 86_400),
    "abstention_seconds": (0, 86_400),
    "hourly_cost": (0, 1_000_000),
    "hours_per_fte": (1, 744),
    "coverage": (0, 1),
    "precision": (0, 1),
    "monetized": (0, 1),
    "setup_cost": (0, 1_000_000_000),
    "operation_cost": (0, 1_000_000_000),
    "maintenance_cost": (0, 1_000_000_000),
}


def assumptions(coverage, precision):
    base = {
        "volume": 6000, "manual_seconds": 90, "accepted_seconds": 30,
        "correction_seconds": 120, "abstention_seconds": 100, "hourly_cost": 800,
        "hours_per_fte": 160, "coverage": coverage, "precision": precision,
        "monetized": 0.65, "setup_cost": 90_000, "operation_cost": 4000,
        "maintenance_cost": 8000,
    }
    return {
        "base": base,
        "pessimistic": {**base, "volume": 4200, "coverage": max(0, coverage - 0.15),
                        "precision": max(0, precision - 0.10), "monetized": 0.30,
                        "correction_seconds": 150, "maintenance_cost": 10_000},
        "optimistic": {**base, "volume": 8000, "coverage": min(1, coverage + 0.15),
                       "precision": min(1, precision + 0.03), "monetized": 0.90,
                       "accepted_seconds": 25, "abstention_seconds": 90},
    }


def expected_seconds(coverage, precision, correct=30, wrong=120, manual=100):
    return coverage * (precision * correct + (1 - precision) * wrong) + (1 - coverage) * manual


def calculate(inputs):
    if not isinstance(inputs, dict) or inputs.keys() != LIMITS.keys():
        raise ValueError("Заполните все параметры сценария.")
    for key, (low, high) in LIMITS.items():
        value = inputs[key]
        if type(value) not in (int, float) or not low <= value <= high:
            raise ValueError(f"Параметр {key} должен быть в диапазоне {low}–{high}.")
    if int(inputs["volume"]) != inputs["volume"]:
        raise ValueError("Количество обращений должно быть целым.")

    a = inputs
    assisted = expected_seconds(a["coverage"], a["precision"], a["accepted_seconds"],
                                a["correction_seconds"], a["abstention_seconds"])
    saved_per_ticket = a["manual_seconds"] - assisted
    current_hours = a["volume"] * a["manual_seconds"] / 3600
    target_hours = a["volume"] * assisted / 3600
    saved_hours = a["volume"] * saved_per_ticket / 3600
    month_cost = a["operation_cost"] + a["maintenance_cost"]
    annual_cost = a["setup_cost"] + 12 * month_cost
    # Дополнительная нагрузка увеличивает затраты полностью.
    cash_per_ticket = saved_per_ticket / 3600 * a["hourly_cost"] * (
        a["monetized"] if saved_per_ticket >= 0 else 1
    )
    gross = saved_hours * a["hourly_cost"]
    cash = a["volume"] * cash_per_ticket
    net = cash - month_cost
    first_year = 12 * cash - annual_cost
    return {
        "assisted_seconds": assisted, "seconds_saved": saved_per_ticket,
        "time_reduction": saved_per_ticket / a["manual_seconds"],
        "current_hours": current_hours, "target_hours": target_hours, "saved_hours": saved_hours,
        "current_fte": current_hours / a["hours_per_fte"],
        "target_fte": target_hours / a["hours_per_fte"],
        "saved_fte": saved_hours / a["hours_per_fte"],
        "gross_month_rub": gross, "cash_month_rub": cash, "net_month_rub": net,
        "first_year_net_rub": first_year, "first_year_roi": first_year / annual_cost if annual_cost else None,
        "payback_months": 0 if a["setup_cost"] == 0 and net >= 0 else a["setup_cost"] / net if net > 0 else None,
        "break_even_volume": math.ceil(month_cost / cash_per_ticket) if cash_per_ticket > 0 else (
            0 if month_cost == 0 and cash_per_ticket == 0 else None
        ),
        "year_break_even_volume": math.ceil(annual_cost / (12 * cash_per_ticket)) if cash_per_ticket > 0 else (
            0 if annual_cost == 0 and cash_per_ticket == 0 else None
        ),
    }


def sensitivity(inputs):
    scenarios = {
        "Охват −10 п. п.": ("coverage", -0.10), "Охват +10 п. п.": ("coverage", 0.10),
        "Точность −10 п. п.": ("precision", -0.10), "Точность +10 п. п.": ("precision", 0.10),
        "Монетизация −10 п. п.": ("monetized", -0.10), "Монетизация +10 п. п.": ("monetized", 0.10),
    }
    base = calculate(inputs)["net_month_rub"]
    rows = []
    for label, (field, delta) in scenarios.items():
        value = min(1, max(0, inputs[field] + delta))
        result = calculate({**inputs, field: value})
        rows.append({"label": label, "value": value, "seconds": result["assisted_seconds"],
                     "net": result["net_month_rub"], "delta": result["net_month_rub"] - base})
    return rows
