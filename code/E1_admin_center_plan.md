# E1 行政中心特征消融执行计划

## 目标

本计划验证行政中心证据的独立增量价值。

E1 只移除以下两维：

- `admin_center_distance_m`
- `admin_center_same`

`area_match`、`street_match`、`poi_district_match` 在 Full Model、LightGBM + POI 和 E1 中保持启用。它们属于行政一致性特征，不能由 `use_admin_center` 控制。

## 方法定义

完整候选库实验的现有七个方法，加上 E1 后按下表固定特征矩阵。规则方法只使用表中写明的单列分数，不隐式读取行政中心两维。

| 方法 | 文本特征 | POI 距离特征 | `area/street_match` | `poi_district_match` | 行政中心特征 |
|---|---:|---:|---:|---:|---:|
| 主字段精确匹配 | 仅 `name_exact` | 关 | 关 | 关 | 关 |
| TF-IDF-like Cosine | 仅 `name_similarity` | 关 | 关 | 关 | 关 |
| LightGBM Text/Structure | 开 | 关 | 开 | 关 | 关 |
| LightGBM + POI | 开 | 开 | 开 | 开 | 关 |
| Full Model | 开 | 开 | 开 | 开 | 开 |
| E1 remove admin center | 开 | 开 | 开 | 开 | 关 |
| E2 remove POI | 开 | 关 | 开 | 关 | 关 |
| E4b 全特征关闭 | 关 | 关 | 关 | 关 | 关 |

Full Model 与 LightGBM + POI 的差异只应来自两维行政中心特征。E1 与 LightGBM + POI 使用同一组特征配置。成对级实验已有的 Text/Structure Rule、Logistic 和 E4a 对照也必须显式标记行政中心特征为关。`full_library.methods` 必须新增 E1，不能只在 README 中添加名称。

## 阶段零：特征独立性预检（在阶段一解析器完成后执行）

阶段一解析器实现并通过单测后，直接调用同一解析函数，使用现有 `code/training_assets_full_v4/pairs_*.csv` 的 pair、label、`area_match` 和 `street_match` 做只读预检。禁止另写一套解析逻辑，预检与正式实现必须共用同一函数，避免口径不一致；不改写 v4 文件。

1. 按 `area_match`、`street_match` 分层，输出正负例的样本数、`admin_center_same` 比例、距离的中位数和分位数。
2. 在整体和各分层内分别计算两维对 `label` 的 AUC 和 KS，并记录缺失值处理方式。
3. 将预检结果写入独立审计文件或阶段报告，和 v4 的 feature manifest 一起保存。
4. 若 `admin_center_same` 在 `street_match=1` 中近似确定，或距离在 `street_match=0` 的正负例中高度重叠，则把“Full Model 与 E1 近似相同”定义为行政中心特征冗余的合法结论。

预检结论只决定结果解释和是否值得运行两小时的完整候选库实验，不改变 E1 的定义。只有当实现结果与预检预期矛盾时，才进入特征顺序、开关传播和数据写入排查。

## 阶段一：行政中心解析器

修改 `code/er/geo_asset.py`。

### 索引和解析顺序

`load_admin_asset()` 加载后建立模块级索引。索引保留以下信息：

- 规范化区县名
- 规范化行政区划名
- `street_key()` 去后缀键
- 中心经纬度
- 原始资产行

解析顺序固定为：

1. `(normalize_name(area), normalize_name(street))` 精确命中。
2. 同一区县或 `_area_equivalent` 等价区县内，使用 `street_key(street)` 回退。
3. 只有前两步未命中时，才进行全局街道名回退。
4. 全局回退只允许唯一街道名。多个区县命中时保留未解析状态，并记录歧义。

精确行政区划名必须优先于去后缀匹配。这样可以避免同一区县内的“南坪街道”和“南坪镇”被错误合并。

### 查询侧和候选侧来源

查询侧只使用业务字段 `area + street`。物业处的 POI `township` 没有独立于业务 `street_name` 的第二来源，因此不能描述为查询侧回退来源。业务字段无法解析时保留未解析状态。

候选侧使用 POI 的 `poi_district + township`。交易表登记区县只用于一致性审计，不能覆盖 POI 行政归属。当前审计应记录 9 条登记区县与高德区县不等价的记录，以及 21 条登记区县缺失的记录。

### 记录字段

`attach_geo()` 为每条记录增加：

- `admin_lng`
- `admin_lat`
- `admin_unit_id`
- `admin_resolved`
- `admin_resolution_method`
- `admin_resolution_ambiguous`

