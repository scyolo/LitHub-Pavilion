# LitHub Pavilion

> 知汇于此，文藏此殿

个人自用的 CCF A/B 论文研究工作台。FastAPI + SQLite FTS5 + React/Vite，提供年度/方向图表、会议期刊浏览、组合筛选、英文全文检索和官方/OA 链接。

**采用“本地 Docker 采集 → 导出公开静态快照 → GitHub Pages 浏览”的模式，不下载 PDF。只有静态网站可以公开；无认证的后端与管理接口仍仅限本机。**

详见 [当前架构](ARCHITECTURE.md)：仅保留这一套网站及采集发布链路，不提供 PDF 下载、归档服务或恢复下载模式的开关。

## 功能

- 研究总览：年度 A/B 图表、主题分布、开放链接覆盖、最近收录；点击图表可进入论文列表。
- 论文探索：A/B 会议和期刊快捷切换，方向多选、年份、来源、开放链接筛选，稳定排序与分页。
- 详情页：摘要、作者、元数据、发表归属提示及安全原文链接；返回保留筛选条件。
- 深浅主题、移动端导航与筛选、键盘操作、减少动态效果支持。
- Docker 启动后自动按配置采集，历史回填断点续传，完成后原子导出快照；部分失败如实记账。
- GitHub Pages 无需本地后端：图表、筛选、英文全文搜索、排序、分页与论文原文链接均在浏览器内工作。
- 本地前端自动检测 API，后端不可用时回退到已导出的快照，恢复后自动切回实时数据；不会用旧快照掩盖真实 400/404 错误。
- 非破坏性维护：链接回填不删除已有文件，种子导入不覆盖已有配置，数据库备份不会自动删除旧备份。

当前 `seeds/venues.csv` 仅配置 **CCF 2026 第七版中的 338 个 A/B 来源**：58 个 A 类会议、132 个 B 类会议、37 个 A 类期刊、111 个 B 类期刊，覆盖 10 大学科领域；TOMM、DKE 的跨领域重复条目按同一来源去重。**不收集 C 类或目录外来源。** 核验依据和逐来源页码保存在 `seeds/ccf_catalog_provenance.json`，FSE 等同名会议不混为同一来源。

提供 16 个研究方向，新增人机交互与可视化、生成式 AI 与扩散模型、系统软件与分布式、图学习与知识图谱，并将原 `multimodal` 标签扩展为“多模态与视觉语言”，保留原筛选 URL 和人工标签。**目录范围不是论文完整率**：新增来源需要后续分批回填；页面单独显示配置数、有论文来源数和正式收录论文数。仓库不附带个人论文数据库或论文 PDF。

### 截稿日历与快速阅读

- `#/deadlines` 提供月历 / 列表、A/B 与 CCF 领域筛选、多轮投稿、摘要截止提醒、北京时间 / UTC 切换和当前结果的 `.ics` 导出。期刊不伪造年度截稿日；TBD 或未知时区不猜日期。
- 截稿数据来自 CCFDDL 社区，按本站 CCF A/B 名单精确匹配会议，不通过模糊简称/共享 DBLP 路径串配（例如 ACM SoCC 与 IEEE Cloud）。生成时间与原始时区可见，超过 7 天显示过期提醒，投稿前仍须确认官网。
- 日历是独立的 `frontend/static/deadlines.json`，不等待论文库下载。Pages 构建尝试同步，失败时保留带日期的上次数据；手工同步：`python -m pip install -r backend/requirements-maintenance.txt`，然后 `python backend/scripts/sync_deadlines.py`。
- 首页仍只读取 manifest + catalog；overview v2 在各范围中仅保存来源计数，名称等元数据只保存一次。来源卡片的主题概况预计算，不拉取论文分片。兼容旧版 v1 快照。
- 重访时先恢复浏览器中经过 SHA-256 校验的公开概览，再后台检查更新；缓存损坏或不可用会回退到正常加载。不会缓存管理 API 或令牌，不把旧快照伪装成实时数据。论文正文/搜索仍按需加载。
- 更新本地来源和方向后，需要重新导出并发布快照，线上网站才会展示新的来源、方向及主题统计。

## 一键运行（Docker Compose）

需要 Docker Desktop 或 Docker Engine + Compose v2。

```bash
# 项目根目录；首次可复制配置模板（不要覆盖已有 .env）
cp .env.example .env
# 可选填写 CONTACT_EMAIL 和 S2_API_KEY
docker compose up -d --build --wait
```

访问 **http://127.0.0.1:8080/**。首次空库会自动创建 SQLite/FTS5 和种子配置，并在后台收集 `STARTUP_YEAR_FROM` 至 `STARTUP_YEAR_TO`（空值代表当前 UTC 年）的已启用 A/B 来源。默认从 2023 年开始，历史完整单元跳过，部分失败单元下次继续；页面不会用演示数据伪装收录结果。首次采集完成前，空库显示 0 篇；没有任何已有快照时，也不会凭空显示论文。

