# 网络与系统方向补全（2026-10-29）

## 范围与结论

本轮处理 CCF A/B 目录中的计算机网络、网络与信息安全、计算机体系结构/并行与分布计算/存储系统，以及软件工程/系统软件/程序设计语言中的系统类来源。相关论文原本已在库中，缺的是方向标签；本轮不重新采集论文，只补方向覆盖并重算标签。

新增 3 个方向：

| code | 名称 | 公开论文数 |
| --- | --- | ---: |
| `network` | 计算机网络 | 27,163 |
| `architecture` | 计算机体系结构 | 18,319 |
| `security` | 网络与信息安全 | 26,973 |

原有 `systems`（系统软件与分布式）由 3,828 篇扩展到公开口径 **12,681 篇**。

计算机网络、网络与信息安全、计算机体系结构三个 CCF 领域内的全部 A/B 论文均已至少获得一个方向标签；系统类来源通过 `systems` 映射与标题规则覆盖。

## 实现

1. **来源级方向先验**：新增 `direction_venues` 表与 `seeds/direction_venues.csv`，把 105 个 A/B 来源映射到 4 个方向（network 22、security 25、architecture 23、systems 35）。论文命中来源映射记 `2.0 × weight`，与一次标题规则命中同权。
2. **标题级关键词**：向 `seeds/direction_rules.csv` 追加 44 条 `title` 字段规则（network 12、systems 14、architecture 10、security 8），权重 1.0。标题命中记 2.0，达到默认阈值 2.0。
3. **重算与保留**：`reindex_topics` 同时应用关键词与来源映射；`source='manual'` 标签、方向名称/阈值/开关和论文主表内容均不改变。来源映射缺失时不覆盖本地配置，只增补缺失行。
4. **规则精化**：沿用 `RULE_REFINEMENTS` 机制替换旧规则，避免重复行；包括 `storage systems` 排除 energy/power/battery 语境，以及移除 `TCP`、`P4`、`SSD`、泛化 `sandboxing`、`hardware-aware`、`task scheduling` 等易碰撞写法。

打分公式保持：`标题命中数 × 2 × weight + 摘要命中数 × 1 × weight + 来源先验 2 × weight`，达到方向 `min_score`（默认 2.0）入选。

## 覆盖构成

打标口径为数据库内 413,803 条 A/B 记录；公开口径为 405,075 篇，方向计数略低。

| 方向 | 标签总数 | 来源内论文 | 仅来源 | 标题命中 | 仅标题 | 两者 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| network | 27,178 | 23,513 | 18,155 | 9,023 | 3,665 | 5,358 |
| architecture | 18,378 | 17,528 | 14,586 | 3,792 | 850 | 2,942 |
| security | 27,203 | 16,882 | 11,260 | 15,943 | 10,321 | 5,622 |
| systems | 12,736 | 8,389 | 6,785 | 5,872 | 4,268 | 1,604 |

`systems` 另有 79 篇由既有摘要规则命中，因此标签总数高于来源与标题的并集。

## 验证

- `python -m scripts.reindex_topics --database data/papers.db`：首次运行新增 44 条标题规则与 105 条来源映射；复核重跑显示 `rules_added=0`、`rules_refined=11`、`venue_rules_added=0`，说明配置已幂等落库。
- 重算前后论文主表指纹一致（413,803 篇），人工标签完全保留，FTS5 完整性检查通过。
- 105 个来源映射逐一核对，来源内论文缺标数为 0；计算机网络、网络与信息安全、计算机体系结构三个 CCF 领域的未打标论文数为 0。
- `/api/directions` 返回 22 个启用方向；`/api/papers?direction=network|architecture|security|systems` 的公开计数与上表一致（公开口径）。
- 后端全量测试通过；前端 39 个测试文件、303 项测试通过，`npm run build` 成功。

## 本地导出与页面验证

- `python -m scripts.export_snapshot --check-database` 完成：revision `2c004928dde05eb7ef1baa35de17a042d6894ea7a9ec4c475b7bc1556537433d`，405,075 篇、406 个分片、22 个方向，`database_consistent=true`。
- `node scripts/check-snapshot-home.js`：首页仅请求 manifest 与 catalog（445,608 字节），论文分片请求 0；`node scripts/check-snapshot-search.js`：33 组精确检索、42 组跨方向检索、405,075 条标题身份与 226 个快照文件校验通过。
- 生产构建页面验证：首页显示 22 个方向，计算机网络 27,163、网络与信息安全 26,973、计算机体系结构 18,319、系统软件与分布式 12,681；四个方向的列表页计数与标签一致，详情页显示方向标签与“标题、摘要与来源先验”说明。

## 上线

- 本次方向补全已于 2026-10-29 随数据提交 `64be208c`（树 `bd21ca71`，父 `7e36865c`）发布到 `site-data`，线上 revision `2c004928`、405,075 篇、22 个方向；发布过程与线上验收见 [发布验收记录](release-20261029.md)。

## 边界

- 来源先验会给该来源的全部论文打上方向标签，包括跨领域应用论文；标题规则只用于补充来源外论文并控制噪声，但仍需语义复核。
- 本轮不改变来源配置、论文数量或公开准入规则，也不代表 CCF A/B 论文已完整收齐。
