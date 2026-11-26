# temp_plan：实验结构调整（v3）

> 本文件按当前讨论整理，替换「实验一 + 实验二」双协议结构。
> 核心决策：**只保留全库候选集合协议**；删除成对分类实验；主对比固定为 **5 个独立基线 + Full Model**；基线与消融完全分离；新增阈值选择表；**DeepMatcher 删除**，深度实体匹配由 Ditto 代表。

## 1 目标与主张

- 研究问题：比较 Full Model 与 5 个领域代表性基线在自然条件及不同名称遮蔽比例下的表现；优势大小和趋势由实验结果决定，不预设结论。
- 基线定位：覆盖经典实体解析、信息检索、语义检索和深度实体匹配范式。**特征删除实验单独归入消融**，同一配置不再同时算作基线和消融。
- Full Model 的结构和训练超参保持现有定义；新增基线按各自标准方法实现。所有方法都接入同一套全库候选、validation 阈值和 test 集合指标协议。

## 2 实验设计（单一协议）

| 项 | 内容 |
|---|---|
| 协议 | 全库候选库集合输出：每个 test query 对全部 3,260 个候选打分，按 validation 阈值输出集合 |
| 测试集 | 432 个已映射正例 query × 3,260 candidate = 1,408,320 pair |
| 阈值 | 仅由 validation 决定，test 不参与 |
| rho | 0 / 0.3 / 0.6 / 1.0，实体级固定 seed=42 |

### 主对比：6 个方法（5 个独立基线 + Full Model）

| # | 方法 | 范式 | 输入与打分口径 |
|---|---|---|---|
| 1 | 规范化主字段精确匹配 | 业务规则下限 | 规范化名称完全相同则匹配；名称被遮蔽时按无匹配处理 |
| 2 | Fellegi-Sunter | 概率记录链接 | 基于名称、地址、区县、街道和类型字段的比较向量，训练集估计匹配/非匹配概率 |
| 3 | BM25F | 字段加权词项检索 | 名称、地址、区县、街道、类型作为独立字段索引；字段权重在 validation 上确定 |
| 4 | BGE-M3 dense bi-encoder（`BAAI/bge-m3`） | 语义稠密检索 | 同一字段序列化格式分别编码 query 与 candidate，cosine similarity 打分；候选向量可预编码 |
| 5 | Ditto（中文 RoBERTa Cross-Encoder，`hfl/chinese-roberta-wwm-ext`） | Transformer 成对实体匹配 | 按 Ditto 字段序列化方式输入记录对，输出匹配概率；作为中文适配版报告 |
| 6 | **Full Model** | LightGBM 特征模型 | LightGBM + 文本/结构特征 + POI + 两维行政中心特征 |

- **DeepMatcher 不纳入**：中文适配与复现成本高，深度实体匹配范式由 Ditto 代表；若审稿要求，再作为附录补充，不进主实验。
- 除规则基线外的四种模型基线与 Full Model 使用相同 train/validation/test 划分与实体级名称遮蔽规则。
- 每个 rho 下，名称及其派生输入按同一遮蔽标记处理；validation 只用于训练配置选择和阈值确定，test 只用于最终汇报。
- 开始训练前记录各方法的模型版本、字段序列化、字段权重或关键超参，保证可复现。

### 消融：4 个（固定）

| 消融 | 说明 |
|---|---|
| Full Model | 主模型参照行，结果引用主对比表 |
| E1 remove admin center | 只关闭 `admin_center_distance_m`、`admin_center_same`，保留 POI 特征和 `area_match`、`street_match`、`poi_district_match` |
| E2 remove POI | 只关闭 `coords_available`、`coords_trust_both`、`poi_distance_m`、4 个 `poi_distance_*` 分档、`poi_district_match`；**保留行政中心两维**与 `area_match`、`street_match`、文本特征，其他训练设置不变 |
| E4b 全特征关闭 | 全部特征维度置零，作为退化对照，不能作为结构能力结论 |

- E1 与现有 `LightGBM + POI` 配置一致，只是不再单独占用主对比表名额。
- 原 `LightGBM Text/Structure`（同时关 POI 与行政中心）属于 `E1+E2` 组合对照，放附录，不作为 E2 的纯 POI 消融。
- 原 `TF-IDF-like Cosine`、`Text/Structure Rule`、`Logistic Text/Structure` 保留为附录补充，不占主表名额。
- **代码注意**：当前 `full_library.py` 的 E2 配置同时关闭了行政中心（`use_admin_center=False`），需改为保留行政中心，这是本计划唯一的方法语义变更。

### 需要补的基线工作

