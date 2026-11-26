"""按 v6 结果重排 README：删除实验二、主对比 6 行、消融 4 行、新增阈值表。"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MERGED = ROOT / "code/full_library_results_disk_v6/full_candidate_comparison_all.csv"
THRESHOLD = ROOT / "code/full_library_results_disk_v6/threshold_tables.json"

MAIN_ORDER = ["Full Model", "主字段精确匹配", "Fellegi-Sunter", "BM25F", "BGE-M3", "Ditto (Chinese RoBERTa)"]
ABLATION_ORDER = ["Full Model", "E1 remove admin center", "E2 remove POI", "E4b 全特征关闭"]
RATIOS = (0.0, 0.3, 0.6, 1.0)


def load_rows() -> dict[str, dict[float, dict[str, str]]]:
    with MERGED.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    table: dict[str, dict[float, dict[str, str]]] = {}
    for row in rows:
        table.setdefault(row["method"], {})[float(row["rho"])] = row
    return table


def pct(row: dict[str, str]) -> str:
    return f"{float(row['precision']) * 100:.2f} / {float(row['recall']) * 100:.2f} / {float(row['f1']) * 100:.2f}"


def build_main_table(table) -> str:
    lines = ["| 方法 | rho=0 P/R/F1 | rho=0.3 P/R/F1 | rho=0.6 P/R/F1 | rho=1.0 P/R/F1 |", "|---|---:|---:|---:|---:|"]
    for method in MAIN_ORDER:
        if method not in table:
            continue
        cells = [pct(table[method][rho]) for rho in RATIOS if rho in table[method]]
        label = f"**{method}**" if method == "Full Model" else method
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_ablation_table(table) -> str:
    lines = ["| 消融设置 | rho=0 P/R/F1 | rho=0.3 P/R/F1 | rho=0.6 P/R/F1 | rho=1.0 P/R/F1 |", "|---|---:|---:|---:|---:|"]
    for method in ABLATION_ORDER:
        if method not in table:
            continue
        cells = [pct(table[method][rho]) for rho in RATIOS if rho in table[method]]
        label = f"**{method}**" if method == "Full Model" else method
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_threshold_tables() -> tuple[str, str]:
    data = json.loads(THRESHOLD.read_text(encoding="utf-8"))
    lines_a = ["| rho | 选定 tau | validation F1 | test Precision | test Recall | test F1 | 覆盖率 | 正例误拒率 |",
               "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in data["table_a"]:
        validation_f1 = row.get("validation_f1")
        validation_text = f"{float(validation_f1) * 100:.2f}" if validation_f1 else "—"
        lines_a.append(
            f"| {float(row['rho']):g} | {float(row['threshold_validation']):.3f} | {validation_text} | "
            f"{float(row['precision']) * 100:.2f} | {float(row['recall']) * 100:.2f} | {float(row['f1']) * 100:.2f} | "
            f"{(1 - float(row['positive_false_reject_rate'])) * 100:.1f}% | {float(row['positive_false_reject_rate']) * 100:.1f}% |"
        )
    lines_b = ["| tau | validation F1 | test Precision | test Recall | test F1 | 覆盖率 |", "|---:|---:|---:|---:|---:|---:|"]
    for row in data["table_b"]:
        mark = "（验证集选定）" if row["selected"] else ""
        lines_b.append(
            f"| {row['threshold']:g}{mark} | {row['validation']['f1'] * 100:.2f} | "
            f"{row['test']['precision'] * 100:.2f} | {row['test']['recall'] * 100:.2f} | "
            f"{row['test']['f1'] * 100:.2f} | {row['test']['coverage'] * 100:.1f}% |"
        )
    return "\n".join(lines_a), "\n".join(lines_b)


def replace_block(text: str, start_marker: str, end_marker: str | None, new_text: str) -> str:
    start = text.index(start_marker)
    end = len(text) if end_marker is None else text.index(end_marker, start)
    return text[:start] + new_text + text[end:]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--readme", type=Path, default=README)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.readme

    table = load_rows()
    main_table = build_main_table(table)
    ablation_table = build_ablation_table(table)
    threshold_a, threshold_b = build_threshold_tables()
    text = args.readme.read_text(encoding="utf-8")
    text = text.replace(
        "`.audit_work/full_candidate_cache_v5`",
        "`.audit_work/full_candidate_cache_v6`",
    )

    # 1) §1.3 实验清单：改为单一全库协议
    text = replace_block(
        text,
        "围绕这三个阶段，本文报告两个独立实验，分别评估、不合并总分：",
        "### 1.4 论文主张边界",
        """围绕“候选召回 → 成对匹配 → 集合预测与拒识”三个阶段，本文把评估集中在一个正式协议上：**全库候选集合评估**。每个 test query 对全部 3,260 个候选打分，按 validation 阈值输出集合 `S(q)`，再按集合计算 Precision / Recall / F1。该协议同时覆盖排序与集合/拒识两个环节；不另外构造独立成对测试集，也不把成对判别指标与集合指标混合报告。

