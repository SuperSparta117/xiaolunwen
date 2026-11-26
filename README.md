# 主实验计划与结果：跨源物理地点实体解析与拒识

## 1 研究目标

### 1.1 核心问题

给定来自两个业务系统的两条记录，判断它们是否描述同一个现实中的物理地点，并找出对应关系；如果候选侧不存在这个地点，则输出空集合并拒识。

这不是“两个字段是否相等”的表连接问题，而是**跨源物理地点实体解析**（cross-source physical-place entity resolution）：同一地点在不同系统中可能有不同的名称、地址格式、行政区划写法、字段缺失和结构表达。

**实体粒度约定：**一期、二期和不同组团默认是不同的物理地点实体；不带期次的整体名称（例如“龙湖花园”）表示覆盖其各期的项目级名称或名称族，可以对应多个期次候选。整体名称与期次之间记录为项目包含关系，不等同于期次级 exact match；同名本身不能证明期次、组团或地址级实体相同。

模型的输入由任务配置决定，可以包括两张异构表、字段映射、已有索引或关系信息，以及允许使用的外源地理资产。每种信息的可用范围、使用阶段和是否属于模型输入，必须在新系统的配置与论文中显式记录。

### 1.2 统一输出

对每条查询记录 `q`，候选侧记录集合记为 `B`。系统输出：

- 每个候选对 `(q,b)` 的匹配分数 `p(q,b)`；
- 查询记录对应的候选集合 `S(q)`；
- 拒识结果：`S(q)=∅`。

不预设 1:1。一个查询可以对应多个候选；一个候选也可能与多个查询有关。输出集合必须由验证集确定的阈值和集合规则产生，测试集不得参与调阈值。

### 1.3 系统分为三个阶段

1. **候选召回**：从候选表中召回可能对应的记录，保证真实候选尽可能进入候选池；
2. **成对匹配**：对每个 `(q,b)` 融合名称、地址、空间、行政区划和结构字段证据，输出匹配分数；
3. **集合预测与拒识**：根据验证集冻结的阈值和集合规则输出 `S(q)`；没有可靠候选时输出空集合。

三个阶段分别评估。候选没有被召回属于候选生成失败，不能混同为排序模型失败。

围绕“候选召回 → 成对匹配 → 集合预测与拒识”三个阶段，本文把评估集中在一个正式协议上：**全库候选集合评估**。每个 test query 对全部 3,260 个候选打分，按 validation 阈值输出集合 `S(q)`，再按集合计算 Precision / Recall / F1。该协议同时覆盖排序与集合/拒识两个环节；不另外构造独立成对测试集，也不把成对判别指标与集合指标混合报告。

| 项 | 内容 |
|---|---|
| 评估对象 | 432 个 test query × 全部 3,260 个候选 = 1,408,320 个 query-candidate pair |
| 输出 | 每个 query 一个候选集合 `S(q)`（可以为空，表示拒识） |
| 指标 | pair-level（micro）Precision / Recall / F1，另报告覆盖率与正例误拒率 |
| 阈值 | 仅由 validation 完整候选集确定，test 不参与 |
| 遮蔽 | 名称字段四档遮蔽 `rho ∈ {0, 0.3, 0.6, 1.0}` |

### 1.4 论文主张边界

论文主张限定为：在给定候选库、字段映射和外源地理资产的条件下，建立一个能够融合多源证据、处理字段缺失和冲突、对新记录进行推理，并在候选侧不存在对应地点时拒识的跨源物理地点实体解析方法。

本文不声称解决任意城市、任意业务表的通用地点解析；所有结论限定在数据字段、空间范围、候选库和外源资产条件内。

## 2 数据事实与评测集

### 2.1 已核实的数据事实

> 以下事实来自当前数据核查，是实验设计依据。数字发生变化时，必须先更新数据版本和本节核算。

| 项目 | 事实 | 实验影响 |
|---|---|---|
| 规模 | A：物业处 8,782 / 房交处 3,260；B：征收处 28,101 / 奥格 28,101 | A、B 是同级评测任务；候选侧规模是主要计算约束 |
| A 关系形态 | 非 1:1；query 侧最多 5 个 pair，平均 1.05 pair/query | 必须按集合输出，不能假设一对一 |
| A 金标准 | 3,026 个 pair，覆盖 2,883 个 query；其中 2,709 个原始标注 pair、317 个外源补全 pair | pair 和 query 必须分开计数；按 provenance 分层报告 |
| A 标签核算 | 已确认正例 2,822 个 query / 2,965 个 pair，其中正例坐标不可用 61 个 pair | 恒等式：`2,965 + 61 = 3,026` 个 pair；`2,883 + 5,899 = 8,782` 个 query |
| A mapping 覆盖 | 8,782 个 query 中 2,883 个在 mapping、5,899 个未覆盖；未覆盖中负例坐标不可用 216、近处待核验 215、同名未配对 156 | 未覆盖不等于空集；未核验样本保持 `unknown`，不得直接作为拒识负例 |
| A 名称一致率 | 3,014 / 3,026 = 99.6%（pair 级） | 自然正例存在名称捷径，必须加入同名异地和名称遮蔽切片 |
| A 名称变体 | 15 条（0.5%） | 自然数据中的异名样本不足，不能单凭自然集声称异名解析能力 |
| A 已复核错误 | 878 条可疑对逐条复核，已知标注错误 0 条 | 主要风险是金标准不完整和证据来源混合，不是已知错标 |
| 坐标系 | 房交原始面坐标为 CGCS2000/WGS84；POI 坐标为 GCJ-02 | 距离计算前必须完成坐标转换并记录版本 |
| B 字段同值率 | 主要同行字段高度同值；地址同行相等率 100%，房屋用途为 97.3021%；`id`、奥格编号和地址均存在重复；原始数据无天然空集 | B 与 A 同级评测但单独报告；不得使用行号、编号或同行关系作为实体键；空集需按固定协议构造 |

### 2.2 版本化数据资产

实验开始前冻结并版本化：

- `gold_pairs`：pair 级金标准；
- `gold_sets`：每个 query 的完整 `G(q)`；
- `evaluation_queries`：全量 query 及标签状态；
- `candidate_pool`：完整候选池及版本；
- `split_manifest`：实体簇与 train/validation/test 划分；
- `mask_manifest`：遮蔽比例、query、seed 和派生字段处理；
- `feature_manifest`：字段白名单、黑名单和特征版本。

每条 gold pair 至少包含：

```text
query_id
candidate_id
gold_status
relation_granularity
provenance
evidence_source_id
annotator_or_script_version
verified_at
split
```

每条 query 还必须包含：

```text
query_label_state  # complete_positive_set / confirmed_empty / unknown
label_completeness
negative_evidence_status
review_status
coordinate_status
```

