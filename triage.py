"""Локальная классификация текстовых обращений учебной платформы."""

import csv
from pathlib import Path
import unicodedata

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline


TRAIN_PATH = Path(__file__).resolve().parent / "data" / "train.csv"
ROUTE_LABELS = ("access", "payment", "schedule", "materials")
DEFAULT_THRESHOLD = 0.60


def normalize(text):
    """Приводит равнозначные формы текста к единому представлению."""
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return " ".join(normalized.split())


def load_model():
    """Обучает модель на включённой в репозиторий выборке."""
    with TRAIN_PATH.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    texts = [normalize(row["text"]) for row in rows]
    labels = [row["label"] for row in rows]
    if not all(texts) or set(labels) != set(ROUTE_LABELS):
        raise ValueError("Учебная выборка должна содержать непустые тексты всех четырёх маршрутов.")

    model = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True),
        LogisticRegression(C=15.0, max_iter=1000),
    )
    return model.fit(texts, labels)


def predict(model, text, threshold=DEFAULT_THRESHOLD):
    """Возвращает маршрут, лучший класс и оценки по четырём классам."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("Порог должен быть в диапазоне от 0 до 1.")

    normalized = normalize(text)
    if not normalized:
        raise ValueError("Введите текст обращения.")

    probabilities = model.predict_proba([normalized])[0]
    scores = {str(label): float(score) for label, score in zip(model.classes_, probabilities)}
    candidate = max(scores, key=scores.__getitem__)
    confidence = scores[candidate]
    route = candidate if confidence >= threshold else "manual"

    return {
        "route": route,
        "candidate": candidate,
        "confidence": confidence,
        "scores": scores,
        "threshold": threshold,
    }