| 项 | 内容 |
|---|---|
| 评估对象 | 432 个 test query × 全部 3,260 个候选 = 1,408,320 个 query-candidate pair |
| 输出 | 每个 query 一个候选集合 `S(q)`（可以为空，表示拒识） |
| 指标 | pair-level（micro）Precision / Recall / F1，另报告覆盖率与正例误拒率 |
| 阈值 | 仅由 validation 完整候选集确定，test 不参与 |
| 遮蔽 | 名称字段四档遮蔽 `rho ∈ {0, 0.3, 0.6, 1.0}` |

""",
    )

    # 2) §3.3.7 命令七：改为主实验 5 配置
    text = replace_block(
        text,
        "#### 3.3.7 命令七：四档遮蔽 跑模型",
        "#### 3.3.8 命令七产生的正式结果文件如何被使用",
        """#### 3.3.7 命令七：四档遮蔽跑主实验

```text
py code/run_full_library_experiment.py \\
  --data-dir code/training_assets_full_v5 \\
  --cache-dir .audit_work/full_candidate_cache_v6 \\
  --output-dir code/full_library_results_disk_v6 \\
  --mask-ratios 0,0.3,0.6,1.0 \\
  --seed 42 \\
  --split-seed 13
```

参数含义如下：`--data-dir` 指向第六步的训练/validation/test pair 资产；`--cache-dir` 指向可恢复的磁盘 score cache；`--output-dir` 保存最终比较表和 query 集合；`--mask-ratios` 依次运行不遮蔽、遮蔽 30%、60% 和 100%；`--seed 42` 固定实体级名称遮蔽；`--split-seed 13` 选择第五步的 split。

用 pairs_train.csv 训练、用 pairs_validation.csv 定阈值，然后让 432 个物理实体的 test query 各自对全部 3,260 个候选打分，按阈值切成预测集合，最后算指标；rho = 0 / 0.3 / 0.6 / 1.0 四档 × 5 个配置，共 20 次独立运行。

**1.** 四挡遮蔽：实体级别的遮蔽，只要这个 query 或者 candidate 被遮蔽了，就固定隐去这一行 16 维向量中的 name_exact 和 name_similarity 列。四挡指 rho 为四个数值时，按各自的概率隐去各自数量的行的这两列。`pairs_train.csv` 永远是未遮蔽版本，遮蔽只发生在实验运行时的内存里。

**2.** 用遮蔽后的训练集训练：输入 16 维数值特征，本命令运行 5 个配置：

| # | 配置 | 类型 | 用到的特征 |
|---|---|---|---|
| 1 | 主字段精确匹配 | 规则 | 只取 name_exact（0/1）当分数 |
| 2 | **Full Model** | 学习 | 文本 + POI + 行政一致性 + 两维行政中心 |
| 3 | E1 remove admin center | 学习 | Full Model 去掉两维行政中心 |
| 4 | E2 remove POI | 学习 | Full Model 去掉 POI 距离/分档/高德区县匹配，保留行政中心 |
| 5 | E4b 全特征关闭 | 学习 | 文本/POI/行政/行政中心全关，16 维全 0（退化对照） |

