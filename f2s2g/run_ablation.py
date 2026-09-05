"""
消融实验批量运行脚本
按论文7.3节配置矩阵运行E0~E9全部消融变体

运行方式:
    python run_ablation.py --config system.yaml
    python run_ablation.py --config system.yaml --task A
    python run_ablation.py --config system.yaml --experiments E0,E1,E8
"""

import argparse
import copy
import os
import sys

import yaml
import torch
import numpy as np

from main import load_config, run_pipeline


ABLATION_MATRIX = {
    "E0": {
        "name": "Full Model（本文）",
        "overrides": {},
    },
    "E1": {
        "name": "w/o Field 类型标签",
        "overrides": {"_ablation_no_field_tag": True},
    },
    "E2": {
        "name": "w/o Semantic SVD",
        "overrides": {"semantic": {"svd_components": 0}},
    },
    "E3": {
        "name": "w/o Graph 结构（仅向量相似度）",
        "overrides": {"_ablation_no_graph": True},
    },
    "E4": {
        "name": "w/o same_district",
        "overrides": {"graph": {"enable_same_district": False}},
    },
    "E5": {
        "name": "w/o geo_near",
        "overrides": {"graph": {"enable_geo_near": False}},
    },
    "E6": {
        "name": "w/o same_company",
        "overrides": {"graph": {"enable_same_company": False}},
    },
    "E7": {
        "name": "w/o 全部辅助边",
        "overrides": {
            "graph": {
                "enable_same_district": False,
                "enable_geo_near": False,
                "enable_same_company": False,
            }
        },
    },
    "E8": {
        "name": "w/o 外部知识补全",
        "overrides": {"knowledge_enhance": {"enabled": False}},
    },
    "E9": {
        "name": "w/o 置信度加权",
        "overrides": {"_ablation_no_confidence_weight": True},
    },
}


def deep_update(base, overrides):
    """递归合并配置"""
    result = copy.deepcopy(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and k in result and isinstance(result[k], dict):
            result[k] = deep_update(result[k], v)
        else:
            result[k] = v
    return result


def run_ablation(cfg, task, experiments=None):
    if experiments is None:
        experiments = list(ABLATION_MATRIX.keys())

    results_table = []

    for exp_id in experiments:
        if exp_id not in ABLATION_MATRIX:
            print(f"未知实验: {exp_id}，跳过")
            continue

        exp = ABLATION_MATRIX[exp_id]
        print(f"\n{'#'*60}")
        print(f"  实验 {exp_id}: {exp['name']}")
        print(f"{'#'*60}")

        exp_cfg = deep_update(cfg, exp["overrides"])

        try:
            results = run_pipeline(exp_cfg, task)
            results_table.append({
                "实验": exp_id,
                "名称": exp["name"],
                **results,
            })
        except Exception as e:
            print(f"  实验 {exp_id} 失败: {e}")
            results_table.append({
                "实验": exp_id,
                "名称": exp["name"],
                "f1_all": -1,
            })

    # 输出汇总表
    print(f"\n\n{'='*80}")
    print(f"  消融实验汇总 - 任务 {task}")
    print(f"{'='*80}")
    print(f"  {'实验':<5} {'名称':<25} {'F1_all':>8} {'F1_head':>8} {'F1_mid':>8} {'F1_tail':>8}")
    print(f"  {'-'*70}")
    for row in results_table:
        print(
            f"  {row['实验']:<5} {row['名称']:<25}"
            f" {row.get('f1_all', -1):>7.4f}"
            f" {row.get('f1_head', -1):>7.4f}"
            f" {row.get('f1_mid', -1):>7.4f}"
            f" {row.get('f1_tail', -1):>7.4f}"
        )

    return results_table


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="F2S2G 消融实验")
    parser.add_argument("--config", type=str, default="system.yaml")
    parser.add_argument("--task", type=str, default="A", choices=["A", "B", "all"])
    parser.add_argument("--experiments", type=str, default=None, help="逗号分隔的实验编号")
    args = parser.parse_args()

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)

    cfg = load_config(config_path)

    experiments = None
    if args.experiments:
        experiments = [e.strip() for e in args.experiments.split(",")]

    if args.task == "all":
        for t in ["A", "B"]:
            run_ablation(cfg, t, experiments)
    else:
        run_ablation(cfg, args.task, experiments)
