# 既有 28 个方向的经典论文补充与大厂技术报告更新（2026-11-02）

## 范围与结论

本轮只做两件事：在既有 28 个方向内补充社区反响最经典的历史论文，以及更新 2025-11 至 2026-11 的大厂技术报告。没有新增方向、没有删除论文，所有入库论文都带有至少一个既有方向标签。

- 经典论文候选 110 篇，经官方来源解析 107 篇，最终入库 **86 篇**；其余 21 篇全部早于 2000 年，被论文表 `year` 字段的 2000–2100 约束挡下，其中 3 篇（DARPA 1988、Eyes 1996、MemConsistency 1990）连元数据都未解析成功。
- 86 篇新论文获得 122 条人工方向标签，覆盖 **24 个既有方向**；其中 35 篇同时获得两个及以上方向。规则复标另外补充 45 条标签，人工标签全部保留。
- 86 篇全部通过公开准入校验（`venue_confirmed=1`、来源为 DOI 或官方会议页、无仓库型来源），导入冲突 0 条、重复 publisher_key 0 条。
- 引用数：48 篇随解析结果带入 OpenAlex 引用数，本轮再为 38 篇零引用论文补抓，35 篇通过标题与第一作者校验后写入；GAN、Spanner、KLEE 未找到可校验记录，保持 0。
- 大厂技术报告库扩至 **140 篇 / 26 家机构**；本轮新增 **28 篇**（2025-11-18 至 2026-10-28），并新增 Amazon、美团两个机构条目。
- 论文主表增至 413,889 篇（本轮 +86）；方向总数保持 28 个；来源目录、方向定义、公开准入规则均未改动。
- 本轮不提交、不推送、不部署。

## 经典论文筛选口径

候选清单见 `seeds/direction_classics.csv`，110 条，按方向标注（分号分隔）。入选标准是“教科书级、领域奠基或长期被引最高”，且必须存在可核验的官方来源：

| 解析途径 | 用途 | 校验 |
| --- | --- | --- |
| Crossref | 有 DOI 的期刊/会议论文 | 标题相似度 ≥ 0.95，年份差 ≤ 2 |
| NeurIPS / PMLR 会议录索引 | 无 DOI 的 NeurIPS、ICML 论文 | 标题精确匹配 + 官方落地页 |
| USENIX / JMLR / NeurIPS D&B meta | 官方页面 `citation_*` 元数据 | 标题、作者逐字比对 |
| arXiv | 兜底 | 标题与年份匹配 |

作者列表按官方元数据整表比对，标题去标点、去大小写后归一化；短标题与副标题（如 ACM 的 `Title: Subtitle` 形式）允许前缀匹配。每一步的解析来源、作者数、官方链接都记录在 `output/analysis-20261102-classics/backfill-report.json`，可逐条复核。

发布前整理：已将 107 条解析元数据存入 `seeds/direction_classics_resolved.json`，维护脚本默认读取该文件，避免临时输出清理后失去必要输入。

**21 篇未能入库的原因**：论文表 `Paper.year` 有 `BETWEEN 2000 AND 2100` 的检查约束，pre-2000 经典（LSTM 1997、SPIN 1997、Byzantine Generals 1982、Rendering Equation 1986、Marching Cubes 1987 等）无法写入。本轮没有修改该约束，也没有为绕过它而伪造年份。

## 入库结果

### 按会议/期刊

| 来源 | 篇数 | 代表论文 |
| --- | ---: | --- |
| NeurIPS | 13 | AlexNet、GAN、Word2Vec、Seq2Seq、GloVe 之外的双 Q、GCN 等 |
| ICML | 10 | BatchNorm、Dropout、TRPO、A3C、SAC、Dueling DQN、BLIP |
| CVPR | 8 | ResNet、YOLO、Faster R-CNN、SIFT、ImageNet 数据库 |
| OSDI | 5 | MapReduce、Bigtable、Spanner、Orca、KLEE |
| SOSP | 4 | 分布式系统经典 |
| KDD / SIGCOMM / ISCA | 各 3 | XGBoost、数据中心网络、体系结构 |
| Bioinformatics | 3 | SAMtools、BWA、STAR |
| 其余 25 个来源 | 各 1–2 | ICCV、EMNLP、S&P、CCS、UIST、ATC、USENIX Security、TR、SIGGRAPH、TPAMI、JMLR 等 |