`unknown` 不自动等同于 `confirmed_empty`，不进入训练负例、确认标签主指标、拒识阈值选择或概率校准。

`provenance` 至少区分：

- `original_annotation`：原始业务标注；
- `external_derived`：依赖外源地理结果形成或补全；
- `independent_review`：不展示同一模型输入中的外源证据而完成的独立复核。

### 2.3 A 任务的全量核算

query-level 标签必须与证据和坐标状态分开记录：

- **`complete_positive_set`**：存在完整且非空的 `G(q)`；
- **`confirmed_empty`**：仅由独立排除证据确认 `G(q)=empty`；
- **`unknown`**：当前 mapping 未覆盖、候选覆盖不足、证据不足或存在冲突，不能自动视为负例；
- **坐标状态**：单独记录，坐标不可用不改变实体标签。

原有“强负例/弱负例”是证据或构造类别，不在完成独立排除前直接等同于 `confirmed_empty`；`5,899` 只表示当前 mapping 未覆盖的 query 数，不表示已确认候选侧不存在对应地点。

`unknown` 和尚未完成核验的未覆盖 query 不进入训练负例、确认标签主指标、TN/拒识率或阈值校准。只有形成逐 query 的独立排除证据后，才可从 `unknown` 升级为 `confirmed_empty`。

主结果必须同时报告：

1. 全量业务覆盖：8,782 个 query 的标签状态、unknown、坐标不可用和待核验数量；
2. 已确认标签性能：仅对确认标签计算正式指标，并报告筛选比例；
3. 证据来源切片：`original_annotation`、`external_derived`、`independent_review` 分层；
4. 坐标可用与不可用切片：坐标不可用样本不能静默删除，应进入文本/结构匹配和拒识分析；
5. 待核验样本：不计入确认标签主分数，但报告数量、抽样复核结果和 unknown 比例。

强负例若使用名称相似度和距离构造，必须明确其为协议规定的反事实负例；另行报告不依赖同一名称阈值的人工或独立证据负例敏感性分析。

### 2.4 Hard Challenge

自然评测集用于反映业务分布；Hard Challenge 单独用于检验物理地点歧义和抗名称捷径能力，不与自然集合并为一个总分。

困难类别包括：

| 类别 | 内容 | 标签要求 |
|---|---|---|
| P1 | 名称变体正例：简称、前后缀、分隔符、轻微错写 | 人工或独立证据确认同一地点 |
| P2 | 同名消歧正例：同名候选中只有部分地点一致 | 按完整 `G(q)` 标注 |
| P3 | 主字段完整遮蔽正例 | 遮蔽前后标签不变 |
| P4 | 整体名称对应多个期次的正例 | 记录 `project_contains_phase`，允许集合输出 |
| N1 | 同名异地负例 | 独立证据确认不同地点 |
| N2 | 近距离异地负例：不同小区、期次或组团 | 至少保留可竞争候选 |
| N3 | 同区县/同街道但不同物理地点 | 不把行政中心当精确地点 |
| N4 | 整体名称下不同期次或不同组团的近邻负例 | 例如一期与二期默认不同实体 |
| P5/N5 | 坐标不可用的可确认正例/负例切片 | 坐标不可用不能自动当负例 |

Hard Challenge 的每条记录至少包含：

```text
query_id
gold_candidate_ids
label
difficulty
name_sim
distance_m
admin_match
coords_trust
evidence_source
provenance
annotation_status
split
mask_seed
```

无法独立确认的样本标记为 `unknown`，不计入确认标签主分数，另报抽样结果。若困难样本只出现在测试集，报告为 OOD stress test；若要解释为常规能力，训练和 validation 也必须包含实体不重叠的同类样本。

### 2.5 主字段遮蔽

遮蔽比例统一设为：

```text
rho in {0, 0.3, 0.6, 1.0}
```

同时报告两种协议：

- `fixed_pool`：候选池在未遮蔽输入上冻结，遮蔽只作用于成对特征和排序，评估固定候选池上的条件性能；
- `end_to_end`：遮蔽后同步清除名称、期次名称、重复拼接片段、召回索引和缓存文本，并重新执行候选召回；这是主结果协议。

query 侧和 candidate 侧执行相同的遮蔽协议。两种协议复用同一 `mask_manifest`，但分别保存候选池版本和召回指标。`fixed_pool` 只能解释为排序诊断，`end_to_end` 才能解释为字段缺失下的完整系统鲁棒性。

当主字段被遮蔽时，同时清除：

- 原始主字段；
- 规范化主字段；
- 期次、组团和拼接字段中的重复名称；
- 地址或 POI 查询文本中的重复名称片段；
- 由主字段派生的缓存文本和召回索引。

遮蔽后的结果报告为字段缺失鲁棒性，不表述为自然缺失分布的无偏估计。

## 3 方法方案

本项目最终采用“统一记录视图 -> 多路候选池 -> 成对特征 -> 成对模型 -> 验证集阈值 -> 集合输出”的六步流程。实现过程中对原计划作了两项重要工程化调整：完整候选库评分改为逐 query、逐候选分批计算并持久化到可恢复的磁盘 score cache（`.audit_work/full_candidate_cache_v6`），避免将 432 × 3,260 的预测字典同时留在内存；名称遮蔽实验同时保留 `fixed_pool` 诊断协议，并将名称遮蔽后的候选召回作为单独的 `end_to_end` 协议，避免混淆“排序退化”和“候选生成退化”。

```text
① 异构输入 + 字段映射
              |
              v
② 标准化统一记录视图 + POI 可信判定
              |
       +------+------+
       |             |
       v             v
③ 多路候选召回    ④ 成对特征和分层负例
       |             |
       +------+------+
              v
⑤ 规则 / 逻辑回归 / LightGBM 成对评分
              |
              v
⑥ validation 阈值 -> 完整候选集合 -> 拒识诊断
```

### 3.1 统一记录视图与坐标可信判定

任务 A 的 query 来自物业处 SQL（`village_id`、`village_name`、`area_name`、`street_name` 等），候选来自房交 CSV（`愉悦安`、`小区名`、`区县`、`地址`、`物业类型`）。`code/er/config.py` 固定原始文件路径与任务字段，`code/er/io.py` 按真实 INSERT 列名解析 SQL，两侧统一为：

```python
{
    "id": "源内稳定记录 ID",
    "name": "规范化小区名称",
    "area": "规范化区县",
    "street": "规范化行政街道",
    "address": "可用时的规范化地址",
    "type": "物业类型",
    "lng": "经度（若可用）",
    "lat": "纬度（若可用）",
    "coords_trust": "坐标可信布尔值",
    "poi_district": "POI 解析区县",
}
```

原始 ID 只用于追踪和 mapping，不进入模型特征；A 的 SQL 源没有独立地址列，查询侧 `address` 恒为空，因此地址证据不能被解释为完整双侧地址匹配。