- 仅 web 的环回端口发布到宿主机，API 不公开端口。
- API 用户 UID 1001、nginx 用户 UID 101；容器只读根文件系统、移除 capabilities。
- 数据保存在 Compose 项目下的 `lithub-data` **命名卷**，包含 WAL 与备份。`docker compose down` 不删除卷。
- **不要执行 `docker compose down -v`**，该命令会删除持久化数据。
- 旧版本的根目录 `./data` 绑定卷不会自动导入。已有本地数据库也不会被复制到容器；迁移前先备份并明确来源，禁止用空库覆盖旧库。

## 公开准入与检索边界

- 公开列表、详情、搜索、统计和静态快照共用准入规则：来源在已配置 A/B 范围内、论文级别与来源一致、发表归属已确认，并保有正式 DOI、出版目录身份或对应来源的 DBLP 记录。未确认候选、仅有预印本身份以及 Preface 等非研究条目留在本地，不进入公开阅读数据；不删除原始记录。
- “官方页面”优先正式出版 DOI，其次出版目录/正式页面，再回退到 DBLP。arXiv、Zenodo 等仓储 DOI 不作为正式出版链接；开放版本单独展示。链接格式校验不是外站在线可用性、全文权限或论文归属的逐篇人工认证。
- 搜索提供 `auto`（默认先关键词、零结果再模糊）、`exact`（规范化完整标题）、`keywords`（词项 AND）、`fuzzy`（有限拼写纠错与末词前缀补全）四种模式，可从论文页“检索方式”切换。精确标题忽略大小写、标点和可规范化的变音符号，不是字节级比较。
- 模糊查询同时考虑原词与词干的一次插入/删除/替换/相邻转置，每词最多保留 4 个候选（含原词）；不扩展两字母缩写，不保证任意拼写错误都可召回。旧静态索引必须重新导出到 reader v3 才有词表纠错能力。
- 一篇论文可关联多个方向，在每个已关联方向及它们的 OR 筛选中均可查到；规则标签仍需语义复核。无结果时可保留查询词、清除范围筛选，在全部已核验论文中重查。

## GitHub Pages：后端关闭后仍可浏览

### 首次发布（只配置一次）

1. 将本项目源码和 `.github/workflows/pages.yml` 放到目标仓库的默认分支（默认 `main`）。GitHub Free 只支持公开仓库的 Pages；私有仓库需要支持 Pages 的套餐，不能仅靠管理员权限绕过。在 GitHub 仓库 **Settings → Pages → Source** 选择 **GitHub Actions**，再在 **Settings → Secrets and variables → Actions → Variables** 设置 `PAGES_DEPLOY_ENABLED=true`。该开关在首次数据分支就绪前可保持关闭，避免未配置网站被误报成部署失败。本地代码尚未推送时，不能触发尚不存在的 workflow。
2. 在根目录 `.env` 填写 `PAGES_REPOSITORY=你的账号/仓库名`。创建仅用于该仓库的 fine-grained token，授予 **Contents: Read and write**（写专用数据分支并发送 repository dispatch），Metadata 的读取权限随令牌提供。令牌不需要进入前端或 Pages Secrets。
3. 将令牌作为单行文本保存到 `.secrets/github_token`；目录和文件已被 Git 忽略。不要将令牌粘贴到代码、聊天、命令历史或截图。Docker 通过只读 secret 挂载读取它；`gh auth login` 本身不会自动给容器提供令牌。
4. 使用发布覆盖配置启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.pages.yml up -d --build --wait
```

此后启动 Docker 就会执行配置范围采集，并在任务结束后导出、上传、触发 Pages 构建。若希望日常直接使用 `docker compose up -d --build`，可在本机 `.env` 设 `PAGES_PUBLISH_ENABLED=true`，并用被 Git 忽略的 `docker-compose.override.yml` 声明同样的 token secret 挂载。已有论文在后台采集期间仍可浏览；本地管理页“静态快照与网站发布”分别显示导出、上传、待部署确认和已上线状态。

默认站点为 `https://账号.github.io/仓库名/`；账号站点仓库 `账号.github.io` 使用根路径。自定义域名需设置 `PAGES_SITE_URL=https://你的域名/`（包含实际站点基路径，禁止内网地址、查询参数及片段）。

### 快照与实时交互的边界

