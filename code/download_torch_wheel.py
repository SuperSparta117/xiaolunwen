# -*- coding: utf-8 -*-
"""直接下载 torch CUDA wheel（绕过代理），断点续传 + 多镜像重试 + 哈希校验。"""
from __future__ import annotations

import hashlib
import sys
import time
import urllib.request
from pathlib import Path

MB = 1024 * 1024
EXPECTED_SIZE = 2_510_680_879
EXPECTED_SHA256 = "3c3f705fb125edbd77f9579fa11a138c56af8968a10fc95834cdd9fdf4f1f1a6"
TARGET = Path(".audit_work/wheels/torch-2.5.1+cu124-cp312-cp312-win_amd64.whl")
URLS = [
    "https://mirror.sjtu.edu.cn/pytorch-wheels/cu124/torch-2.5.1%2Bcu124-cp312-cp312-win_amd64.whl",
    "https://download.pytorch.org/whl/cu124/torch-2.5.1%2Bcu124-cp312-cp312-win_amd64.whl",
    "https://mirrors.aliyun.com/pytorch-wheels/cu124/torch-2.5.1%2Bcu124-cp312-cp312-win_amd64.whl",
]


def fetch(url: str, offset: int, timeout: int = 60) -> int:
    """从 offset 续传，返回本次写入字节数；异常或提前断开时抛错/返回增量。"""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    written = 0
    started = time.time()
    deadline = started + 150
    last_report = started
    with opener.open(request, timeout=timeout) as response:
        status = response.status
        if offset and status != 206:
            raise RuntimeError(f"server did not honor range (status={status})")
        mode = "ab" if offset else "wb"
        with TARGET.open(mode) as handle:
            while True:
                if time.time() > deadline:
                    print("attempt time box reached, rotating", flush=True)
                    break
                chunk = response.read(4 * MB)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                if time.time() - last_report > 15:
                    last_report = time.time()
                    total = offset + written
                    elapsed = max(1e-9, last_report - started)
                    print(f"{total / MB:8.1f} MB / {EXPECTED_SIZE / MB:.0f} MB "
                          f"({total / EXPECTED_SIZE * 100:.1f}%) {written / MB / elapsed:.2f} MB/s", flush=True)
    print(f"attempt wrote {written / MB:.1f} MB in {(time.time() - started) / 60:.1f} min", flush=True)
    return written


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * MB), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    attempts = 0
    while attempts < 40:
        size = TARGET.stat().st_size if TARGET.exists() else 0
        if size >= EXPECTED_SIZE:
            break
        url = URLS[attempts % len(URLS)]
        attempts += 1
        print(f"attempt {attempts} from {size / MB:.1f} MB: {url}", flush=True)
        before = size
        try:
            fetch(url, size)
        except Exception as exc:
            print("failed:", exc, flush=True)
            time.sleep(1)
            continue
        after = TARGET.stat().st_size if TARGET.exists() else 0
        if after <= before:
            print("no progress, next mirror", flush=True)
            time.sleep(1)
    size = TARGET.stat().st_size if TARGET.exists() else 0
    print(f"final size: {size / MB:.1f} MB", flush=True)
    if size < EXPECTED_SIZE:
        print("download incomplete", flush=True)
        sys.exit(1)
    actual = sha256(TARGET)
    print("sha256:", actual, flush=True)
    print("match:", actual == EXPECTED_SHA256, flush=True)
    if actual != EXPECTED_SHA256:
        print("HASH MISMATCH, deleting file", flush=True)
        TARGET.unlink(missing_ok=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
