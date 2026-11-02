# 剩余未命中论文的方向扩充（2026-11-01）

## 范围与结论

上一轮把未命中任何方向的论文从 161,890 篇降到 96,120 篇后，剩余论文主要落在现有 22 个方向之外：语音与声学、软件工程、理论计算机科学、生物信息、机器人、图形学，以及遥感、控制、认知科学、交通等尚未建方向的领域。本轮新增 6 个方向，方向总数由 22 增至 28；不重新采集论文，只对库内 413,803 条 CCF A/B 记录重算方向标签。

- 新增 99 条来源先验：`software` 45、`speech` 5、`robotics` 3、`bioinformatics` 7、`theory` 29、`graphics` 10。
- 新增 6 条标题规则，每个新方向 1 条，均为 `title` 字段、权重 1.0、启用。
- 未命中任何方向的论文由 96,120 篇降至 **37,048** 篇；获得方向标签的论文由 317,683 篇增至 **376,755** 篇。
- 新增方向标签 94,202 条，移除 0 条；59,072 篇论文首次获得方向标签，其中 482 篇同时获得两个新方向。
- 既有 22 个方向的标签数量逐方向完全不变（0 增减）。
- 论文主表、来源目录、公开准入规则和既有方向定义均未改变。本轮不提交、不推送、不部署。

| 方向 | 新增来源 | 标签总数 | 新打标论文 | 其中既有方向论文另有新标签 |
| --- | ---: | ---: | ---: | ---: |
| `speech` 语音、音频与声学 | 5 | 20,905 | 16,175 | 4,730 |
| `software` 软件工程与形式化方法 | 45 | 19,224 | 11,286 | 7,938 |
| `robotics` 机器人与自动化 | 3 | 16,591 | 7,250 | 9,341 |
| `bioinformatics` 生物信息与医学信息 | 7 | 15,778 | 9,761 | 6,017 |
| `theory` 理论与算法 | 29 | 13,271 | 11,603 | 1,668 |
| `graphics` 计算机图形学与虚拟现实 | 10 | 8,433 | 3,479 | 4,954 |
| 合计 | 99 | 94,202 | 59,072 | 34,648 |

“标签总数”是数据库口径；同一条论文可同时属于多个新方向，因此逐方向“新打标论文”相加大于 59,072。新方向标签中有 59,554 条落在 59,072 篇首次打标论文上，其余 34,648 条落在已有其他方向标签的论文上，形成多方向标注。

## 方向定义

| 代码 | 名称 | 英文 | 覆盖范围 |
| --- | --- | --- | --- |
| `software` | 软件工程与形式化方法 | Software Engineering & Formal Methods | 软件工程、程序语言、编译、测试与分析、形式化方法与验证 |
| `speech` | 语音、音频与声学 | Speech, Audio & Acoustics | 语音识别/合成/增强/分离、说话人、音频与声学 |
| `robotics` | 机器人与自动化 | Robotics & Automation | 机器人、SLAM、操作与抓取、运动规划、控制与自动化应用 |
| `bioinformatics` | 生物信息与医学信息 | Bioinformatics & Medical Informatics | 计算生物学、基因组/蛋白组、单细胞、医学信息学 |
| `theory` | 理论与算法 | Theory & Algorithms | 算法与复杂度、自动机与逻辑、数据库理论、算法博弈与经济 |
| `graphics` | 计算机图形学与虚拟现实 | Computer Graphics & VR | 渲染、几何处理、动画与仿真、VR/AR/XR、CAD |

方向代码均为小写字母，满足前端 `^[a-z]+$` 的方向代码约束；`min_score` 均为 2.0，来源先验与标题规则都按既有打分公式（来源 × 2.0、标题 × 2.0）达到阈值。

## 实现

### 来源先验

仅选择主题单一的 CCF A/B 来源，权重 1.0、启用。来源先验作用于来源内全部论文，因此混合来源不建先验，避免整库系统性误标。

