# CCF A/B 论文覆盖更新（2026-10-16）

本轮接续聊天 `01a14488-8824-72d3-8de3-0af347002c9a`，在现有 338 个 CCF A/B 来源、16 个研究方向、2023—2026 年范围执行元数据和原文链接补采。没有下载论文 PDF、全文或整库归档。

## 经数据库审计确认的变化

| 指标 | 更新前 | 更新后 |
|---|---:|---:|
| 原始数据库记录 | 389,630 | 402,348 |
| 可公开论文记录（含保留的 8 条更早记录） | 381,441 | 393,958 |
| 2023—2026 年可公开记录 | 381,433 | 393,950 |
| 有直接论文的来源 | 325 | 325 |
| 有直接论文或官方会议关联的来源 | 336 / 338 | 336 / 338 |
| 直接及关联记录均为空的来源／年份 | 114 | 108 |

新增可公开记录 **12,711 条**；194 条既有“卷期说明”“编者按”等非论文条目从公开展示中排除，原始数据库记录仍然保留。公开总量因此**净增 12,517 条**。另有 7 条本轮新增原始记录未通过公开准入。

本轮填补的空白均为 2026 年：COLT、ICRA、ISSTA、JASA、SAS、VR。新增公开记录较多的来源如下；这些数字是本轮增量，不是来源总量或完整率。

| 来源 | 新增可公开记录 |
|---|---:|
| JASA | 5,038 |
| ICRA | 1,880 |
| Bioinformatics | 1,880 |
| ICASSP | 821 |
| SIGIR | 468 |
| ISSTA | 211 |
| COLT | 196 |
| WWW | 166 |
| TGARS | 117 |
| TMM | 102 |

新记录按现有规则匹配研究方向，不把所有论文强制归入某个方向。3,169 条新增公开记录至少命中一个现有方向，多方向归属保留。

## 采集与代码修复

- 核对全部 148 个期刊的 Crossref 注册信息。新增 127 个有证据支持的备用 ISSN（包含先单独修复的 JASA 电子 ISSN），保留逐项注册接口地址及日期。其他新增别名要求两个注册入口互相列出对方 ISSN，并具有一致的规范刊名。JMLR 注册入口 404，使用其官方目录；TDSC 的一处注册关联无法双向验证，未采用。
- 新增 `backend/scripts/backfill_registry_gaps.py`，同时检查已有论文和空白来源。支持期刊、已发现的主会目录、会议期刊专辑及经过父书 DOI／ISBN／会议年份核验的 Springer 论文集。既有公开 DOI 跳过重复导入，部分失败保留断点；Windows 短暂读取占用进度文件时会有限重试。
- 官方批量目录任务补上 NAACL，并为导入记录执行方向打标；专门测试确认人工标签不会被规则覆盖。
- PMLR 2026 目录通过明确的同篇 OpenReview 链接对应既有 ICML 记录。修复后保留原 ID 和内部身份，网站阅读入口指向正式 PMLR 页面。本轮为 5,931 条既有论文补上该入口，未通过作者／标题核验的记录继续保留待核对状态。
- 新增准确的非论文标题过滤，处理 `Issue Information`、`Note from the Editor`、`ICRA YYYY Commentary`，不按宽泛关键词排除研究论文。

运行示例（从 `backend` 目录）：

```powershell
.\.venv\Scripts\python.exe -m scripts.backfill_registry_gaps --database data\papers.db --journals --output ..\release-artifacts\coverage-20261016\registry --resume --apply
```

会议、专辑和论文集补采分别使用 `--discovery`、`--series`、`--books`。发现结果只是候选入口，每条记录仍需再次通过来源与年份校验；成功读取注册目录不代表出版方全量完整。

## 数据保留与本轮纠正

初次读取新的 PMLR 卷时，旧代码未使用其 OpenReview 交叉链接，曾误增 6,551 条 ICML 重复记录。本轮先备份当前库，再严格按该次导入回执的 ID 清单撤回未被人工修改的新记录，然后用修复后的匹配重放。没有删除更新前的论文。最终增量已经扣除这些重复项，不能直接累加最早的导入日志。

独立只读审计确认：更新前全部 389,630 个记录 ID 保留；既有来源归属、备注及旧文件路径没有丢失或改变；SQLite `quick_check` 和外键检查通过。人工标签保留逻辑另有数据库测试。备份和撤回清单位于本地验收目录。

## 尚未证明完整的部分

- LISA、VEE 在目标年份仍没有可核实的论文记录；不伪造替代会议。
- 剩余 108 个零记录来源／年份包含不举办年份、联合会议、尚未公开出版物及待核实情况，不能全部称为“漏采论文”。
- SIGCHI 最新公开程序已复核；127 条正式发表日期晚于 2026-10-16 的记录暂缓导入，其余无法与正式出版元数据对应的条目保留未匹配状态。
- TALG、TKDD 各有一条 DOI 被早期未确认的 ICML 版本记录占用；不同出版版本没有被强行合并。621 条 ICML/PMLR 的作者或标题差异也保留待核对。
- 来源出现记录、索引游标耗尽和本轮增加论文均不等于全部来源、全部年份、全部主轨的完整率达到 100%。

## 验证与交付状态

后端 1,024 项测试通过，前端 274 项测试通过；仓库 F/E9 检查及新脚本的项目内 Ruff 检查通过。数据库与增量审计、全量导出字段对照、生产构建和真实浏览器检查均通过。

- 已安装快照 revision：`c489ae693d95abcacf6e5950915350fc0513e0a4af3268e6e78e62cccafa8d44`；393,958 个标题身份及搜索回归通过，旧／新检索算法在同一语料上结果一致。
- 已核对 8,226 个快照文件及 13 个来源核验文件，与经过验证的导出目录 SHA-256 全部一致。
- 首页为 2 个元数据文件、0 个论文分片、484,498 字节，低于 512 KiB；检索传输仍满足每次 3 MiB／40 个请求的既有预算。
- 浏览器确认 ICRA、COLT、JASA 新论文的年份筛选、精确标题、方向归属及原文链接；ICML 原 ID 133474 指向正确 PMLR 论文。390px 手机布局无横向溢出、无未捕获页面错误。这里只验证了本地预览，不承诺任意公网或手机网络延迟。
- 整站构建 694,464,106 字节，低于十进制 1 GB 上限。

本地预览为 `http://127.0.0.1:5181/`。原快照完整保留在 `release-artifacts/coverage-20261016/previous-local-snapshot/`，旧来源核验文件保留在 `previous-data-sources/`。

工作分支为 `codex/coverage-refresh-20261016`，本轮只更新本地项目，没有提交、推送或发布线上网站。

可追溯记录位于 `release-artifacts/coverage-20261016/`：

- `coverage-before.json`、`coverage-after.json`、`remaining-source-years.json`：来源与年份对照。
- `incremental-integrity.json`：公开增量、原始数据保留检查和浏览器核验样例。
- `journal-registry/`、`conference-discovery/`、`book-discovery/`：采集依据。
- `registry/`、`registry-tail/`、`registry-supplement/`、`sigchi/`：实际执行回执。
- `icml-repair.json`：撤回本轮重复项与严格重放的记录。
- `snapshot-export.log`、`backend-tests-accepted.log`、`frontend-tests.log`：导出与测试日志。
- `installed-assets.json`、`search-check.json`、`performance-check.json`、`home-check.log`、`browser-qa-result.json`、`site-size.log`：安装、检索、页面与体积验收。

这些本地文件不随源代码自动发布，数据库备份保留在 `backend/data/backups/`。
