# -*- coding: utf-8 -*-
"""下载 BGE-M3 与中文 RoBERTa 权重（使用 hf-mirror 加速）。"""
from __future__ import annotations

import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from huggingface_hub import snapshot_download  # noqa: E402

TARGETS = [
    ("BAAI/bge-m3", ".audit_work/models/bge-m3"),
    ("hfl/chinese-roberta-wwm-ext", ".audit_work/models/chinese-roberta-wwm-ext"),
]

for repo_id, local_dir in TARGETS:
    print(f"downloading {repo_id} -> {local_dir}", flush=True)
    try:
        path = snapshot_download(
            repo_id=repo_id,
            local_dir=local_dir,
            ignore_patterns=["*.onnx", "onnx/*", "*.h5", "*.msgpack", "*.tflite", "*.safetensors.index.json"],
        )
        print("ok:", path, flush=True)
    except Exception as exc:
        print("failed:", repo_id, exc, flush=True)
