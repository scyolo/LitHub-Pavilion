# 联邦学习方向覆盖扩充（2026-10-27）

用户反馈检索不到预期论文。诊断出两个独立问题并分别修复：**方向标签召回不足**（论文在库但未打标）与**历史年份未采集**（FL 奠基论文集中在 2019–2022，而项目采集窗口从 2023 开始）。采集范围仍严格限定 CCF 2026 第七版 338 个 A/B 来源。

## 一、标签召回修复（5,052 → 6,517）

原 5 条规则只匹配 `federated learning` 这类**相邻词**写法，导致 "Federated Graph Learning"、"Federated Prompt Learning"、"Federated Semi-supervised Learning" 等完全漏标：库内 6,572 篇提到 `federat*` 的公开论文中，仅 4,948 篇被打标（**召回 75.3%**）。

新增 5 条规则（`seeds/direction_rules.csv`）：

| 规则 | 命中形态 | 权重 |
|---|---|---:|
| 跨度匹配 | `federated` 与 learning/training/clustering/recommendation/unlearning/tuning/aggregation/averaging/optimization/inference/adaptation/selection 之间可隔词 | 1.0 |
| 上下文 A | `federated` + client/privacy/personalized/aggregation/non-IID/heterogeneous/cross-silo/cross-device/server/local model/global model/communication-efficient/model poisoning/byzantine | 1.0 |
| 上下文 B | `federated` + domain generalization/graph learning/multi-view/semi-supervised/reinforcement/bandits/recommendation/retrieval/prompt/LoRA/conformal/anomaly detection/split learning/category discovery/out-of-distribution/differential privacy/secure aggregation/incentive 等 | 1.0 |
| 广谱任务词 | `federated` + recognition/classification/detection/estimation/regression/segmentation/backdoor/attack/defense/privacy/compression/algorithm/SVM/transformer/statistics/frequency/Langevin 等 | 1.0 |
| 方法名前缀 | 标题中 `Fed` 前缀方法名（FedLPA/FedRNC/FedGOG…），排除 federal/federated/feedback/FedEx 等英文词 | 1.0 |

误判防护经探测验证：`Federated Assemblies`（社会选择）、`Beyond Mandatory Federations`、`Federal Learning Budget Allocations`、`Federated Identity Management`、`Federated States of Micronesia` 均**不命中**。重跑 `reindex_topics` 后：

- 联邦学习标签：5,052 → **6,517**（+1,465，+29%）
- 库内 `federat*` 论文召回率：75.3% → **99.2%**（余下多为仅在摘要提及、按 ≥2.0 阈值不达标者）
- 论文元数据与人工标签零变更（指纹校验通过）

## 二、历史年份补采（2019–2022，新增 935 篇）

项目采集窗口从 2023 年开始，因此 FL 领域最具影响力的早期论文（SCAFFOLD/ICML 2020、无线 FL 经典 TWC 2020、FedAvg 派生工作等）此前一篇都没有。本轮两条路径补采，**只收录标题通过联邦学习规则的论文**，并如实标注为方向定向补采（不宣称这些年份的完整覆盖）：

| 路径 | 脚本 | 结果 |
|---|---|---:|
| 逐来源 Crossref 检索（期刊按 ISSN、会议按容器名，共 338 个来源，扫描 25,026 条记录） | `scripts/backfill_federated_history.py` | **719 篇** |
| 官方卷目录（ICML 经 PMLR、NeurIPS、CVPR/ICCV 经 CVF、AAAI 经 OJS、ACL/EMNLP/NAACL 经 ACL Anthology、ECCV 经 ECVA、UAI/COLT 经 PMLR、AAMAS、KR、ICAPS，2019–2022） | `scripts/backfill_federated_official_history.py` | **216 篇** |

零身份冲突。分布亮点：TWC 2022=34、JSAC 2021=28、ICASSP 2022=27、TPDS 2022=22、NeurIPS 2022=43、ICML 2022=37、CVPR 2022=20、ICAIJ 2022=15、INFOCOM 2021=12、SIGKDD 2022=12。经典论文如 SCAFFOLD、Federated Learning Over Wireless Fading Channels、SplitFed、CalFAT、Federated Reconstruction 现已入库并带 FL 标签。

验证样例：`S&P 2019`（隐私分析）、`Bioinformatics 2021`（FL-QSAR 联邦药物发现）、`Neural Networks 2022`（客户端调度）等均为真实 FL 论文。

### 仍无法补采的来源

- **ICLR 2019–2022**：官方 virtual-site JSON 不含任何论文级可核验标识（无 `paper_url`/OpenReview forum id），OpenReview API 与 DBLP 在本机网络均被 403/Anubis 拦截，本轮未能导入。**2026-10-28 已解决**：改用官方 Schedule 卡片（2019）与 PaperCopilot OpenReview ID 对齐（2020）等保留论文身份的官方材料，补入 2019–2022 全部主会接收论文 3,143 篇（另补 2018 年 336 篇），FedBN/FedDyn/HeteroFL/FedMA 均已入库；见 [ICLR／AI 经典／大厂报告扩充记录](coverage-expansion-20261028.md)。
- **IJCAI 2019–2022 官方卷**：`www.ijcai.org` 301 跳转与客户端禁止跟随重定向冲突；该年份区间已通过 Crossref 收录 54 篇 FL 论文，覆盖尚可。
- FedProx（MLSys 2020）、Advances and Open Problems（Foundations and Trends in ML）等**不在 CCF A/B 目录内**，按范围规则不入库。

## 三、当前覆盖

| 指标 | 本轮前 | 本轮后 |
|---|---:|---:|
| 联邦学习方向公开论文 | 4,984 | **7,371** |
| 联邦学习标签总数 | 5,052 | **7,452** |
| 2019 / 2020 / 2021 / 2022 年 FL 论文 | 0 / 0 / 0 / 0 | 20 / 93 / 273 / 503 |
| 正式快照论文 | 399,163 | **400,099** |

## 四、边界

- 2019–2022 年份仅为**方向定向补采**（只含 FL 论文），不表示这些年份的其他方向已覆盖；页面年度图表仍按 2023–2026 惯例展示，总量包含补采论文。
## 五、发布

已于 2026-10-28 03:10（北京时间）完成推送与网站上线：

- 源码提交 `8d7ccb76`（规则、两个补采脚本、覆盖文档）、`0d32b4ec`（首页 catalog 预算修复）。
- 数据提交 `6484a38a`，快照 revision `4eefc858`；`Pages` 构建 [40563349161](https://github.com/scyolo/LitHub-Pavilion/actions/runs/40563349161) 成功。
- 线上验收：manifest revision `4eefc858`、400,099 篇；catalog 哈希校验通过、体积 366,006 字节；联邦学习方向 **7,371** 篇；末分片检出 2022 年 NeurIPS 的 FL 论文（如 SemiFL）。

### 首页预算修复

首次构建失败：`Pages homepage must have a verified summary below 512 KiB`。原因是 catalog 中的 `venue_topics` 为每个来源发送全部方向（平均 11.7 个），而来源卡片只渲染前 3 个；随 FL 标签扩充后 catalog 变大使 catalog+manifest 达 539,221 字节。

修复：导出时按 `VENUE_TOPIC_LIMIT = 3` 截断已发布目录（`snapshot.py`），校验器改为**前缀容差**（要求保留项与重算结果的最频繁前缀完全一致，同时兼容此前写入完整列表的旧快照）。修复后 catalog+manifest 为 437,336 字节，符合同一 512 KiB 契约，未提高任何体积上限。