任务 A 的召回主字段是整体项目名称/小区名称，实体判定字段是期次、组团、地址、行政区划、可信空间证据和结构字段；任务 B 的主匹配字段是 `征收处_房屋地址` ↔ `fwxxdz`，原始数据保留同行结构。A、B 分别报告、不合并总分，B 的留空负例按固定协议构造。

外源 POI 资产按 `(来源, 记录ID)` 连接两侧。`code/er/geo_asset.py` 复用冻结资产中的“可信/不可信原因”，并按侧使用不同判据：物业处看坐标是否在重庆范围、解析 `level` 是否可信、解析区县是否与业务区县一致；房交坐标来自面坐标质心、没有 `level`，改看面坐标包围盒对角线是否 < 1000m 且逆地理编码区县是否与登记区县一致。当前资产 12,042 条记录中 9,451 条可信（物业处 6,329 + 房交 3,122），可信标记和不可信原因写入地理 manifest。

只有两侧坐标都可信时才计算 Haversine 距离、距离分档和 `poi_district_match`；不可信坐标保留原因，不填为 `(0,0)`，不生成空间证据。mapping 中的原始标注和外源补全在 gold manifest 中分为 `original_annotation` 与 `external_derived`；未覆盖 query 保持 `unknown`，判定规则见 §2.2。

每条外源结果还必须记录用途（`external_used_for_label` / `external_used_for_candidate` / `external_used_as_feature`）；既参与 gold 确认又进入特征的样本，须由不展示该结果的人工或第二来源复核，或标为 `external_derived` 单独报告。外源快照在标签确认、split 和调参前冻结。

行政中心特征：把 query 的业务 `(区县, 街道)` 与房交的 `(高德区县, 乡镇街道)` 按「等价区县类 + 规范化行政原名」解析到资产二中心；当前 query 侧 8,780/8,782、candidate 侧 3,260/3,260 解析成功，2 条脏区县记录无法解析。两侧都解析成功才计算中心距离；v5 资产中 4 个未解析 pair 用 `-1` 哨兵编码。审计见 `code/geo_assets/admin_center_audit.json`，独立性预检见 `code/geo_assets/admin_center_precheck.json`。

### 3.2 多路候选召回与两个遮蔽协议

自然候选池由名称字符 n-gram、地址字符 n-gram、区县和其他结构通道取并集生成；可信 POI 还通过 2 km 网格及相邻 8 个网格召回。`code/build_candidates.py` 输出候选池、通道来源、候选版本、`candidate_recall_at_k.csv` 和通道增量覆盖率。

名称捷径诊断发现自然名称 n-gram Recall@10 约为 99.83%，因此加入实体级固定 seed=42 的 `rho in {0, 0.3, 0.6, 1.0}` 遮蔽：

两个协议的定义、清除范围和报告口径见 §2.5；本节只区分用途：`fixed_pool` 隔离排序对名称的依赖，`end_to_end` 测完整系统鲁棒性。

四档完整候选库结果采用前者，因此其候选召回率恒为完整库条件下的 100%，不能当作 `end_to_end` 召回结论。

### 3.3 按命令展开的真实数据流示例

本节严格按实际执行命令展开，分为两个阶段：命令一至三是测试阶段（回归测试、小样本流程冒烟、小样本金标准资产生成），不会构成正式实验结果；命令四至六是使用全量数据准备正式实验资产；命令七才运行完整候选库四档遮蔽模型评估并生成正式结果。为追踪端到端数据流，使用一个真实测试 query `1680855546638295042` 和它的两个真实 gold candidate：`3556656f402e943645de829cc3fe6b17`、`72fb5d015b2cd8492ca8d9c7918e45ea`。该 query 在原始 SQL 中确实存在，mapping 中确实对应这两个候选，其中一条来源标为原始标注，另一条来源标为外源补全。由于当前终端读取中文源文件时可能显示编码替代字符，下面不把乱码强行反解为中文地名，而以稳定 ID、文件字段和生成的 CSV 为准。命令示例均从仓库根目录执行。

阶段分界：

| 命令 | 阶段 | 输入范围 | 产物用途 |
|---|---|---|---|
| 一：单元测试 | 测试 | 固定小型测试夹具 | 验证代码行为 |
| 二：冒烟测试 | 测试 | 12 query、最多 48 candidate | 验证流程可运行 |
| 三：小样本金标准 | 测试 | 12 query、48 candidate、20 mapping | 检查资产格式与标签政策 |
| 四：地理资产审计 | 正式资产准备 | 全量 POI / 行政地理资产 | 冻结正式实验使用的外源资产 |
| 五：实体划分 | 正式资产准备 | 全量 gold mapping | 生成防泄漏 split |
| 六：成对训练资产 | 正式资产准备 | 全量记录、mapping、split 和 POI | 生成 train/validation/test 特征数据 |
| 七：完整候选库实验 | 正式实验 | 全量训练资产及 3,260 candidates | 生成四档比较表和 query 集合 |

#### 3.3.1 命令一：运行回归测试（测试）

```text
py -m unittest discover -s code/tests -v
```

这条命令不读取全量业务数据，也不生成论文结果。`unittest discover` 在 `code/tests` 下寻找测试文件，验证标准化、候选生成、地理计算、标签状态、遮蔽和 split 等基础函数。实际结果为 19 项测试通过；例如测试会验证 `龙湖花园一期` 的名称标准化、候选 `b1` 能被名称通道召回，以及集合阈值 `0.72` 能输出分数 `0.8` 的候选。这里的 `q`/`b1` 是测试代码中人工构造的 fixture，不是业务数据。该命令把源码行为转换成可重复的“代码契约”，失败时后续资产不能视为可靠。

#### 3.3.2 命令二：12 条样本冒烟测试（测试）

```text
py code/smoke_test.py --sample-size 12
```

`--sample-size 12` 使 `run_sample_pipeline()` 读取前 12 条物业 query；当前冒烟测试代码内部把候选读取上限写成 `sample_size * 4`，因此这次对应前 48 条房交 candidate，并读取有限 POI。这个“4 倍”不是业务规则、模型假设或评测协议，也不是因为每个 query 理论上只对应 4 个 candidate；它只是为了让小样本测试中候选侧比 query 侧更大，能够实际走一遍候选召回、成对特征和集合输出路径，同时把运行时间控制在很小范围内。

因此，`12 -> 48` 在当前 `smoke_test.py` / `run_sample_pipeline()` 入口中是**代码写死的冒烟测试启发式比例**，用户不能通过 `--sample-size` 单独改变这个倍数：改成 `--sample-size 20` 会读取 20 条 query 和 80 条 candidate，改成 `--sample-size 5` 会读取 5 条 query 和 20 条 candidate。它不代表正式实验的候选池大小，也不能据此计算 `candidate_recall@K` 或论文指标。冒烟测试只验证流程能否贯通；正式候选池命令使用 `build_candidates.py` 的 `--query-limit`、`--candidate-limit` 和 `--k` 显式控制读取规模，完整候选库实验则使用全部 3,260 条 candidate。

