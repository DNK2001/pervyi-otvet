"""Сборка и проверка версионируемого синтетического корпуса."""

import csv
import hashlib
from itertools import combinations
from pathlib import Path
import re

from triage import ROUTE_LABELS, normalize

DATA = Path(__file__).resolve().parent / "data" / "v2"
SPLITS = ("train", "validation", "benchmark", "test", "challenge")
CLASSES = (*ROUTE_LABELS, "other")
FIELDS = ("id", "text", "label", "family", "tag", "source")


def read_rows(split):
    with (DATA / f"{split}.csv").open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def build_rows(split):
    family = label = None
    rows = []
    for line in (DATA / "source" / f"{split}.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if line.startswith("@ "):
            label, family = line[2:].split("/", 1)
            continue
        tag, separator, text = line.partition("|")
        rows.append({
            "id": f"{split[:2]}-{len(rows) + 1:03}",
            "text": text.strip() if separator else line.strip(),
            "label": label,
            "family": family,
            "tag": tag if separator else "standard",
            "source": "synthetic_codex_v2",
        })
    if split == "train":
        rows.extend(legacy_train())
    return rows


def legacy_train():
    """Ручное сопоставление исходных тренировочных примеров семействам v2."""
    mapping = (DATA / "source" / "legacy_families.txt").read_text(encoding="utf-8").split()
    with (DATA.parent / "train.csv").open(encoding="utf-8-sig", newline="") as file:
        legacy = list(csv.DictReader(file))
    return [
        {"id": f"lg-{index:03}", "text": row["text"], "label": row["label"],
         "family": family, "tag": "standard", "source": "synthetic_codex_v1"}
        for index, (row, family) in enumerate(zip(legacy, mapping, strict=True), start=1)
    ]


def canonical(text):
    return " ".join(re.findall(r"\w+", normalize(text)))


def shingles(text):
    text = canonical(text)
    return {text[index:index + 4] for index in range(max(1, len(text) - 3))}


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(splits):
    texts, families, ids = {}, {}, set()
    for split, rows in splits.items():
        if {row["label"] for row in rows} != set(CLASSES):
            raise ValueError(f"{split}: отсутствуют классы или есть неизвестные метки")
        texts[split] = []
        for row in rows:
            clean = canonical(row["text"])
            family = row["family"]
            if not clean or not family or row["id"] in ids or len(row["text"]) > 1000:
                raise ValueError(f"Некорректная строка {row}")
            if families.setdefault(family, split) != split:
                raise ValueError(f"Семейство {family} в нескольких выборках")
            ids.add(row["id"])
            texts[split].append((row["id"], clean, shingles(clean)))
        if len({clean for _, clean, _ in texts[split]}) != len(rows):
            raise ValueError(f"Повтор строки в {split}")

    closest = []
    for left, right in combinations(splits, 2):
        similarity, left_id, right_id = max(
            (len(first & second) / len(first | second), left_id, right_id)
            for left_id, _, first in texts[left]
            for right_id, _, second in texts[right]
        )
        if similarity >= 0.60:
            raise ValueError(f"Близкий повтор {left_id} / {right_id}: {similarity:.3f}")
        closest.append({"splits": [left, right], "ids": [left_id, right_id],
                        "jaccard_char4": round(similarity, 4)})
    return closest


def main():
    splits = {split: build_rows(split) for split in SPLITS}
    pairs = audit(splits)
    for split, rows in splits.items():
        with (DATA / f"{split}.csv").open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"{split}: {len(rows)} строк")
    for pair in pairs:
        print(pair)


if __name__ == "__main__":
    main()
