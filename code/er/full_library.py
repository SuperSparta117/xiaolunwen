from __future__ import annotations

import csv
import gc
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Mapping

import numpy as np

from .config import A_CANDIDATE_PATH, A_QUERY_PATH, MAPPING_PATH, POI_PATH
from .disk_cache import prepare_run, write_json_atomic
from .experiments import FEATURES, read_rows, vector
from .geo_asset import _area_equivalent, attach_geo, load_poi_asset
from .io import read_csv_sample, read_sql_sample, standardize_property, standardize_transaction
from .lightgbm_model import train_lightgbm

SCORE_FIELDS = ["query_id", "candidate_id", "label", "probability"]
QUERY_FIELDS = [
    "rho", "method", "query_id", "gold_candidate_ids", "predicted_candidate_ids",
    "prediction_count", "gold_count", "query_label_state",
]
SUMMARY_FIELDS = [
    "rho", "method", "model_type", "threshold_validation", "query_count",
    "candidate_count_per_query", "TP", "FP", "FN", "TN", "precision", "recall",
    "f1", "positive_query_count", "query_macro_precision", "query_macro_recall",
    "query_macro_f1", "any_hit_rate", "positive_false_reject_rate",
    "evaluation_label_caveat",
]
HISTOGRAM_BINS = 20_000


def entity_is_masked(entity_id: str, seed: int, ratio: float) -> bool:
    return random.Random(f"{seed}:{entity_id}").random() < ratio


def _distance(q: Mapping[str, object], candidate: Mapping[str, object]) -> float | None:
    if not q.get("coords_trust") or not candidate.get("coords_trust"):
        return None
    try:
        lng1, lat1 = float(q["lng"]), float(q["lat"])
        lng2, lat2 = float(candidate["lng"]), float(candidate["lat"])
    except (KeyError, TypeError, ValueError):
        return None
    radians = math.pi / 180
    dlat = (lat2 - lat1) * radians
    dlng = (lng2 - lng1) * radians
    haversine = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * radians) * math.cos(lat2 * radians) * math.sin(dlng / 2) ** 2
    )
    return 6_371_000 * 2 * math.asin(math.sqrt(haversine))


def record_features(
    query: Mapping[str, object],
    candidate: Mapping[str, object],
    *,
    rho: float,
    seed: int,
    use_poi: bool,
    use_admin: bool,
    use_text: bool = True,
) -> dict[str, float]:
    from .normalize import normalize_address, normalize_name, similarity, street_key

    mask_name = entity_is_masked(str(query.get("id", "")), seed, rho) or entity_is_masked(
        str(candidate.get("id", "")), seed, rho
    )
    query_name = "" if mask_name or not use_text else normalize_name(query.get("name"))
    candidate_name = "" if mask_name or not use_text else normalize_name(candidate.get("name"))
    query_address = normalize_address(query.get("address"))
    candidate_address = normalize_address(candidate.get("address"))
    query_street = street_key(query.get("street"))
    candidate_street = street_key(candidate.get("street"))
    name_similarity = similarity(query_name, candidate_name) if query_name and candidate_name else 0.0
    name_exact = int(bool(query_name and query_name == candidate_name))
    distance = _distance(query, candidate) if use_poi else None
    return {
        "name_exact": name_exact,
        "name_similarity": name_similarity,
        "address_similarity": similarity(query_address, candidate_address),
        "area_match": int(_area_equivalent(query.get("area"), candidate.get("area"))) if use_admin else 0,
        "street_match": int(bool(query_street and candidate_street and query_street == candidate_street)) if use_admin else 0,
        "coords_available": int(distance is not None),
        "coords_trust_both": int(bool(use_poi and query.get("coords_trust") and candidate.get("coords_trust"))),
        "poi_distance_m": distance if distance is not None else 0.0,
        "poi_distance_lt_100m": int(distance is not None and distance < 100),
        "poi_distance_100_300m": int(distance is not None and 100 <= distance < 300),
        "poi_distance_300_1000m": int(distance is not None and 300 <= distance < 1000),
        "poi_distance_gt_1000m": int(distance is not None and distance >= 1000),
        "poi_district_match": int(bool(use_poi) and _area_equivalent(query.get("poi_district"), candidate.get("poi_district"))),
        "type_match": int(bool(query.get("type") and query.get("type") == candidate.get("type"))),
        "admin_center_distance_m": 0.0,
    }


