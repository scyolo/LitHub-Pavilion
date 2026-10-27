# 零记录缺口清核与 2026 届次采集（2026-10-25）

本轮对全部 89 个零记录来源/年份缺口做了系统性清核：逐一探测出版方容器、核验会议届次实情（双年/合并/停办/未出版），能采集的用项目标准路径采集，暂不能采集的用官方证据更新核验状态。采集范围仍严格限定 CCF 2026 第七版 338 个 A/B 来源；不下载 PDF。

## 一、本轮采集（净增 3,228 篇正式论文）

| 来源 | 年份 | 篇数 | 采集路径 | 证据 |
|---|---|---:|---|---|
| EMNLP | 2026 | 2,701 | ACL Anthology XML 官方目录（`collect_official_unit`，走 pipeline 同款 `fetch_official_inventory` + `apply_records`） | anthology `2026.emnlp.xml`（main 2,704 篇，3 篇作者重名冲突按项目规则保守跳过） |
| MobiCom | 2026 | 207 | Crossref 发现式目录（`backfill_conference_year_gaps`，先 `collect_gap_discovery` 生成证据） | ACM 官方容器 "Proceedings of the 32nd Annual International Conference on Mobile Computing and Networking" |
| MobileHCI | 2026 | 41 | 同上 | "Proceedings of the 28th International Conference on Mobile Human-Computer Interaction" |
| SIGGRAPH | 2026 | 195 | ACM 父书 `10.1145/3799902`（仿 2025 年已验证路径，`import_siggraph2026`） | Crossref 父书 ISBN 9798400725548；`catalog_conferences.py` 与 `siggraph_parent_provenance.json` 增加 2026 映射 |
| LICS | 2026 | 84 | Dagstuhl LIPIcs（`backfill_dagstuhl`，`dagstuhl_catalog.py` SERIES 增加 LICS） | DataCite `10.4230/LIPIcs.LICS.2026.*`（85 条注册，1 条 front matter 排除） |

正式快照 395,935 → **399,163**（+3,228）。所有写入前均有 `scripts.backup` 自动备份；EMNLP 单元另含 3 条 `identity_conflicts` 记录在 `release-artifacts/gap-probe-20261025/emnlp2026/report.json`。

## 二、届次实情核验（零记录 89 → 84）

用项目自带的发现式探测（`probe_zero_gap_containers.py`，只读）扫全部 89 个缺口，结论：86 个无出版方容器、2 个有（MobiCom/MobileHCI，已采）、1 个网络错误（NAACL 2023，已知 Anthology 无卷）。

再用 CCFDDL 届次日历（项目 `frontend/static/deadlines.json`，338 来源精确名称匹配）核验 2026 缺口的届次安排，关键发现：

| 类别 | 数量 | 说明 |
|---|---:|---|
| 已采集消除 | 5 | EMNLP/MobiCom/MobileHCI/SIGGRAPH/LICS 2026（上表）+ CODES+ISSS 2023（上轮关联） |
| 双年/无届次 → `not_scheduled` | 11 | **GROUP 2026（CCFDDL 明确列出 GROUP 2027 两轮截稿，双年制确认）**、CADE 2026（下届 2027）、HiPEAC（见下）及既有 ICCV/ECCV/PPSN/COLING/FM/HotOS 项 |
| 已开会未出版 → `publication_pending` | 16 | HSCC（5月）、SECON（6月）、ICME（7月，仅 ICMEW 工作坊卷已存入）、DAC（7月）、HOT CHIPS（8月）、SRDS/ICSME（9月）、RAID/ICNP/ITC/PACT/ISMAR/ASE/ISWC/ESEM（10月）等：会议已举行但出版方尚未存入正式主会 proceedings |
| 未开会 → `unverified`（预期零计数） | 44 | CCS/SC/CIKM/ICDM/FOCS/ACM MM/MICRO 等均于 2026-11/12 举行，截稿日历点（10-25）尚未开会，零记录属预期 |
| 无 proceedings 出版 | 1 | **HiPEAC**：年会由工作坊/教程/展览组成，官方不出版主会论文集（Crossref/ACM/IEEE 均无会议卷），下届 2027 |
| 联合届次 | 4 | CADE 2024/2026（IJCAR 合并卷）、ECAI 2026（IJCAI 联合）、IPSN 2026（并入 SenSys）——保留原证据注记 |
| 届次未核实 | 7 | LISA/VEE 2023–2026（USENIX 档案止于 2021/2022，不据此推断停办）、COLING 2026、NAACL 2026（Anthology 无卷；CCFDDL 显示下届 2027） |
| 检索失败 | 1 | ISS 2025（维持原状态） |

## 三、方法与脚本

| 新脚本 | 用途 |
|---|---|
| `scripts/probe_zero_gap_containers.py` | 只读探测全部零缺口的出版方容器（走项目 `discover_containers` 逻辑），输出 `release-artifacts/gap-probe-20261025/report.json` |
| `scripts/collect_gap_discovery.py` | 为指定缺口生成 discovery 证据文件（`backfill_conference_year_gaps --discovery` 的输入格式） |
| `scripts/collect_official_unit.py` | 单元式官方目录采集（fetch_official_inventory → apply_records → tagging），用于 Anthology 上线卷 |
| `scripts/import_siggraph2026.py` | SIGGRAPH 2026 父书导入（仿已验证的 2025 路径） |
| `scripts/update_scope_notes_20261025.py` | 按本轮证据批量更新 `seeds/source_scope_notes.json`（62 条更新；joint_edition 原证据注记已从 git 历史恢复，未被覆盖） |

代码变更：`dagstuhl_catalog.py` SERIES 加 LICS；`catalog_conferences.py` SIGGRAPH 父书映射加 2026；`seeds/siggraph_parent_provenance.json` 加 2026 条目。

## 四、验证

- 快照 revision `358ad9c5...`，399,163 篇；`--validate-only --check-database` 通过（`database_consistent: true`）。
- `source-coverage.json`：`zero_source_year_units: 84`，状态分布 44 unverified / 16 publication_pending / 11 not_scheduled / 7 edition_unverified / 4 joint_edition / 1 no_proceedings / 1 retrieval_failed——**无未注记缺口**。
- scope notes 全量通过 `source_year_checks` 校验（0 错误）。
- 新脚本 ruff 全部通过；测试套件运行见交付记录。
- SQLite `integrity_check` 通过；每次写库前有独立备份。

## 边界与未完成

- 本轮仅本地数据库与快照，未提交、未推送、未发布 Pages。
- 44 个 unverified 2026 缺口待会议结束、官方目录上线后补采（多数 2026-11/12 开会）；16 个 publication_pending 需出版方存入 proceedings 后重试。
- IJCAI 2026（972 篇）已在线且库内已有 973 篇对应记录；KR/AAMAS/AAAI/NeurIPS 等 2026 均已在库，无需处理。