- 网站只访问同站点 `snapshot/manifest.json` 和已校验的内容哈希文件，不向访客的 localhost 发请求，不携带发布令牌；HashRouter 保证详情链接在 Pages 子目录刷新不 404。
- 首页只下载已校验的 manifest 和轻量 catalog（包含同版本论文生成的总量、年份、方向、来源×年份分布及最新论文），不等待完整摘要库。Pages 构建会从同一份已公开论文分片为旧快照生成缺失的首页摘要，不读取私有数据库、不更改论文或数据时间；构建必须通过“两次快照请求、零论文分片、总量不超过 512 KiB”的检查。reader v6（内层 v5）将浏览卡片、详情、排序元数据和 gzip 倒排索引分开：先精确筛选、排序和分页，再加载当前页需要的 256 条卡片分片；词项桶包含标题位置，保留全局 BM25、短语、模糊检索的结果和分数。打开详情仍按论文 ID 加载单分片，旧快照仍兼容；首页矩阵先预览 20 个来源，可展开全部，不改变覆盖统计。单次读请求超过 12 秒会停止阻塞的 Worker 并明确提示重新加载，不自动再等一轮。首次读取仍有网络及解压成本，不能承诺任意网络都成功秒开。
- 首页摘要与完整论文数据是两个明确的验证层：导出和发布时会用全部论文重算并验证首页摘要；浏览器先验证摘要文件的哈希、公开字段与计数，请求其他资产时逐一核对内容哈希与分片记录数。主动完整验证会核对全部分片及统计；失败保留已验证的旧版，不混合版本。每 60 秒、窗口聚焦及“检查更新”时检查 manifest。
- 普通论文列表和首页最新论文默认按上游发布日期从新到旧排序；只有年份或日期无效时按归属年，同年排在具体日期之后，最终以论文 ID 稳定排序。不用入库时间代替发布日期，不伪造月份和日期。英文搜索默认按相关性，显式选择的排序在修改/清空关键词后保留。上一页、下一页及每页条数变化会立即回到页面顶部。
- 原文链接是直接指向 DOI、出版方、DBLP 或 arXiv 的 HTTP(S) 链接，与后端是否运行无关。本站不能保证外站永久在线、无需付费或免登录。
- 同一 revision 不重复提交 Git 数据。后台运行时默认每 5 分钟核对数据库与快照的全部公开字段、论文 ID、作者、方向关系和来源；发现变化会重新导出，采集中等待本轮结束。发布前再核对，不仅比较总数。只有数据库核对通过且线上 manifest 与该快照一致才显示已上线；上传不等于部署完成，30 分钟仍未上线则重新派发。后端关闭、令牌不可用或网络失败时，公开站保留上次版本并显示数据时间，不承诺与停机后的数据库实时一致。
- 发布只更新专用 `site-data` 分支，不 force push；已存在的同名分支没有本项目所有权标记时会拒绝覆盖。Pages 保留当前及上一版经公开字段校验的资产，避免更新途中旧页面请求的文件失效。
- 公开内容仅含论文元数据、摘要、作者、链接、方向和已结束任务摘要；不含备注、数据库、PDF、错误日志正文、SMTP 凭据或令牌。发布前自行确认上游元数据的再分发条件。

### 仅导出、验证或本地预览

从项目根目录使用已有本地数据库导出（不启动 API、不采集外网）：

```bash
# Git Bash / Linux / macOS
PYTHONPATH=backend python -m scripts.export_snapshot --output frontend/static/snapshot
PYTHONPATH=backend python -m scripts.export_snapshot --output frontend/static/snapshot --validate-only
# 另核对当前数据库，不上传；发现数据不一致则失败退出
PYTHONPATH=backend python -m scripts.export_snapshot --output frontend/static/snapshot --validate-only --check-database
```

PowerShell 对应先执行 `$env:PYTHONPATH='backend'`，再运行 `python -m scripts.export_snapshot ...`。Docker 中的数据库与本地数据库相互独立，导出容器数据用：

```bash
docker compose exec api python -m scripts.export_snapshot
# 只有明确要公开发布时才追加 --publish；先配置上述 token/仓库。
```

生成的 `frontend/static/snapshot/` 不进源码 Git。首次下载源码尚无快照时必须先导出或采集，页面会提示未发布数据，不能离线凭空显示论文。有快照后，直接在 `frontend/` 运行 `npm run dev` 即可不启动后端浏览。若需要同步 Docker 最新快照到独立开发前端，在已有目标备份后使用 `docker compose cp api:/app/data/snapshot/. frontend/static/snapshot/`；不要把数据库复制到公开目录。

纯静态本地预览（`frontend/`）：

```bash
npm run build
npm run preview -- --host 127.0.0.1
```

若测试 Pages 子路径，构建和预览都要传同一 `VITE_BASE_PATH=/仓库名/`。Windows Git Bash 会自动转换部分以 `/` 开头的环境值，可使用 PowerShell 的 `$env:VITE_BASE_PATH='/仓库名/'` 避免它被改成磁盘路径。默认 `npm run build` 是静态模式；Docker 构建显式使用自动 API/快照模式。

## 本地开发

需要 Python 3.11+（Docker 使用 3.12）、Node.js 22.12+。

```bash
# backend/，建议使用虚拟环境
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn app.api.main:app --workers 1 --host 127.0.0.1 --port 8000

# 另开终端，从 frontend/ 运行
npm ci
npm run dev
```

访问 **http://127.0.0.1:5180/**。Vite 固定 IPv4 和端口，`/api` 代理到 8000。默认自动模式：后端断开时读取 `frontend/static/snapshot/`，每 15 秒及窗口聚焦时检查后端，恢复后清理旧查询缓存并切回 API；不会把静态模式当作可操作的采集管理。`VITE_DATA_MODE=api` 可显式禁用回退，`snapshot` 则完全不请求 API。只有一个后端 worker：调度与任务状态按单实例设计。

