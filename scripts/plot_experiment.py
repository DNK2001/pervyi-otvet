"""Сохраняет графики подбора порога по зафиксированным результатам validation."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter

OUT = Path(__file__).resolve().parents[1] / "docs" / "experiments"


def main():
    report = json.loads((OUT / "v2.json").read_text(encoding="utf-8"))
    curve = report["curves"]
    chosen = next(row for row in curve if row["threshold"] == report["release"]["threshold"])
    has_suggestions = [row for row in curve if row["precision"] is not None]
    color = "#254dc3"
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 3.8), layout="constrained")
    for ax in axes:
        ax.grid(axis="y", color="#dce4f1")
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    specs = [
        (has_suggestions, "coverage", "precision", "Точность подсказок", "Охват", "Доля верных"),
        (curve, "threshold", "net_month_rub", "Чистый эффект в месяц", "Порог", "Прогноз, ₽"),
        (curve, "threshold", "manual_share", "Доля ручного разбора", "Порог", "Доля потока"),
    ]
    for ax, (rows, x, y, title, xlabel, ylabel) in zip(axes, specs):
        ax.plot([row[x] for row in rows], [row[y] for row in rows], "o-", ms=4, color=color)
        ax.scatter(chosen[x], chosen[y], s=78, marker="D", facecolor="white", edgecolor=color, zorder=4)
        ax.set(title=title, xlabel=xlabel, ylabel=ylabel, xlim=(0, 1.02))
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        if y == "net_month_rub":
            ax.axhline(0, color="#a2adbf", linewidth=.85)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda amount, _: f"{amount / 1000:.0f} тыс."))
        else:
            ax.set_ylim(0, 1.04)
            ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    fig.suptitle("Подбор порога на 75 синтетических обращениях · ромб отмечает выбранный порог")
    fig.savefig(OUT / "validation_curves.png", dpi=157, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
