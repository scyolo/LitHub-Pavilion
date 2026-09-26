# LitHub Pavilion

> 知汇于此，文藏此殿

个人自用的 CCF A/B 论文研究工作台。FastAPI + SQLite FTS5 + React/Vite，提供年度/方向图表、会议期刊浏览、组合筛选、英文全文检索和官方/OA 链接。

**采用“本地 Docker 采集 → 导出公开静态快照 → GitHub Pages 浏览”的模式，不下载 PDF。只有静态网站可以公开；无认证的后端与管理接口仍仅限本机。**

## 功能

- 研究总览：年度 A/B 图表、主题分布、开放链接覆盖、最近收录；点击图表可进入论文列表。
- 论文探索：A/B 会议和期刊快捷切换，方向多选、年份、来源、开放链接筛选，稳定排序与分页。
- 详情页：摘要、作者、元数据、发表归属提示及安全原文链接；返回保留筛选条件。
- 深浅主题、移动端导航与筛选、键盘操作、减少动态效果支持。
- Docker 启动后自动按配置采集，历史回填断点续传，完成后原子导出快照；部分失败如实记账。
- GitHub Pages 无需本地后端：图表、筛选、英文全文搜索、排序、分页与论文原文链接均在浏览器内工作。
- 本地前端自动检测 API，后端不可用时回退到已导出的快照，恢复后自动切回实时数据；不会用旧快照掩盖真实 400/404 错误。
- 非破坏性维护：链接回填不删除已有文件，种子导入不覆盖已有配置，数据库备份不会自动删除旧备份。

默认配置 28 个来源、9 个方向：LLM、投机解码、智能体、计算机视觉、多模态、强化学习、NLP、信息检索/RAG、安全与对齐。目录位于 `seeds/`；仓库不附带个人论文数据库或 PDF。

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
- 首页只下载已校验的 manifest 和轻量 catalog（含 9 种级别/出版类型组合的统计与最新发表卡片），不等待完整摘要库。首次进入论文列表、详情或全文检索时再在 Worker 中下载并校验完整快照；首次检索仍有整库下载成本，之后复用内存索引。旧快照没有首页摘要时自动走兼容全量路径。
- 首页摘要与完整论文数据是两个明确的验证层：导出和发布时会用全部论文重算并验证首页摘要；浏览器先验证摘要文件的哈希、公开字段与计数，完整数据使用前再校验全部分片，并交叉检查统计。已有完整版本换版仍须新版本全量验证成功才切换；失败保留旧版，不混合版本。每 60 秒、窗口聚焦及“检查更新”时检查 manifest。
- 普通论文列表和首页最新论文默认按上游发布日期从新到旧排序；只有年份或日期无效时按归属年，同年排在具体日期之后，最终以论文 ID 稳定排序。不用入库时间代替发布日期，不伪造月份和日期。英文搜索默认按相关性，显式选择的排序在修改/清空关键词后保留。上一页、下一页及每页条数变化会立即回到页面顶部。
- 原文链接是直接指向 DOI、出版方、DBLP 或 arXiv 的 HTTP(S) 链接，与后端是否运行无关。本站不能保证外站永久在线、无需付费或免登录。
- 同一 revision 不重复提交 Git 数据。接受 dispatch 不等于部署完成：本地每 5 分钟读取线上公开 manifest 确认版本；30 分钟仍未上线则重新派发，同一快照不再创建新提交。网络不可达时保留回执并下次复查。
- 发布只更新专用 `site-data` 分支，不 force push；已存在的同名分支没有本项目所有权标记时会拒绝覆盖。Pages 保留当前及上一版经公开字段校验的资产，避免更新途中旧页面请求的文件失效。
- 公开内容仅含论文元数据、摘要、作者、链接、方向和已结束任务摘要；不含备注、数据库、PDF、错误日志正文、SMTP 凭据或令牌。发布前自行确认上游元数据的再分发条件。

### 仅导出、验证或本地预览

从项目根目录使用已有本地数据库导出（不启动 API、不采集外网）：