本地 Python 启动同样默认启用自动采集/导出；仅导入工具不会启动生命周期任务，测试夹具会禁用这些副作用。不希望启动时采集可设置 `STARTUP_CRAWL_ENABLED=false`。相对 `SNAPSHOT_DIR` 固定从项目根目录解析。

默认数据库固定为 `backend/data/papers.db`，不再随终端工作目录变化。可通过 `DATABASE_URL` 指定其他 SQLite 文件；当前发布版不支持直接替换成 PostgreSQL，FTS 适配仍需实现。

## 配置与调度

环境变量通过根目录/后端目录的 `.env` 读取；真实密钥不要写入源码。

| 配置 | 默认值 | 用途 |
|---|---|---|
| `S2_API_KEY` | 空 | Semantic Scholar API key，可选 |
| `CONTACT_EMAIL` | 空 | 上游请求的联系信息，建议填写真实邮箱 |
| `OUTBOUND_DNS_MODE` | `system` | Fake-IP 网络可设 `https`，仍只允许公网目标 |
| `SCHEDULER_ENABLED` | `true` | 是否注册自动任务 |
| `STARTUP_CRAWL_ENABLED` | `true` | 启动时后台采集；不受定时开关影响 |
| `STARTUP_YEAR_FROM` / `STARTUP_YEAR_TO` | `2023` / 当前年 | 启动范围；持续增量取配置范围最后两年 |
| `SNAPSHOT_ENABLED` | `true` | 每轮结束导出完整只读数据 |
| `SNAPSHOT_DIR` | 本地 `frontend/static/snapshot` | Docker 固定使用 `/app/data/snapshot` |
| `SNAPSHOT_STATE_FILE` | `backend/data/snapshot-state.json` | 私有发布回执，不得放进公开静态目录 |
| `PAGES_PUBLISH_ENABLED` | `false` | 发布覆盖配置自动设为 `true` |
| `PAGES_REPOSITORY` | 模板 `scyolo/LitHub-Pavilion` | 必须改为有权限的目标仓库 |
| `PAGES_RETRY_SECONDS` | `300` | 数据库/快照一致性检查、变更补导出、上传重试及线上版本检查周期 |
| `PAGES_DEPLOY_RETRY_SECONDS` | `1800` | dispatch 后未确认上线的重派发等待 |
| `PAGES_SITE_URL` | 自动推导 | 自定义域名的规范 HTTPS 站点地址 |
| `INITIALIZE_ON_STARTUP` | `true` | 自动初始化空库；不覆盖已有种子记录 |
| `LINKS_MAX_BATCHES` | `20` | 每次链接维护最多 20 批，每批 50 条 |
| `DATABASE_URL` | 本地 `backend/data/papers.db` | SQLite 位置 |
| `WEB_PORT` | `8080` | Docker 前端环回端口 |

时区：`Asia/Shanghai`，CronTrigger 显式指定。

| 任务 | 时间 |
|---|---|
| 论文元数据增量 | 每周一 04:00 |
| 开放链接维护 | 每周二 06:30 |
| 既有引用字段维护 | 每月 1 日 06:00 |

在线 API 模式每 30 秒刷新总览、列表和详情；快照模式只定期检查 manifest，不向外部论文源发送请求。没有每天抓取论文或批量下载 PDF 的任务。手动重复提交返回 409；定时任务遇到忙碌会等待，单实例运行避免多写。调度器不持久保存停机期间的 cron，重启补齐依赖启动采集开关。

“配置范围”以数据库中启用的 A/B 来源和年份设置为准，九个方向用于打标签而非将无标签论文排除。修改 CSV 不会覆盖已有来源配置，可运行 `python -m scripts.seed` 增补缺失项。禁用来源/缩小采集年份不会删除已有论文，静态导出仍包含已有的公开 A/B 记录。部分采集失败时允许导出已经完整提交的可用数据，并明确保留失败/不完整状态；空库和无效快照不会替换旧网站。

## 数据准确性边界