解析失败保留 `None`，禁止使用 `(0, 0)`。`admin_unit_id` 表示解析到的同一行政资产行或规范化行政单元。行政中心距离只在两侧 `admin_resolved=True` 时计算。

### 资产审计门槛

新增只读审计输出，至少包含以下统计：

- 查询侧总数、精确命中数、后缀回退数、别名回退数、全局唯一回退数、未解析数和歧义数
- 候选侧同上统计
- 歧义记录数及其区县、街道、候选中心点
- 业务区县与 POI 高德区县不一致的记录
- 登记区县与高德区县不等价的 9 条记录，以及登记区县缺失的 21 条记录
- 行政中心坐标范围和资产哈希

当前资产的预期结果如下：

- 查询侧和候选侧原始记录解析率均不低于 99.5%，manifest 必须记录 resolved、unresolved 和 ambiguous 的数量及比例
- 当前实测：查询侧 8,780/8,782 = 99.98%（2 条业务区县为脏值 `二期`、`蔬菜公司大河沟集资楼`，无法解析），候选侧 3,260/3,260 = 100%；不把 100% 写成跨数据版本的硬门槛
- 未解析 pair 在训练资产中用显式哨兵 `admin_center_distance_m=-1.0`、`admin_center_same=0` 编码，并在 manifest 记录数量；禁止静默编码成 0 米
- 全局街道名回退不承担主要覆盖率，且不产生未经确认的跨区县匹配

`attach_geo()` 的签名保持不变，模块级行政索引由 `geo_asset.py` 统一缓存。以下四个调用点必须使用同一索引和同一解析规则：`code/er/training_data.py` 的查询侧与候选侧两处，以及 `code/er/full_library.py` 的查询字典与候选列表两处。

## 阶段二：两维特征接入

修改以下文件：

- `code/er/features.py`
- `code/er/full_library.py`
- `code/er/experiments.py`
- `code/er/training_data.py`
- `code/er/lightgbm_model.py`

### 特征计算

`pair_features()` 和 `record_features()` 都增加：

- `admin_center_distance_m`
- `admin_center_same`

距离使用现有 `haversine_m()`。原始特征值保留米，进入模型向量时统一执行：

```text
min(distance_m / 2000.0, 10.0)
```

`admin_center_same` 仅在两侧解析成功且 `admin_unit_id` 相同的情况下为 `1`，其余情况为 `0`。不能用浮点坐标相等代替行政单元身份。`admin_unit_id` 定义为「等价区县类 + 规范化行政原名」：等价区县族内同名重复行（如双桥经开区/大足区 通桥街道）归为同一单元；`街道` 与 `镇` 保留原名差异（如南坪街道 ≠ 南坪镇）。重复行与重复坐标必须在审计中记录。

未解析距离在特征层保留 `None`；生成训练资产时若仍有未解析 pair，使用显式哨兵 `-1.0`（`admin_center_same=0`）并在 manifest 记录数量，禁止把未知距离编码成 0 米。

### 特征白名单

`experiments.FEATURES` 从 14 维扩展为 16 维，新增两维放在现有 14 维之后。`training_data.FEATURE_FIELDS` 同步增加两维。

审计文件统一落盘到 `code/geo_assets/admin_center_audit.json`，并同时写入 v5 的 `feature_manifest.json`。

`vector()` 需要为 `admin_center_distance_m` 新增归一化分支（与 `poi_distance_m` 相同的 `min(d/2000, 10)`）；未解析值在 `vector()` 中必须显式处理，禁止经由 `_float(None)->0` 静默变成 0 米。

`feature_manifest.json` 增加：

- `admin_center_feature: true`
- 行政中心资产路径和 SHA-256
- 查询侧和候选侧解析规则
- 各 split 的解析覆盖率
- 各 split 正负例的同中心比例和距离分布
- `admin_center_resolved`、`admin_center_unresolved`、`admin_center_ambiguous` 数量及比例
- 878 条 `external_used_for_label=true` 复核记录的数量、来源哈希和敏感性分析结果

### 开关传播

新增 `use_admin_center`，并从训练到评分完整透传：

- `vector()`
- `evaluate_model()`
- `train_lightgbm()`
- `record_features()`
- `_feature_vector()`
- `run_full_library_experiment()` 的训练和评分阶段

`use_admin_center=False` 时，两维都置为关闭状态。`use_admin=False` 继续只控制原有行政一致性字段，两个开关不能混用。

`experiments.py` 内部还有三处 `vector()` 调用（`evaluate_model` 的规则与逻辑回归分支、scorer 闭包），`full_library.py` 的 `_feature_vector()` 还有一处；这四处必须同步透传 `use_admin_center`，否则训练与评分不一致。