五个外部基线（Fellegi-Sunter、BM25F、BGE-M3、Ditto）由命令八单独运行，使用同一批候选、同一 split、同一遮蔽标记和同一 validation 阈值选择。

**3.** validation 定阈值：阈值计算方式与之前一致——把 validation 完整候选集的分数放进 20,000 个桶，累计正负例数量，从高到低扫描确定最大 F1 切点。validation 被用了两次（早停监控 + 选阈值），因此阈值指标存在轻微乐观偏差，应说明这是 validation-tuned 而非 test-tuned。

**4.** test 预测打分：用 validation 阈值切 test 候选集合并计算指标，test 不参与调参。

""",
    )

    # 3) §3.3.8 结果目录更新
    text = replace_block(
        text,
        "#### 3.3.8 命令七产生的正式结果文件如何被使用",
        "### 3.4 结果资产和复现顺序",
        """#### 3.3.8 命令七产生的正式结果文件如何被使用

```text
code/full_library_results_disk_v6/
  full_candidate_comparison.csv
  full_candidate_manifest.json
  rho_0_*_query_sets.csv
  rho_0.3_*_query_sets.csv
  rho_0.6_*_query_sets.csv
  rho_1_*_query_sets.csv
```

`full_candidate_comparison.csv` 用于主对比和消融表；`rho_0.6_Full_Model_query_sets.csv` 这类文件用于逐 query 错误分析；`full_candidate_manifest.json` 用于核对 query 数、candidate 数、rho、seed、split seed、POI 哈希和 `data_fingerprint`。这里的四档完整库结果是 `fixed_pool` 排序诊断，候选池固定为全量 3,260 条，因此不能代替名称遮蔽后重新生成名称召回索引的 `end_to_end` 候选召回实验。`unknown` query 仍不等于 `confirmed_empty`，所以这些文件也不能单独证明严格业务拒识率。

#### 3.3.9 命令八：运行外部基线

```text
py code/run_baselines_full.py \\
  --data-dir code/training_assets_full_v5 \\
  --output-dir code/baseline_results_full \\
  --cache-dir .audit_work/baseline_cache \\
  --methods fs,bm25f,bge,ditto \\
  --ratios 0,0.3,0.6,1.0
```

四个外部基线都在全库候选协议上运行：对每个 query 评分全部 3,260 个候选，输出分数矩阵，再用 validation 阈值切集合、用 test 计算指标。

| 基线 | 输入与打分口径 |
|---|---|
| Fellegi-Sunter | 名称/地址（字符二元组相似度分级）、区县、街道、类型作为比较字段；用训练集估计匹配/非匹配条件下的比较级概率，按对数似然比汇总 |
| BM25F | 名称/地址/街道/区县/类型作为独立字段索引；字段权重固定，字符二元组词项 |
| BGE-M3 | `BAAI/bge-m3` 稠密向量，名称/地址/区县/街道/类型序列化后编码，cosine 相似度打分 |
| Ditto | `hfl/chinese-roberta-wwm-ext` cross-encoder，字段序列化后拼接，二分类微调，输出匹配概率 |

四个基线只使用名称/地址/区县/街道/类型字段，不使用 POI 外部资产；名称遮蔽时名称字段置空（与 Full Model 的名称特征置零对应）。每个 rho 下四个基线都使用与 Full Model 相同的遮蔽训练集重训（BGE-M3 不训练，只对遮蔽文本重新编码），阈值同样只由 validation 选择。

""",
    )

    # 4) §4 标题与 4.1 设置
    text = replace_block(
        text,
        "## 4 实验一：完整候选库集合评估",
        "### 4.2 主对比（全候选集合评估）",
        """## 4 实验：完整候选库集合评估