1. CCF 范围由配置清单限制，不代表已对 2026 目录逐行、逐篇重新核验。正式级别、主会/分轨和录用信息以官方出版页为准。
2. 优先采集官方目录，缺失时以 DBLP TOC、Crossref、OpenAlex/Semantic Scholar 继续补采。官方目录逐条核对论文身份、标题与年份；Crossref 即使枚举完成，也只证明已登记 DOI 的覆盖，不代表整届会议/整年期刊全量。二级索引、主题检索、零结果及失败不写完整回填断点，不绕过上游质询或权限限制。
3. 直接 DBLP TOC、已校验官方目录、匹配 DOI 和正式容器的出版元数据可以确认关联；仅手工指定 venue、S2 key 前缀或 arXiv 提交不够。正式年份优先于预印本年份，ECML-PKDD 章节还核对父书会议副标题，不以延迟印刷年替代会议年。旧的未核实记录保留并显式列入审计。arXiv 已正式发表版本会保留开放链接；同一 arXiv 对应不同正式论文时不强行合并。
4. 方向使用关键词规则，可多标签重叠；引用数来自上游而非实时评估。摘要缺失/纯标点占位不伪装为有效摘要。
5. 在线英文检索基于 FTS5 `porter unicode61`；静态 reader v3 在导出时为标题与完整摘要生成词干倒排索引，浏览器 Worker 按需获取分片，不再首次下载整库建索引。词项 AND 召回不要求相邻；相关性依次优先规范化精确标题、标题短语、全部词在标题、摘要命中，标题权重高于摘要。精确标题另有独立召回，避免数学符号/变音符号被分词漏掉。关键词检索保持最多 300 字符、24 个英文词条的输入保护；已收录的完整标题支持最多 2000 字符（包括标题中的非英文字符），超长输入只走精确标题索引。普通中文关键词检索明确报错。外链做安全校验，不保证每个出版站均可访问。
6. 外部元数据 HTTP 客户端只连接 DNS 解析并验证后的公网 IP，保留原主机 TLS SNI；禁止自动重定向和环境代理。Fake-IP/TUN 网络把域名映射到 `198.18.*` 等非公网地址时，设置 `OUTBOUND_DNS_MODE=https`，使用固定公网 HTTPS DNS 解析器取得真实 IPv4 地址；仍检查每条结果、固定连接目标并验证证书，不允许私网地址，不修改系统代理。默认 `system` 保持系统 DNS 行为。

## 数据采集与覆盖边界

默认范围是配置中启用的 A/B 来源（当前清单 40 个）及 2023 年起的年份，不是 CCF 全部领域目录。九个方向用于检索和多标签筛选，不是穷尽分类；没有命中方向规则的论文仍保留并可查询。**全部已收录论文可检索，不等于已证明所有上游论文均已收齐。**

2026-09-30 本地库审计时有 133,417 条出版记录；11 个已配置来源仍为零：SIGIR、SIGKDD、WWW、ACM MM、WSDM、CIKM、TOIS、TKDE、TMM、TKDD、TOMM。这些空缺是待核对/采集项，不应在页面上解读为不存在论文。COLT 2023–2025 官方 PMLR 目录的 522 条已有记录已补充逐篇 PDF 链接，其中包含每年各一篇 Preface，不能将目录条目数全部解释为研究论文数。本地数据也不证明所有来源/年份均有完整官方目录。

- 官方目录适配包括 AAAI/ICAPS/JAIR 的 OJS、IJCAI、KR、ICLR、ICML/UAI/COLT、NeurIPS、CVF、JMLR、ACL Anthology、ECCV、AAMAS，以及 TPAMI 的 IEEE CSDL 逐期目录。目录分页、文章身份、作者和正式年份逐项验证，解析异常不能写完整断点。
- TPAMI 按正式期次而非 early-access/DOI 年份归档。Crossref 期刊补采同时枚举普通出版日期与印刷日期，以 DOI 去重并集，避免“先在线、后编卷”的论文漏收；TASLP 包括已配置的续刊 ISSN。
- ICML 优先用 PMLR；缺少卷索引时核验官网已结束会议的目录，包含正式 Position Paper Track，排除工作坊及期刊展示。ECCV 可使用官方 catalogue。未来录用列表和 ICRA 程序页不能冒充正式 proceedings。
- ACL/EMNLP 的 Findings、非主会分轨和 AAAI 的 IAAI/EAAI、演示、学生摘要、期刊展示不冒充 CCF 主会确认；原记录保留可查询，并展示归属未确认提示。ECAI 2026 按 IJCAI 联合届次处理，不复制独立 B 类记录。
- 正式官方题名、卷年优先于 Crossref 的展示或早期日期。ECCV 已核实目录勘误保存在 `title_corrections.json`，同时匹配官方 URL、DOI、年份、完整作者和旧标题，禁止按模糊标题批量覆盖。共享 arXiv 的不同正式出版物保留独立身份和开放链接。COLT 的 OA 链接补齐可用 `python -m scripts.collect_official_inventories --venues COLT --year-from 2023 --year-to 2025 --oa-links-only`，先备份并验证已有出版身份，只填空字段，不新增论文或替换既有链接；不请求 PDF 文件。
- ECAI、ECML-PKDD、ICRA、AI、IJCV、TASLP、TNNLS、PR 的 DOI 元数据补采不等于独立官方目录已经完整匹配。尚未公开的当年目录、受限上游以及身份冲突保留为未完成状态，后续重试，不编造 DOI 或年份，不绕过访问验证。

维护脚本 `collect_official_inventories.py`、`repair_publications.py` 与日常采集共用身份和出版规则；`audit_publications.py` 可只读核对采集缓存与数据库。按需生成的审计/测试输出属于本地产物，不进入源码仓库；删除它们不会删除论文、正式来源字段或数据库备份。

