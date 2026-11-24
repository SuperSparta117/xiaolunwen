from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

FEATURES = [
    "name_exact", "name_similarity", "address_similarity", "area_match", "street_match",
    "coords_available", "coords_trust_both", "poi_distance_m", "poi_distance_lt_100m",
    "poi_distance_100_300m", "poi_distance_300_1000m", "poi_distance_gt_1000m",
    "poi_district_match", "type_match",
]


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def mask_rows(rows: list[dict[str, str]], ratio: float, seed: int = 42) -> list[dict[str, str]]:
    """Apply a deterministic primary-name mask to pair features."""
    import random
    masked = []
    for row in rows:
        result = dict(row)
        rng = random.Random(f"{seed}:{row.get('query_id','')}:{row.get('candidate_id','')}")
        if ratio > 0 and rng.random() <= ratio:
            for field in ("name_exact", "name_similarity"):
                result[field] = "0"
        masked.append(result)
    return masked


def vector(row: dict[str, str], *, use_poi: bool = True, use_text: bool = True) -> list[float]:
    values = []
    for field in FEATURES:
        if not use_poi and field.startswith("poi_") or not use_poi and field == "coords_trust_both":
            values.append(0.0)
        elif not use_text and field in {"name_exact", "name_similarity", "address_similarity", "street_match", "type_match"}:
            values.append(0.0)
        else:
            value = _float(row.get(field))
            if field == "poi_distance_m":
                value = min(value / 2000.0, 10.0) if value else 0.0
            values.append(value)
    return values


def sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


class LogisticModel:
    def __init__(self, dimension: int):
        self.weights = [0.0] * (dimension + 1)

    def fit(self, rows: list[dict[str, str]], *, use_poi: bool = True, use_text: bool = True, epochs: int = 500, lr: float = 0.08) -> None:
        if not rows:
            return
        for _ in range(epochs):
            gradient = [0.0] * len(self.weights)
            for row in rows:
                x = [1.0] + vector(row, use_poi=use_poi, use_text=use_text)
                error = sigmoid(sum(w * v for w, v in zip(self.weights, x))) - _float(row.get("label"))
                for index, value in enumerate(x):
                    gradient[index] += error * value
            scale = lr / len(rows)
            self.weights = [w - scale * g for w, g in zip(self.weights, gradient)]

    def predict(self, row: dict[str, str], *, use_poi: bool = True, use_text: bool = True) -> float:
        x = [1.0] + vector(row, use_poi=use_poi, use_text=use_text)
        return sigmoid(sum(w * v for w, v in zip(self.weights, x)))


def rule_probability(row: dict[str, str], mode: str) -> float:
    name = _float(row.get("name_similarity"))
    address = _float(row.get("address_similarity"))
    area = _float(row.get("area_match"))
    street = _float(row.get("street_match"))
    distance = _float(row.get("poi_distance_m"))
    if mode == "exact":
        return 1.0 if _float(row.get("name_exact")) else 0.0
    if mode == "tfidf_like":
        return name
    if mode == "text_structure":
        return 0.55 * name + 0.2 * address + 0.15 * area + 0.1 * street
    if mode == "poi_rule":
        return (0.8 if distance and distance < 300 else 0.2) * (0.7 + 0.3 * area)
    return 0.0


def _f1(tp: int, fp: int, fn: int) -> float:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _label(row: Mapping[str, object]) -> int:
    return int(_float(row.get("label")))


def pair_metrics(rows: list[dict[str, object]], threshold: float) -> dict[str, float | int]:
    tp = sum(int(_label(row) == 1 and float(row["probability"]) >= threshold) for row in rows)
    fp = sum(int(_label(row) == 0 and float(row["probability"]) >= threshold) for row in rows)
    fn = sum(int(_label(row) == 1 and float(row["probability"]) < threshold) for row in rows)
    tn = sum(int(_label(row) == 0 and float(row["probability"]) < threshold) for row in rows)
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": tp / (tp + fp) if tp + fp else 0.0, "recall": tp / (tp + fn) if tp + fn else 0.0, "f1": _f1(tp, fp, fn)}


def query_metrics(rows: list[dict[str, object]], threshold: float) -> dict[str, float | int]:
    by_query: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_query[str(row["query_id"])].append(row)
    values = []
    for candidates in by_query.values():
        gold = {str(row["candidate_id"]) for row in candidates if _label(row) == 1}
        predicted = {str(row["candidate_id"]) for row in candidates if float(row["probability"]) >= threshold}
        tp, fp, fn = len(gold & predicted), len(predicted - gold), len(gold - predicted)
        values.append((tp, fp, fn))
    tp = sum(item[0] for item in values); fp = sum(item[1] for item in values); fn = sum(item[2] for item in values)
    return {"query_count": len(values), "query_precision": tp / (tp + fp) if tp + fp else 0.0, "query_recall": tp / (tp + fn) if tp + fn else 0.0, "query_f1": _f1(tp, fp, fn)}


