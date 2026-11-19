# LLM 推理研究跟踪清单：第二轮（2026-11-19）

本轮从 11 月 14–18 日的推理相关 arXiv 条目中筛选 10 项研究，再补充一份 11 月 18 日发布的扩散语言模型技术报告。共 11 项，覆盖投机解码、KV Cache、分离式服务、端侧 MoE、智能体公平性和基础设施优化。

下表日期保留首次提交日期，优先级是阅读建议。内容依据作者摘要与官方元数据，实验结论尚未独立复现；不同硬件、模型和负载下的加速倍数没有直接可比性。尚未取得 CCF A/B 主会或期刊出版证据的条目留在此清单，作者备注中的接收或 Workshop 信息单独注明。

| 优先级 | 首次提交 | 原始资料 | 阅读关注点 |
| --- | --- | --- | --- |
| 高 | 2026-11-18 | [LoopCache: Accelerating Long-Context Self-Speculative Decoding for Looped Transformers](https://arxiv.org/abs/2611.24301) | 循环 Transformer 的多套 KV Cache 会放大长上下文访存；关注循环式缓存轮换与动态草稿更新如何配合无损验证。 |
| 高 | 2026-11-17 | [SpecSearch: Towards Hardware-Aware Efficient Speculative Decoding](https://arxiv.org/abs/2611.22296) | 结合 GPU、显存和负载联合选择解码策略、草稿长度及精度；区分完整硬件校准与面向未校准设备的预测。 |
| 高 | 2026-11-17 | [XM-Sparse: High-Throughput Sparse-Attention LLM Serving over Scale-up Memory Pools](https://arxiv.org/abs/2611.22280) | 区分动态 KV 访问与可预测索引访问的 I/O 路径，将稀疏注意力和扩展内存池联合设计；实验采用模拟的 scale-up 内存池。 |
| 高 | 2026-11-17 | [Towards Fair Resource Sharing in Agentic LLM Serving](https://arxiv.org/abs/2611.23558) | Duru 以智能体相对独占执行的减速比衡量公平性，联动路由、准入、运行时调度与扩缩容，缓解多轮任务饥饿。 |
| 高 | 2026-11-15 | [Making Preemption Productive in Long-Output LLM Serving](https://arxiv.org/abs/2611.20106) | Stint 以 CPU KV 快照、按等待年龄重新准入及短期解码保护降低缓存抖动；关注长推理输出中的完成时间与尾部延迟。作者注明 under review。 |
| 高 | 2026-11-14 | [LoopFill: Pipelined Multi-Token Speculative Decoding for Looped Transformers](https://arxiv.org/abs/2611.19649) | 将多 token 后缀草稿与浅层循环预测合成一棵草稿树，使多个未来 token 同时进入流水线，并用全深度验证保持输出分布。 |
| 中 | 2026-11-16 | [Memory-Efficient Speculative Decoding with Quantized Draft KV Cache](https://arxiv.org/abs/2611.20565) | 压缩草稿缓存、保留目标缓存和验证器精度；关注 K/V 量化布局与接受率的共同影响。作者备注为 NeurIPS 2026 的 AXIOM Workshop 接收。 |
| 中 | 2026-11-15 | [CECAR: Cache & Expert Co-Aware Routing Accelerates On-Device Inference of MoE LLMs](https://arxiv.org/abs/2611.20119) | 预测专家的再使用距离，将缓存策略与专家路由共同优化，研究显存受限且专家从 SSD 取回的端侧服务。作者称获 NeurIPS 2026 接收，本轮未取得主会出版目录证据。 |
| 中 | 2026-11-18 | [RSIBench-Infra: Can Agents Optimize Their Own Training and Inference Infrastructure at Production Scale?](https://arxiv.org/abs/2611.24395) | 从独立内核优化转向训练与推理的完整执行栈；关注可复现的提交协议、质量约束及端到端独立验收。 |
| 中 | 2026-11-16 | [A Matter of Stages: Energy-Latency Trade-offs in Multimodal LLM Serving](https://arxiv.org/abs/2611.21165) | 视觉编码、prefill、decode 分离和 GPU 频率共同改变能耗、通信与排队；关注满足延迟约束时的整条请求能耗。 |
| 中 | 2026-11-18 | [Clover-35B-A3B-Preview Technical Report](https://arxiv.org/abs/2611.24636) | DiffuSpace 的 35B 总参数、3B 激活参数扩散语言模型，将历史循环记忆与块内双向注意力结合；关注块大小、推理模式及智能体负载评估。 |

网站的独立技术报告目录另外新增 6 项：Cap-and-Track、NarrowSpec、MiSTiQ、Nemotron 3.5 Transcribe 服务内核、Sage S2.1 Flash 和 LongCat-Video-Avatar 1.6。各条目的机构、首次日期、后续修订和来源哈希见 [第二轮技术报告证据](../seeds/industry_report_provenance_20261119.json)。

本地检索与原始来源记录位于 `output/crawl-20261119/industry/`。推理条目来自经过核验的 Atom 响应，Clover 报告的题名、日期及机构由官方摘要页与 HTML 作者块交叉核验。检索覆盖的是本轮查询和筛选范围。
