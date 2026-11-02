# 方向覆盖扩充（2026-11-01）

## 范围与结论

本轮不重新采集论文，只对库内 413,803 条 CCF A/B 记录重算方向标签。重点扩充 LLM 推理优化、投机解码、计算机网络与系统软件，并同步补齐检索、生成式、图学习、对齐、智能体与安全。

- 新增 52 条标题规则：`systems` 15、`network` 14、`inference` 8、`specdec` 7、`retrieval` 3，`generative`、`graph`、`alignment`、`agent`、`security` 各 1。
- 精化 2 条产生误报的 `network` 标题规则（语义通信、量子网络），通过 `RULE_REFINEMENTS` 原位替换，不新增重复规则。
- 本轮未新增来源先验；打分公式、方向阈值、来源目录（`venues.csv`）、公开准入规则和论文主表均未改变。
- 规则覆盖 10 个方向，其余 12 个方向的规则与来源映射保持不变。

| 方向 | 本轮前 | 本轮后 | 变化 |
| --- | ---: | ---: | ---: |
| `inference` 推理优化 | 10,900 | 11,122 | +222 |
| `network` 计算机网络 | 27,332 | 27,566 | +234 |
| `systems` 系统软件与分布式 | 12,947 | 13,466 | +519 |
| `specdec` 投机解码 | 351 | 362 | +11 |
| `retrieval` 信息检索 | 4,173 | 4,266 | +93 |
| `generative` 生成式 AI 与扩散模型 | 13,554 | 13,719 | +165 |
| `graph` 图学习与知识图谱 | 9,336 | 9,389 | +53 |
| `alignment` 安全与对齐 | 3,329 | 3,380 | +51 |
| `agent` 智能体 | 18,001 | 18,030 | +29 |
| `security` 安全 | 27,203 | 27,233 | +30 |

本轮共新增方向标签 1,407 条，移除 2 条；获得任一方向标签的论文由 251,471 篇增至 251,913 篇（+442），未命中任何方向的论文由 162,332 篇降至 **161,890** 篇。标签增量大于新打标论文数，是因为多数新增标签落在已有其他方向标签的论文上。上表为数据库口径；公开快照受来源确认、级别匹配和非研究条目标题等准入规则约束，计数略低。

## 实现

### 标题规则

规则写入 `seeds/direction_rules.csv`，新增规则均为 `title`、权重 1.0、启用；标题命中记 2.0 分，达到默认阈值 2.0。规则普遍要求技术语境，避免把应用领域的普通用词当作方向：

- **推理优化**（8 条）：overthinking；高效/快速推理与推理压缩；test-time / inference-time compute；prompt/context 压缩与剪枝；模型路由与级联；视觉 token 剪枝；带 LLM 语境的通用 token 剪枝；reasoning/thought/CoT 压缩。
- **计算机网络**（14 条）：语义通信；ISAC 全称；带 5G/6G 语境的 ISAC 缩写；量子网络；带网络语境的 LEO 卫星星座；NTN 与星地网络；TSN/确定性网络；O-RAN 与 RIC；反向散射通信；可见光通信；广域网；网内聚合/处理/缓存/遥测；意图驱动网络与网络数字孪生；联合信源信道编码。
- **系统软件**（15 条）：数据库查询优化；基数估计与学习索引；事务处理/MVCC；并发控制；隔离级别；向量数据库；编译器优化/测试；LLVM/MLIR；带计算语境的实时系统；WCET/可调度性分析；Kubernetes；根因分析与故障诊断；性能缺陷/回归；AIOps；机密计算。
- **投机解码**（7 条）：draft/speculative tree 与 verification/rejection；speculative decoding/sampling/inference/prefill/generation/draft/token；speculative KV cache 与 key-value caching；speculative early exiting；带 LLM 语境的 asynchronous/pipelined/parallel speculation；attention-level speculation；speculative tree。
- **信息检索**（3 条）：reranking/reranker；hybrid、multi-stage、two-stage retrieval；late interaction 与 ColBERT。
- **其他方向**：diffusion language models/DLLM（生成式）；GraphRAG（图学习）；reward hacking 与 sycophancy（对齐）；computer-use agents（智能体）；IoT/firmware/supply-chain 攻击、安全与漏洞（安全）。

### 规则精化

两条首轮新增的 `network` 规则在复核样本时仍有过宽匹配，使用 `RULE_REFINEMENTS` 替换为带排除条件的版本：

