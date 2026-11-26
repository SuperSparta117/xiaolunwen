"""神经基线：BGE-M3 稠密检索 与 Ditto 风格中文 RoBERTa Cross-Encoder。

两者只使用名称/地址/区县/街道/类型字段，不使用 POI 外部资产。
名称被遮蔽时名称字段置空；Ditto 在每个 rho 下用同一套遮蔽训练对重训。
针对 8GB 共享显存做了内存优化：Adafactor + autocast 训练、fp16 + 动态 padding 推理。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import numpy as np

from .normalize import normalize_address, normalize_name, street_key

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_BGE_CACHE: dict[str, object] = {}
MODEL_ROOT = Path(".audit_work/models")


def _local_or_default(name: str, default: str) -> str:
    candidate = MODEL_ROOT / name
    return str(candidate) if candidate.exists() else default


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _fields(record: Mapping[str, object], masked: bool) -> list[tuple[str, str]]:
    values = [
        ("name", "" if masked else normalize_name(record.get("name"))),
        ("address", normalize_address(record.get("address"))),
        ("area", normalize_name(record.get("area"))),
        ("street", street_key(record.get("street"))),
        ("type", normalize_name(record.get("type"))),
    ]
    return [(key, value) for key, value in values if value]


def serialize_bge(record: Mapping[str, object], masked: bool) -> str:
    fields = _fields(record, masked)
    return "；".join(f"{key}：{value}" for key, value in fields) if fields else "[EMPTY]"


def serialize_side(record: Mapping[str, object], masked: bool) -> str:
    fields = _fields(record, masked)
    return " ".join(f"COL {key} VAL {value}" for key, value in fields)


class BgeM3Scorer:
    name = "BGE-M3 dense bi-encoder"
    use_external_geo = False

    def __init__(self, model_name: str | None = None, batch_size: int = 16) -> None:
        self.model_name = model_name or _local_or_default("bge-m3", "BAAI/bge-m3")
        self.batch_size = batch_size
        self.candidate_vectors: np.ndarray | None = None

    def _load(self):
        import torch
        from transformers import AutoModel, AutoTokenizer

        if self.model_name not in _BGE_CACHE:
            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModel.from_pretrained(self.model_name)
            model.eval()
            model.to(_device())
            if _device() == "cuda":
                model.half()
            _BGE_CACHE[self.model_name] = (tokenizer, model)
        return _BGE_CACHE[self.model_name]

    def _encode(self, texts: list[str]) -> np.ndarray:
        import torch

        tokenizer, model = self._load()
        device = _device()
        vectors = []
        with torch.no_grad():
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start:start + self.batch_size]
                inputs = tokenizer(batch, padding=True, truncation=True, max_length=256, return_tensors="pt")
                inputs = {key: value.to(device) for key, value in inputs.items()}
                output = model(**inputs).last_hidden_state[:, 0]
                output = torch.nn.functional.normalize(output.float(), p=2, dim=1)
                vectors.append(output.cpu().numpy())
        return np.vstack(vectors) if vectors else np.zeros((0, 1), dtype=np.float32)

    def fit(self, pairs, queries, candidates, *, masked_queries, masked_candidates) -> None:
        texts = [serialize_bge(candidate, masked_candidates[index]) for index, candidate in enumerate(candidates)]
        self.candidate_vectors = self._encode(texts)

    def score_query(self, query, candidates, masked_query: bool, masked_candidates: list[bool]) -> np.ndarray:
        query_vector = self._encode([serialize_bge(query, masked_query)])[0]
        return (self.candidate_vectors @ query_vector).astype(np.float64)


class DittoScorer:
    """Ditto 风格 cross-encoder：字段序列化 + [SEP] 拼接 + 二分类微调。"""

    name = "Ditto (Chinese RoBERTa)"
    use_external_geo = False

    def __init__(self, model_name: str | None = None, epochs: int = 3,
                 batch_size: int = 32, lr: float = 1e-4, max_length: int = 96) -> None:
        self.model_name = model_name or _local_or_default("chinese-roberta-wwm-ext", "hfl/chinese-roberta-wwm-ext")
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.max_length = max_length
        self.tokenizer = None
        self.model = None
        self.right_ids: list[list[int]] = []

    def _load(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if self.tokenizer is None:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name, num_labels=1)
            self.model.to(_device())
        return self.tokenizer, self.model

    def _side_ids(self, tokenizer, text: str) -> list[int]:
        return tokenizer(text, add_special_tokens=False, truncation=True, max_length=self.max_length // 2)["input_ids"]

    def fit(self, pairs, queries, candidates, *, masked_queries, masked_candidates) -> None:
        import torch
        from transformers.optimization import Adafactor

        tokenizer, model = self._load()
        device = _device()
        candidate_by_id = {str(candidate["id"]): index for index, candidate in enumerate(candidates)}
        encoded: list[tuple[list[int], list[int], float]] = []
        for pair in pairs:
            query = queries.get(str(pair["query_id"]))
            index = candidate_by_id.get(str(pair["candidate_id"]))
            if query is None or index is None:
                continue
            left = self._side_ids(tokenizer, serialize_side(query, masked_queries.get(str(pair["query_id"]), False)))
            right = self._side_ids(tokenizer, serialize_side(candidates[index], masked_candidates[index]))
            encoded.append((left, right, float(pair["label"])))
        if not encoded:
            raise ValueError("Ditto 训练集为空")

        self.right_ids = [
            self._side_ids(tokenizer, serialize_side(candidate, masked_candidates[index]))
            for index, candidate in enumerate(candidates)
        ]

        optimizer = Adafactor(model.parameters(), lr=self.lr, scale_parameter=False, relative_step=False)
        scaler = torch.amp.GradScaler("cuda", enabled=(device == "cuda"))
        loss_fn = torch.nn.BCEWithLogitsLoss()
        generator = np.random.RandomState(42)
        model.train()
        for epoch in range(self.epochs):
            order = generator.permutation(len(encoded))
            total_loss = 0.0
            for start in range(0, len(order), self.batch_size):
                rows = [encoded[i] for i in order[start:start + self.batch_size]]
                input_ids, token_type_ids, attention = _assemble_batch(rows, tokenizer.cls_token_id,
                                                                       tokenizer.sep_token_id,
                                                                       tokenizer.pad_token_id, dynamic=True)
                labels = torch.tensor([row[2] for row in rows], dtype=torch.float32, device=device)
                optimizer.zero_grad()
                with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=(device == "cuda")):
                    logits = model(
                        input_ids=torch.tensor(input_ids, dtype=torch.long, device=device),
                        token_type_ids=torch.tensor(token_type_ids, dtype=torch.long, device=device),
                        attention_mask=torch.tensor(attention, dtype=torch.long, device=device),
                    ).logits.squeeze(-1)
                    loss = loss_fn(logits, labels)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                total_loss += float(loss.item()) * len(rows)
            print(f"  ditto epoch {epoch + 1}/{self.epochs} loss={total_loss / max(1, len(encoded)):.4f}", flush=True)
        model.eval()
        if device == "cuda":
            model.half()

    def score_query(self, query, candidates, masked_query: bool, masked_candidates: list[bool]) -> np.ndarray:
        import torch

        tokenizer, model = self._load()
        device = _device()
        left = self._side_ids(tokenizer, serialize_side(query, masked_query))
        batch_size = 64
        scores = np.zeros(len(candidates), dtype=np.float64)
        with torch.inference_mode():
            for start in range(0, len(candidates), batch_size):
                right_batch = self.right_ids[start:start + batch_size]
                rows = [(left, right, 0.0) for right in right_batch]
                input_ids, token_type_ids, attention = _assemble_batch(rows, tokenizer.cls_token_id,
                                                                       tokenizer.sep_token_id,
                                                                       tokenizer.pad_token_id, dynamic=True)
                logits = model(
                    input_ids=torch.tensor(input_ids, dtype=torch.long, device=device),
                    token_type_ids=torch.tensor(token_type_ids, dtype=torch.long, device=device),
                    attention_mask=torch.tensor(attention, dtype=torch.long, device=device),
                ).logits.squeeze(-1)
                scores[start:start + len(right_batch)] = torch.sigmoid(logits.float()).cpu().numpy()
        return scores


def _assemble_batch(rows, cls_id: int, sep_id: int, pad_id: int, dynamic: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    assembled = []
    for left, right, _ in rows:
        ids = [cls_id] + left + [sep_id] + right + [sep_id]
        split = 1 + len(left)
        assembled.append((ids, split))
    if dynamic:
        max_length = max(len(ids) for ids, _ in assembled)
    else:
        max_length = max(len(ids) for ids, _ in assembled)
    input_ids, token_type_ids, attention = [], [], []
    for ids, split in assembled:
        types = [0] * split + [1] * (len(ids) - split)
        pad = max_length - len(ids)
        input_ids.append(ids + [pad_id] * pad)
        token_type_ids.append(types + [0] * pad)
        attention.append([1] * len(ids) + [0] * pad)
    return np.asarray(input_ids), np.asarray(token_type_ids), np.asarray(attention)