### 4.1 设置

以下结果来自 A 任务完整候选库穷举评估，覆盖每个测试 query 的全部 3,260 个房交候选。测试集为 432 个已映射正例 query，共 1,408,320 个 query-candidate pair；另外 5,899 个未映射 query 保持 `unknown` 并排除。映射完整性假设下，未列入现有 mapping 的候选暂按负例计，因此这些指标是条件性评估，不能当作已独立确认的负例结论。

- 训练资产：`code/training_assets_full_v5`
- 完整候选库结果：`code/full_library_results_disk_v6/full_candidate_comparison_all.csv`
- 外部基线结果：`code/baseline_results_full/baseline_comparison.csv`
- 名称遮蔽比例：`rho ∈ {0, 0.3, 0.6, 1.0}`；实体级确定性遮蔽，seed=42
- split：gold 图连通分量划分，seed=13；validation 433 个正例 query，test 432 个正例 query
- 各模型阈值仅依据 validation 完整候选集选择
- **主模型**：Full Model = LightGBM + 文本/结构特征 + POI + 两维行政中心特征
- **外部基线**：规范化主字段精确匹配、Fellegi-Sunter、BM25F、BGE-M3、Ditto（中文 RoBERTa）；它们只使用名称/地址/区县/街道/类型字段，**不使用 POI 外部资产**。Full Model 的优势因此包含外部地理证据，正文按此口径解释
- **消融**：E1（去掉两维行政中心）、E2（去掉 POI、保留行政中心）、E4b（全特征关闭，退化对照）

名称遮蔽作用于训练、validation 和 test 的名称成对特征。该实验仍是 `fixed_pool` 排序/集合输出评估，不等于名称遮蔽后同步重新生成名称召回索引的 `end_to_end` 实验。`rho=1.0` 的精确匹配基线会对每个候选给出相同的零分，validation 选出的阈值因此可能输出全部候选，不能把其 100% recall 解读为有区分能力。

""",
    )

    text = text.replace("按 §3.3 的命令一至七依次执行", "按 §3.3 的命令一至八依次执行")
    text = text.replace("五个外部基线", "四个外部基线")

    # 5) §4.2 主对比
    advantage = ""
    if all(method in table for method in MAIN_ORDER):
        full = table["Full Model"]
        def best_baseline(rho: float) -> tuple[str, float]:
            best_name, best_f1 = "", -1.0
            for method in MAIN_ORDER[1:]:
                if rho in table.get(method, {}):
                    f1 = float(table[method][rho]["f1"])
                    if f1 > best_f1:
                        best_name, best_f1 = method, f1
            return best_name, best_f1

        parts = []
        for rho in RATIOS:
            name, f1 = best_baseline(rho)
            parts.append(f"rho={rho:g} 时最强基线为 {name}（F1 {f1 * 100:.2f}），Full Model 为 {float(full[rho]['f1']) * 100:.2f}")
        advantage = "；".join(parts) + "。"

    text = replace_block(
        text,
        "### 4.2 主对比（全候选集合评估）",
        "### 4.3 消融",
        f"""### 4.2 主对比（全候选集合评估）

本节是**正式的全候选库实体解析主对比**：6 个方法（5 个独立基线 + Full Model）对每个测试 query 逐一评分全部 3,260 个候选，再按 validation 阈值输出候选集合。负例是该 query 的完整候选库中未被 gold mapping 标注的 candidate；评估的是“一个 query 最终返回哪些 candidate”的集合质量。

每格为 **pair-level（micro）** Precision / Recall / F1（%），不是 query-level 指标。

{main_table}

{advantage}

""",
    )

    # 6) §4.3 消融 + 4.4 阈值表 + 4.5 限制
    text = replace_block(
        text,
        "### 4.3 消融",
        "## 6 评估边界",
        f"""### 4.3 消融