| 方向 | 原规则问题 | 精化后 |
| --- | --- | --- |
| `network` | 语义通信规则命中“LLM 之间的语义通信”和 MICRO 的处理器验证论文 | 排除 `between (large) language models` 与含 `processor verification` 的标题 |
| `network` | 量子网络规则命中“post-quantum networks”和量子网络嵌入（VQNE） | 排除 `post-` 前缀及 `embedding` 结尾 |

精化移除 2 条 `network` 标签：DiffTest-H（硬件加速处理器验证中的语义通信）与 VQNE（变分量子网络嵌入，用于网络对齐）。两条论文均保留原有方向标签（DiffTest-H 仍属 `architecture`；VQNE 无方向标签）。

## 覆盖构成

数据库口径下各方向的标签来源（同一论文可同时被标题和来源命中）：

| 方向 | 标签总数 | 来源先验 | 仅来源 | 标题命中 | 仅标题 | 两者 | 其他 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `inference` | 11,122 | 0 | 0 | 6,102 | 6,102 | 0 | 5,020 |
| `network` | 27,566 | 23,513 | 16,171 | 11,395 | 4,053 | 7,342 | 0 |
| `systems` | 13,466 | 8,389 | 6,593 | 6,795 | 4,999 | 1,796 | 78 |
| `specdec` | 362 | 0 | 0 | 291 | 291 | 0 | 71 |
| `retrieval` | 4,266 | 0 | 0 | 3,925 | 3,925 | 0 | 341 |
| `generative` | 13,719 | 0 | 0 | 11,111 | 11,111 | 0 | 2,608 |
| `graph` | 9,389 | 0 | 0 | 8,841 | 8,841 | 0 | 548 |
| `alignment` | 3,380 | 0 | 0 | 2,337 | 2,337 | 0 | 1,043 |
| `agent` | 18,030 | 0 | 0 | 15,672 | 15,672 | 0 | 2,358 |
| `security` | 27,233 | 16,882 | 11,235 | 15,998 | 10,351 | 5,647 | 0 |

“其他”为不命中标题规则的既有摘要规则或人工标签。新增标题规则会让部分原本只由摘要规则命中的标签也进入“标题命中”，因此 `specdec` 的“其他”由 76 降至 71，而标签总数只增加 11。

## 投机解码覆盖边界

`specdec` 从 351 条增至 362 条（+11），新增标题包括 Attention-Level Speculation、SpecCache、SpeCache、CXL-SpecKV、SpecEE、SpecPrefill、PipeInfer、SMART、Speculative Rejection 与 TreeBoN 等，均属于 draft/verify、KV cache 投机、投机预填充、投机早退或流水线投机等解码加速方法。

复核后 `specdec` 已接近标题层面的饱和：

- 未标 `specdec` 的标题中已无 `speculative decoding` 字样；`speculative tree` 与 `attention-level speculation` 也已由本轮规则覆盖。
- 仍有 222 条未标标题含 `speculat`，但绝大多数是 HCI 的思辨设计/共同思辨、CPU 投机执行与侧信道、存储/网络投机等非 LLM 解码主题。
- 其余 LLM 侧标题属于投机搜索、投机推理、投机规划、Speculative RAG、投机智能体、投机服务调度等更宽泛的“投机推理/投机执行”，本轮未纳入，以保持 `specdec` 作为投机解码的方向边界。
- 未按方法名（EAGLE、Medusa、Lookahead 等）建规则：同名词条会命中视觉模型、服务端框架和语音识别论文，误报率高。

因此 `specdec` 的绝对数量仍会低于 `inference`；继续扩充需要摘要级语义规则或人工复核，而不是继续放宽标题匹配。

## 验证

本轮共执行四次方向重算，规则与标签变化如下：

- 首轮：`rules_added=46`、`updated_scores=2,183`，新增标签 1,400 条（`inference` 222、`network` 236、`systems` 519、`specdec` 2、`retrieval` 93、`generative` 165、`graph` 53、`alignment` 51、`agent` 29、`security` 30）。
- 精化：`rules_refined=2`、`updated_scores=0`，移除 `network` 2 条，新增 0。
- 补充投机解码：`rules_added=4`、`updated_scores=239`，新增 `specdec` 6 条。
- 补充注意力级与投机树：`rules_added=2`、`updated_scores=3`，新增 `specdec` 3 条。

