from __future__ import annotations

from typing import Any


class NativeLightGBMModel:
    def __init__(self, booster: Any):
        self.booster_ = booster

    def predict_proba(self, rows: list[list[float]]) -> list[list[float]]:
        probabilities = self.booster_.predict(rows)
        return [[1.0 - float(probability), float(probability)] for probability in probabilities]


def train_lightgbm(
    train_rows: list[dict[str, str]],
    validation_rows: list[dict[str, str]],
    feature_names: list[str],
    *,
    use_poi: bool = True,
    use_text: bool = True,
    use_admin_center: bool = True,
    seed: int = 42,
) -> NativeLightGBMModel:
    """Train LightGBM through its native API, without requiring scikit-learn."""
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise RuntimeError(
            "LightGBM is not installed. Install the official PyPI package with "
            "`py -m pip install lightgbm`, then rerun the experiment."
        ) from exc

    from .experiments import _float, vector

    import numpy as np
    x_train = np.asarray([vector(row, use_poi=use_poi, use_text=use_text, use_admin_center=use_admin_center) for row in train_rows], dtype=float)
    y_train = np.asarray([_float(row.get("label")) for row in train_rows], dtype=float)
    x_valid = np.asarray([vector(row, use_poi=use_poi, use_text=use_text, use_admin_center=use_admin_center) for row in validation_rows], dtype=float)
    y_valid = np.asarray([_float(row.get("label")) for row in validation_rows], dtype=float)
    if x_train.ndim != 2 or x_valid.ndim != 2:
        raise ValueError(f"LightGBM matrix shape invalid: train={x_train.shape}, validation={x_valid.shape}")
    train_set = lgb.Dataset(x_train, label=y_train, feature_name=feature_names, free_raw_data=False)
    valid_set = lgb.Dataset(x_valid, label=y_valid, feature_name=feature_names, reference=train_set, free_raw_data=False)
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.04,
        "num_leaves": 31,
        "min_child_samples": 20,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "seed": seed,
        "feature_fraction_seed": seed,
        "bagging_seed": seed,
        "data_random_seed": seed,
        "verbosity": -1,
        "num_threads": 1,
    }
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=300,
        valid_sets=[valid_set],
        valid_names=["validation"],
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )
    return NativeLightGBMModel(booster)
