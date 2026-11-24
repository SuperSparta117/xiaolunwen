from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CACHE_VERSION = "full-library-cache-v2"


def run_key(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def prepare_run(root: Path, *parts: object) -> Path:
    path = root / f"full_library_{run_key(CACHE_VERSION, *parts)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