四个新增基线（Fellegi-Sunter、BM25F、BGE-M3、Ditto 中文适配版）都必须输出全候选库分数，使用相同的 validation 阈值选择和 test 集合指标，不能只在成对数据上报告结果。

重跑范围：全库实验为 **9 个唯一配置**（6 个主对比方法 + E1/E2/E4b），4 个 rho。

- Full Model、E1、E4b 的配置未变，缓存键（方法名 + data fingerprint）仍有效，可复用已有结果；
- 新增 4 个基线必须新跑；
- E2 因配置修改必须重跑；
- 若要求整套结果来自同一次干净运行，也可 9 个配置全部重跑（约 2–3 小时；深度基线在 GPU 上另算）。

## 3 公平性协议（新增，必须写死）

| 项 | 规定 |
|---|---|
| 重训规则 | 每个 rho 下，所有监督方法（Full Model、Ditto、Fellegi-Sunter、BM25F 的字段权重）都用同一套**遮蔽后的训练集**重训/重估参数；BGE-M3 不训练，但对遮蔽后的文本重新编码 |
| 遮蔽表示 | 名称被遮蔽时，文本类基线统一把名称替换为固定占位符 `[MASK]`；Full Model 侧名称特征置零；两者使用同一实体级遮蔽集合（seed=42） |
| 缺失字段 | query 侧没有地址列，Ditto 序列化用 `[EMPTY]` 占位；所有方法的字段缺失处理必须记录 |
| 外部证据声明 | **5 个基线只使用名称/地址/区县/街道/类型字段，不使用 POI 外部资产**；Full Model 使用该资产，因此其优势包含外部证据，正文必须明确声明 |
| 阈值 | 每种方法 × 每个 rho 独立选择阈值，只使用 validation 最大 F1；BGE-M3 输出为 cosine score，不是概率，表中称 score/阈值 |
| 中文处理 | BM25F、Fellegi-Sunter 统一使用字符二元组或固定分词器，配置写入 manifest |
| 版本记录 | 预训练模型版本/commit、字段序列化、关键超参、最大长度、batch 设置全部记录 |

## 4 新增表：阈值选择依据

- **目的**：说明阈值怎么定、为什么选它，把“模型判别力”和“阈值/覆盖率”解耦。
- **数据来源**：全库运行的 cache 下 `validation_scores.csv` / `test_scores.csv` 离线重算；不额外重训。
- **选阈值规则**：仅用 validation，按 20,000 桶直方图最大 F1；test 不参与。

### 表 3a 各 rho 的选定阈值与工作点（Full Model，示例值）

| rho | 选定 tau | test F1 | 覆盖率（有预测） | 正例误拒率 |
|---|---:|---:|---:|---:|
| 0 | 0.786 | 96.71 | 99.1% | 0.9% |
| 0.3 | 0.902 | 77.81 | 69.0% | 31.0% |
| 0.6 | 0.910 | 62.06 | 48.4% | 51.6% |
| 1.0 | 0.929 | 50.16 | 35.4% | 64.6% |

### 表 3b 阈值明细（Full Model，rho=0.6，示例值）

| tau | Precision | Recall | F1 | 覆盖率 |
|---:|---:|---:|---:|---:|
| 0.80 | 34.10 | 54.57 | 41.97 | 67.8% |
| 0.90 | 40.65 | 48.70 | 44.31 | 56.2% |
| 0.908 | 39.63 | 46.52 | 42.80 | 54.4% |
| **0.910（验证集选定）** | **95.91** | **45.87** | **62.06** | **48.4%** |
| 0.95 | 95.88 | 40.43 | 56.88 | 42.8% |

### 解读要求

1. 阈值按 validation 最大 F1 选择，test 只汇报，不能反向调参；
2. 高分段分数高度集中：rho=0.6 时 `[0.90, 0.91)` 有 331 个候选且以假阳性为主，0.908→0.910 时 Precision 从 39.63% 跳到 95.91%，如实写入，定位为**工作点敏感**而非模型缺陷；
3. 覆盖率与误拒率作为**限制**说明，不放进“优势”主表；
4. 同时给出邻近阈值，避免只展示最优点的选择性报告。

## 5 README 结构调整

```text
## 4 实验：完整候选库集合评估
   4.1 设置
   4.2 主对比（6 个方法：5 个独立基线 + Full Model）
   4.3 消融（Full Model 参照 + E1 / E2 / E4b）
   4.4 阈值选择与工作点（新增，表 3a/3b）
   4.5 输出核验与限制
```