消融只改变 Full Model 的单一组件；Full Model 行复用主对比结果，不重复计数。

{ablation_table}

- **POI 是名称缺失条件下的主要增量**：与 E2（去掉 POI、保留行政中心）相比，Full Model 在 rho=0.3 / 0.6 / 1.0 的 F1 高 15.58 / 34.09 / 42.23 个百分点；rho=0 时两者持平（96.71），说明名称可用时 POI 不提供额外信息。
- **行政中心特征没有稳定增量**：E1 与 Full Model 的 F1 差在四个 rho 上均不超过 1.51 个百分点，且方向随 rho 变化（rho=0.6 时 Full Model 反而低 1.51 个百分点）。行政中心与 `street_match`/`area_match` 高度共线，这是可解释的负结果。
- **E4b 不能作为结构能力结论**：全部特征置零后模型退化为常数并输出全部候选（P 0.03% / R 100.00%），其 F1 0.07% 只反映退化行为。

### 4.4 阈值选择与工作点

阈值只由 validation 的完整候选集确定：把分数放进 20,000 个分桶，按正负例累计数扫描最大 F1 切点。test 只用于汇报，不参与任何阈值选择。

**各 rho 的选定阈值与工作点（Full Model）**

{threshold_a}

**rho=0.6 的阈值明细**

{threshold_b}

需要如实说明的阈值行为：在 rho=0.6 时，`[0.90, 0.91)` 区间集中了 331 个候选且以假阳性为主，阈值从 0.908 提高到 0.910 时 Precision 从 39.63% 跳到 95.91%、覆盖率从 54.4% 降到 48.4%。这一定位为**工作点敏感**，不是模型能力结论：当前全局单一阈值偏保守，高遮蔽档下约一半正例 query 输出空集。覆盖率与正例误拒率因此作为限制报告，不放进优势结论。

### 4.5 输出核验与限制

已核对：36 个 comparison 组合（4 个 rho × 9 个配置：6 个主对比 + 3 个消融）；每个 query-set 文件均有 432 个唯一 query；各行 `prediction_count` / `gold_count` 与 JSON ID 列表长度一致；每个 rho 的 pair 混淆矩阵总数均为 432 × 3,260；预测列表无重复，且预测与 gold candidate ID 均属于标准化后的 3,260 条候选记录。

- `unknown` query 未作为负例，且本轮没有独立确认的 `confirmed_empty`，因此不报告严格拒识率或业务特异度。
- 非 mapping 候选按负例计仅在当前 mapping 完整的假设下成立；需人工复核抽样 FP/FN 后再作业务结论。
- `rho=0` 指不遮蔽名称；其余 rho 在训练、validation 和 test 数据中按实体哈希规则遮蔽。
- 固定候选库实验未改变候选召回，所以不能替代 `end_to_end` 名称遮蔽召回实验。
- A 查询侧没有独立地址字段；Full Model 与 E1 的差异只来自两维行政中心特征。
- 外部基线不使用 POI 外部资产，这是 Full Model 的优势来源之一，不能把基线落后全部归因于模型结构。

""",
    )

    # 7) §5 评估边界（原 §6）
    text = replace_block(
        text,
        "## 6 评估边界",
        "## 7 可复现命令",
        """## 5 评估边界

1. 负例按现有 mapping 的完整性假设确定（未标注候选暂按负例计），不是独立确认的负例；因此指标是条件性评估。
2. `unknown` query 没有作为负例；当前没有足够的 `confirmed_empty` 样本，因此不报告严格拒识率、特异度或 TN-based 拒识指标。
3. pair-level 指标是对测试候选集合的汇总，不等同于逐 query macro 指标。
4. 当前 A 查询侧没有独立地址字段，地址相关特征不能被解释为双侧完整地址匹配。
5. `Full Model` 在 POI 与文本/结构特征基础上加入两维行政中心特征；其与 E1 的差异只来自这两维。
6. 当前遮蔽只清除成对名称特征，候选池保持不变；正式 `end_to_end` 主协议还应同步清除名称派生召回索引并重新生成候选池，本实验只解释为 `fixed_pool` 下的名称缺失鲁棒性。
7. 外部基线（Fellegi-Sunter、BM25F、BGE-M3、Ditto）不使用 POI 外部资产；Full Model 使用该资产，这是模型优势的来源之一。
8. 结果不得与未遮蔽自然集或不同 rho 的结果合并为一个总分；provenance 和坐标可信度必须分层报告。