def _feature_vector(query, candidate, *, rho: float, seed: int, use_poi: bool, use_admin: bool, use_text: bool):
    features = record_features(
        query, candidate, rho=rho, seed=seed, use_poi=use_poi, use_admin=use_admin, use_text=use_text
    )
    return vector({key: str(value) for key, value in features.items()})


def _model_probability(model, feature_matrix: list[list[float]]) -> list[float]:
    if model is None:
        return [0.0] * len(feature_matrix)
    probabilities = model.predict_proba(np.asarray(feature_matrix, dtype=float))
    return [float(row[1]) for row in probabilities]


def threshold_from_histogram(positive: np.ndarray, negative: np.ndarray) -> float:
    total_positive = int(positive.sum())
    if total_positive == 0:
        return 1.0
    cumulative_positive = np.cumsum(positive[::-1])
    cumulative_negative = np.cumsum(negative[::-1])
    denominator = 2 * cumulative_positive + cumulative_negative + total_positive - cumulative_positive
    f1 = np.divide(
        2 * cumulative_positive,
        denominator,
        out=np.zeros_like(cumulative_positive, dtype=float),
        where=denominator > 0,
    )
    index = int(np.argmax(f1))
    return max(0.0, 1.0 - (index + 1) / len(positive))


def _score_full_candidate_library(
    score_path: Path,
    query_id: str,
    query: Mapping[str, object],
    candidates: list[Mapping[str, object]],
    gold_ids: set[str],
    model,
    *,
    rho: float,
    seed: int,
    use_poi: bool,
    use_admin: bool,
    use_text: bool,
    rule: str | None,
    batch_size: int,
) -> None:
    mode = "w" if not score_path.exists() or score_path.stat().st_size == 0 else "a"
    with score_path.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORE_FIELDS)
        if mode == "w":
            writer.writeheader()
        for offset in range(0, len(candidates), batch_size):
            candidate_batch = candidates[offset:offset + batch_size]
            feature_batch = [
                _feature_vector(
                    query, candidate, rho=rho, seed=seed, use_poi=use_poi,
                    use_admin=use_admin, use_text=use_text,
                )
                for candidate in candidate_batch
            ]
            if rule == "exact":
                scores = [float(row[0]) for row in feature_batch]
            elif rule == "tfidf":
                scores = [float(row[1]) for row in feature_batch]
            else:
                scores = _model_probability(model, feature_batch)
            for candidate, score in zip(candidate_batch, scores):
                candidate_id = str(candidate["id"])
                writer.writerow({
                    "query_id": query_id,
                    "candidate_id": candidate_id,
                    "label": int(candidate_id in gold_ids),
                    "probability": float(score),
                })
            del candidate_batch, feature_batch, scores
            handle.flush()


def _aggregate_test_scores(
    score_path: Path,
    threshold: float,
    query_output_path: Path,
    rho: float,
    method: str,
    test_ids: list[str],
    gold_by_query: dict[str, set[str]],
    candidate_count: int,
) -> dict[str, object]:
    tp = fp = fn = tn = positive_queries = any_hit = false_reject = 0
    macro_precision = macro_recall = macro_f1 = 0.0
    current_query = None
    predicted: set[str] = set()

    def flush(writer, query_id: str | None) -> None:
        nonlocal tp, fp, fn, tn, positive_queries, any_hit, false_reject
        nonlocal macro_precision, macro_recall, macro_f1
        if query_id is None:
            return
        gold = gold_by_query.get(query_id, set())
        intersection = gold & predicted
        local_tp = len(intersection)
        local_fp = len(predicted - gold)
        local_fn = len(gold - predicted)
        tp += local_tp
        fp += local_fp
        fn += local_fn
        tn += max(0, candidate_count - len(gold) - local_fp)
        if gold:
            positive_queries += 1
            precision = local_tp / len(predicted) if predicted else 0.0
            recall = local_tp / len(gold)
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            macro_precision += precision
            macro_recall += recall
            macro_f1 += f1
            any_hit += bool(intersection)
            false_reject += not bool(predicted)
        writer.writerow({
            "rho": rho,
            "method": method,
            "query_id": query_id,
            "gold_candidate_ids": json.dumps(sorted(gold), ensure_ascii=False),
            "predicted_candidate_ids": json.dumps(sorted(predicted), ensure_ascii=False),
            "prediction_count": len(predicted),
            "gold_count": len(gold),
            "query_label_state": "complete_positive_set_from_existing_mapping",
        })

    test_set = set(test_ids)
    with query_output_path.open("w", encoding="utf-8", newline="") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=QUERY_FIELDS)
        writer.writeheader()
        with score_path.open("r", encoding="utf-8-sig", newline="") as score_handle:
            for row in csv.DictReader(score_handle):
                query_id = row["query_id"]
                if query_id not in test_set:
                    continue
                if query_id != current_query:
                    flush(writer, current_query)
                    current_query = query_id
                    predicted = set()
                if float(row["probability"]) >= threshold:
                    predicted.add(row["candidate_id"])
            flush(writer, current_query)

    denominator = max(1, positive_queries)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "rho": rho,
        "method": method,
        "model_type": "rule" if method in {"主字段精确匹配", "TF-IDF-like Cosine"} else "lightgbm",
        "threshold_validation": threshold,
        "query_count": len(test_ids),
        "candidate_count_per_query": candidate_count,
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "positive_query_count": positive_queries,
        "query_macro_precision": macro_precision / denominator,
        "query_macro_recall": macro_recall / denominator,
        "query_macro_f1": macro_f1 / denominator,
        "any_hit_rate": any_hit / denominator,
        "positive_false_reject_rate": false_reject / denominator,
        "evaluation_label_caveat": "conditional_on_current_mapping_completeness",
    }