| 方向 | 来源数 | 来源 | 先验覆盖标签 |
| --- | ---: | --- | ---: |
| `software` | 45 | ICSE、FSE、ASE、ISSTA、OOPSLA、POPL、PLDI、TSE、TOSEM、TOPLAS、JSS、IST、ESE、SCP、SPE、SoSyM、RE、ICSME、SANER、ICPC、ICFP、ECOOP、CAiSE、ESEM、FM、FMCAD、CAV、ETAPS、ASE Journal、Journal of Software: Evolution and Process、ICWS、TSC、MoDELS、ISSRE、STVR、IETS、VMCAI、JFP、SAS、ICSOC、RE Journal、CC、FAC、FMSD、CADE | 17,766 |
| `speech` | 5 | JASA、INTER- SPEECH、TASLP、SPECOM、JSLHR | 18,261 |
| `robotics` | 3 | ICRA、TR、TASAE | 11,913 |
| `bioinformatics` | 7 | PLOS Computational Biology、Bioinformatics、Briefings in Bioinformatics、BIBM、TCBB、JAMIA、RECOMB | 14,654 |
| `theory` | 29 | TIT、TCS、SODA、STOC、FOCS、ICALP、ESA、Algorithmica、IANDC、SoCG、JSC、LICS、SICOMP、COCOON、JCSS、TALG、MSCS、CCC、CONCUR、SAT、TOMS、TOCL、JGO、INFORMS、JACM、PODS、ICDT、WINE、CC Journal | 12,158 |
| `graphics` | 10 | TOG、CGF、SIGGRAPH、VR、ISMAR、CAD、CAGD、CVMJ、I3D、SCA | 4,568 |

共 99 条映射，`(direction_id, venue_id)` 无重复；新增来源均无既有方向先验，仍保持“一个来源只对应一个方向先验”的约束。

选择口径与排除项：

- **JASA 计入 `speech`**：方向名称包含声学，JASA 的物理声学、水声、噪声与心理声学均属该方向；JASA 单刊贡献 10,472 条标签，其中 9,747 条此前未命中。
- **TASAE 计入 `robotics`**：来源为自动化科学与工程，内容以控制、制造自动化、机器人与多智能体为主，混有少量医疗、农业与商业应用论文，仍按自动化主题整体映射。
- **ICSOC、TSC、ICWS 计入 `software`**：三者 CCF 领域均为软件工程/系统软件/程序设计语言，内容以服务计算、微服务与云边系统为主。
- **TVCG 不重复映射**：TVCG 已有 `hci` 先验，为保持单来源单先验，不向 `graphics` 增补；视觉化与 VR 论文由标题规则补充（本轮 488 条 TVCG 论文获得 `graphics` 标签）。
- **不建先验的混合来源**：ICASSP（信号处理，仅语音/音频子集由规则新增打标 952 篇）、TGARS（遥感）、Information Sciences、TKDE、TCSVT、TITS（交通）、TSMC、IEEE Transactions on Cybernetics、TFS、TEC、TAC（控制/模糊/情感计算）、AEI（工程信息学）、SCIS、WWW、CogSci、Cognition 等。它们同时刊登多个子领域论文，整刊加先验会系统性误标；其中属于 28 个方向的主题由标题规则捕捉。

### 标题规则

6 条规则写入 `seeds/direction_rules.csv`，均为 `title` 字段、权重 1.0、启用；标题命中记 2.0 分，达到阈值。规则针对跨来源的明确主题，并要求技术语境，避免普通用词误报。

| 方向 | 主题 | 标题命中（全库） | 未命中论文命中 | 先验之外命中 | 规则独有标签 |
| --- | --- | ---: | ---: | ---: | ---: |
| `speech` | 语音识别/合成/增强/分离/翻译、说话人、关键词检出、语音活动检测、音频描述、声事件、音频深伪、歌声 | 5,185 | 2,688 | 1,009 | 2,644 |
| `robotics` | 机器人、SLAM、操作与抓取、足式运动、人机协作、多机器人、遥操作；UAV/无人机需带导航/控制语境 | 8,722 | 2,560 | 618 | 4,678 |
| `bioinformatics` | 基因组/蛋白组/转录组、单细胞、系统发育、蛋白结构/功能、基因表达、DNA/RNA 测序、医学信息 | 4,401 | 2,377 | 127 | 1,124 |
| `theory` | NP 难/完全、近似/在线/参数化算法、自动机、可满足性、证明与电路复杂度、组合优化、类型论 | 1,892 | 1,028 | 271 | 1,113 |
| `software` | 程序分析、修复、测试与模糊测试、程序合成、模型检验、形式验证、重构、需求工程、漏洞检测 | 3,765 | 1,222 | 76 | 1,458 |
| `graphics` | 渲染（神经/体/可微/实时/注视点）、几何与网格、动画与流体/布料仿真、VR/AR/XR、辐射场 | 4,517 | 658 | 198 | 3,865 |

