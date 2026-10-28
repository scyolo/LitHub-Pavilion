# ICLR 历史、AI 经典论文与大厂技术报告扩充（2026-10-28）

本轮处理三项用户需求：补齐 ICLR 2019–2022 的联邦学习及其它论文；补充 Transformer／LLM／推理优化的早期经典论文；新增独立的“大厂技术报告”板块。前两项进入 CCF A/B 主库，仍严格限定 338 个 A/B 来源；第三项是独立静态目录，不进入论文库、不计入任何 CCF 统计。源码与数据快照已于 2026-10-28 提交、推送并发布上线（见 [release-20261028.md](release-20261028.md)）。

## 一、ICLR 2018–2022 官方全量补采（新增 3,479 篇）

2026-10-27 的联邦学习报告曾把 ICLR 2019–2022 列为无法补采：virtual-site JSON 缺少 OpenReview forum 标识，OpenReview API 与 DBLP 又被 403／Anubis 拦截。本轮改用**官方日程与官方 JSON 内的论文身份**，不再依赖 OpenReview API：

| 年份 | 官方依据 | 验收数 |
|---|---|---:|
| 2018 | 官方 Schedule 海报页卡片 + 缺失作者从官方 event 详情页补齐 | 336 |
| 2019 | 官方 Schedule 海报页（501）并与 Oral 日程（24）交叉核对 | 501 |
| 2020 | 官方 virtual-site poster 目录（687）与 PaperCopilot OpenReview ID 按题名／摘要对齐 | 687 |
| 2021 | 官方 virtual-site JSON 自带的 OpenReview forum 链接 | 860 |
| 2022 | 同上 | 1,095 |

- 只收主会已接收的 Poster／Spotlight／Talk／Oral，不混入 workshop；不下载 PDF。
- 每年数量必须与解析出的官方目录完全一致，否则整年拒绝导入；2020 年题名不一致时保留官方目录题名并记录开放评审题名，不静默覆盖。
- 2019 年官方日程页有 20 张卡片的题名被活动模板覆盖（显示为 Keynote、Coffee Break、Poster session 等），使用按 OpenReview forum 逐条核验的 `title_corrections.json` 校正（新增 20 条）。
- 入库走既有 publisher TOC 路径，`publisher_key` 为对应 OpenReview forum；3,143 篇（2019–2022）与 336 篇（2018）分别全部通过唯一身份与 `venue_confirmed=1` 校验，零冲突。
- 用户点名的 FedBN、FedDyn、HeteroFL、FedMA（Federated Learning with Matched Averaging）现均可在库内检索到 ICLR 正式记录。

采集入口：`backend/app/collectors/iclr.py`（被 `publisher_toc.fetch_official_inventory` 的 ICLR 分支调用），补采脚本 `backend/scripts/backfill_iclr_history.py`。该适配器同时修复了 NeurIPS 目录允许缺失作者的读取路径（仅用于历史补采，不放松正常采集校验）。

## 二、AI 经典论文与 Transformer 方向（新增 1,492 篇、方向 11,311 篇）

项目原有的完整卷采集从 2023 年开始。本轮按官方卷目录补采 2017–2022 年的 Transformer／LLM／推理优化／投机解码论文，只保留题名达到方向规则阈值者，另以 28 篇领域基石论文的白名单兜底（题名过于通用、规则无法命中）：

- 覆盖单元：NeurIPS、ICML、JMLR（2017–2022），ACL、EMNLP（2020–2022），NAACL（2021–2022），CVPR（2021–2022），ICCV 2021，ECCV 2020／2022；4 篇 ACL Anthology 缺失 XML 的论文（BERT、Transformer-XL、ELMo、Sentence-BERT）逐篇按官方 landing page 元数据核验后补入。
- 新增 1,493 篇，按来源：EMNLP 336、NeurIPS 271、ACL 256、CVPR 162、ECCV 143、NAACL 138、ICML 103、ICCV 79、JMLR 5；按年份：2017 年 9、2018 年 15、2019 年 34、2020 年 256、2021 年 486、2022 年 693。
- 代表论文包括 Attention Is All You Need、BERT、GPT-3、T5、InstructGPT、Chain-of-Thought、FlashAttention、Swin Transformer、ViT/DeiT、CLIP、DDPM、DETR、NeRF、MAE、ConvNeXt，以及投机解码的前身 Blockwise Parallel Decoding（NeurIPS 2018）等。**这不是 2017–2022 年的完整覆盖**，只补与目标方向相关的题名。