def run_full_library(
    data_dir: Path,
    cache_root: Path,
    output_dir: Path,
    *,
    ratios: tuple[float, ...] = (0.0, 0.3, 0.6, 1.0),
    seed: int = 42,
    split_seed: int = 13,
    score_batch_size: int = 256,
) -> dict[str, object]:
    """Run exhaustive candidate scoring with resumable on-disk score caches."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    query_rows = read_sql_sample(A_QUERY_PATH, 10_000_000)
    candidate_rows = read_csv_sample(A_CANDIDATE_PATH, 10_000_000)
    poi_index, poi_manifest = load_poi_asset(POI_PATH)
    queries = {
        str(row["village_id"]): attach_geo(standardize_property(row), "property", poi_index)
        for row in query_rows
    }
    candidates = [attach_geo(standardize_transaction(row), "transaction", poi_index) for row in candidate_rows]
    with MAPPING_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        mapping = list(csv.DictReader(handle))
    gold_by_query: dict[str, set[str]] = defaultdict(set)
    for row in mapping:
        query_id = str(row.get("sql_village_id", "")).strip()
        candidate_id = str(row.get("csv_yuyue_id", "")).strip()
        if query_id in queries and candidate_id:
            gold_by_query[query_id].add(candidate_id)

    split_path = data_dir.parent / "split_manifest_full" / "split_manifest.json"
    split_manifest = json.loads(split_path.read_text(encoding="utf-8"))
    split = split_manifest["seed_manifests"][str(split_seed)]["query_splits"]
    validation_ids = sorted(
        query_id for query_id, part in split.items()
        if part == "validation" and query_id in gold_by_query
    )
    test_ids = sorted(
        query_id for query_id, part in split.items()
        if part == "test" and query_id in gold_by_query
    )
    training = read_rows(data_dir / "pairs_train.csv")
    validation = read_rows(data_dir / "pairs_validation.csv")

    # 断点续跑的“完成标记”必须绑定输入数据，否则换 --data-dir 后会静默复用旧分数。
    fingerprint = hashlib.sha256()
    for name in ("pairs_train.csv", "pairs_validation.csv", "pairs_test.csv", "feature_manifest.json"):
        path = data_dir / name
        fingerprint.update(name.encode("utf-8"))
        fingerprint.update(path.read_bytes() if path.exists() else b"<missing>")
    data_fingerprint = fingerprint.hexdigest()
    methods = [
        ("主字段精确匹配", False, False, True, "exact"),
        ("TF-IDF-like Cosine", False, False, True, "tfidf"),
        ("LightGBM Text/Structure", False, True, True, None),
        ("LightGBM + POI", True, True, True, None),
        ("Full Model", True, True, True, None),
        ("E2 remove POI", False, True, True, None),
        ("E4b 全特征关闭", False, False, False, None),
    ]

    summary_path = output_dir / "full_candidate_comparison.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as summary_handle:
        summary_writer = csv.DictWriter(summary_handle, fieldnames=SUMMARY_FIELDS)
        summary_writer.writeheader()
        for rho in ratios:
            masked_train = []
            masked_validation = []
            for row in training:
                masked = entity_is_masked(str(row["query_id"]), seed, rho) or entity_is_masked(
                    str(row["candidate_id"]), seed, rho
                )
                masked_train.append({**row, "name_exact": "0" if masked else row["name_exact"], "name_similarity": "0" if masked else row["name_similarity"]})
            for row in validation:
                masked = entity_is_masked(str(row["query_id"]), seed, rho) or entity_is_masked(
                    str(row["candidate_id"]), seed, rho
                )
                masked_validation.append({**row, "name_exact": "0" if masked else row["name_exact"], "name_similarity": "0" if masked else row["name_similarity"]})

            for method, use_poi, use_admin, use_text, rule in methods:
                run_dir = prepare_run(cache_root, rho, method, seed, split_seed)
                model_train = masked_train
                model_validation = masked_validation
                if not use_text:
                    model_train = [{**row, "name_exact": "0", "name_similarity": "0"} for row in masked_train]
                    model_validation = [{**row, "name_exact": "0", "name_similarity": "0"} for row in masked_validation]
                model = train_lightgbm(
                    model_train, model_validation, FEATURES, use_poi=use_poi, use_text=use_text, seed=seed
                ) if rule is None else None

                for split_name, query_ids in (("validation", validation_ids), ("test", test_ids)):
                    score_path = run_dir / f"{split_name}_scores.csv"
                    completed_path = run_dir / f"{split_name}_completed.json"
                    if completed_path.exists():
                        try:
                            marker = json.loads(completed_path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            marker = {}
                        if marker.get("data_fingerprint") == data_fingerprint:
                            continue
                        # 输入数据已变（如换了 pairs_*.csv），旧分数作废
                        completed_path.unlink()
                    if score_path.exists():
                        score_path.unlink()
                    for query_id in query_ids:
                        _score_full_candidate_library(
                            score_path,
                            query_id,
                            queries[query_id],
                            candidates,
                            gold_by_query[query_id],
                            model,
                            rho=rho,
                            seed=seed,
                            use_poi=use_poi,
                            use_admin=use_admin,
                            use_text=use_text,
                            rule=rule,
                            batch_size=score_batch_size,
                        )
                    write_json_atomic(
                        completed_path,
                        {
                            "query_count": len(query_ids),
                            "rows": len(query_ids) * len(candidates),
                            "sha256": hashlib.sha256(score_path.read_bytes()).hexdigest(),
                            "data_fingerprint": data_fingerprint,
                        },
                    )

                positive_histogram = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
                negative_histogram = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
                with (run_dir / "validation_scores.csv").open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        probability = max(0.0, min(1.0, float(row["probability"])))
                        index = min(HISTOGRAM_BINS - 1, int(probability * HISTOGRAM_BINS))
                        (positive_histogram if row["label"] == "1" else negative_histogram)[index] += 1
                threshold = threshold_from_histogram(positive_histogram, negative_histogram)
                safe_method = method.replace(" ", "_").replace("/", "_")
                result = _aggregate_test_scores(
                    run_dir / "test_scores.csv",
                    threshold,
                    output_dir / f"rho_{rho:g}_{safe_method}_query_sets.csv",
                    rho,
                    method,
                    test_ids,
                    gold_by_query,
                    len(candidates),
                )
                summary_writer.writerow(result)
                summary_handle.flush()
                del model, model_train, model_validation, positive_histogram, negative_histogram
                gc.collect()

    manifest = {
        "task_id": "A",
        "candidate_evaluation": "full candidate library, one-query-at-a-time, disk cached",
        "query_count_total": len(queries),
        "candidate_count": len(candidates),
        "mapped_positive_query_count": len(gold_by_query),
        "gold_pair_count": sum(map(len, gold_by_query.values())),
        "unknown_query_count": len(queries) - len(gold_by_query),
        "validation_query_count": len(validation_ids),
        "test_query_count": len(test_ids),
        "ratios": list(ratios),
        "seed": seed,
        "split_seed": split_seed,
        "score_batch_size": score_batch_size,
        "data_dir": str(data_dir),
        "data_fingerprint": data_fingerprint,
        "poi_manifest": poi_manifest,
        "label_caveat": "Unknown queries excluded; unmapped candidates conditionally negative under existing mapping completeness assumption.",
    }
    write_json_atomic(output_dir / "full_candidate_manifest.json", manifest)
    return manifest