最终库内 311 条规则全部启用，`(direction_id, keyword)` 无重复；论文主表 413,803 篇不变，论文元数据指纹一致，5 条人工标签完全保留，FTS5 完整性检查 `ok`，数据库 `quick_check` `ok`。`pytest tests/test_topic_index.py` 8 项通过。

重算前备份：

- `backend/data/backups/before-topic-reindex-20261101T094754503025Z.db`（首轮）
- `backend/data/backups/before-topic-reindex-20261101T095845736390Z.db`（精化前）
- `backend/data/backups/before-topic-reindex-20261101T102554744053Z.db`（投机规则补充前）
- `backend/data/backups/before-topic-reindex-20261101T103502496187Z.db`（最后两条规则前）

## 本地快照

本地快照已重新导出并通过数据库一致性校验：公开论文仍为 405,075 篇（本轮只改变方向标签），406 个分片、22 个方向，revision `a8a46ae8a82e22d58340b70b6e2c51309317f65b6c988e3d90111cad9ef48183`，生成时间 2026-11-01T10:54:51Z。按发布文件闭包统计，站点 8,338 个文件、812,183,957 字节，低于 1,000,000,000 字节预算，余量 187,816,043 字节。

| 方向 | 公开前 | 公开后 | 变化 |
| --- | ---: | ---: | ---: |
| `inference` 推理优化 | 10,383 | 10,590 | +207 |
| `network` 计算机网络 | 27,317 | 27,551 | +234 |
| `systems` 系统软件与分布式 | 12,890 | 13,408 | +518 |
| `specdec` 投机解码 | 337 | 347 | +10 |
| `retrieval` 信息检索 | 3,949 | 4,040 | +91 |
| `generative` 生成式 AI 与扩散模型 | 13,331 | 13,491 | +160 |
| `graph` 图学习与知识图谱 | 9,110 | 9,160 | +50 |
| `alignment` 安全与对齐 | 3,105 | 3,152 | +47 |
| `agent` 智能体 | 17,265 | 17,293 | +28 |
| `security` 安全 | 26,973 | 27,003 | +30 |

公开计数略低于数据库口径，原因是公开快照还会过滤未确认来源、级别不匹配和非研究条目；方向间差异来自各方向的公开论文占比不同。

- `check:snapshot-home` 通过：首页仅请求 manifest 与 catalog 2 个元数据文件，论文分片请求 0，元数据 445,821 字节（低于 512 KiB 预算），处理 48 ms。
- `check:snapshot-search` 通过：校验 33 项精确标题、8 项自动匹配、43 项跨方向筛选、8 项非相邻 AND 查询，并离线核对全部 405,075 条标题身份；首屏冷查询 131 ms、6 个请求、1,215,133 字节，在 3 MiB／40 个请求预算内。整轮检查请求 227 个文件、18,670,551 字节，耗时 4,276 ms。该检查为本地文件传输，不等同于浏览器或移动端弱网性能。
- 因快照 revision 变化，`frontend/static/data-sources/source-coverage.json` 已重新导出并生成 14 个新关联分片；`npm run check:source-coverage` 通过：338 个来源中 325 个有直接记录、336 个在快照中有代表，14 个关联分片的哈希与论文 ID 校验一致，84 个来源／年份缺口保持原证据状态。
- `check:snapshot-performance` 通过：legacy parity 为 true；browse、broad-learning、rare-and、scoped、fuzzy 五类查询冷加载 259–494 ms、13–36 个请求、1.57–2.35 MB，均为本地文件传输口径。
- `npm test` 通过 39 个测试文件 304 项；`npm run build` 完成（24.04 s）；后端方向/打标与快照相关 73 项测试通过。

## 边界

- 标题规则仍可能产生跨领域误报。抽样中新打标的 `security` 包括 IoT 安全与隐私标签的人机研究，`alignment` 包括 sycophancy 的用户信任研究，`specdec` 包括面向推理时对齐的投机拒绝/树搜索；这些标签表示主题相关性，不应视为精确的方法论文清单。
- 本轮只改变方向标签，不改变来源目录、论文数量、公开准入规则或前端筛选契约，也不代表 CCF A/B 论文已完整收齐。其余 12 个方向未新增规则。
- 公开快照已在本地重新导出，但本轮没有提交、推送或部署；线上仍为 2026-10-31 发布的快照。
