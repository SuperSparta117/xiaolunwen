# -*- coding: utf-8 -*-
"""严格版实验：Ditto 输入中加入 POI / 行政地理特征后重训。

与 Ditto 基线（仅文本字段）对比的唯一差别：
- 每个 pair 追加一段 GEO 证据 token（区县/街道匹配、POI 距离分档、POI 区县匹配、
  坐标可用/可信、行政中心距离分档、行政中心一致、类型匹配）；
- 这些证据来自与 Full Model 完全相同的外源资产与特征定义，不额外引入信息。

训练：每个 rho 下用同一套遮蔽训练对重训；
评估：与全库协议一致（validation 定阈值，test 汇报）。
结果写到 code/ditto_geo_results/，不写入 README。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from er.full_data import load_full_library_data  # noqa: E402
from er.full_library import (  # noqa: E402
    HISTOGRAM_BINS,
    SUMMARY_FIELDS,
    _aggregate_test_scores,
    entity_is_masked,
    threshold_from_histogram,
)
from er.geo import as_point, haversine_m  # noqa: E402
from er.geo_asset import _area_equivalent  # noqa: E402
from er.normalize import normalize_address, normalize_name, street_key  # noqa: E402

csv.field_size_limit(2 ** 31 - 1)
MODEL_DIR = ".audit_work/models/chinese-roberta-wwm-ext"
RATIOS = (0.0, 0.3, 0.6, 1.0)


def admin_bin(distance):
    if distance is None:
        return 9
    if distance < 500:
        return 0
    if distance < 2000:
        return 1
    if distance < 5000:
        return 2
    if distance < 10000:
        return 3
    return 4


def poi_bin(distance):
    if distance is None:
        return 9
    if distance < 100:
        return 0
    if distance < 300:
        return 1
    if distance < 1000:
        return 2
    return 3


def geo_codes(query: dict, candidate: dict) -> tuple[int, ...]:
    q_street = street_key(query.get("street"))
    b_street = street_key(candidate.get("street"))
    q_point = as_point(query) if query.get("coords_trust") else None
    b_point = as_point(candidate) if candidate.get("coords_trust") else None
    distance = haversine_m(q_point, b_point)
    q_admin = (query.get("admin_lng"), query.get("admin_lat")) if query.get("admin_resolved") else None
    b_admin = (candidate.get("admin_lng"), candidate.get("admin_lat")) if candidate.get("admin_resolved") else None
    admin_distance = haversine_m(q_admin, b_admin)
    admin_same = int(bool(query.get("admin_unit_id") and candidate.get("admin_unit_id") and query.get("admin_unit_id") == candidate.get("admin_unit_id")))
    return (
        int(_area_equivalent(query.get("area"), candidate.get("area"))),
        int(bool(q_street and b_street and q_street == b_street)),
        int(distance is not None),
        int(bool(query.get("coords_trust") and candidate.get("coords_trust"))),
        poi_bin(distance),
        int(_area_equivalent(query.get("poi_district"), candidate.get("poi_district"))),
        int(bool(query.get("type") and query.get("type") == candidate.get("type"))),
        admin_bin(admin_distance),
        admin_same,
    )


def row_geo_codes(row: dict) -> tuple[int, ...]:
    def to_float(value):
        if value in ("", "None", None):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    distance = to_float(row.get("poi_distance_m"))
    admin_distance = to_float(row.get("admin_center_distance_m"))
    return (
        int(float(row.get("area_match") or 0)),
        int(float(row.get("street_match") or 0)),
        int(float(row.get("coords_available") or 0)),
        int(float(row.get("coords_trust_both") or 0)),
        poi_bin(distance),
        int(float(row.get("poi_district_match") or 0)),
        int(float(row.get("type_match") or 0)),
        admin_bin(admin_distance),
        int(float(row.get("admin_center_same") or 0)),
    )


def geo_text(codes: tuple[int, ...]) -> str:
    area, street, coord, trust, pbin, pdist, type_match, abin, asame = codes
    return f"GEO area {area} street {street} coord {coord} trust {trust} pdist {pbin} pdistmatch {pdist} type {type_match} adist {abin} asame {asame}"


def side_text(record: dict, masked: bool) -> str:
    fields = []
    if not masked and normalize_name(record.get("name")):
        fields.append(f"COL name VAL {normalize_name(record.get('name'))}")
    if normalize_address(record.get("address")):
        fields.append(f"COL address VAL {normalize_address(record.get('address'))}")
    if normalize_name(record.get("area")):
        fields.append(f"COL area VAL {normalize_name(record.get('area'))}")
    if street_key(record.get("street")):
        fields.append(f"COL street VAL {street_key(record.get('street'))}")
    if normalize_name(record.get("type")):
        fields.append(f"COL type VAL {normalize_name(record.get('type'))}")
    return " ".join(fields) if fields else "[EMPTY]"


class DittoGeoModel:
    def __init__(self, max_length: int = 128, epochs: int = 3, batch_size: int = 32, lr: float = 1e-4) -> None:
        self.max_length = max_length
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        self.model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR, num_labels=1).cuda()

    def _encode_pair(self, left: str, right: str, geo: str) -> list[int]:
        text = f"{left} [SEP] {right} [SEP] {geo}"
        return self.tokenizer(text, add_special_tokens=True, truncation=True, max_length=self.max_length)["input_ids"]

    def _batch(self, rows: list[list[int]]):
        max_length = max(len(row) for row in rows)
        input_ids = [row + [self.tokenizer.pad_token_id] * (max_length - len(row)) for row in rows]
        attention = [[1] * len(row) + [0] * (max_length - len(row)) for row in rows]
        return (torch.tensor(input_ids, dtype=torch.long, device="cuda"),
                torch.tensor(attention, dtype=torch.long, device="cuda"))

    def fit(self, training_rows: list[tuple[list[int], float]]) -> None:
        from transformers.optimization import Adafactor

        optimizer = Adafactor(self.model.parameters(), lr=self.lr, scale_parameter=False, relative_step=False)
        scaler = torch.amp.GradScaler("cuda")
        loss_fn = torch.nn.BCEWithLogitsLoss()
        generator = np.random.RandomState(42)
        self.model.train()
        for epoch in range(self.epochs):
            order = generator.permutation(len(training_rows))
            total_loss = 0.0
            for start in range(0, len(order), self.batch_size):
                batch = [training_rows[i] for i in order[start:start + self.batch_size]]
                input_ids, attention = self._batch([row[0] for row in batch])
                labels = torch.tensor([row[1] for row in batch], dtype=torch.float32, device="cuda")
                optimizer.zero_grad()
                with torch.autocast("cuda", dtype=torch.float16):
                    logits = self.model(input_ids=input_ids, attention_mask=attention).logits.squeeze(-1)
                    loss = loss_fn(logits, labels)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                total_loss += float(loss.item()) * len(batch)
            print(f"  epoch {epoch + 1}/{self.epochs} loss={total_loss / max(1, len(training_rows)):.4f}", flush=True)
        self.model.eval()
        self.model.half()

    def score_query(self, query: dict, masked_query: bool, candidates: list[dict], masked_candidates: list[bool],
                    geo_codes_row: np.ndarray) -> np.ndarray:
        left = side_text(query, masked_query)
        right_texts = [side_text(candidate, masked_candidates[index]) for index, candidate in enumerate(candidates)]
        scores = np.zeros(len(candidates), dtype=np.float64)
        with torch.inference_mode():
            for start in range(0, len(candidates), 64):
                chunk = range(start, min(start + 64, len(candidates)))
                rows = [self._encode_pair(left, right_texts[index], geo_text(tuple(int(v) for v in geo_codes_row[index])))
                        for index in chunk]
                input_ids, attention = self._batch(rows)
                logits = self.model(input_ids=input_ids, attention_mask=attention).logits.squeeze(-1)
                scores[start:start + len(rows)] = torch.sigmoid(logits.float()).cpu().numpy()
        return scores


def build_geo_matrix(ids, queries, candidates) -> np.ndarray:
    matrix = np.zeros((len(ids), len(candidates), 9), dtype=np.int8)
    for row, query_id in enumerate(ids):
        query = queries[query_id]
        for column, candidate in enumerate(candidates):
            matrix[row, column] = geo_codes(query, candidate)
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("code/ditto_geo_results"))
    parser.add_argument("--ratios", default="0,0.3,0.6,1.0")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--skip-features", action="store_true")
    parser.add_argument("--limit-queries", type=int, default=0)
    args = parser.parse_args()
    ratios = tuple(float(value) for value in args.ratios.split(","))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data = load_full_library_data(ROOT / "code/training_assets_full_v5", split_seed=13)
    queries = data["queries"]
    candidates = data["candidates"]
    candidate_ids = [str(candidate["id"]) for candidate in candidates]
    candidate_by_id = {cid: candidate for cid, candidate in zip(candidate_ids, candidates)}
    validation_ids = data["validation_ids"]
    test_ids = data["test_ids"]
    if args.limit_queries:
        validation_ids = validation_ids[: args.limit_queries]
        test_ids = test_ids[: args.limit_queries]
    gold = data["gold_by_query"]

    with (ROOT / "code/training_assets_full_v5/pairs_train.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        train_rows = list(csv.DictReader(handle))

    feature_dir = args.output_dir / "geo_features"
    feature_dir.mkdir(parents=True, exist_ok=True)
    matrices = {}
    for name, ids in (("validation", validation_ids), ("test", test_ids)):
        path = feature_dir / f"{name}_geo_codes.npy"
        if path.exists() and not args.skip_features:
            matrices[name] = np.load(path)
            print(f"loaded {name} geo codes: {matrices[name].shape}", flush=True)
            continue
        print(f"computing {name} geo codes ({len(ids)} x {len(candidates)}) ...", flush=True)
        matrices[name] = build_geo_matrix(ids, queries, candidates)
        np.save(path, matrices[name])
        print(f"saved {path}", flush=True)

    comparison_path = args.output_dir / "ditto_geo_comparison.csv"
    rows: list[dict[str, object]] = []
    if comparison_path.exists():
        with comparison_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

    for rho in ratios:
        if any(row["method"] == "Ditto + GEO" and abs(float(row["rho"]) - rho) < 1e-9 for row in rows):
            print(f"skip rho={rho}", flush=True)
            continue
        masked_queries = {qid: entity_is_masked(qid, 42, rho) for qid in queries}
        masked_candidates_map = {cid: entity_is_masked(cid, 42, rho) for cid in candidate_ids}
        masked_candidates = [masked_candidates_map[cid] for cid in candidate_ids]

        model = DittoGeoModel(epochs=args.epochs)
        encoded = []
        for row in train_rows:
            query = queries.get(str(row["query_id"]))
            candidate = candidate_by_id.get(str(row["candidate_id"]))
            if query is None or candidate is None:
                continue
            text = f"{side_text(query, masked_queries[str(row['query_id'])])} [SEP] {side_text(candidate, masked_candidates_map[str(row['candidate_id'])])} [SEP] {geo_text(row_geo_codes(row))}"
            encoded.append((model.tokenizer(text, add_special_tokens=True, truncation=True, max_length=model.max_length)["input_ids"], float(row["label"])))
        print(f"rho={rho}: training {len(encoded)} pairs", flush=True)
        model.fit(encoded)

        for split_name, ids in (("validation", validation_ids), ("test", test_ids)):
            scores = np.zeros((len(ids), len(candidates)), dtype=np.float32)
            geo_matrix = matrices[split_name]
            for row, query_id in enumerate(ids):
                scores[row] = model.score_query(queries[query_id], masked_queries[query_id], candidates,
                                                masked_candidates, geo_matrix[row])
                if (row + 1) % 100 == 0:
                    print(f"  {split_name} {row + 1}/{len(ids)}", flush=True)
            if split_name == "validation":
                validation_scores = scores
            else:
                test_scores = scores

        def thresholds_and_labels(scores, ids):
            labels = np.zeros(scores.shape, dtype=bool)
            for row, query_id in enumerate(ids):
                labels[row] = [cid in gold.get(query_id, set()) for cid in candidate_ids]
            positive = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
            negative = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
            bins = np.minimum(HISTOGRAM_BINS - 1, (scores * HISTOGRAM_BINS).astype(np.int64))
            positive += np.bincount(bins[labels], minlength=HISTOGRAM_BINS)
            negative += np.bincount(bins[~labels], minlength=HISTOGRAM_BINS)
            return threshold_from_histogram(positive, negative)

        threshold = thresholds_and_labels(validation_scores, validation_ids)
        score_path = args.output_dir / f"ditto_geo_rho_{rho:g}_test_scores.csv"
        with score_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["query_id", "candidate_id", "label", "probability"])
            writer.writeheader()
            for row, query_id in enumerate(test_ids):
                for column, candidate_id in enumerate(candidate_ids):
                    writer.writerow({
                        "query_id": query_id,
                        "candidate_id": candidate_id,
                        "label": int(candidate_id in gold.get(query_id, set())),
                        "probability": float(test_scores[row, column]),
                    })
        query_output = args.output_dir / f"rho_{rho:g}_Ditto_GEO_query_sets.csv"
        result = _aggregate_test_scores(score_path, threshold, query_output, rho, "Ditto + GEO", ids, gold, len(candidates))
        rows.append(result)
        with comparison_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"done rho={rho}: F1={float(result['f1']) * 100:.2f} P={float(result['precision']) * 100:.2f} "
              f"R={float(result['recall']) * 100:.2f} tau={threshold:.4f}", flush=True)


if __name__ == "__main__":
    main()