对当前 `12 -> 48` 的运行，每条样本 query 会从这 48 条 candidate 中得到候选池，再为每个候选产生 `candidate_id`、`probability`、特征和 `recall_sources`。命令输出 `task=A`、实际 sample size、candidate rows、pair rows 和警告 `unknown is not confirmed_empty`，并把汇总写到 `code/sample_output/sample_report.json`。这一命令确认“原始文件 -> 统一记录 -> 候选 -> 特征 -> 集合”的数据类型和字段能贯通，但它不是正式指标。

#### 3.3.3 命令三：生成小样本金标准资产（测试）

```text
py code/build_evaluation_assets.py \
  --query-limit 12 \
  --candidate-limit 48 \
  --mapping-limit 20 \
  --output-dir code/_smoke/evaluation_assets
```

这条命令从相同原始数据读取 12 条 query、48 条候选和 20 条 mapping，生成四个文件：

```text
code/_smoke/evaluation_assets/
  gold_pairs.csv
  gold_sets.csv
  evaluation_queries.csv
  manifest.json
```

对真实 query `1680855546638295042`，如果它在这 12 条 query 和前 20 条 mapping 范围内，`gold_pairs.csv` 会把 mapping 的每一条 pair 变成一行，并保留 `match_type`、`source`、`confidence`、距离和备注；`gold_sets.csv` 会把该 query 的两个 candidate ID 聚合为一个 JSON 集合。`evaluation_queries.csv` 则写 `complete_positive_set`、gold 数量、provenance 和 coordinate status。若 query 不在有限范围，代码会写 `unknown`，而不是假造空集。`manifest.json` 还保存输入文件 SHA-256、读取限制和 mapping 重复检查，因此小样本阶段能确认标签政策和输出结构。

#### 3.3.4 命令四：审计并锁定外源数据 POI与行政地理，生成sha256指纹（正式资产准备）

```text
py code/audit_geo_assets.py --output-dir code/geo_assets
```

这条命令读取两张外源全量长表，并只生成一个 `code/geo_assets/geo_manifest.json` 审计报告，包含后续流程会用到的指纹(用来锁定数据文件的，只要改动，后续流程会报警)。**其中 `asset1_poi_coord.csv` 当前只包含任务 A 的两侧记录：物业处 8,782 条和房交处 3,260 条，不包含任务 B 的征收处或奥格记录；`asset2_admin_geo.csv` 是重庆行政区划及行政中心坐标参考表，不是任务 A 或任务 B 的业务记录表。**

命令对 POI 长表按 `(来源, 记录ID)` 检查记录键，统计总行数、可索引行数、来源分布、重复键数量以及可信/不可信原因分布；对行政区划长表检查中心坐标是否可解析，并统计总行数和可索引行数。报告还记录两张输入文件的路径和 SHA-256。

当前报告中的汇总结果为 POI 12,042 条、可信 9,451 条、重复键 0 个，行政区划记录 1,094 条。


#### 3.3.5 命令五：并查集区分实体并划分数据集（正式资产准备）

```text
py code/build_entity_splits.py \
  --output-dir code/split_manifest_full \
  --version split-v1
```

这条命令只有一个输入文件：邻接表`数据/A_mission_匹配映射_v2.csv`（3,026 行，SHA-256 `8a4bee5c0d9dbf3d15041e346f055495a59d3b9198b7e4f3877a1ee1a8e7caa5`），实际读取的字段只有 `sql_village_id` 和 `csv_yuyue_id` 两列 ID。**本命令不读任务 B**，映射路径由 `er/config.py` 的 `MAPPING_PATH` 固定。

**第 1 步** · 读边。 从邻接表 数据/A_mission_匹配映射_v2.csv 取两列 ID，得到 3,026 条 (小区ID, 房源ID)。

**第 2 步** · 并查集建实体。 由于源表格是多对多的，所以使用并查集算法，把每个物理实体分到一组，放在split_entities.csv 文件内（实际上第3步和第2步在代码里面是同时做的），里面内容如下。
```text
entity_type,entity_id,component_id,split,seed
query,1674362158372081665,component-000001,train,13
query,1680855546638295042,component-000002,test,13
query,1681204215828897794,component-000003,train,13
```
逐行解读
```text
query                           ← 被分类为 query 记录（只有query或candidate两类）
1680855546638295042             ← 它自己在源文件中的 ID
component-000002                ← 它被分到了 2 号物理实体
test                            ← 2 号组整体被分到 test数据集（划分为train validation test） 
13                              ← 这套划分是 seed=13 产生的
```

| 一组物理实体内构成 | 物理实体数  | 含义 |
|---|---|---|
| 1 query + 1 candidate | 2,754 | 普通一对一 gold |
| 1 query + 2 candidates | 107 | 一个小区对上两个房源 |
| 1 query + 3 candidates | 7 | 同上 |
| 1 query + 4 candidates | 6 | 同上 |
| 1 query + 5 candidates | 1 | 示例之外最"多对一"的一个 |
| 2 queries + 1 candidate | 4 | 两个小区同时主张同一个房源 |

**第 3 步** · 划分train/validation/test数据集
使用哈希排序（实际上就是一次随机）后，将数据集train validation test的物理实体各自划分为 2,015 / 432 / 432 即 70.0% / 15.0% / 15.0%，放在split_entities.csv 文件内。如果是"pair 单位"，train/validation/test 应该是 2,114 / 452 / 460；如果写"候选库单位"，是 2,111 / 451 / 460。

问：为什么必须整簇分，不能按 pair 随机分？
答：看那 4 个 2 queries + 1 candidate 的簇——同一个房源被两个小区都标成了 gold。如果按 pair 随机切，完全可能出现：query A 和这个房源在 train（模型见到这条正例），query B 和同一个房源在 test（模型又被要求再判一次）。模型等于背过了这个房源的名字和坐标，test 指标虚高，而且这种泄漏从结果上看不出来。

主结果报告两种协议：**跨记录归纳**（测试记录 ID 未在训练出现，但同一物理地点可能有另一条记录）与**跨地点归纳**（测试物理地点实体簇完全不出现在训练；论文主协议）。随机 pair 划分只作附录诊断；整体名称覆盖多个期次时，项目级名称与其期次实体进入同一实体簇；B 侧地址重复且确认属同一建筑物的记录共享 `entity_cluster_id`，原记录保留、不删行。使用 5 个固定 seed，方法之间配对复用 split、候选池、负例和 mask。