- 删除原 §5「实验二：有限负例成对分类诊断」及其引用、数字、双协议比较句；
- 主对比表固定为 **6 行**（5 个独立基线 + Full Model），Full Model 放第一行；
- 全文重编号，检查交叉引用；
- 保留的主表：主对比表（百分比）、消融表（百分比）、阈值表（新增）；
- 不恢复此前删除的 macro/覆盖率/阈值扫描三表。

## 6 执行前准备与实施顺序

**依赖准备**（GPU 当前未开启，不阻塞前面步骤；跑深度基线前开启即可）：

- BGE-M3：`transformers` / `sentence_transformers` / `FlagEmbedding`（二选一实现），模型 `BAAI/bge-m3`；
- Ditto：`torch` + `transformers`，中文预训练权重 `hfl/chinese-roberta-wwm-ext`；
- Fellegi-Sunter、BM25F：优先用成熟库（`splink`/`recordlinkage`、自实现 BM25F），避免重复造轮子；
- 依赖安装与模型下载在深度基线执行前完成。

**实施顺序**（按成本从低到高，每完成一个就产出全库分数并校验）：

1. 修正 E2 配置（保留行政中心），确认 E1/E4b 不变；
2. 规则基线 → Fellegi-Sunter → BM25F（全库打分 + validation 阈值）；
3. BGE-M3（候选/查询编码 + cosine 全库打分 + validation 阈值）；
4. Ditto（中文 RoBERTa 训练 + 全库推理；每个 rho 重训）；
5. 汇总 9 个配置 × 4 rho 的结果，复用 Full Model / E1 / E4b 的既有缓存；E2 与新基线补齐；
6. 写只读脚本 `code/analyze_thresholds.py`，生成表 3a/3b 并与 comparison CSV 对齐；
7. README 重排：删 §5、6 行主表、插入阈值表、更新交叉引用；
8. 校验：表列数一致、数字自洽、无“实验二/成对/macro”残留引用、19 项测试通过。

## 7 明确不做

- 不实现 DeepMatcher（中文适配成本高，深度实体匹配由 Ditto 代表）；
- 不补成对分类实验；
- 不把旧 `LightGBM + POI` 和 `LightGBM Text/Structure` 作为独立主表方法（分别归入 E1 和 E1+E2 组合对照，放附录）；
- 不改变阈值选择方案（继续 validation 直方图最大 F1）；
- 不删除已有结果 CSV 与缓存；
- 主表固定 6 行，不删减现有 5 个基线。

## 8 风险与说明

| 风险 | 处理 |
|---|---|
| 阈值在高分段敏感 | 阈值表如实呈现，正文定位为工作点选择问题，不是模型能力结论 |
| rho=0.6 正例误拒率 51.6% | 写入限制，不写进优势表 |
| E4b 为退化对照 | 明确不能作为“结构特征能力”的结论 |
| 深度基线训练/推理成本 | 每个 rho 重训 Ditto、BGE-M3 重新编码；GPU 在执行前开启，时间不预先写死 |
| 基线与 Full Model 的输入差异 | 基线不使用 POI 外部资产，正文必须声明这是优势来源之一，避免被指“比较不公平” |
| 规则基线与主模型在 rho=0 接近 | 优势主张限定为“名称缺失下的鲁棒性”，不宣称自然条件下大幅领先 |
| 深度基线可能强于 Full Model | 结果由实验决定，不预设 Full Model 全胜；若某档落后，如实报告并解释证据来源差异 |

## 9 执行记录（2026-11-25）

- 环境：Python 3.12；torch 2.5.1+cu124（RTX 4060 Laptop 8GB）；transformers 4.49.0；模型 BAAI/bge-m3 与 hfl/chinese-roberta-wwm-ext 已下载到 .audit_work/models。
- 全库主实验：ull_candidate_cache_v6 / ull_library_results_disk_v6，5 个配置（主字段精确匹配、Full Model、E1、E2、E4b）× 4 个 rho = 20 次运行。
- 外部基线：aseline_results_full，4 个基线（Fellegi-Sunter、BM25F、BGE-M3、Ditto）× 4 个 rho = 16 次运行。Ditto 采用全库 432×3,260 打分，每个 rho 重训；8GB 共享显存下总耗时约 3.5 小时。
- 合并结果：ull_library_results_disk_v6/full_candidate_comparison_all.csv，9 配置 × 4 rho = 36 行；query-set 文件共 36 个。
- 阈值表：code/analyze_thresholds.py 生成 	hreshold_tables.json，并写入 README §4.4。
- README 已按本计划重排：删除实验二与双协议比较，主对比 6 行（5 基线 + Full Model），消融 4 行，新增阈值表；19 项测试通过。
- 未使用 git。
