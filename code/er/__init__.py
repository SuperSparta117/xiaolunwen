"""Minimal, auditable entity-resolution pipeline."""

from .candidate_pool import build_candidate_pool
from .config import TASK_A, TASK_B, TaskConfig
from .gold import build_evaluation_assets
from .mask_sweep import run_mask_sweep
from .split import build_split_manifest
from .geo_asset import build_geo_manifest, load_poi_asset
from .pipeline import run_sample_pipeline

__all__ = ["TASK_A", "TASK_B", "TaskConfig", "build_evaluation_assets", "build_candidate_pool", "run_mask_sweep", "build_split_manifest", "build_geo_manifest", "load_poi_asset", "run_sample_pipeline"]