def choose_threshold(rows: list[dict[str, object]]) -> float:
    candidates = sorted({round(float(row["probability"]), 4) for row in rows})
    best = (0.5, -1.0)
    for threshold in candidates + [0.5]:
        score = float(pair_metrics(rows, threshold)["f1"])
        if score > best[1]:
            best = (threshold, score)
    return best[0]


def evaluate_model(name: str, train: list[dict[str, str]], validation: list[dict[str, str]], test: list[dict[str, str]], *, use_poi: bool, use_text: bool, rule: str | None = None, model_type: str = "logistic", model_output_dir: Path | None = None) -> dict[str, object]:
    model = None
    if rule:
        scorer = lambda row: rule_probability(row, rule)
        calibration = "validation_f1_threshold"
    elif model_type == "lightgbm":
        from .lightgbm_model import train_lightgbm
        model = train_lightgbm(train, validation, FEATURES, use_poi=use_poi, use_text=use_text)
        scorer = lambda row: float(model.predict_proba([vector(row, use_poi=use_poi, use_text=use_text)])[0][1])
        calibration = "lightgbm_raw"
    else:
        model = LogisticModel(len(FEATURES))
        model.fit(train, use_poi=use_poi, use_text=use_text, epochs=160)
        scorer = lambda row: model.predict(row, use_poi=use_poi, use_text=use_text)
        calibration = "logistic_raw"
    validation_scored = [{**row, "probability": scorer(row)} for row in validation]
    threshold = choose_threshold(validation_scored)
    test_scored = [{**row, "probability": scorer(row)} for row in test]
    if model_type == "lightgbm" and model is not None and model_output_dir is not None:
        model.booster_.save_model(str(model_output_dir / f"{name.replace(' ', '_').replace('/', '_').replace('\\\\', '_')}.txt"))
    return {"method": name, "model_type": model_type if not rule else "rule", "calibration": calibration, "threshold": threshold, **pair_metrics(test_scored, threshold), **query_metrics(test_scored, threshold)}


def run_experiments(data_dir: Path, output_dir: Path, *, mask_ratio: float = 0.6, mask_seed: int = 42) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    train = mask_rows(read_rows(data_dir / "pairs_train.csv"), mask_ratio, mask_seed)
    validation = mask_rows(read_rows(data_dir / "pairs_validation.csv"), mask_ratio, mask_seed)
    test = mask_rows(read_rows(data_dir / "pairs_test.csv"), mask_ratio, mask_seed)
    if not train or not validation or not test:
        raise ValueError("train, validation, and test CSVs must all contain rows")
    for split_name, rows in (("train", train), ("validation", validation), ("test", test)):
        labels = {_label(row) for row in rows}
        if labels != {0, 1}:
            raise ValueError(f"{split_name} must contain both classes; found {sorted(labels)}")
    results = [
        evaluate_model("主字段精确匹配", train, validation, test, use_poi=False, use_text=True, rule="exact"),
        evaluate_model("TF-IDF-like Cosine", train, validation, test, use_poi=False, use_text=True, rule="tfidf_like"),
        evaluate_model("Text/Structure Rule", train, validation, test, use_poi=False, use_text=True, rule="text_structure"),
        evaluate_model("Logistic Text/Structure", train, validation, test, use_poi=False, use_text=True),
        evaluate_model("LightGBM Text/Structure", train, validation, test, use_poi=False, use_text=True, model_type="lightgbm", model_output_dir=output_dir),
        evaluate_model("LightGBM + POI", train, validation, test, use_poi=True, use_text=True, model_type="lightgbm", model_output_dir=output_dir),
        evaluate_model("Full Model", train, validation, test, use_poi=True, use_text=True, model_type="lightgbm", model_output_dir=output_dir),
    ]
    fields = sorted({key for result in results for key in result})
    with (output_dir / "main_comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(results)
    ablations = []
    for name, use_poi, use_text in [
        ("Full Model LightGBM", True, True),
        ("E1 remove admin", True, True),
        ("E2 remove POI", False, True),
        ("E3 text structure only", False, True),
        ("E4 structure-only", False, False),
    ]:
        ablations.append(evaluate_model(name, train, validation, test, use_poi=use_poi, use_text=use_text, model_type="lightgbm", model_output_dir=output_dir))
    fields = sorted({key for result in ablations for key in result})
    with (output_dir / "ablation.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(ablations)
    report = {"train_rows": len(train), "validation_rows": len(validation), "test_rows": len(test), "mask_ratio": mask_ratio, "mask_seed": mask_seed, "main_comparison": results, "ablation": ablations, "dependency_note": "LightGBM 4.x and standard-library logistic baselines."}
    (output_dir / "experiment_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
