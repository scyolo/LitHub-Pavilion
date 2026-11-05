# 2026-11-04 方向收敛与论文覆盖重置

按课题需要对语料做了收敛：删除两个与课题无关的方向，把原本未分类的论文核查后分别归入现有方向或删除，未分类论文从 32,240 篇降为 **0**。

## 变更结果

| 指标 | 变更前 | 变更后 |
|---|---|---|
| 论文总数 | 413,889 | **333,119** |
| 方向数 | 28 | **26** |
| 未分类论文 | 32,240 | **0** |
| 方向标签数 | 662,177 | 610,104 |
| 停用来源 | 0 | **30** |
| 快照论文 | 405,161 | **324,418** |
| 快照 revision | `6174707f…` | `8f8474f0…` |

## 删除的方向

`speech`（语音、音频与声学，23,365 篇）与 `bioinformatics`（生物信息与医学信息，15,781 篇）连同其 3 条关键词规则、12 条来源映射和 6 篇经典论文条目一并删除。经典论文中 `ctc`、`deepspeech2` 因同时带有 `dl` 标签而保留，仅移除其语音方向归属。

## 未分类论文的成因核查

32,240 篇未分类论文**全部**位于 41 个「无方向映射」的来源中，成因已确认：

1. 采集器（`pipeline.py`）会抓取 `seeds/venues.csv` 中全部 338 个 CCF A/B 来源，**采集阶段不按方向过滤**；
2. 方向标签由下游的规则引擎（`tagging.py`）独立生成，依赖 `direction_rules.csv` 关键词与 `direction_venues.csv` 来源先验；
3. 这 41 个来源既没有来源先验映射，其论文标题也命不中关键词规则——实测用现有规则重跑，**可归属数量为 0**（仅 922 篇有弱信号但低于阈值）；
4. 这些论文中 91% 缺少摘要（仅 2,929 篇有摘要），标题信息不足以支撑关键词匹配。

因此「未分类」是采集范围与方向体系脱节的必然结果，而非打标器故障。

## 分类处置

### 补方向映射后保留（24 个来源，24,498 篇）

数据库/数据挖掘、多媒体、人机交互类来源，按内容归入现有方向：

- **retrieval**：TKDE、WWW、IPM、KAIS、DASFAA、DKE、WISE、JASIST、TWEB、TODS、GeoInformatica、Information Sciences、IS、WWW Journal、DSE、ICWSM
- **graph**：TKDE、WWW、KAIS、DASFAA、DKE、WWW Journal、DSE
- **ml**：Information Sciences、IEEE Transactions on Cybernetics
- **multimodal**：DCC、TCSVT、ICMR
- **cv**：TCSVT、SIIMS、ICMR
- **hci**：ICWSM、TAP、EJIS
- **security**：BCRA

另有 7 个暂无论文的图形学来源（IEEE VIS、Eurographics、EuroVis、SGP、EGSR、PG、SPM）补 `graphics` 映射，避免后续采集时再次产生未分类论文。

### 删除论文并停用来源（29 个来源，80,770 篇）

判定为与课题无关，论文删除且 `venues.active=0`，后续采集不再抓取：

- **语音/声学**：JASA、INTER- SPEECH、TASLP、JSLHR、SPECOM、ICASSP
- **生物信息/医学信息**：BIBM、PLOS Computational Biology、Bioinformatics、Briefings in Bioinformatics、TCBB、JAMIA、RECOMB
- **遥感/交通/认知科学**：TGARS、TITS、CogSci、Cognition
- **控制/进化计算/非线性系统**：TSMC、AEI、TFS、TEC、PPSN、Evolutionary Computation、HSCC
- **非研究性内容**：Proc. IEEE
- **综合/跨学科**：SCIS、The Computer Journal、FCS、JCST

另停用无论文的 ISMB（生物信息）。

## 验证