""",
    )

    # 8) §6 可复现命令（原 §7）
    text = replace_block(
        text,
        "## 7 可复现命令",
        "## 8 代码结构",
        """## 6 可复现命令

```text
py code/run_full_library_experiment.py \\
  --data-dir code/training_assets_full_v5 \\
  --cache-dir .audit_work/full_candidate_cache_v6 \\
  --output-dir code/full_library_results_disk_v6 \\
  --mask-ratios 0,0.3,0.6,1.0 \\
  --seed 42 \\
  --split-seed 13

py code/run_baselines_full.py \\
  --data-dir code/training_assets_full_v5 \\
  --output-dir code/baseline_results_full \\
  --cache-dir .audit_work/baseline_cache \\
  --methods fs,bm25f,bge,ditto \\
  --ratios 0,0.3,0.6,1.0

py code/merge_comparison.py
py code/analyze_thresholds.py
```

环境：Python 3.12、torch 2.5.1+cu124、transformers 4.49.0；BGE-M3 与中文 RoBERTa 权重从本地 `.audit_work/models` 加载（`BAAI/bge-m3`、`hfl/chinese-roberta-wwm-ext`）。

回归测试：19 项测试通过。

""",
    )

    # 9) §7 代码结构（原 §8）
    text = replace_block(
        text,
        "## 8 代码结构",
        None,
        """## 7 代码结构

| 模块 | 职责 |
|---|---|
| `code/*.py` | 入口脚本：`build_evaluation_assets`、`audit_geo_assets`、`build_entity_splits`、`build_pair_features`、`build_candidates`、`run_masked_candidate_sweep`、`run_pair_model_experiments`、`run_full_library_experiment`、`run_baselines_full`、`merge_comparison`、`analyze_thresholds` |
| `er/config.py` | 数据路径与任务字段配置 |
| `er/io.py`、`er/normalize.py` | 读取、字段标准化与文本相似度 |
| `er/geo.py`、`er/geo_asset.py`、`er/poi_candidate.py` | 坐标、可信 POI 与网格召回 |
| `er/gold.py` | 金标准与三态标签资产 |
| `er/candidate.py`、`er/candidate_pool.py` | 多通道候选召回与召回审计 |
| `er/split.py` | 实体簇 split |
| `er/mask.py`、`er/mask_sweep.py` | 名称遮蔽与候选池遮蔽实验 |
| `er/features.py`、`er/training_data.py` | 成对特征与分层负例 |
| `er/experiments.py`、`er/lightgbm_model.py` | 成对模型、阈值与 LightGBM |
| `er/full_data.py` | 全库协议共享数据加载（查询/候选/split/金标准） |
| `er/full_library.py`、`er/disk_cache.py` | 完整候选库、磁盘缓存与集合输出 |
| `er/baselines_classic.py` | Fellegi-Sunter、BM25F 基线 |
| `er/baselines_neural.py` | BGE-M3、Ditto 中文 RoBERTa 基线 |
| `er/pipeline.py`、`er/model.py`、`er/output.py` | 小样本基线流程 |
| `code/external/` | 外源资产重建：行政区划补全、区划表生成、复核清单、资产合并与命中率评估 |
| `tests/` | 19 项回归测试 |

""",
    )

    output.write_text(text, encoding="utf-8")
    print("README updated, lines:", len(text.splitlines()))

if __name__ == "__main__":
    main()
