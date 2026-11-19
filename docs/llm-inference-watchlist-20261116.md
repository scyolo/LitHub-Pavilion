# LLM 推理跟踪清单（2026-11-16）

本轮围绕推理系统与加速、推理时计算、智能体服务和相关人工智能技术报告采集。本文保留 11 项值得继续跟踪、但未在本轮取得 CCF A/B 主会或期刊正式出版证据的材料，不计入论文主库新增数量。日期采用 arXiv 首次提交日期，不能用后续修订日期代替首次发表日期。

优先阅读顺序是本轮的研究建议：先看服务架构与 KV 管理，再看投机解码和本地部署，最后看新硬件执行模型。摘要来自作者提交的元数据，未独立复现实验，也不把不同论文的加速倍数作横向比较。

| 优先级 | 首次提交 | 材料与原始来源 | 阅读关注点 |
| --- | --- | --- | --- |
| 高 | 2026-10-07 | [vLLM-Omni Technical Report: A Unified Serving Runtime for Omni-Modality Generation](https://arxiv.org/abs/2610.09307) | 多阶段多模态推理如何统一编排、传输中间结果、流式返回，以及处理持续会话。属于项目技术报告。 |
| 高 | 2026-11-09 | [Evolving Infra: Agent-Adaptive LLM Serving at Scale](https://arxiv.org/abs/2611.12304) | 智能体负载变化下动态调整 prefill/decode 配比，并利用智能体上下文信号管理分布式 KV Cache。 |
| 高 | 2026-11-13 | [Callo: Serving Cache-Miss Requests with Speculative Decoding on Invalidated KV under Prefill-Decode Disaggregation](https://arxiv.org/abs/2611.18459) | 上下文编辑使缓存失效后，用旧 KV 生成草稿，待重新 prefill 后用准确 KV 验证，缩短等待时间。 |
| 高 | 2026-11-10 | [REAL Loss: Optimizing Real Expected Acceptance Length for Speculative Decoding](https://arxiv.org/abs/2611.14399) | 草稿模型的训练目标怎样直接对应实际接受长度；重点检查估计偏差和训练目标与在线验证的对应关系。 |
| 高 | 2026-11-10 | [SinkState: On-the-Fly SVD of Recurrent States for Efficient Hybrid LLM Serving](https://arxiv.org/abs/2611.14246) | 混合注意力模型的循环状态采用自适应低秩表示，结合缓冲更新与 CPU 异步整理降低内存流量。 |
| 中 | 2026-11-10 | [Can KV Cache Be Reused Across Model Updates? A DeepSeek-V4-Flash Case Study](https://arxiv.org/abs/2611.14051) | 区分“任务上仍有用”和“忠实复现更新后模型行为”；跨版本缓存复用可能改变答案与停止行为。 |
| 中 | 2026-11-02 | [Multi-layer Indexer: Overlapping Selection and Attention in DeepSeek Sparse Attention](https://arxiv.org/abs/2611.03768) | 利用相邻层的选择重合，让索引与注意力重叠执行；作者备注称获 NeurIPS 2026 LCFM Workshop 接收，不能据此计入 NeurIPS 主会。 |
| 中 | 2026-11-09 | [BridgeKV: Large-Model Prefill and Small-Model Decoding for LLM Inference via KV Cache Translation](https://arxiv.org/abs/2611.11761) | 大模型 prefill、小模型 decode，以学习到的 KV 转换连接两阶段；区分真实单卡测量与服务模拟结果。 |
| 高 | 2026-11-08 | [Ostinato: Fast CPU-GPU MoE Inference for Local Agents via Resident Experts in Every Forward Pass](https://arxiv.org/abs/2611.11533) | 让常用专家在每次前向执行时驻留 GPU，兼顾智能体短 prefill、长 prefill 与 decode。 |
| 高 | 2026-11-07 | [Hibana: Fast Agentic Inference on Unified-Memory Devices](https://arxiv.org/abs/2611.10469) | 统一内存设备上的模型结构调整、跨轮状态保留与自适应投机解码，适合端侧及本地智能体推理研究。 |
| 中 | 2026-11-13 | [Mutable Inference: Architecting LLM Accelerators for Inference-Time Learning](https://arxiv.org/abs/2611.18523) | 推理时学习的前向、反向与权重更新如何共享硬件，并通过权重版本管理与可恢复计算控制延迟。 |

另有 12 条经机构核验的材料已加入网站的独立技术报告目录，涵盖 MNN-Pocket-0.3B、ForeSpark、Fuse-All MoE、NVLink 单边专家通信、KSA V2、FlashMLA 技术详解及多模态和语音报告。具体身份、日期、官方来源和内容哈希见 [本轮技术报告来源记录](../seeds/industry_report_provenance_20261116.json)。这些目录条目同样不会因所属机构或论文标题而被自动认定为 CCF A/B 正式论文。

检索证据保存在本地 `output/crawl-20261116/`：`recent-inference.json`、`recent-reports.json`、`reasoning-reports.json` 及对应 Atom 响应、来源 URL 和 SHA-256。本轮是主题筛选与来源刷新，不宣称覆盖全部相关预印本。