```bash
# Git Bash / Linux / macOS
PYTHONPATH=backend python -m scripts.export_snapshot --output frontend/static/snapshot
PYTHONPATH=backend python -m scripts.export_snapshot --output frontend/static/snapshot --validate-only
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
| `PAGES_RETRY_SECONDS` | `300` | 上传重试及线上版本检查周期 |
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
2. DBLP、Semantic Scholar、OpenAlex 可能被限流、质询、延迟收录。S2 主题搜索是**非完整兜底**，不应等同于整届会议目录。零记录/失败不会写完整回填断点。
3. 新记录只有直接 DBLP TOC 来源才标为已关联；手工指定 venue 或 S2 的 key 前缀不等于已核验发表年份与主会录用。旧数据保留原标记，并继续显示核验提示。
4. 方向使用关键词规则，可多标签重叠；引用数来自上游而非实时评估。摘要缺失/纯标点占位不伪装为有效摘要。
5. 在线英文检索基于 FTS5 `porter unicode61`，静态版在 Worker 内对标题和完整摘要建立词干索引，均按所有英文词项交集匹配。中文分词不在当前范围，接口明确报错。外链做安全校验，不保证每个出版站均可访问。
6. 外部元数据 HTTP 客户端只连接 DNS 解析并验证后的公网 IP，保留原主机 TLS SNI；禁止自动重定向和环境代理。Fake-IP/TUN 网络把域名映射到 `198.18.*` 等非公网地址时，设置 `OUTBOUND_DNS_MODE=https`，使用固定公网 HTTPS DNS 解析器取得真实 IPv4 地址；仍检查每条结果、固定连接目标并验证证书，不允许私网地址，不修改系统代理。默认 `system` 保持系统 DNS 行为。

## 维护

从 `backend/` 执行：

```bash
python -m scripts.backup        # 新建快照并 quick_check，不删除旧备份
python -m scripts.rebuild_fts   # 原子重建 FTS 索引并校验主表一致性
python -m scripts.seed          # 仅增加缺失种子，不覆盖现有 source ID / active 等配置
python -m scripts.extend_topics # 先备份，再增补六个相邻方向标签；保留人工标签
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
npm audit --omit=dev
```

`.github/workflows/verify.yml` 定义后端测试、前端测试/构建与 Docker 空库冒烟；推送后才由 GitHub 实际执行，本地通过不代表远端 CI 已运行。

隔离容器验证（不动现有库）：

```bash
WEB_PORT=8180 SCHEDULER_ENABLED=false STARTUP_CRAWL_ENABLED=false SNAPSHOT_ENABLED=false PAGES_PUBLISH_ENABLED=false docker compose -p lithub-release-check up -d --build --wait
python scripts/smoke_release.py
docker compose -p lithub-release-check down
```

Windows PowerShell 可先设置 `$env:WEB_PORT='8180'; $env:SCHEDULER_ENABLED='false'; $env:STARTUP_CRAWL_ENABLED='false'; $env:SNAPSHOT_ENABLED='false'; $env:PAGES_PUBLISH_ENABLED='false'` 再执行 Compose 命令。测试夹具也禁用所有真实采集/导出/发布副作用。只关闭调度器不会关闭启动采集。

## 项目结构

```text
backend/app/api/           共享筛选、序列化、API 和本地写请求保护
backend/app/collectors/    数据适配与公网地址绑定传输
backend/app/services/      任务编排、入库、补全、链接维护和标签
backend/app/bootstrap.py   非破坏数据库初始化
backend/scripts/           备份、索引维护、种子与标签扩展
backend/tests/             隔离数据库/模拟网络回归测试
frontend/src/              研究工作台、图表、卡片与交互测试
seeds/                    配置来源和方向规则
scripts/smoke_release.py   固定本机测试端口的 Docker 冒烟
.github/workflows/         自动测试流水线
```

`系统设计方案.md`、`设计审查报告.md`、`界面改版与验收.md` 为历史设计/验收记录。运行方式、安全边界和当前版本限制以本 README 和代码为准。界面结构参考 [CCF 论文雷达](https://szy12021130.github.io/ccf-a-radar/#/)，未复制其数据集或品牌资产。