链接只校验安全 HTTP(S) 格式及已实现目录的来源、年份、单篇身份；没有逐一在线探测，不能保证外站当前可用或开放获取。

## 维护

从 `backend/` 执行：

```bash
python -m scripts.backup        # 新建快照并 quick_check，不删除旧备份
python -m scripts.rebuild_fts   # 原子重建 FTS 索引并校验主表一致性
python -m scripts.seed          # 仅增加缺失种子，不覆盖现有 source ID / active 等配置
python -m scripts.reindex_topics # 先校验备份，再增补九方向规则并重算；保留手工标签及自定义规则设置
```

规则升级后运行 `python -m scripts.reindex_topics` 才会应用到既有数据库；仅改 CSV 不会自动覆盖已有规则。该命令只重算已启用方向，保留人工标签、方向名称/阈值/开关与自定义规则，校验前后论文主表内容完全一致，并验证 FTS5。旧版默认 `multimodal` 泛词规则仅在未被本地定制且启用时细化，避免把多峰优化误判为多模态信息。月度补全新增摘要后也会重打方向标签。

维护后需重新运行 `python -m scripts.export_snapshot` 生成带新关联和轻量首页的快照；代码与快照都更新并完成 Pages 部署后，线上网站才会变化。Docker 数据卷与本地库相互独立：容器内对应执行 `python -m scripts.reindex_topics` 和 `python -m scripts.export_snapshot`，不要拿本地数据库覆盖已有卷。方向统计仅说明规则覆盖，不等于补齐未采集论文，也不保证语义标签完全准确。

`DELETE /api/papers/{id}` 仅删除元数据与关联行，不删除文件。人工方向 PATCH 为当前方向集合替换，自动采集仍可重新增加规则命中的标签；人工保留的标签不会被覆盖。

## 验证与 CI

```bash
# backend/
python -m ruff check app scripts tests --select F,E9
python -m pytest -o addopts= --disable-warnings

# frontend/
npm test
npm run build
# 导出真实快照后再运行（不依赖示例数据，不触发网络发布）：
node scripts/check-snapshot-home.js
node scripts/check-snapshot-search.js ../artifacts/snapshot-search.json
# 真实数据库只读检索检查（PowerShell，从项目根目录执行；不启动 API、不采集、不联网）：
# $env:PYTHONPATH='backend'; backend/.venv/Scripts/python.exe backend/scripts/check_database_search.py --samples artifacts/snapshot-search.json --output artifacts/database-search.json
npm audit --omit=dev
```

`.github/workflows/verify.yml` 定义后端测试、前端测试/构建与 Docker 空库冒烟；推送后才由 GitHub 实际执行，本地通过不代表远端 CI 已运行。

隔离容器验证（不动现有库）：

```bash
WEB_PORT=8180 SCHEDULER_ENABLED=false STARTUP_CRAWL_ENABLED=false SNAPSHOT_ENABLED=false PAGES_PUBLISH_ENABLED=false docker compose -f docker-compose.yml -p lithub-release-check up -d --build --wait
python scripts/smoke_release.py
docker compose -f docker-compose.yml -p lithub-release-check down
```

Windows PowerShell 可先设置 `$env:WEB_PORT='8180'; $env:SCHEDULER_ENABLED='false'; $env:STARTUP_CRAWL_ENABLED='false'; $env:SNAPSHOT_ENABLED='false'; $env:PAGES_PUBLISH_ENABLED='false'` 再执行 Compose 命令。显式 `-f docker-compose.yml` 排除本机发布覆盖配置，不挂载发布令牌；测试夹具也禁用所有真实采集/导出/发布副作用。只关闭调度器不会关闭启动采集。

## 项目结构

```text
backend/app/api/           本地 API、共享筛选/序列化和写请求保护
backend/app/collectors/    元数据适配与公网地址绑定传输
backend/app/services/      采集、索引、链接维护、快照导出与发布
backend/app/bootstrap.py   非破坏数据库初始化
backend/scripts/           备份、九方向索引维护、种子和快照导出
backend/tests/             隔离数据库/模拟网络回归测试
frontend/src/              唯一 React 网站、快照 Worker 与交互测试
frontend/static/           公开资源目录；生成快照不进入源码 Git
seeds/                    来源、方向和方向规则
scripts/prepare_pages.py  校验并整理当前/上一版公开快照
scripts/smoke_release.py  固定本机测试端口的 Docker 冒烟
.github/workflows/         自动测试与 GitHub Pages 发布
```

