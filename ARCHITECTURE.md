# 当前网站架构

LitHub Pavilion 只维护一套 React 网站。公开阅读端使用静态快照，本地采集与管理端负责产生和发布这些快照；二者共用页面、数据契约及筛选语义，不是两套需要同时维护的新旧网站。

## 运行链路

```text
官方出版目录 / DBLP TOC / Crossref / OpenAlex / Semantic Scholar
                  │ HTTPS 元数据
                  ▼
本地 FastAPI 生命周期、单实例任务与定时调度
                  │ 清洗、归并、补全和方向规则
                  ▼
             SQLite + FTS5
                  │ 公开字段投影、内容哈希、原子写入
                  ▼
           公开 snapshot 目录
                  │ 校验、上传专用 site-data 分支、触发 Actions
                  ▼
       GitHub Pages：静态 React 网站
                  │ 同站点 manifest / catalog / chunks
                  ▼
       浏览器 Worker：筛选、排序和英文检索
```

本地 Docker 另外通过 nginx 提供同一个网站，并反向代理本地管理 API。默认仅发布 `127.0.0.1:8080`，无认证 API 不得暴露到公网或不可信局域网。

## 模块边界

| 模块 | 职责 |
|---|---|
| `backend/app/api/` | 本地读写接口、共享筛选与公开序列化、输入和浏览器来源校验 |
| `backend/app/collectors/` | 元数据适配、请求限速、经过公网 DNS 校验和地址绑定的 HTTPS 传输 |
| `backend/app/collectors/publisher_toc.py` / `ojs.py` / `csdl.py` / `crossref.py` | 官方目录逐项枚举、主会范围校验、DOI/ISSN/父书出版证据；不获取论文文件 |
| `backend/app/services/publisher_import.py` / `publisher_metadata.py` | 日常与手工共用的保守身份匹配、正式年份修复、出版证据与冲突记录 |
| `backend/app/migrations.py` | 备份后迁移 publisher_key，保留主键、关系、人工标签并重建校验 FTS |
| `backend/scripts/audit_publications.py` | 只读重放目录缓存、核对逐篇覆盖、版本/年份疑点及基线变化 |
| `backend/app/services/pipeline.py` | 单实例串行采集、完整性记账、历史回填断点及任务退出 |
| `backend/app/services/topic_index.py` | 九方向规则维护和重算，保留人工标签与本地自定义设置 |
| `backend/app/services/snapshot*.py` | 快照导出、公开 schema 验证、首页摘要、数据分支上传与部署确认 |
| `backend/app/services/site_sync.py` | 采集完成后的导出与发布编排、私有回执和失败重试 |
| `frontend/src/data/` | 快照校验、按需加载、Worker 索引和版本切换 |
| `frontend/src/api.js` | 统一数据接口；公开构建固定快照，本地支持 API 故障回退和恢复 |
| `.github/workflows/` | 隔离回归测试、容器冒烟和 GitHub Pages 发布 |

本地 FastAPI 启动入口同时拥有初始化、采集、快照同步和调度生命周期。静态网站不需要后端持续在线，并不意味着可以删除这个采集发布入口。

## 阅读与更新契约

- 公开构建使用 `snapshot` 模式和 HashRouter，只获取同站点公开资源，不访问访客的 localhost，不含发布令牌。
- 首页先验证 manifest 和轻量 catalog；Pages 构建从已校验的同版本论文生成缺失摘要，并用实际前端读取器验证只请求两个文件、零论文分片。进入列表、详情或检索时才下载并校验完整分片，在 Worker 内建立英文词干索引。
- 公开网站是已发布数据，不是实时数据库。导出、重试及上线确认前逐项比较数据库的公开字段、作者、标签和来源；变更触发重新导出。后台运行时默认每 300 秒检查一次，采集结束立即处理；停机期间不承诺自动更新，页面明确显示数据时间。
- 本地 `auto` 模式只在连接失败、超时、服务器故障等情况下回退到真实快照；业务 400/404 不会被旧数据掩盖。API 恢复后清理查询缓存并切回实时模式。
- 新快照完整验证成功后才切换完整数据；失败保留已验证版本。当前及上一版快照资产用于更新期间的在途读取，不属于待删除的旧架构。
- 发布仅写专用 `site-data` 分支，不强推。接受构建请求不等于已经上线，须读取正式网站 manifest 确认 revision。
- 官方、DOI、DBLP 和开放版本链接直接指向原站；本站不下载、代理或重新分发论文文件，也不保证外站免费或永久可用。

## 出版身份、年份与完整性