#### 3.3.6 命令六：构造train/vali/test的负例 并向量化（正式资产准备）

```text
py code/build_pair_features.py \
  --output-dir code/training_assets_full_v5 \
  --split-manifest code/split_manifest_full/split_manifest.json \
  --candidate-source full \
  --negative-ratio 3 \
  --split-seed 13
```
输入任务A的3个文件和外源的2个文件的excel表格，3个文件所属的任务A的mapping 里只有正例（3,026 条），一条负例标签都没有，所以需要构造。

构造负例，以 query_id=1852284257089507329 为例，它在 mapping 里只有一行（配 da915017… 明月小区）。要造 3 条负例（`--negative-ratio 3`设置的数量）：
**1.** 把同训练集(split) 的所有元素都当候选池：这个 query 在 train训练集中，train训练集有 2015个物理实体簇(共 2,111 个 candidate)；
**2.** 扣掉同物理实体簇的金标准gold：把这 1 条 gold（da915017… 明月小区）从池子里剔除 → 剩 2,110个candidate,共2014个物理实体；
**3.** 计算 16 维向量：放入 `pairs_train.csv`中

| # | 特征 | 怎么算 | 备注 |
|---|---|---|---|
| 1 | name_exact | 归一化名字相等且非空 → 1 | 会被 rho 遮蔽 |
| 2 | name_similarity | 归一化名字的字符二元组 Jaccard | 会被 rho 遮蔽 |
| 3 | address_similarity | 同样的 Jaccard，作用在地址上 | query 地址恒空 → 恒 0；无合法对称替代 |
| 4 | area_match | 区县字符串相等（应走别名/代管等价） |  |
| 5 | street_match | 行政街道/镇/乡一致（去后缀，不按文本相似度） | candidate 侧已由逆地理编码补全 |
| 6 | coords_available | 距离算得出来 → 1 |  |
| 7 | coords_trust_both | 两侧坐标都可信 → 1 |  |
| 8 | poi_distance_m | 距离（米）除以 2000，上限 10 | 158.1 m → 0.0791 |
| 9–12 | poi_distance_lt_100m / 100_300m / 300_1000m / gt_1000m | 距离分档 one-hot |  |
| 13 | poi_district_match | 高德区县相等 |  |
| 14 | type_match | 物业类型相等 |  |
| 15 | admin_center_distance_m | 两侧行政中心球面距离（米）除以 2000，上限 10 | 未解析记 -1；只在两侧解析成功时可用 |
| 16 | admin_center_same | 两侧解析到同一行政单元 → 1 | 单元 = 等价区县类 + 规范化行政原名 |

**3.** 按三个维度组合候选：先按 POI 距离升序（query 坐标周围 9 个网格、最近 30 个），再按名字相似度name_similarity降序，最后同区县兜底；三段是按优先级首尾相接的一条队列，先来的先筛掉，后来的不用；POI 距离近的行够多时，文本和区县通道对结果没有任何贡献。
**4.** 取前 3 条（3 × gold 数 = 3 × 1 = 3），写成 3 行 label=0、provenance=constructed_negative、match_type=full_hard_negative。

最后如果这个源query是train的，就都放入 `pairs_train.csv`。如果是另外两个数据集就放入对应的文件。结果就是 pairs_train.csv 里这 4 行：

| candidate_id | label | 候选名 | 候选区县 | poi_distance_m |...|
|---|---|---|---|---|---|
| da915017…f835 | 1 | 明月小区 | 垫江县 | 158.11 | ...|
| 252bfe53…1765 | 0 | 丽水南岸 | 垫江县 | 184.40 |... |
| 0931ed39…ae25 | 0 | 翠湖名都 | 垫江县 | 194.20 | ...|
| 4cafda4a…ffd45 | 0 | 滨湖郡 | 垫江县 | 265.19 | ...|


这 4 行的 address_similarity=0.0、street_match=0、poi_distance_lt_100m=0、poi_distance_100_300m=1 也写入 CSV。两项恒 0 的原因不同且都是**结构性**的：

- `address_similarity`：物业处 SQL 没有地址列，query 侧 `address` 恒为空，`similarity()` 任一侧为空即返回 0.0，因此**正例也为 0**；
- `street_match`：房交 CSV 没有街道列，candidate 侧 `street` 恒为空，比较式恒为假。

`street_match` 已在资产侧修复：对房交已冻结的面坐标质心做逆地理编码，补出行政街道与 `高德区县`（3,260/3,260，坐标未改动），使 `street_match` 在现有成对资产上的正例命中达到 94.1% / 91.6% / 91.7%（train/validation/test）、负例 58.9% / 34.0% / 38.0%。地址侧没有合法的对称定义（粗粒度街道不能推细粒度门牌），应改为单向的行政一致性特征或删除。下表是**补全前**的字段快照：
| 字段 | query（物业处 SQL） | candidate 负例（房交 CSV） |
|---|---|---|
| name | 明月小区 | 丽水南岸 |
| area | 垫江县 | 垫江县 |
| street | 桂阳街道 | （空字符串） |
| address | （空字符串） | 丽水南岸6栋1单元1楼 |
| type | 住宅（纯住宅） | 住宅 |

补全后，candidate 负例的 `street` 变为逆地理编码得到的行政街道（同一批垫江县记录多为 `桂阳街道`），`poi_district_match` 也随之可用；query 侧仍没有地址，`address_similarity` 保持恒 0。

输出为：

```text
pairs_train.csv       # 8,454 rows
pairs_validation.csv  # 1,788 rows
pairs_test.csv        # 1,835 rows
feature_manifest.json # 只记字段白名单、输入哈希、负例政策，不存任何向量
```

#### 3.3.7 命令七：四档遮蔽跑主实验

```text
py code/run_full_library_experiment.py \
  --data-dir code/training_assets_full_v5 \
  --cache-dir .audit_work/full_candidate_cache_v6 \
  --output-dir code/full_library_results_disk_v6 \
  --mask-ratios 0,0.3,0.6,1.0 \
  --seed 42 \
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

四个外部基线（Fellegi-Sunter、BM25F、BGE-M3、Ditto）由命令八单独运行，使用同一批候选、同一 split、同一遮蔽标记和同一 validation 阈值选择。

**3.** validation 定阈值：阈值计算方式与之前一致——把 validation 完整候选集的分数放进 20,000 个桶，累计正负例数量，从高到低扫描确定最大 F1 切点。validation 被用了两次（早停监控 + 选阈值），因此阈值指标存在轻微乐观偏差，应说明这是 validation-tuned 而非 test-tuned。

**4.** test 预测打分：用 validation 阈值切 test 候选集合并计算指标，test 不参与调参。

#### 3.3.8 命令七产生的正式结果文件如何被使用

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
py code/run_baselines_full.py \
  --data-dir code/training_assets_full_v5 \
  --output-dir code/baseline_results_full \
  --cache-dir .audit_work/baseline_cache \
  --methods fs,bm25f,bge,ditto \
  --ratios 0,0.3,0.6,1.0
```