架构说明统一见 [ARCHITECTURE.md](ARCHITECTURE.md)。旧设计可从 Git 历史查阅；运行方式、安全边界和最新验证命令以本 README 和代码为准。界面结构参考 [CCF 论文雷达](https://szy12021130.github.io/ccf-a-radar/#/)，未复制其数据集或品牌资产。

### ACM 空来源的证据采集与研究分轨核验

`seeds/acm_proceedings.json` 保存已经用出版方 Crossref 元数据核对过的 18 个 ACM 论文集身份（名称、年份、父 DOI），不是完整覆盖证明。新增年份不得仅按往届 DOI 或届次猜测。

从 backend 目录运行（只采集元数据，不修改数据库、不下载 PDF）：

```powershell
python -m scripts.collect_acm_evidence --registry ../seeds/acm_proceedings.json --evidence ../release-artifacts/acm-evidence
```

每次在线验证父论文集与文章 DOI、题名容器、发表年份；按游标逐页核对去重后的数量，保留原始响应及摘要。遇到限流等待重试；抓取失败、零结果、提前结束和重复 DOI 不计为完成。Crossref DOI 清单完成仍不证明全部主会/研究分轨完整。

当前有独立研究名单适配器的单元：SIGIR 2024 `Full Papers`（官网 JSONL 中 `fp`，160 条）、WSDM 2024 官网 Accepted Papers（109 条）、ACM MM 2024 官方 Accepted Papers（1,151 条）、WWW 2024 Research Tracks（405 条）、WWW 2023 官方存档的 Research Tracks CSV（367 条）和 CIKM 2025 Full Research Papers（442 条）。将官方页面保存到同一 evidence 目录后，先运行 `python -m scripts.import_acm_research_tracks --evidence 路径` 审计；显式添加 `--apply` 才会备份数据库并导入精确题名、完整作者集合和出版身份全部一致的条目。题名或作者差异写入 unresolved，不模糊合并、不按页数推测分轨。完整姓名词项完全相同的姓名顺序变化可以匹配，但不省略中间名、不猜测缩写/别名。使用 `--venues WWW --year 2023` 可只处理 WWW 2023；CIKM 可用 `--venues CIKM --year 2025`；默认年份为 2024。官方原始文件哈希与每次运行的独立时间戳报告一并保存，历史报告不被后一次运行覆盖。原始官网地址保存在导入报告及论文来源备注中。

本轮新增数据需要另行导出快照并验收后才会出现在静态网站；采集/导入命令本身不发布。该维护链路尚未自动接入所有年份的定时采集，不能将“入口已配置”解释为“无需人工复核即可全量收录”。

研究分轨适配器现亦支持 `--venues WSDM SIGIR --year 2025`：分别核对官网的 106 篇研究论文与 239 篇 Full Papers。WSDM 2025 正式论文集使用 “Eighteenth”，通过官网父 DOI `10.1145/3701551` 核实；不可由数字届次自动猜测出版标题，查询零结果不表示未发表。

研究名单核验也支持 `--venues SIGIR WSDM --year 2023`，分别以 SIGIR 官网 Full Papers（165 条）和 WSDM 官网 Accepted Papers（123 条）对账。WSDM 2023 通过官网父 DOI `10.1145/3539597` 核实其正式名称中的 “Sixteenth”，不把不存在的 “16th” 查询结果当作未发表。名单差异继续保留，完整 DOI 清单不等于所有研究论文均已核验。

WSDM 2023 官网的 ACM Proceedings HTML 同时提供摘要，可用 `python -m scripts.fill_wsdm2023_abstracts --evidence 路径` 先审计，再显式加 `--apply` 补齐已核验论文的空摘要并刷新规则标签。只匹配正式 DOI、题名和完整作者；不覆盖已有摘要、不修改人工标签、不新增论文、不获取 PDF。每次应用前备份，记录来源 URL 和文件哈希。

同一摘要补齐命令现支持 `--year 2024`，默认仍为 2023。WSDM 2024 从官网 `https://www.wsdm-conference.org/2024/acm-proceedings/` 的 175 条出版摘要核对已准入论文；仅填空白摘要，不以目录中的 Keynote、Demo 等条目新增公开论文。验收需包含新增摘要词项的真实库检索与人工标签不变检查。

SIGIR 2026 适配器可用 `--venues SIGIR --year 2026`，只解析官方页面内的 JSON 字面量 Full Papers（233 条），不执行外部脚本，重复一致载荷只读一次，冲突载荷或截断则拒绝。官方录用名单不能单独证明正式出版：仍逐篇核对出版方父 DOI、文章 DOI、年份、题名与作者，差异保留待核验。

WWW 2025 的正式容器名称为 `Proceedings of the ACM on Web Conference 2025`，父 DOI 为 `10.1145/3696410`（包含 on）。官方系列网站已指向 `https://archives.iw3c2.org/www2025/`；旧域名不可访问不表示当年没有论文。可用 `python -m scripts.audit_www2025_schedule --evidence 路径` 只读对账官方日程的编号研究场次；Industry 与 TWeb 期刊展示不计入会议候选，重复官方投稿编号单列待查。该日程不提供作者且未证明海报论文全量，审计命令不执行入库。

SIGIR 2024 的官网论文集摘要可用 `python -m scripts.fill_sigir2024_abstracts --evidence 路径` 审计，显式添加 `--apply` 后备份并仅填已有确认论文的空摘要。解析官网 HTML 内嵌的 ACM DOI，不访问邮件链接包装器或下载 PDF；题名、完整作者不一致的条目保留待查。

SIGIR 摘要命令同时支持 `--year 2023`（默认 2024）：读取 SIGIR 2023 官网正式论文集的 469 个摘要块，逐篇核对已有论文身份后补空摘要。主会研究资格沿用先前独立核验；Keynote 等目录条目不通过摘要工具新增论文。

SIGIR 2023 官方名单存在题名最后一个词位于 `strong` 标签外的真实格式。解析必须先固定每个 `p` 段落，再分开题名/作者，不能用跨段落正则寻找下一个 `br`；否则会把相邻两篇合并并错误统计为 164 篇。完整官方名单为 165 篇，此格式已加回归测试。

覆盖核验可运行 `python -m scripts.audit_coverage_ledger --evidence 路径 --output 报告.json`：只读数据库，重新解析当前支持的 ACM 官方研究名单，逐 DOI、题名、作者及公开准入比较，不引用历史导入数量作为成功证明。报告包含全部配置来源的 2023–2026 年计数、空摘要和无方向标签数量；未被该工具复核的其他采集证据标记为未审计，而非无数据。单一研究名单完全匹配也不代表该来源所有分轨或指定方向全部覆盖。

CIKM 2025 作者机构标签存在嵌套 `i` 元素，必须按 HTML 层级去除机构信息，不能用首个闭合标签截断，否则国家名会被错误识别为作者。嵌套标签解析已覆盖回归测试；不平衡标签的行保留在官方预期数量中并标记 `official_author_markup_invalid`，不猜测作者或丢弃整份清单。

SIGIR 摘要命令支持 `--year 2025`，但已观察到的官网 proceedings 页面仅有 100 条摘要，不代表完整论文集。只补已核验且题名、作者一致的空缺摘要；解析 Google 链接参数中明确的 ACM 目标，不请求跳转服务。报告始终注明未证明全论文集覆盖。

ACM 作者数量核验保留多重集合：同名不等于同人。仅在出版元数据中的重复条目具有相同完整 ORCID 且整个作者对象完全相同时，才可折叠重复登记，并记录折叠数量；不同 ORCID、缺少 ORCID 或机构字段不同都不能按姓名去重。原始证据文件保持不变。

WSDM 2026 可用 `--venues WSDM --year 2026` 核对官网 100 篇 Full Papers。同名出版容器存在两个父 DOI（`10.1145/3773966` 与 `10.1145/3779211`），必须先逐条验证并按父 DOI 分开，不能把容器名称相同当作同一论文集；本次保留了混合查询原始结果与两个父记录。分区元数据不作为全量覆盖断点。

同名容器的多父 DOI 采集现由 `other_parent_dois` 显式配置：每个父记录必须重新在线验证相同年份和精确容器，未知父 DOI 仍失败。结果保留主分区 `items` 与 `other_parent_partitions`，并区分 `container_count` 与 `selected_parent_count`。`doi_inventory_complete` 仅表示该次 Crossref 查询已按数量完整枚举，不代表研究分轨或 CCF 覆盖完成；不会把备用父分区直接导入主来源。

WWW 2026 支持 `--venues WWW --year 2026`：官网 `accepted/research-tracks.html` 提供 676 条带投稿编号和作者的研究名单，逐篇与正式出版身份核验，不包含短文、工业、演示或工作坊名单；未匹配记录保留待查。导航链接由官网 header-loader 动态加载，采集入口应跟随实际组件链接，不把首页没有直接链接误当作无论文。

现有作者表按规范化姓名去重，同篇论文中两个同名作者不能由当前关联主键无损表达。官方出版导入对此返回 `author_multiplicity_not_representable` 冲突并保留完整作者列表，不静默丢弃作者、不把待核验论文升级为确认。此保护不是完整支持同名作者：已有冲突需通过独立作者位置/身份模型迁移或可靠来源更正解决，不能视为覆盖完成。

### 2026-10-02 来源与性能复核

本轮额外核实 WWW 2025（87 篇）、Middleware 2023（24 篇）、SIGGRAPH 2025（174 篇），新快照共 381,441 条公开论文。336/338 表示来源已有直接记录或逐篇官网关联，**不表示所有论文已收齐**；LISA/VEE 和其余零记录年份继续保留待核验。详见 [验收记录](docs/performance-coverage-20261002.md)。

在 `frontend` 下运行 `npm run check:snapshot-home`、`npm run check:snapshot-search`、`npm run check:snapshot-performance`。最后一项同时比较同一完整数据集上新旧引擎的结果、分数和分页，强制执行首屏流量/请求数/处理预算。浏览器复测可启动 `python scripts/benchmark_static_server.py frontend/dist --mbps 4 --latency-ms 80`，再用 Playwright CLI 的 `run-code --filename frontend/scripts/benchmark-browser.js` 测试所打开的预览地址；可在地址参数中设置 `cpu=4` 做主线程慢化和 390px 视口检查。
