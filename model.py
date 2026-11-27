"""Версионируемая локальная модель и политика выдачи подсказок."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import FeatureUnion, make_pipeline
from sklearn.svm import LinearSVC

from dataset import DATA, fingerprint, read_rows
from triage import ROUTE_LABELS, normalize

ROOT = Path(__file__).resolve().parent
EXPERIMENT = ROOT / "config" / "experiment.json"
RELEASE = ROOT / "config" / "release.json"
RULES = {
    "access": r"парол|аккаунт|учетн|учетк|авториз|логин|\bвойти\b",
    "payment": r"оплат|платеж|списан|возврат|квитанц|\bчек\b|рассроч|счет",
    "schedule": r"расписан|календар|перенес|перенос|во сколько|когда.{0,20}(?:урок|заняти)|слот",
    "materials": r"запис[ьи].{0,15}(?:урок|занят|вебинар)|конспект|файл|материал|слайд|видео|методич",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def code_hash():
    return fingerprint(Path(__file__))


def make_estimator(name, seed):
    vectorizer = FeatureUnion([
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)),
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, token_pattern=r"(?u)\b\w+\b")),
    ])
    estimators = {
        "naive_bayes": MultinomialNB(alpha=0.15),
        "logistic": LogisticRegression(C=10, max_iter=1000, random_state=seed),
        "svm": LinearSVC(C=1, random_state=seed),
    }
    return make_pipeline(vectorizer, estimators[name])


def fit_model(name, config, calibrated=True):
    train = read_rows("train")
    texts = [normalize(row["text"]) for row in train]
    labels = [row["label"] for row in train]
    groups = [row["family"] for row in train]
    estimator = make_estimator(name, config["seed"])
    if calibrated:
        splitter = StratifiedGroupKFold(config["calibration_folds"], shuffle=True, random_state=config["seed"])
        folds = list(splitter.split(texts, labels, groups))
        estimator = CalibratedClassifierCV(estimator, method="sigmoid", cv=folds, ensemble=False)
    return estimator.fit(texts, labels)


def score_rows(model, texts):
    probabilities = model.predict_proba([normalize(text) for text in texts])
    return [{str(label): float(score) for label, score in zip(model.classes_, row)} for row in probabilities]


def decision(scores, text, threshold, margin):
    ranked = sorted(scores, key=scores.__getitem__, reverse=True)
    candidate = ranked[0]
    score = scores[candidate]
    if len(re.findall(r"\w+", normalize(text))) < 2:
        reason = "short"
    elif candidate == "other":
        reason = "other"
    elif score < threshold:
        reason = "low_score"
    elif score - scores[ranked[1]] < margin:
        reason = "close_scores"
    else:
        reason = None
    return {
        "route": "manual" if reason else candidate,
        "candidate": candidate, "confidence": score, "scores": scores, "threshold": threshold,
        "reason": reason, "margin": score - scores[ranked[1]],
    }


def rules(text):
    normalized = normalize(text)
    matches = [label for label, pattern in RULES.items() if re.search(pattern, normalized)]
    return matches[0] if len(matches) == 1 else "other"


def release_info(name, threshold, config):
    values = {
        "algorithm": name, "threshold": threshold, "margin": config["margin"],
        "train_sha256": fingerprint(DATA / "train.csv"), "config_sha256": fingerprint(EXPERIMENT),
        "model_code_sha256": code_hash(), "normalizer_sha256": fingerprint(ROOT / "triage.py"),
        "sklearn": sklearn.__version__,
    }
    signature = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    return {**values, "version": f"v2-{name}-{signature[:12]}"}


@dataclass(frozen=True)
class Predictor:
    estimator: object
    release: dict

    def predict(self, text):
        if not normalize(text):
            raise ValueError("Введите текст обращения.")
        scores = score_rows(self.estimator, [text])[0]
        result = decision(scores, text, self.release["threshold"], self.release["margin"])
        return {**result, "model_version": self.release["version"]}


def load_predictor():
    config = read_json(EXPERIMENT)
    release = read_json(RELEASE)
    expected = release_info(release["algorithm"], release["threshold"], config)
    if release != expected:
        raise ValueError("Версия модели не соответствует данным, коду или окружению. Проверьте инструкцию запуска.")
    return Predictor(fit_model(release["algorithm"], config), release)