四个外部基线都在全库候选协议上运行：对每个 query 评分全部 3,260 个候选，输出分数矩阵，再用 validation 阈值切集合、用 test 计算指标。

| 基线 | 输入与打分口径 |
|---|---|
| Fellegi-Sunter | 名称/地址（字符二元组相似度分级）、区县、街道、类型作为比较字段；用训练集估计匹配/非匹配条件下的比较级概率，按对数似然比汇总 |
| BM25F | 名称/地址/街道/区县/类型作为独立字段索引；字段权重固定，字符二元组词项 |
| BGE-M3 | `BAAI/bge-m3` 稠密向量，名称/地址/区县/街道/类型序列化后编码，cosine 相似度打分 |
| Ditto | `hfl/chinese-roberta-wwm-ext` cross-encoder，字段序列化后拼接，二分类微调，输出匹配概率 |

四个基线只使用名称/地址/区县/街道/类型字段，不使用 POI 外部资产；名称遮蔽时名称字段置空（与 Full Model 的名称特征置零对应）。每个 rho 下四个基线都使用与 Full Model 相同的遮蔽训练集重训（BGE-M3 不训练，只对遮蔽文本重新编码），阈值同样只由 validation 选择。把 POI/行政地理证据加入 Ditto 输入的重训版见 §5。

### 3.4 结果资产和复现顺序

按 §3.3 的命令一至八依次执行；结果、manifest、query 集合和审计文件必须与 `rho`、split seed、数据版本和候选库协议一同保存。

## 4 任务A实验：完整候选库集合评估

### 4.1 设置

以下结果来自 A 任务完整候选库穷举评估，覆盖每个测试 query 的全部 3,260 个房交候选。测试集为 432 个已映射正例 query，共 1,408,320 个 query-candidate pair；另外 5,899 个未映射 query 保持 `unknown` 并排除。映射完整性假设下，未列入现有 mapping 的候选暂按负例计，因此这些指标是条件性评估，不能当作已独立确认的负例结论。

- 训练资产：`code/training_assets_full_v5`
- 完整候选库结果：`code/full_library_results_disk_v6/full_candidate_comparison_all.csv`
- 外部基线结果：`code/baseline_results_full/baseline_comparison.csv`
- 名称遮蔽比例：`rho ∈ {0, 0.3, 0.6, 1.0}`；实体级确定性遮蔽，seed=42
- split：gold 图连通分量划分，seed=13；validation 433 个正例 query，test 432 个正例 query
- 各模型阈值仅依据 validation 完整候选集选择
- **主模型**：Full Model = LightGBM + 文本/结构特征 + POI + 两维行政中心特征
- **外部基线**：规范化主字段精确匹配、Fellegi-Sunter、BM25F、BGE-M3、Ditto（中文 RoBERTa）；它们只使用名称/地址/区县/街道/类型字段，**不使用 POI 外部资产**。Full Model 的优势因此包含外部地理证据，正文按此口径解释（Ditto 加入 GEO 证据的重训版单独见 §5）
- **消融**：E1（去掉两维行政中心）、E2（去掉 POI、保留行政中心）、E4b（全特征关闭，退化对照）

名称遮蔽作用于训练、validation 和 test 的名称成对特征。该实验仍是 `fixed_pool` 排序/集合输出评估，不等于名称遮蔽后同步重新生成名称召回索引的 `end_to_end` 实验。`rho=1.0` 的精确匹配基线会对每个候选给出相同的零分，validation 选出的阈值因此可能输出全部候选，不能把其 100% recall 解读为有区分能力。

### 4.2 主对比（全候选集合评估）

本节是**正式的全候选库实体解析主对比**：6 个方法（5 个独立基线 + Full Model）对每个测试 query 逐一评分全部 3,260 个候选，再按 validation 阈值输出候选集合。负例是该 query 的完整候选库中未被 gold mapping 标注的 candidate；评估的是“一个 query 最终返回哪些 candidate”的集合质量。

每格为 **pair-level（micro）** Precision / Recall / F1（%），不是 query-level 指标。

| 方法 | rho=0 P/R/F1 | rho=0.3 P/R/F1 | rho=0.6 P/R/F1 | rho=1.0 P/R/F1 |
|---|---:|---:|---:|---:|
| **Full Model** | 94.59 / 98.91 / 96.71 | 94.14 / 66.30 / 77.81 | 95.91 / 45.87 / 62.06 | 98.10 / 33.70 / 50.16 |
| 主字段精确匹配 | 91.38 / 99.13 / 95.10 | 88.66 / 47.61 / 61.95 | 84.15 / 15.00 / 25.46 | 0.03 / 100.00 / 0.07 |
| Fellegi-Sunter | 94.58 / 98.70 / 96.60 | 92.77 / 47.39 / 62.73 | 92.00 / 15.00 / 25.79 | 0.03 / 100.00 / 0.07 |
| BM25F | 89.90 / 94.78 / 92.28 | 88.19 / 45.43 / 59.97 | 40.08 / 21.09 / 27.64 | 8.72 / 37.39 / 14.14 |
| BGE-M3 | 85.91 / 96.74 / 91.00 | 76.28 / 41.96 / 54.14 | 30.40 / 16.52 / 21.41 | 6.10 / 38.48 / 10.54 |
| Ditto (Chinese RoBERTa) | 92.77 / 97.61 / 95.13 | 91.95 / 47.17 / 62.36 | 9.51 / 31.96 / 14.66 | 0.05 / 6.30 / 0.11 |

rho=0 时最强基线为 Fellegi-Sunter（F1 96.60），Full Model 为 96.71；rho=0.3 时最强基线为 Fellegi-Sunter（F1 62.73），Full Model 为 77.81；rho=0.6 时最强基线为 BM25F（F1 27.64），Full Model 为 62.06；rho=1.0 时最强基线为 BM25F（F1 14.14），Full Model 为 50.16。

需要说明：`rho=1.0` 时规则基线、Fellegi-Sunter 与 Ditto 的 validation 阈值分别退化为“输出全部候选”或“几乎不输出”，其 100%（规则/FS）与 6.30%（Ditto）的 recall 不代表有区分能力；该档比较以 F1 为准。Ditto 与 Full Model 的专项对比（含把 POI/行政地理证据直接输入 Ditto 的重训版）见 §5。

### 4.3 消融

消融只改变 Full Model 的单一组件；Full Model 行复用主对比结果，不重复计数。