“先验之外命中”指不在该方向来源先验内的论文，是规则相对来源先验的增量；“规则独有标签”指只由标题规则命中、未命中来源先验的标签，其中多数落在已有其他方向标签的论文上。仅靠规则首次打标的论文合计 1,817 篇。

### 规则复核与精化

首轮草稿在抽样中暴露了系统性误报，均通过收紧正则解决，未新增重复规则：

| 方向 | 首轮问题 | 精化 |
| --- | --- | --- |
| `robotics` | 裸 `uav|drone` 命中 UAV 通信、遥感与物流论文（先验之外 788 篇中大量为网络/遥感） | 仅在导航、路径规划、编队、集群、控制、降落、抓取等语境下匹配 UAV/无人机；保留多无人机与“控制/编队 + of/for + UAV”结构 |
| `graphics` | 裸 `rendering`、`ray tracing` 命中空间音频渲染、水声与地震射线追踪 | 改为神经渲染、体渲染、可微渲染、实时渲染、注视点渲染、路径追踪等图形学复合词；保留 VR/AR/XR、几何、动画、辐射场 |
| `bioinformatics` | 裸 `gene|protein|dna|rna` 命中 DNA 存储编码、基因池进化算法、粮食蛋白遥感反演 | 改为蛋白结构/功能/稳定性、基因表达/集合、DNA 测序/甲基化/变异、RNA 结构/编辑、单细胞 RNA 等复合语境 |
| `theory` | `lower/upper bounds` 命中统计置信界、语音暴露上界；`approximation algorithm` 命中随机逼近算法 | 移除泛化的上下界与图灵机词条；对 `stochastic approximation` 加负向断言 |
| `software` | `code generation` 命中 Gray code 生成 | 对 `gray`、`qr` 前缀加负向断言，并补充动态分析、测试选择、可靠性、技术债等词条 |
| `speech` | 首轮漏掉语音到语音、语音活动检测与歌声转换 | 补充 `speech-to-speech`、`voice activity detection`、`singing voice` 等词条 |

精化后各规则在先验之外的命中数分别为 1,009、618、127、271、76、198；六条规则的全库标题命中合计由首轮 29,670 条降至 28,482 条，但先验之外的增量保持稳定（合计 2,299 条）。

## 覆盖构成

数据库口径下新方向标签的来源构成（同一论文可同时被来源与标题命中）：

| 方向 | 标签总数 | 来源命中 | 标题命中 | 两者 | 仅来源 | 仅标题 | 新打标论文 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `software` | 19,224 | 17,766 | 3,765 | 2,307 | 15,459 | 1,458 | 11,286 |
| `speech` | 20,905 | 18,261 | 5,185 | 2,541 | 15,720 | 2,644 | 16,175 |
| `robotics` | 16,591 | 11,913 | 8,722 | 4,044 | 7,869 | 4,678 | 7,250 |
| `bioinformatics` | 15,778 | 14,654 | 4,401 | 3,277 | 11,377 | 1,124 | 9,761 |
| `theory` | 13,271 | 12,158 | 1,892 | 779 | 11,379 | 1,113 | 11,603 |
| `graphics` | 8,433 | 4,568 | 4,517 | 652 | 3,916 | 3,865 | 3,479 |

新方向标签在来源与规则之外的重复很少；`graphics` 与 `speech` 的规则贡献占比最高，因为 ICASSP、CVPR、TVCG 等混合来源中的图形与语音论文只能靠标题识别。`theory` 几乎全部由 29 个单一主题来源覆盖，规则的边际增量最小。

新方向的标签还会落在已有其他方向标签的论文上：例如 CVPR 的神经渲染论文同时属于 `cv` 与 `graphics`，ICASSP 的语音论文同时属于 `speech` 与 `nlp`/`multimodal`，ICRA 的机器人学习论文同时属于 `robotics` 与 `rl`/`agent`。这类多标签是有意的主题相关性标注，不改变既有方向的标签集合。

## 验证

重算使用 `backend/scripts/reindex_topics.py`，重算前备份数据库，并在提交前校验论文数量、论文元数据指纹、人工标签与 FTS5 完整性。本轮结果：