### 按年份

2000–2009 年 24 篇，2010–2014 年 20 篇，2015–2019 年 31 篇，2020–2022 年 11 篇。2017 年最多（11 篇），对应深度学习与系统方向的集中爆发期。

### 按方向（人工标签）

| 方向 | 新增 | 方向 | 新增 | 方向 | 新增 |
| --- | ---: | --- | ---: | --- | ---: |
| `cv` 计算机视觉 | 18 | `ml` 机器学习 | 6 | `retrieval` 信息检索 | 4 |
| `systems` 系统软件 | 11 | `nlp` 自然语言处理 | 5 | `network` 计算机网络 | 4 |
| `dl` 深度学习 | 11 | `generative` 生成模型 | 5 | `robotics` 机器人 | 4 |
| `security` 安全 | 8 | `graph` 图学习 | 5 | `multimodal` 多模态 | 3 |
| `rl` 强化学习 | 6 | `architecture` 体系结构 | 5 | `federated` 联邦学习 | 3 |
| `software` 软件工程 | 5 | `speech` 语音 | 5 | `hci` 人机交互 | 3 |
| `bioinformatics` 生物信息 | 3 | `llm` 大语言模型 | 2 | `alignment` 对齐 | 2 |
| `graphics` 图形学 | 2 | `inference` 推理优化 | 1 | `ai` 人工智能 | 1 |

未新增论文的 4 个方向：`agent`、`specdec`、`transformer` 的经典论文（Attention、GPT-3、CoT、FlashAttention、Blockwise Parallel Decoding、ReAct 等）已在此前的 AI 经典补录中入库，本轮不重复导入；`theory` 的 6 篇候选（STOC 1971、JACM 1991、TIT 1976 等）全部早于 2000 年，被 schema 约束挡下。

## 标注与准入验证

- 人工标签：86 篇共 122 条，`source='manual'`、`score=2.0`，全部指向既有方向 code；规则复标运行后人工标签未被覆盖。
- 规则标签：45 条，来自既有标题规则与来源先验，未新增规则。
- 准入：86/86 `venue_confirmed=1`，publisher_key 唯一，冲突 0；公开准入要求的形式化引用（DOI 或官方 URL）全部满足，没有 arXiv、Zenodo、OSF 等仓库型来源。
- 数据一致性：`apply_records` 返回 `new=86`，导入报告 `verified=true`，`conflict_total=0`。

## 引用数补全

86 篇中 48 篇随解析带入引用数（OpenAlex），其余 38 篇为 0。本轮通过 Semantic Scholar 标题匹配补抓：

- 35 篇通过“标题归一化相同或相似度 ≥ 0.95 + 第一作者姓氏一致”校验后写入；其中 AlexNet 132,814、Faster R-CNN 77,156、BatchNorm 48,569、Dropout 45,203、GCN 38,486。
- 3 篇保持 0：GAN（Semantic Scholar 只返回作者不匹配的合并记录）、Spanner（匹配到 Haifa 会议的另一条记录）、KLEE（未匹配到标题）。
- 补录后 86 篇的引用数总和约 169 万，中位数 6,240。

引用数只影响榜单排序，不影响方向标签与公开准入。

## 大厂技术报告更新（2025-11 至 2026-11）

`seeds/industry_reports.csv` 扩至 140 篇，`seeds/industry_orgs.csv` 扩至 26 家机构；`frontend/static/industry.json` 已重建（`--verify-arxiv` 校验通过）。

- 时间窗内（2025-11 起）共 43 篇，其中本轮新增 28 篇。
- 新增机构：Amazon（Nova 2.0 Lite 安全评估）、美团（LongCat 系列）。
- 新增 28 篇构成：技术报告 17 篇、系统卡 6 篇、模型卡 5 篇；覆盖 15 家机构。

