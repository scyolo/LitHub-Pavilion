# LitHub Pavilion

> 知汇于此，文藏此殿

个人自用的 CCF A/B 论文研究工作台。FastAPI + SQLite FTS5 + React/Vite，提供年度/方向图表、会议期刊浏览、组合筛选、英文全文检索和官方/OA 链接。

**本版本采用链接模式，不自动下载 PDF。无登录系统，仅供本机使用，不应直接暴露到公网。**

## 功能

- 研究总览：年度 A/B 图表、主题分布、开放链接覆盖、最近收录；点击图表可进入论文列表。
- 论文探索：A/B 会议和期刊快捷切换，方向多选、年份、来源、开放链接筛选，稳定排序与分页。
- 详情页：摘要、作者、元数据、发表归属提示及安全原文链接；返回保留筛选条件。
- 深浅主题、移动端导航与筛选、键盘操作、减少动态效果支持。
- 每周采集、断点续传、部分失败如实记账、退出时安全取消后台任务。
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

访问 **http://127.0.0.1:8080/**。首次空库会自动创建 SQLite/FTS5 和种子配置；页面此时显示 0 篇，而不是演示数据。可以在管理页显式触发历史回填。

- 仅 web 的环回端口发布到宿主机，API 不公开端口。
- API 用户 UID 1001、nginx 用户 UID 101；容器只读根文件系统、移除 capabilities。
- 数据保存在 Compose 项目下的 `lithub-data` **命名卷**，包含 WAL 与备份。`docker compose down` 不删除卷。
- **不要执行 `docker compose down -v`**，该命令会删除持久化数据。
- 旧版本的根目录 `./data` 绑定卷不会自动导入。已有本地数据库也不会被复制到容器；迁移前先备份并明确来源，禁止用空库覆盖旧库。

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

访问 **http://127.0.0.1:5180/**。Vite 固定 IPv4 和端口，`/api` 代理到 8000。只有一个后端 worker：调度与任务状态按单实例设计。

默认数据库固定为 `backend/data/papers.db`，不再随终端工作目录变化。可通过 `DATABASE_URL` 指定其他 SQLite 文件；当前发布版不支持直接替换成 PostgreSQL，FTS 适配仍需实现。

## 配置与调度

环境变量通过根目录/后端目录的 `.env` 读取；真实密钥不要写入源码。

| 配置 | 默认值 | 用途 |
|---|---|---|
| `S2_API_KEY` | 空 | Semantic Scholar API key，可选 |
| `CONTACT_EMAIL` | 空 | 上游请求的联系信息，建议填写真实邮箱 |
| `SCHEDULER_ENABLED` | `true` | 是否注册自动任务 |
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

页面刷新每 30 秒查询**本地统计**，不是外部采集。没有每天抓取论文或批量下载 PDF 的任务。重复任务提交返回 409，不会得到一个永远不执行的 run ID。

## 数据准确性边界

1. CCF 范围由配置清单限制，不代表已对 2026 目录逐行、逐篇重新核验。正式级别、主会/分轨和录用信息以官方出版页为准。
2. DBLP、Semantic Scholar、OpenAlex 可能被限流、质询、延迟收录。S2 主题搜索是**非完整兜底**，不应等同于整届会议目录。零记录/失败不会写完整回填断点。
3. 新记录只有直接 DBLP TOC 来源才标为已关联；手工指定 venue 或 S2 的 key 前缀不等于已核验发表年份与主会录用。旧数据保留原标记，并继续显示核验提示。
4. 方向使用关键词规则，可多标签重叠；引用数来自上游而非实时评估。摘要缺失/纯标点占位不伪装为有效摘要。
5. 英文检索基于 FTS5 `porter unicode61`；中文分词不在当前范围，接口明确报错。外链做安全校验，不保证每个出版站均可访问。
6. 外部元数据 HTTP 客户端只连接 DNS 解析并验证后的公网 IP，保留原主机 TLS SNI；禁止自动重定向和环境代理。企业代理网络需要显式适配，不能关闭边界检查来访问私网。

## 维护

从 `backend/` 执行：

```bash
python -m scripts.backup        # 新建快照并 quick_check，不删除旧备份
python -m scripts.rebuild_fts   # 原子重建 FTS 索引并校验主表一致性
python -m scripts.seed          # 仅增加缺失种子，不覆盖现有 source ID / active 等配置
python -m scripts.extend_topics # 先备份，再增补六个相邻方向标签；保留人工标签
```

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
WEB_PORT=8180 SCHEDULER_ENABLED=false docker compose -p lithub-release-check up -d --build --wait
python scripts/smoke_release.py
docker compose -p lithub-release-check down
```

Windows 可先设置 `$env:WEB_PORT='8180'; $env:SCHEDULER_ENABLED='false'` 再执行 Compose 命令。

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
