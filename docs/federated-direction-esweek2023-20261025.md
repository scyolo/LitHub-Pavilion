# 新增联邦学习方向与 ESWEEK 2023 期刊关联（2026-10-25）

本轮完成两项覆盖优化：新增第 18 个研究方向“联邦学习”，并用 ESWEEK 官方日程证据补齐 CODES+ISSS 2023 与 EMSOFT 2023 的期刊关联。采集范围仍严格限定 CCF 2026 第七版 338 个 A/B 来源；不下载 PDF，不引入目录外来源。

## 一、联邦学习方向

### 规则与检索

- `seeds/directions.csv` 新增 `federated,联邦学习,2.0,1`，成为第 18 个方向。
- `seeds/direction_rules.csv` 新增 5 条规则，全部先在 396,844 篇公开语料上离线校准：
  - 权重 2：`\bfederated[- ](?:learning|training|optimization|analytics|evaluation|inference|unlearning|clustering|distillation|recommendation)\b`
  - 权重 1：`federated (learning|neural networks|fine-tuning)` 变体、`cross-silo/cross-device/horizontal/vertical/split/personalized federated`、`FedAvg/FedProx/FedDyn` 等算法名、`communication-efficient/client-heterogeneous/non-IID` 组合。
  - 校准中去掉了 `scaffold`（与 3D 高斯泼溅、分子骨架等大量误配）与裸 `federated` 词匹配（`federal`、`federation` 误配），未使用宽泛前缀规则。
- 中文检索别名 `联邦学习 / 联邦训练 / 联邦机器学习 → federated` 同步加入 `seeds/query_aliases.json` 与 `frontend/src/data/query_aliases.json`（两者必须逐字节一致，由 `test_query_aliases.py` 强制）。

### 打标结果

`python -m scripts.reindex_topics`（先自动备份 `before-topic-reindex-20261025T114127115779Z.db`，校验论文元数据、人工标签、FTS 完整性不变）：

| 项目 | 结果 |
|---|---:|
| 打上联邦学习标签的论文 | 5,052 |
| 其中公开论文（dashboard 口径） | 4,980 |
| 2023 / 2024 / 2025 / 2026 | 872 / 1,301 / 1,444 / 1,370 |
| 论文元数据变更 | 0（paper_count_unchanged=404,669，指纹一致） |
| 人工标签变更 | 0 |

方向可与其他 17 个方向重叠（如联邦+LLM、联邦+CV），不做互斥。

### 综述覆盖核验

用户要求“经典综述可以采集”。核验结论：

- 库内已有 **25+ 篇** CCF A/B 来源的 FL 综述，包括 TPAMI 2024《Federated Learning for Generalization, Robustness, Fairness: A Survey》（287 引）、TPAMI 2024《The Impact of Adversarial Attacks on FL: A Survey》（198 引）、TKDE 2023/2024/2025、Proc. IEEE 2025、SCIS 2025、IJCAI 2023–2026 等系列综述，均已被采集并通过方向规则自动覆盖。
- 两篇最经典的 FL 综述 **不在 CCF A/B 目录内，不能入库**：Kairouz et al.《Advances and Open Problems in Federated Learning》（Foundations and Trends in ML / ACM TIST——TIST 不在本届 CCF A/B 名单）；Li, Yang et al.《Federated Learning: Challenges, Methods, and Future Directions》（IEEE Signal Processing Magazine，非 CCF 期刊）。按 README“不收集 C 类或目录外来源”的边界，不为其破例。

## 二、ESWEEK 2023 期刊关联（补齐 CODES+ISSS 2023 零记录）

### 问题

CODES+ISSS 2023 一直是零记录年份（90 个缺口之一）。根因：ESWEEK 采用 journal-integrated 出版模式——官方日程与 CFP 明确“三会（CASES/CODES+ISSS/EMSOFT）所有 regular papers 发表在 ACM TECS”，会议论文集（ACM 10.1145/3607888）只是 Companion（WiP/专题）。主会论文早已作为 TECS 22(5s) 特刊（59 篇）全部在库，但缺与会议的关联。

### 证据与执行

- 从官方可检索日程 `2023.esweek.org/events/` 解析出每个 session 的完整论文清单，将 TECS 22(5s) 的 59 篇论文逐一归属：CODES+ISSS 17、EMSOFT 21、CASES 21（CASES 非本站配置来源，不入库）。
- 证据存档 `release-artifacts/esweek2023-backfill/`：官方日程 HTML（SHA-256 `ffde72b1...`）、Crossref 59 篇元数据缓存（`98ace130...`）、DOI→会议映射 JSON。
- 新增 `backend/app/services/esweek_associations.py` 与 `backend/scripts/link_esweek_issues.py`（仿照 ISMB 关联模式：精确 DOI、完整作者集合、正式来源、公开准入五重校验，绝不新建论文或改写正式来源）。
- 先 dry-run 后 `--apply`（执行前 `python -m scripts.backup` 自动备份）。

| 来源 | 2023 关联 | 结果 |
|---|---:|---|
| CODES+ISSS | 17 篇 TECS 论文 | 零记录年份消除，status=journal_linked |
| EMSOFT | 21 篇 TECS 论文 | 从 9 篇 companion WiP 升级为有正式期刊关联 |

`seeds/source_scope_notes.json` 移除 CODES+ISSS 2023 零记录注记（该年份不再是零记录）。全站零记录来源/年份 **90 → 89**。

## 三、验证

- 后端测试 **1,136 通过**（1 项环境预存失败：本地 starlette 1.2.1 低于测试要求的 1.3.1，与本次改动无关）。
- 新增文件 ruff 检查干净（仓库其余 281 个 lint 为预存问题）。
- 快照重新导出：revision `55a96da7a064310d...`，395,935 篇不变（关联不新增论文）；`--validate-only --check-database` 返回 `database_consistent: true`。
- `source-coverage.json`：CODES+ISSS `associated_years {"2023": 17}`、EMSOFT `{"2023": 21}`；dashboard directions 含 `federated 联邦学习 4,980`；`conference_associations` 导出 17+21 个论文 ID。
- SQLite `integrity_check` / `foreign_key_check` 通过。

## 边界与未完成

- 本轮仅本地数据库与快照，未提交、未推送、未发布 Pages；线上仍为 2026-10-21 数据。
- EMSOFT 2026、CODES+ISSS 2026 及其余 61 个 `unverified` 缺口维持原状：2026 届次多为期刊-first 尚未出版或官方目录未上线，需后续轮次核验。
- ESL（IEEE Embedded Systems Letters）的 18 篇 LB 论文不在 CCF A/B 期刊名单，未入库。