| 日期 | 机构 | 类型 | 标题 |
| --- | --- | --- | --- |
| 2025-11-18 | Google | 模型卡 | Gemini 3 Pro Model Card |
| 2025-11-24 | Anthropic | 系统卡 | Claude Opus 4.5 System Card |
| 2025-11-26 | 阿里 | 技术报告 | Qwen3-VL Technical Report |
| 2025-12-08 | 美团 | 技术报告 | LongCat-Image Technical Report |
| 2025-12-15 | Ai2 | 技术报告 | Olmo 3 |
| 2025-12-24 | NVIDIA | 技术报告 | Nemotron 3: Efficient and Open Intelligence |
| 2026-01-06 | 小米 | 技术报告 | MiMo-V2-Flash Technical Report |
| 2026-01-13 | Mistral | 技术报告 | Ministral 3 |
| 2026-01-14 | 阶跃星辰 | 技术报告 | STEP3-VL-10B Technical Report |
| 2026-01-23 | 美团 | 技术报告 | LongCat-Flash-Thinking-2601 Technical Report |
| 2026-01-27 | Amazon | 技术报告 | Evaluating Nova 2.0 Lite under Frontier Safety |
| 2026-02-02 | 月之暗面 | 技术报告 | Kimi K2.5: Visual Agentic Intelligence |
| 2026-02-04 | 百度 | 技术报告 | ERNIE 5.0 Technical Report |
| 2026-02-11 | 阶跃星辰 | 技术报告 | Step 3.5 Flash |
| 2026-02-17 | Anthropic | 系统卡 | Claude Sonnet 4.6 System Card |
| 2026-02-19 | Google | 模型卡 | Gemini 3.1 Pro Model Card |
| 2026-03-21 | 字节 | 模型卡 | Seed1.8 Model Card |
| 2026-04-23 | OpenAI | 系统卡 | GPT-5.5 System Card |
| 2026-05-05 | OpenAI | 系统卡 | GPT-5.5 Instant System Card |
| 2026-05-11 | 阿里 | 技术报告 | Qwen-Image-2.0 Technical Report |
| 2026-05-25 | 百度 | 技术报告 | ERNIE-Image Technical Report |
| 2026-05-26 | MiniMax | 技术报告 | The MiniMax-M2 Series |
| 2026-06-30 | 字节 | 模型卡 | Seed2.0 Model Card |
| 2026-09-02 | Google | 模型卡 | Gemini 3.8 Flash Model Card |
| 2026-09-22 | Anthropic | 系统卡 | Claude Opus 5.5 System Card |
| 2026-10-07 | Anthropic | 系统卡 | Claude Haiku 5.5 System Card |
| 2026-10-20 | 阿里 | 技术报告 | Qwen-Audio-3.1-ASR Technical Report |
| 2026-10-28 | NVIDIA | 技术报告 | Nemotron 3.5 Super and Lightning |

重建后的行业数据统计：`tech_report` 89、`paper` 27、`system_card` 8、`model_card` 8、`code_release` 5、`journal_article` 2、`blog` 1；按年 2019–2026 分别为 1/1/4/10/18/41/30/35。

## 验证

- 后端：完整测试套件通过（退出码 0），其中 `test_direction_classics.py` 校验候选清单完整性、方向与来源合法性，`test_industry_data.py` 校验机构数、报告数、时间序与首条记录。
- 前端：`npm test` 39 个文件 304 项通过；`npm run build` 构建成功。
- 数据库：413,889 篇；86 篇经典全部 `venue_confirmed=1`；人工标签 122 条；引用数 83/86。
- 快照：重建为 405,161 篇，revision `6174707f7599d480b34d7b765eb49a86f9d38c5c953f46d09fb65803a7bc97b4`，`generated_at` 2026-11-02T07:46:45Z，与数据库逐字段比对一致（`database_consistent=true`）；`check:snapshot-home` 首屏元数据 457,697 字节、68 ms；`check:snapshot-search` 读取 179 个索引文件、9.6 s；`check:source-coverage` 通过（338 个来源、14 个关联文件）。
- 来源覆盖：`export_source_audit` 显示 338 个配置来源中 336 个在快照有论文、325 个为直接来源，`full_coverage_verified=false`，84 个来源-年份单元仍为零收录，状态分布为未验证 44、待发表 16、未排期 11、版本未核实 7、联合版本 4、无会议录 1、抓取失败 1。

## 未做与限制

- pre-2000 经典 21 篇无法入库；如需收录需迁移论文表年份约束，本轮未做。
- GAN、Spanner、KLEE 三篇引用数缺失。
- 本轮所有改动只在本地工作区，未提交、未推送、未部署。
