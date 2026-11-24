from __future__ import annotations

import re
import unicodedata

_MISSING = {"", "nan", "none", "null", "nat", "未填写", "无", "暂无"}
_STREET_SUFFIXES = ("街道办事处", "街道", "镇", "乡")


def clean(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"[\\s\\u3000]+", "", text)
    return "" if text in _MISSING else text


def normalize_name(value: object) -> str:
    text = clean(value)
    return re.sub(r"[，。、“”‘’'\"()（）【】\[\]{}·,./\\-_]", "", text)


def normalize_address(value: object) -> str:
    text = normalize_name(value)
    for prefix in ("重庆市", "重庆"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def street_key(value: object) -> str:
    """行政街道的可比键：去 `街道办事处 / 街道 / 镇 / 乡` 后缀后再比。

    街道是行政区划单元，不是地名；`蔡家岗街道` 与 `蔡家岗镇` 视为同一单元，
    但 `街道` 与 `路` 不做任何文本相似处理。
    """
    text = normalize_name(value)
    for suffix in _STREET_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def tokens(text: str) -> set[str]:
    text = clean(text)
    if not text:
        return set()
    if len(text) < 2:
        return {text}
    return {text[i : i + 2] for i in range(len(text) - 1)}


def similarity(left: object, right: object) -> float:
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / (len(ta | tb) or 1)