| 消融设置 | rho=0 P/R/F1 | rho=0.3 P/R/F1 | rho=0.6 P/R/F1 | rho=1.0 P/R/F1 |
|---|---:|---:|---:|---:|
| **Full Model** | 94.59 / 98.91 / 96.71 | 94.14 / 66.30 / 77.81 | 95.91 / 45.87 / 62.06 | 98.10 / 33.70 / 50.16 |
| E1 remove admin center | 92.74 / 100.00 / 96.23 | 94.12 / 66.09 / 77.65 | 95.63 / 47.61 / 63.57 | 98.08 / 33.26 / 49.68 |
| E2 remove POI | 94.59 / 98.91 / 96.71 | 93.07 / 46.74 / 62.23 | 71.43 / 17.39 / 27.97 | 4.15 / 91.96 / 7.93 |
| E4b 全特征关闭 | 0.03 / 100.00 / 0.07 | 0.03 / 100.00 / 0.07 | 0.03 / 100.00 / 0.07 | 0.03 / 100.00 / 0.07 |

- **POI 是名称缺失条件下的主要增量**：与 E2（去掉 POI、保留行政中心）相比，Full Model 在 rho=0.3 / 0.6 / 1.0 的 F1 高 15.58 / 34.09 / 42.23 个百分点；rho=0 时两者持平（96.71），说明名称可用时 POI 不提供额外信息。
- **行政中心特征没有稳定增量**：E1 与 Full Model 的 F1 差在四个 rho 上均不超过 1.51 个百分点，且方向随 rho 变化（rho=0.6 时 Full Model 反而低 1.51 个百分点）。行政中心与 `street_match`/`area_match` 高度共线，这是可解释的负结果。
- **E4b 不能作为结构能力结论**：全部特征置零后模型退化为常数并输出全部候选（P 0.03% / R 100.00%），其 F1 0.07% 只反映退化行为。

### 4.4 阈值选择与工作点

阈值只由 validation 的完整候选集确定：把分数放进 20,000 个分桶，按正负例累计数扫描最大 F1 切点。test 只用于汇报，不参与任何阈值选择。

**各 rho 的选定阈值与工作点（Full Model）**

| rho | 选定 tau | validation F1 | test Precision | test Recall | test F1 | 覆盖率 | 正例误拒率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.786 | 98.47 | 94.59 | 98.91 | 96.71 | 99.1% | 0.9% |
| 0.3 | 0.902 | 78.80 | 94.14 | 66.30 | 77.81 | 69.0% | 31.0% |
| 0.6 | 0.910 | 59.70 | 95.91 | 45.87 | 62.06 | 48.4% | 51.6% |
| 1.0 | 0.929 | 47.91 | 98.10 | 33.70 | 50.16 | 35.4% | 64.6% |

**rho=0.6 的阈值明细**

| tau | validation F1 | test Precision | test Recall | test F1 | 覆盖率 |
|---:|---:|---:|---:|---:|---:|
| 0.7 | 16.61 | 9.45 | 76.30 | 16.81 | 91.4% |
| 0.8 | 39.75 | 34.10 | 54.57 | 41.97 | 67.8% |
| 0.85 | 36.97 | 35.28 | 50.00 | 41.37 | 63.9% |
| 0.88 | 38.40 | 40.36 | 48.70 | 44.14 | 56.2% |
| 0.9 | 38.12 | 40.65 | 48.70 | 44.31 | 56.2% |
| 0.905 | 37.62 | 40.44 | 48.26 | 44.00 | 56.0% |
| 0.908 | 35.56 | 39.63 | 46.52 | 42.80 | 54.4% |
| 0.91（验证集选定） | 59.70 | 95.91 | 45.87 | 62.06 | 48.4% |
| 0.912 | 58.19 | 95.79 | 44.57 | 60.83 | 47.2% |
| 0.92 | 58.19 | 95.79 | 44.57 | 60.83 | 47.2% |
| 0.95 | 57.81 | 95.88 | 40.43 | 56.88 | 42.8% |

需要如实说明的阈值行为：在 rho=0.6 时，`[0.90, 0.91)` 区间集中了 331 个候选且以假阳性为主，阈值从 0.908 提高到 0.910 时 Precision 从 39.63% 跳到 95.91%、覆盖率从 54.4% 降到 48.4%。这一定位为**工作点敏感**，不是模型能力结论：当前全局单一阈值偏保守，高遮蔽档下约一半正例 query 输出空集。覆盖率与正例误拒率因此作为限制报告，不放进优势结论。

### 4.5 输出核验与限制

已核对：36 个 comparison 组合（4 个 rho × 9 个配置：6 个主对比 + 3 个消融）；每个 query-set 文件均有 432 个唯一 query；各行 `prediction_count` / `gold_count` 与 JSON ID 列表长度一致；每个 rho 的 pair 混淆矩阵总数均为 432 × 3,260；预测列表无重复，且预测与 gold candidate ID 均属于标准化后的 3,260 条候选记录。

- `unknown` query 未作为负例，且本轮没有独立确认的 `confirmed_empty`，因此不报告严格拒识率或业务特异度。
- 非 mapping 候选按负例计仅在当前 mapping 完整的假设下成立；需人工复核抽样 FP/FN 后再作业务结论。
- `rho=0` 指不遮蔽名称；其余 rho 在训练、validation 和 test 数据中按实体哈希规则遮蔽。
- 固定候选库实验未改变候选召回，所以不能替代 `end_to_end` 名称遮蔽召回实验。
- A 查询侧没有独立地址字段；Full Model 与 E1 的差异只来自两维行政中心特征。
- 主对比中的外部基线不使用 POI 外部资产，这是 Full Model 的优势来源之一，不能把基线落后全部归因于模型结构；§5 的 Ditto + GEO 重训版使用该资产。

## 5 Ditto 与 Full Model 在任务A上的专项对比

### 5.1 两个 Ditto 变体

主对比（§4.2）中的 Ditto 只使用文本字段（名称/地址/区县/街道/类型），不使用 POI 外部资产。为回答“把 POI/行政地理证据直接输入 Ditto 能否超过 Full Model”，补充一个**重训版**：

| 变体 | 输入 | 是否使用外源资产 |
|---|---|---|
| Ditto（文本版） | 名称/地址/区县/街道/类型字段 | 否 |
| Ditto + GEO（重训版） | 文本字段 + GEO 证据 token | 是（与 Full Model 同一套） |
| Full Model | 16 维特征（文本/结构/POI/行政/行政中心） | 是 |

GEO 证据 token 包括：`area`（区县匹配）、`street`（街道匹配）、`coord`（坐标可用）、`trust`（坐标可信）、`pdist`（POI 距离分档）、`pdistmatch`（POI 区县匹配）、`type`（类型匹配）、`adist`（行政中心距离分档）、`asame`（行政中心一致）。Ditto + GEO 在每个 rho 下用同一套遮蔽训练对（8,454 条）重训 3 epochs，其余训练配置与 Ditto 文本版一致。

