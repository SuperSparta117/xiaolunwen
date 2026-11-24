from __future__ import annotations

from pathlib import Path

from .candidate import generate_candidates
from .config import A_CANDIDATE_PATH, A_QUERY_PATH, MAPPING_PATH, POI_PATH
from .features import pair_features
from .io import index_poi, load_poi_sample, read_csv_sample, read_sql_sample, standardize_property, standardize_transaction
from .model import baseline_score
from .output import predict_set


def run_sample_pipeline(sample_size: int = 12, output_dir: Path | None = None) -> dict[str, object]:
    query_raw = read_sql_sample(A_QUERY_PATH, sample_size)
    candidate_raw = read_csv_sample(A_CANDIDATE_PATH, sample_size * 4)
    poi = index_poi(load_poi_sample(POI_PATH, sample_size * 8), "物业处")
    queries = [standardize_property(row, poi.get(str(row.get("village_id", "")))) for row in query_raw]
    candidates = [standardize_transaction(row) for row in candidate_raw]
    result_rows: list[dict[str, object]] = []
    predicted: dict[str, list[dict[str, object]]] = {}
    for query in queries:
        pool = generate_candidates(query, candidates)
        scored = []
        for candidate in pool:
            features = pair_features(query, candidate)
            scored.append({"candidate_id": candidate["id"], "probability": round(baseline_score(features), 6), "features": features, "recall_sources": candidate["_recall_sources"]})
        predicted[str(query["id"])] = predict_set(scored, 0.72)
        result_rows.extend({"query_id": query["id"], **row} for row in scored)
    report = {"task": "A", "sample_size": len(queries), "candidate_rows": len(candidates), "pair_rows": len(result_rows), "predicted_sets": predicted, "mapping_path": str(MAPPING_PATH), "warning": "smoke-test baseline; unknown is not confirmed_empty"}
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "sample_report.json").write_text(__import__("json").dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