必须修改 `code/er/lightgbm_model.py` 中训练矩阵构造的硬编码调用，把 `use_admin_center` 从 `train_lightgbm()` 透传到 `vector()`。评分端和训练端必须使用相同开关、相同 16 维顺序。`record_features()` 的恒 0 占位字段必须删除并改为真实计算。

## 阶段三：测试

新增或扩展单元测试，覆盖以下情况：

1. 精确行政区划名优先于去后缀匹配。
2. 同一区县的街道和乡镇后缀可以回退匹配。
3. `_area_equivalent` 对两江新区、渝北区、江北区、北碚区等代管关系生效。
4. 多区县同名街道不会被全局匹配到任意第一项。
5. 候选侧使用高德区县时，登记区县冲突不会覆盖 POI 行政归属。
6. 两侧解析到同一 `admin_unit_id` 时 `admin_center_same=1` 且距离为 0；等价区县族内同名重复行视为同一单元；南坪街道与南坪镇视为不同单元。
7. 任一侧未解析时距离保留缺失语义。
8. `use_admin_center=False` 只关闭两维，不影响 `area_match`、`street_match` 和 `poi_district_match`。
9. LightGBM 训练矩阵、验证矩阵和评分向量均为 16 维。

执行：

```powershell
py -m unittest discover -s code/tests -v
```

验收标准是现有 16 项测试全部通过，并新增行政中心测试全部通过。测试还要断言训练和评分均显式传递 `use_admin_center`。

## 阶段四：生成 v5 训练资产

不覆盖 v4，执行：

```powershell
py code/build_pair_features.py `
  --output-dir code/training_assets_full_v5 `
  --split-manifest code/split_manifest_full/split_manifest.json `
  --candidate-source full `
  --negative-ratio 3 `
  --split-seed 13
```

验收内容：

- `feature_manifest.json` 明确列出 16 个模型特征
- 包含 `admin_center_distance_m` 和 `admin_center_same`
- `pairs_train.csv`、`pairs_validation.csv`、`pairs_test.csv` 行数分别为 8454、1788、1835
- split、映射和负例数量与 v4 一致
- 将 v4/v5 两套 CSV 的 `(query_id, candidate_id, label)` 排序后逐行比较，集合必须完全一致。允许新增的只有两列行政中心特征及其 manifest 元数据
- 原始记录解析覆盖率不低于 99.5%，manifest 记录 resolved、unresolved、ambiguous；当前 pair 资产 12,073/12,077 解析成功，4 个未解析 pair 按哨兵编码并记录
- 正负例同中心比例和距离分布已写入 manifest 或独立审计文件
- 对 878 条 `external_used_for_label=true` 记录分别做纳入和排除重训/评估，至少报告方向和差异；若样本量不足以重训，必须写明限制。878 条清单取自 `数据/外源数据/regeo_fangjiao.jsonl` 的 `source` 字段（既有响应 878 条），排除口径为按 `candidate_id` 剔除相关 pair，并报告被剔除的 query 数

如果行数、映射数量或 split 发生变化，停止后续实验，先检查解析器是否改变了候选构造逻辑。

## 阶段五：先跑成对级实验

```powershell
py code/run_pair_model_experiments.py `
  --data-dir code/training_assets_full_v5 `
  --output-dir code/pair_model_results_v5 `
  --mask-ratio 0.6 `
  --mask-seed 42
```

验收重点：

- Full Model 和 E1 都出现在结果表中
- Full Model 的模型特征数为 16
- E1 的两维行政中心特征确实被关闭
- Full Model 与 E1 的差异按阶段零预检解释。两者相同或近似相同，在预检显示行政中心冗余时属于合法结果，不作为失败条件
- LightGBM + POI 与 E1 使用同一组特征配置，两者数值应完全相同；这是预期，不是 bug

如果 Full Model 与 E1 仍完全相同，只有在阶段零预检预测存在独立信号时，才检查以下项目：

1. `FEATURES` 是否真的包含两维。
2. v5 CSV 是否真的写入两维。
3. `use_admin_center` 是否同时作用于训练和评分。
4. 训练和评分的特征顺序是否一致。
5. 行政中心距离是否被全部写成 0 或空值。

若预检已显示独立信号弱且上述实现检查通过，记录“行政中心证据在现有特征条件下没有可观测增量”，不要把结果改写成实现缺陷。

## 阶段六：完整候选库实验

v5 用 16 维重训会改变所有方法的数值，README 的完整候选库表格必须整体替换，因此本阶段必须执行（约 1.5–2 小时）。E1 与 Full Model 相同或近似相同是允许的验收结果，但 Full Model、LightGBM + POI、E2 等其余方法也要同步更新。

```powershell
py code/run_full_library_experiment.py `
  --data-dir code/training_assets_full_v5 `
  --cache-dir .audit_work/full_candidate_cache_v5 `
  --output-dir code/full_library_results_disk_v5 `
  --mask-ratios 0,0.3,0.6,1.0 `
  --seed 42 `
  --split-seed 13