- `publisher_key` 是真实官方文章 URL 的唯一身份，不伪造 DOI、DBLP 或第三方 ID。无 DOI 的正式论文也可收录；`crawl_logs.year` 保留逐年覆盖证据。旧数据库通过备份和事务迁移增加这些字段。
- 强 DOI/DBLP/OpenAlex/S2/arXiv 身份冲突不按标题强合并。普通标题回退还要求完整作者集合一致；经证实的版本归并保留旧 ID、来源、开放链接及人工标签。一份预印本可对应会议文章和期刊扩展，旧 `arxiv_id` 唯一约束下通过 `oa_url` 保留第二篇正式文章的共享链接。
- 正式目录的会议年或期刊卷年优先，不用 arXiv 首次提交年份或记录创建时间；TPAMI 逐期核对 CSDL 年份和分页。Crossref 期刊按普通出版日期与印刷日期双查询并集补漏，后续补全不得回退已核实的官方题名和卷年。ECML-PKDD 由章节 DOI 关联父书，再核对明确的会议年；没有同年完整日期就不编造日期。
- 官方 TOC 完整解析、逐项入库且没有身份冲突，才具备该来源当时目录的完成证据；官方目录优先于二级索引，跨版本断点使用 `complete-v6`。DBLP、Crossref、OpenAlex、S2 的分页耗尽不等于出版目录全量，仍按 partial 处理。2026 等开放年份必须保留后续新增的可能性。
- ICML 的 PMLR 卷尚未出现在索引时，可回退至官网已结束会议的公开录用目录。验证来源 track、Accept 决定、OpenReview 文章 ID、完整分页和会议日期；去掉口头/海报重复与期刊展示，不把未来录用列表当已结束会议目录。
- ECCV 2026 在常规页面缺失时回退到官方 catalogue；Crossref markup 只按白名单解码合法科学 token，官方题名优先，不用展示差异覆盖论文身份。ECAI 2026 标记为 IJCAI 联合届次，不复制独立库存；ICRA 2026 标记 `official_program_only`，程序条目不当作正式 proceedings 全量。
- 已证实的 ECCV 目录标题勘误要求官方 URL、DOI、年份、完整作者和旧标题全部匹配。CCF 归属还检查非主会分轨；版本归并不得把未确认记录自动升级为主会论文。
- 在线与静态检索均先保障词项 AND 和规范化精确标题召回，再做标题优先排序。普通关键词限制 300 字符、24 词；已收录完整标题支持 2000 字符并可绕过关键词分词损失。仅更新后端不能修复公开站：必须重新导出、验证和构建静态快照。
- 快照导出可通过 `--check-database` 校验公开投影；全标题可检索检查与真实库样本检索由维护脚本执行；后端只读检查使用 SQLite `mode=ro` 与 `PRAGMA query_only=ON`，不启动 API 生命周期、不采集、不联网。

覆盖范围和未取得完整官方目录的来源见 README 的“数据采集与覆盖边界”。审计不会因为记录增多、上游 HTTP 200 或数据库结构完整就声称全量；未标签不等于未收录，碰巧同名不等于重复论文。

## 唯一支持的维护方式

定时调度保持元数据每周一 04:00、链接维护每周二 06:30、引用维护每月 1 日 06:00，时区为 `Asia/Shanghai`。启动采集与定时开关分别控制，测试必须关闭真实采集和发布副作用。

规则维护统一使用 `python -m scripts.reindex_topics`。该命令先校验备份，再应用当前九方向规则，并验证论文主表、人工标签及全文索引。它会移除不再匹配的自动规则标签，不是旧六方向增补脚本的“只增加标签”操作；不会自动在用户原始库上运行。

运行和配置命令见 [README](README.md)，贡献检查见 [CONTRIBUTING](CONTRIBUTING.md)，公网与数据边界见 [SECURITY](SECURITY.md)。

## 退役内容与数据兼容

已移除 PDF 下载器、下载白名单模型与种子、PDF 定时任务、PDF 文件/Range 服务、下载模式开关，以及六方向增补脚本和早期本地归档架构文档。`PDF_DOWNLOAD_ENABLED`、`PAPERS_ROOT`、`PDF_DAILY_LIMIT`、`ARXIV_INTERVAL_S` 即使仍存在于旧 `.env` 中，也不会恢复这些功能。旧 `/api/papers/{id}/pdf` 路由不存在；请求 PDF 采集 scope 会按普通无效参数拒绝。

为避免破坏用户已有数据和已发布的 schema-v1 快照，保留以下兼容信息，而非保留旧功能：

- 论文的 `pdf_status`、`pdf_source` 以及数据库内的历史 `pdf_path`；`closed` 是旧数据状态，不是经过核实的付费墙结论，开放性由安全原文链接展示。
- 历史采集日志中的 PDF 计数和任务类型；系统不再生成 PDF 下载任务。
- 现有数据库中的 `pdf_whitelist` 表若已存在，不读取、不更新、不删除；新库不创建该表。
- 原始数据库、备注、人工标签、采集断点、归档文件和备份。删除论文元数据或维护链接都不删除归档文件。

数据库、密钥、发布回执、PDF 和生成快照不能进入源码提交。历史设计可从 Git 历史查阅。按需生成的验收/测试报告不随源码保留；保留自动化测试源代码和生产维护脚本。
