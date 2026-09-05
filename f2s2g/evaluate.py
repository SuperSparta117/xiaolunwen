"""独立评估脚本：加载已训练模型进行评估"""

import argparse
import os
import sys

import yaml
import torch
import numpy as np

from main import load_config, resolve_path
from src.data_loader import load_task_data
from src.f2s2g import F2S2GPipeline
from src.knowledge_enhance import inject_knowledge
from src.model import LightGCN, get_device
from src.utils import evaluate_metrics


def evaluate(cfg, task):
    device = get_device(cfg)

    # 加载数据
    records_a, records_b, labeled_pairs, task_cfg = load_task_data(cfg, task)

    # F2S2G
    pipeline = F2S2GPipeline(cfg, task_cfg)
    texts_a, texts_b = pipeline.stage1_field(records_a, records_b)
    features, vectorizer, svd = pipeline.stage2_semantic(texts_a, texts_b)
    graph, train_pairs, val_pairs, test_pairs = pipeline.stage3_graph(
        features, records_a, records_b, labeled_pairs, cfg
    )

    # 知识增强
    knowledge_cfg = cfg.get("knowledge_enhance", {})
    if knowledge_cfg.get("enabled", True):
        graph = inject_knowledge(
            graph, records_b, features, vectorizer, svd, task_cfg, knowledge_cfg
        )

    # 加载模型
    model_cfg = cfg["model"]
    n_a = graph.num_users
    n_b = graph.num_items
    n_kn = graph.num_knowledge

    model = LightGCN(n_a, n_b, model_cfg["embedding_dim"], model_cfg["num_layers"], n_kn)

    output_dir = resolve_path(cfg, "output_dir")
    model_path = os.path.join(output_dir, f"model_task_{task}.pt")
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location=device))
        print(f"已加载模型: {model_path}")
    else:
        print(f"模型文件不存在: {model_path}，使用随机初始化")
        model.init_from_features(graph)

    model = model.to(device)
    graph = graph.to(device)
    model.eval()

    with torch.no_grad():
        user_emb, item_emb = model(graph)

    results = evaluate_metrics(model, (user_emb, item_emb), test_pairs, records_a, records_b, features, cfg)

    print(f"\n{'='*50}")
    print(f"  评估结果 - 任务 {task}")
    print(f"{'='*50}")
    print(f"  {'指标':<12} {'全量':>8} {'头部':>8} {'中部':>8} {'长尾':>8}")
    print(f"  {'-'*48}")
    for metric in ["precision", "recall", "f1"]:
        row = f"  {metric:<12}"
        for group in ["all", "head", "mid", "tail"]:
            val = results.get(f"{metric}_{group}", 0)
            row += f" {val:>7.4f}"
        print(row)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="F2S2G 评估")
    parser.add_argument("--config", type=str, default="system.yaml")
    parser.add_argument("--task", type=str, default="A", choices=["A", "B"])
    args = parser.parse_args()

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)

    cfg = load_config(config_path)
    evaluate(cfg, args.task)
