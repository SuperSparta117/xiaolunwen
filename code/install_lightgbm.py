from __future__ import annotations

import argparse
import json
import sys

parser = argparse.ArgumentParser(description="诊断当前 LightGBM 安装状态")
parser.add_argument("--install", action="store_true", help="使用当前 Python 环境安装官方 PyPI lightgbm 包")
args = parser.parse_args()

try:
    import lightgbm
except ImportError:
    if not args.install:
        print(json.dumps({"available": False, "install_command": f'"{sys.executable}" -m pip install lightgbm'}, ensure_ascii=False))
        raise SystemExit(2)
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "lightgbm"], check=True)
    import lightgbm
print(json.dumps({"available": True, "version": lightgbm.__version__}, ensure_ascii=False))