```

验收内容：

- `full_candidate_comparison.csv` 包含 Full Model、LightGBM + POI 和 E1
- `rho=0` 与 `rho=0.6` 下记录 E1 与 Full Model 的差异或相同结果及其预检解释
- E1 的变化方向与成对级实验一致，或有明确的候选库解释
- Full Model 与 E1 的训练和评分矩阵均使用同一套 16 维顺序

## 阶段七：文档同步

README 必须按 v5 结果整体同步，而不是只增加一行 E1：

- 方法表第 11 行从“未做实验”改为已完成，并写明 Full Model 的两维行政中心特征
- §4.1 设置、§4.3 主结果和消融表、§5.3 消融表及解读、§6 第 5 条全部更新
- 所有受 v5 重训影响的方法数值整体替换并标明数据版本，不能只填 E1 行
- 删除“Full Model 与 LightGBM + POI 特征配置相同”和“E1 尚未形成独立有效消融”的旧描述
- 明确 E1 只移除行政中心两维
- 保留行政一致性字段的定义和作用说明
- 记录资产解析覆盖率、回退规则、未解析处理方式，以及 878 条标签复核样本同源风险的敏感性结果或限制
- §5.1 输出核验里的“28 个 comparison 组合（4 个 rho × 7 个方法）”改为 32 个组合（4 × 8）

## 阶段八：提交边界

为保证 v5 可复现，`code/training_assets_full_v5/` 按现有 v4 规则作为训练输入资产入库。将 `code/pair_model_results_v5/`、`code/full_library_results_disk_v5/` 和 `.audit_work/full_candidate_cache_v5/` 加入 `.gitignore`，模型缓存和长跑结果不纳入版本库。执行前确认 `.gitignore` 已覆盖这些精确目录。

```powershell
git add code/E1_admin_center_plan.md code/er code/tests code/training_assets_full_v5 README.md .gitignore
git commit -m "接入行政中心特征并完成 E1 消融"
```

## 最终判定

行政中心版 E1 只有在以下条件同时满足时才算完成：

- 行政中心解析覆盖率达标
- 16 维特征在训练和评分两侧一致
- 行政一致性字段未被误关闭
- 阶段零独立性预检已完成，Full Model 和 E1 相同或不同都有可解释记录
- 完整候选库结果与成对级方向一致，或对差异/相同给出候选库层面的解释（v5 必须更新完整库表）
- v4/v5 pair 集合逐行一致，标签来源重叠敏感性或限制已记录

## 执行记录（2026-11-25）

- 解析器与审计：`code/er/geo_asset.py` 新增等价区县类 + 规范化行政原名的 unit 解析；`code/audit_admin_center.py` 输出 `code/geo_assets/admin_center_audit.json`。查询侧 8,780/8,782（2 条脏区县）、候选侧 3,260/3,260；登记区县冲突 9 条、缺失 21 条；重复行政行 60 组。
- 阶段零预检：`code/precheck_admin_center.py` 输出 `code/geo_assets/admin_center_precheck.json`。pair 两侧解析 12,073/12,077；`street_match=1` 时同中心比例正负例均约 100%，`area=1,street=0` 中心距 AUC 0.532、KS 0.113，判定为高冗余、弱信号。
- v5 资产：`code/training_assets_full_v5/`，8,454 / 1,788 / 1,835 行，`(query_id, candidate_id, label)` 与 v4 逐行一致；4 个未解析 pair 用 `-1.0` 哨兵编码并写入 manifest。
- 成对级：Full Model 87.31 / 88.26 / 87.78，E1 88.96 / 89.35 / 89.15，E1 与 LightGBM + POI 完全一致；剔除 878 条复核样本后方向不变（91.64 vs 92.52）。
- 完整候选库：8 方法 × 4 rho = 32 组。E1 与 Full Model 的 F1 差为 rho=0 -0.47、rho=0.3 -0.16、rho=0.6 +1.51、rho=1.0 -0.49 个百分点，幅度 ≤1.51 个百分点且方向随 rho 变化。
- 结论：行政中心特征没有稳定的独立增量，与阶段零预检一致；E1 保留为消融行并写入 README §4.3 / §5.3。
- 测试：19 项通过。