`seeds/directions.csv` 新增第 19 个方向 `transformer`（Transformer 架构），`seeds/direction_rules.csv` 新增 15 条规则（Transformer 9 条、LLM 2 条、推理优化 3 条、投机解码 1 条），覆盖自注意力、视觉 Transformer、高效注意力、BERT 系模型、RLHF、量化／剪枝／蒸馏及 Blockwise Parallel Decoding 等写法。重跑 `reindex_topics` 后方向标签变化：

| 方向 | 本轮前 | 本轮后 |
|---|---:|---:|
| transformer（新） | 0 | **11,311** |
| llm | 42,242 | **43,180** |
| inference | 7,012 | **10,131** |
| specdec | 323 | **324** |

投机解码只增加 1 篇：2017–2022 年 CCF A/B 来源内符合该方向的早期代表是 Blockwise Parallel Decoding（NeurIPS 2018，多 token 并行预测＋验证的前身）；库内原有的 323 篇已覆盖 2023 年起的 speculative decoding／sampling 工作（如 Fast Inference from Transformers via Speculative Decoding，ICML 2023）。重索引未改动论文元数据与人工标签，FTS 完整性为 ok。

采集脚本：`backend/scripts/backfill_ai_classics.py`。

## 三、大厂技术报告：独立静态板块（112 份 / 24 家机构）

新增“大厂技术报告”页面（`#/industry`），把 DeepSeek 及国内外主要大厂的模型技术报告、系统卡、模型卡、官方博客与代码发布集中为**一个大的方向**，机构作为子目录：

- 数据是独立的 `frontend/static/industry.json`（schema_version 1，47 KB），由 `backend/scripts/build_industry_data.py` 从 `seeds/industry_orgs.csv` 与 `seeds/industry_reports.csv` 生成；不写入 SQLite、不进入论文快照、不计入 CCF A/B 统计。
- 当前收录 112 份 / 24 家机构：DeepSeek 26、Google DeepMind 11、Meta AI 8、OpenAI 8、阿里巴巴通义实验室 8、智谱 AI 7、月之暗面 5、艾伦人工智能研究所 4、微软研究院 4、NVIDIA 4、上海人工智能实验室 4、Anthropic 3、腾讯混元 3、Apple 2、字节跳动 Seed 2、华为 2、MiniMax 2、Mistral AI 2、阶跃星辰 2、零一万物 1、百川智能 1、百度 1、xAI 1、小米 1。
- 构成：技术报告 72、研究论文 27、系统卡 2、模型卡 3、期刊论文 2、官方博客 1、代码与权重 5；覆盖 2019–2026 年，最新为 2026-10-16 的 DeepInfer。
- 2026 年补录：新增 15 份 2025-11 至 2026-10 的发布，其中 DeepSeek 11 份（V3.2、Math-V2、Engram、OCR 2、V4 / V4-Pro、DeepSpec、Harness、V4.1-Flash、DSec、DeepInfer），另补阿里巴巴 Qwen3.5-Omni、智谱 GLM-5、月之暗面 Kimi K3、腾讯 Hunyuan-A13B 各 1 份。
- 99 份带 arXiv ID，入库前通过 arXiv API 逐篇核对规范化题名；另 13 份为非 arXiv 官方来源（DeepSeek 的 Math-V2 / V4-Pro 权重、V3.2-Exp / Engram / DeepSpec / Harness / DeepInfer 代码库与 DeepSeek-R1 的 Nature 论文，Grok-1 代码库、Llama 4 官方博客、Claude 3 模型卡、Pangu-Weather 的 Nature 论文、GPT-2 论文 PDF），逐条核对官方账号／域名与 HTTPS。
- 生成器强制：机构与报告 ID 唯一、题名唯一、类型合法、年份与发布日期一致、公开 HTTPS 链接、arXiv ID 与 URL 互相一致、摘要 10–180 字、1–6 个标签、拒绝私有地址与未知机构。输出确定性排序，便于 diff 与缓存校验。
- 前端 `frontend/src/lib/industry.js` 再次校验静态数据；页面支持机构、类型、模糊搜索，URL 参数可分享，机构分组按当前结果数排序，DeepSeek 置顶突出。页面与论文库完全解耦，论文库不可用时仍可浏览（只依赖静态 JSON）。
- 重建命令：`python backend/scripts/build_industry_data.py --verify-arxiv`（可加 `--generated-at` 固定时间戳）。