- 数据库 `integrity_check=ok`，`foreign_key_check` 无违规，无孤立 `paper_directions`/`paper_authors`/`paper_conferences` 记录。
- 333,119 篇论文全部带方向标签；停用来源下无残留论文。
- 120 条手工标签保持不变（`manual_tags_unchanged`）。
- 快照：325 个分片、324,418 篇，`validate_snapshot` 通过；7,545 个文件全部被 manifest/reader 引用，无缺失、无冗余（清理 8,286 个旧版本残留、796.3 MB）。
- 来源覆盖清单按快照重新导出，`check:source-coverage` 通过（338 个配置来源、296 个直接来源、13 个关联分片）。
- 后端 Ruff 通过；后端测试 1,227 项通过；前端测试 304 项通过、生产构建成功。

后端测试 `test_catalog_expansion.py` 中硬编码的方向清单、来源映射计数与方向样例已同步更新为 26 个方向和 320 条映射。

## 数据安全

- 变更前完整备份：`backend/data/backups/lithub-20261104T072343610640Z.db`（821 MB）。
- 重打标自动备份：`backend/data/backups/before-topic-reindex-20261104T072546573586Z.db`。
- 迁移脚本保留在 `backend/scripts/prune_directions.py`，默认试运行，`--apply` 才写入。

## 待办

本次只更新本地数据库与快照，尚未推送到 `site-data` 分支或触发 Pages 部署；线上站点仍是 2026-11-02 的 405,161 篇版本。

## 补充：方向来源锚点补全（同日）

初版只给 17 个领域方向配了来源映射，`llm`、`inference`、`specdec`、`transformer`、`generative`、`rl`、`federated`、`alignment`、`dl` 这 9 个方向**没有任何来源锚点**，只能靠关键词命中，导致同一批 CCF A/B 顶会顶刊在不同方向上的整理程度不一致。

现在 26 个方向都有 CCF A/B 来源锚点，映射从 320 条增至 **394 条**。权重分两档：

- **1.0（17 个领域方向）**：来源即该方向的归属，来源先验 2.0×1.0 单独达到 `min_score`。如 `systems`→OSDI/SOSP、`cv`→CVPR/ICCV/TPAMI。
- **0.5（9 个横切方向）**：来源只是佐证，2.0×0.5=1.0 低于阈值，论文仍需自身关键词命中才入选。

第二档是必要的：横切方向横跨宽口径来源，若给 1.0 会让该来源的**全部**论文获得标签。实测把 `generative` 的 CVPR/ICCV 设为 1.0 时，该方向从 12,435 篇暴涨到 34,151 篇——所有 CV 论文都被误标为生成式。改为 0.5 后回落到 14,537 篇。

调整后分布（每篇平均 1.89 个标签，未分类 0）：

| 方向 | 标签数 | 锚点 | 方向 | 标签数 | 锚点 |
|---|---|---|---|---|---|
| ml | 92,542 | 18 | graph | 16,298 | 9 |
| cv | 81,798 | 13 | robotics | 15,902 | 3 |
| nlp | 47,461 | 6 | dl | 15,340 | 10 |
| llm | 43,989 | 9 | generative | 14,537 | 8 |
| multimodal | 33,041 | 7 | theory | 13,376 | 30 |
| security | 27,940 | 26 | rl | 13,006 | 9 |
| network | 26,661 | 22 | transformer | 11,890 | 5 |
| retrieval | 26,206 | 22 | inference | 11,736 | 12 |
| ai | 24,195 | 9 | graphics | 8,152 | 17 |
| hci | 19,964 | 24 | federated | 6,818 | 9 |
| software | 19,162 | 45 | alignment | 4,186 | 9 |
| architecture | 18,303 | 23 | specdec | 348 | 3 |
| systems | 18,042 | 43 | | | |
| agent | 17,369 | 3 | | | |

新增两条约束测试：每个方向必须有来源锚点；横切方向锚点权重必须小于 1.0，防止再次出现宽口径来源整站误标。

快照随之重建为 revision `726780ed…`，仍未推送部署。