- `rules_added=6`、`venue_rules_added=99`、`updated_scores=0`；新增标签 94,202 条、移除 0 条。
- 可打标论文 413,803 篇不变，未命中由 96,120 降至 37,048；获得方向标签的论文由 317,683 增至 376,755。
- 论文元数据指纹一致，5 条人工标签完全保留。
- 方向 28 个、启用规则 328 条、启用来源先验 285 条；`(direction_id, keyword)` 与 `(direction_id, venue_id)` 均无重复，没有任何来源对应两个方向先验。
- 既有 22 个方向的标签数量与备份库逐方向一致，增减均为 0。
- 数据库 `quick_check` 为 `ok`，FTS5 完整性检查 `ok`。
- 重算前的模拟与实跑逐方向一致：未命中 37,048 篇，六个新方向标签数与模拟完全相同。
- 后端测试套件 1,200 项通过。新增 12 项方向规则测试，覆盖六个新方向的正例与反例（Gray code、Keynote Speech、UAV 缓存、DNA 存储编码、随机逼近、音频渲染）；`test_catalog_expansion.py` 的方向集合更新为 28 个，来源映射更新为 285 条。

重算前备份：`backend/data/backups/before-topic-reindex-20261101T130256652415Z.db`。

## 本地快照

本地快照已按新方向重算并重新导出，未发布：

- 版本 `0a9eba2be96a0697d75b052a4b6b874e6d770e3b9417b1a8023e1b7dfef422bc`，生成时间 `2026-11-01T13:25:58Z`，公开论文 405,075 篇（与上一版一致，公开准入规则未变）。
- 导出命令 `python -m scripts.export_snapshot --check-database` 退出码 0，`database_consistent=true`。
- 公开口径方向 28 个；获得方向标签 368,112 篇，未命中 36,963 篇（数据库口径为 376,755 / 37,048，差异来自公开准入过滤）。
- 公开口径六个新方向论文数：`speech` 20,834、`software` 18,963、`robotics` 16,503、`bioinformatics` 15,735、`theory` 12,886、`graphics` 8,397；与数据库口径的差额分别为 71、261、88、43、385、36 篇。
- 快照文件闭包 8,353 个文件、832,953,032 字节（约 794 MiB），低于 1 GB 上限。
- `frontend/static/data-sources` 已用 `scripts.export_source_audit` 针对该版本重新导出：338 个来源、325 个直接来源、336 个有论文来源、14 个关联分片。
- 前端验收通过：`check:snapshot-home`、`check:snapshot-search`（405,075 条标题身份）、`check:source-coverage`、`check:snapshot-performance`（同语料旧引擎一致性 `true`）、`npm run build`。
- `npm test` 默认并发在 39 个测试文件同时启动时，`PaperList.test.jsx` 的 5 秒超时用例超时；单文件运行 5 项全过，`--maxWorkers=4` 全量 39 文件 / 304 项全过，判定为本机并发下的计时抖动，而非功能回归。

## 边界

- 方向标签表示主题相关性，不是精确的方法论文清单。来源先验会整刊标注，标题规则仍可能产生跨领域误报；公开快照还会过滤未确认来源、级别不匹配和非研究条目。
- `TASAE`、`ICSOC`、`TSC`、`ICWS` 等来源比方向名称更宽，来源先验会把少量应用论文纳入对应方向；`JASA` 的声学论文全部计入 `speech`，其中包含水声与噪声控制。
- `TVCG` 仍只映射 `hci`，视觉化论文通过图形学规则获得第二标签；`ICASSP`、`TGARS`、`Information Sciences`、`TKDE`、`TCSVT`、`TITS`、`AEI`、`SCIS`、`WWW`、`CogSci`、`Cognition` 等混合来源保持无整刊先验。
- 剩余 37,048 篇未命中论文主要来自 28 个方向之外的领域：未命中语音规则的 ICASSP 信号处理论文 5,319 篇、TGARS 遥感 4,613 篇、CogSci 与 Cognition 认知科学 3,894 篇、Information Sciences 2,808 篇、TITS 交通 2,787 篇、TSMC 与 Cybernetics 3,768 篇、AEI 工程信息 1,493 篇、TFS 1,205 篇、TKDE 1,113 篇、TCSVT 1,022 篇、SCIS 941 篇。继续覆盖需要新增遥感/地学、控制/控制论、认知科学、交通等方向，属于分类体系决策，而不是继续放宽现有规则。
- 本轮只改变方向分类与标签，不改变来源目录、论文数量、公开准入规则或前端筛选契约，也不代表 CCF A/B 论文已完整收齐。
- 本地快照已在本地重新导出，但本轮没有提交、推送或部署；线上仍为 2026-10-31 发布的快照。