### 5.2 结果

| rho | Ditto 文本版 | Ditto + GEO（重训） | Full Model | GEO − Full |
|---|---:|---:|---:|---:|
| 0 | 95.13 | 96.38 | **96.71** | −0.33 |
| 0.3 | 62.36 | 51.36 | **77.81** | −26.45 |
| 0.6 | 14.66 | 61.34 | **62.06** | −0.72 |
| 1.0 | 0.11 | 57.44 | 50.16 | +7.28 |

rho=1.0 的差异不作为优势结论：该档是名称完全缺失的压力测试边界，F1 差异主要来自单一全局阈值下的工作点不同（见 5.3）。

rho=1.0 的明细（两种方法的 precision/recall 取舍）：

| 方法 | Precision | Recall | F1 | 覆盖率 | 正例误拒率 |
|---|---:|---:|---:|---:|---:|
| Ditto + GEO | 89.04 | 42.39 | 57.44 | 46.1% | 53.9% |
| Full Model | 98.10 | 33.70 | 50.16 | 35.4% | 64.6% |

### 5.3 解读

- **真实场景下 Ditto 不如 Full Model**：rho=0 / 0.3 / 0.6 三档（名称仍可部分或全部使用的常规条件）Full Model 的 F1 分别为 96.71 / 77.81 / 62.06，均高于 Ditto 文本版（95.13 / 62.36 / 14.66）和加入 GEO 证据的重训版（96.38 / 51.36 / 61.34）；rho=0.6 时 Ditto + GEO 只差 0.72 个百分点，但仍未超过。
- **rho=1.0 的“反超”不能作为优势**：该档是名称完全缺失的压力测试边界，真实业务数据中几乎不会出现两侧都没有名称、只能依靠地理证据判断的情况，因此不代表可用场景。该档 F1 差异也不是判别能力差异，而是单一全局阈值下的工作点不同：Full Model 覆盖率为 35.4%（正例误拒率 64.6%），Ditto + GEO 覆盖率为 46.1%（误拒率 53.9%），前者偏保守、后者多输出；再加上单 seed，不能据此声称 Ditto 更强。
- **分数融合不奏效（补充实验）**：把 Ditto 概率与 Full Model 概率做线性加权或逻辑堆叠，最好只在 rho=0 提升 +0.02、rho=0.3 提升 +0.15；rho=0.6 / 1.0 的权重完全落到 Full Model 上。说明 Ditto 的文本信号与 Full Model 的特征高度重叠。

### 5.4 结论与边界

真实场景（rho=0 / 0.3 / 0.6）下 Ditto 不如 Full Model，原因可归纳为三点：

1. **输入形态与归纳偏置不匹配**：真实场景的决定性证据是数值型地理/行政证据（POI 距离、距离分档、区县/街道匹配、行政中心距离与一致性、坐标可信度），Full Model 用 16 维数值特征 + GBDT 直接分裂；Ditto 只能把这些证据序列化成文本 token，损失数值精度与顺序信息，还要从小样本中自行学习阈值关系。
2. **训练样本不足**：Ditto 仅用 8,454 个 pair、3 epochs 从预训练权重微调，远未饱和；Full Model 的 16 维特征已注入领域知识（名称规范化、等价区县、街道键、距离分档），GBDT 在同样的小数据上即可稳定工作。
3. **名称遮蔽后主信号消失**：rho=0.6 时 Ditto 文本版从 95.13 跌到 14.66；加入 GEO token 后回升到 61.34，说明深模型确实能用地理证据，但仍低于 Full Model 的 62.06；rho=0.3 时训练不稳（51.36 低于文本版的 62.36），进一步说明小样本下深模型不如 GBDT 稳定。

rho=1.0 的边界结果由阈值/覆盖率差异造成、且场景不真实，不作为 Ditto 的优势主张；Ditto + GEO 为补充实验，不计入 §4 主对比的 36 个组合（结果目录 `code/ditto_geo_results/`）。

## 6 评估边界

1. 负例按现有 mapping 的完整性假设确定（未标注候选暂按负例计），不是独立确认的负例；因此指标是条件性评估。
2. `unknown` query 没有作为负例；当前没有足够的 `confirmed_empty` 样本，因此不报告严格拒识率、特异度或 TN-based 拒识指标。
3. pair-level 指标是对测试候选集合的汇总，不等同于逐 query macro 指标。
4. 当前 A 查询侧没有独立地址字段，地址相关特征不能被解释为双侧完整地址匹配。
5. `Full Model` 在 POI 与文本/结构特征基础上加入两维行政中心特征；其与 E1 的差异只来自这两维。
6. 当前遮蔽只清除成对名称特征，候选池保持不变；正式 `end_to_end` 主协议还应同步清除名称派生召回索引并重新生成候选池，本实验只解释为 `fixed_pool` 下的名称缺失鲁棒性。
7. 主对比中的外部基线（Fellegi-Sunter、BM25F、BGE-M3、Ditto 文本版）不使用 POI 外部资产；Full Model 与 §5 的 Ditto + GEO 重训版使用该资产，这是模型优势的来源之一。
8. 结果不得与未遮蔽自然集或不同 rho 的结果合并为一个总分；provenance 和坐标可信度必须分层报告。

## 7 可复现命令

```text
py code/run_full_library_experiment.py \
  --data-dir code/training_assets_full_v5 \
  --cache-dir .audit_work/full_candidate_cache_v6 \
  --output-dir code/full_library_results_disk_v6 \
  --mask-ratios 0,0.3,0.6,1.0 \
  --seed 42 \
  --split-seed 13

py code/run_baselines_full.py \
  --data-dir code/training_assets_full_v5 \
  --output-dir code/baseline_results_full \
  --cache-dir .audit_work/baseline_cache \
  --methods fs,bm25f,bge,ditto \
  --ratios 0,0.3,0.6,1.0

py code/merge_comparison.py
py code/analyze_thresholds.py

py code/run_ditto_geo.py \
  --ratios 0,0.3,0.6,1.0 \
  --output-dir code/ditto_geo_results
```

环境：Python 3.12、torch 2.5.1+cu124、transformers 4.49.0；BGE-M3 与中文 RoBERTa 权重从本地 `.audit_work/models` 加载（`BAAI/bge-m3`、`hfl/chinese-roberta-wwm-ext`）。

回归测试：19 项测试通过。

## 8 代码结构

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
| `code/run_ditto_geo.py` | Ditto 输入注入 POI/行政地理证据的重训实验（§5） |
| `er/pipeline.py`、`er/model.py`、`er/output.py` | 小样本基线流程 |
| `code/external/` | 外源资产重建：行政区划补全、区划表生成、复核清单、资产合并与命中率评估 |
| `tests/` | 19 项回归测试 |