### 测试

- `backend/tests/test_iclr_history.py`：7 项（官方日程解析、2020 对齐、题名校正、数量不完整时拒绝等）。
- `backend/tests/test_industry_data.py`：6 项（种子结构、统计与排序、非法报告、非法机构与生成、时间戳等）。
- `frontend/src/lib/industry.test.js`：3 项（校验、筛选、分组）。
- `frontend/src/pages/Industry.test.jsx`：2 项（机构／类型筛选、搜索）。
- 全量验证：后端 1,155 项 pytest 全部通过，Ruff `F,E9` 通过；前端 39 个测试文件、303 项全部通过；`vite build` 成功且 `dist/industry.json` 与源文件逐字节一致。

## 四、库内状态与边界

| 指标 | 本轮前 | 本轮后 |
|---|---:|---:|
| 数据库论文总数 | 408,832 | **413,803** |
| ICLR 2018 / 2019 / 2020 / 2021 / 2022 | 0 / 0 / 0 / 0 / 0 | 336 / 501 / 687 / 860 / 1,095 |
| 研究方向数 | 18 | **19** |
| Transformer 标签 | — | 11,311 |
| LLM / 推理优化／投机解码标签 | 42,242 / 7,012 / 323 | 43,180 / 10,131 / 324 |

- 2017–2022 年的补采与 2019–2022 年 FL 定向补采一样，只覆盖题名命中目标方向的论文，不代表这些年份的全量收录；页面年度图表仍应把补采年份与完整采集年份区分理解。
- ICLR 只收主会接收论文；workshop、tutorial 与 withdrawn 记录不在范围内。
- 线上快照已更新为 2026-10-28 发布的 405,075 篇公开论文（库内 413,803 条记录）、19 个方向，revision `3ba69d84`；首页 catalog 441,220 字节，仍在 512 KiB 预算内。大厂技术报告页随源码部署上线，独立读取 `industry.json`。
- 大厂技术报告是独立元数据索引，不代表对报告结论的独立评测，也不镜像全文；arXiv 条目链接官方摘要页，博客与代码库链接原始发布。

## 五、涉及文件

- 采集：`backend/app/collectors/iclr.py`、`backend/app/collectors/publisher_toc.py`、`backend/app/collectors/title_corrections.json`
- 补采：`backend/scripts/backfill_iclr_history.py`、`backend/scripts/backfill_ai_classics.py`
- 种子：`seeds/directions.csv`、`seeds/direction_rules.csv`
- 产业目录：`seeds/industry_orgs.csv`、`seeds/industry_reports.csv`、`backend/scripts/build_industry_data.py`、`frontend/static/industry.json`
- 前端：`frontend/src/pages/Industry.jsx`、`frontend/src/lib/industry.js`、`frontend/src/App.jsx`、`frontend/src/index.css`
- 测试：`backend/tests/test_iclr_history.py`、`backend/tests/test_industry_data.py`、`frontend/src/lib/industry.test.js`、`frontend/src/pages/Industry.test.jsx`
