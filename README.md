# LitHub Pavilion

[![Verify](https://github.com/scyolo/LitHub-Pavilion/actions/workflows/verify.yml/badge.svg)](https://github.com/scyolo/LitHub-Pavilion/actions/workflows/verify.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 面向 CCF A/B 论文研究的本地优先工作台。

LitHub Pavilion 将论文元数据采集、清洗、索引和阅读整合到一个小型研究工具中。它支持按会议、期刊、年份和研究方向浏览论文，提供英文全文检索、开放链接和来源覆盖信息；后端运行在本地，前端既可以连接实时 API，也可以读取导出的静态快照并部署到 GitHub Pages。

项目适合希望长期维护自己的 CCF A/B 论文阅读入口、同时保留数据采集和发布控制权的研究者。它保存论文元数据、摘要、作者、标签和外链，不下载或提供 PDF 文件。

在线预览：<https://scyolo.github.io/LitHub-Pavilion/>

## 功能

- **论文浏览与筛选**：按 CCF A/B、会议或期刊、年份、研究方向、开放链接等条件组合筛选。
- **英文全文检索**：在标题和摘要中进行关键词、精确标题和有限模糊检索，支持分页和稳定排序。
- **作者姓名检索**：选择“作者姓名”，按全部作者搜索论文；姓名各部分须属于同一作者，忽略词序、大小写和重音，并支持元数据中已有的中文姓名。
- **论文详情**：查看摘要、作者、出版信息、方向标签以及官方页面、DOI、DBLP 或开放版本链接。
- **研究总览**：查看年度分布、来源统计、方向概况和最近收录论文。
- **来源覆盖与截稿日历**：检查来源和年份的采集状态，浏览 CCF A/B 会议投稿截止时间。
- **技术报告目录**：独立浏览主要机构的模型报告、系统卡、模型卡、官方博客和代码发布。
- **静态阅读模式**：将本地数据库导出为公开快照；GitHub Pages 无需后端即可浏览、筛选和搜索。

## 工作方式

```text
官方出版目录 / DBLP / Crossref / OpenAlex / Semantic Scholar
                              │
                              ▼
                    FastAPI 采集与清洗
                              │
                              ▼
                         SQLite + FTS5
                              │
                  导出并校验公开静态快照
                              │
              React/Vite 本地网站或 GitHub Pages
```

后端负责本地采集、数据维护和快照发布；前端负责浏览、筛选和检索。Docker 默认只把网站绑定到 `127.0.0.1:8080`，API 保持在容器内部。公开部署使用不含数据库、密钥和管理接口的静态快照。

详细的数据契约、发布链路和模块边界见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 快速开始

需要 Docker Desktop 或 Docker Engine + Compose v2。

```bash
# Linux / macOS / Git Bash
cp .env.example .env
docker compose up -d --build --wait
```

PowerShell：

```powershell
Copy-Item .env.example .env
docker compose up -d --build --wait
```

打开 <http://127.0.0.1:8080/>。首次启动会初始化 SQLite/FTS5，并按配置采集 `seeds/venues.csv` 中启用的 CCF A/B 来源。首次采集完成前显示 0 篇是正常现象，数据保存在 Compose 命名卷中。

停止服务：

```bash
docker compose down
```

不要使用 `docker compose down -v`，否则会删除本地数据卷。

## 本地开发

需要 Python 3.11+、Node.js 22+。

先启动后端：

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Linux / macOS:     source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
cd frontend
npm ci
npm run dev
```

访问 <http://127.0.0.1:5180/>。Vite 会将 `/api` 请求代理到本地后端。

构建并预览前端：

```bash
cd frontend
npm run build
npm run preview -- --host 127.0.0.1
```

## 静态快照与 GitHub Pages

从本地数据库导出公开快照：

```bash
cd backend
python -m scripts.export_snapshot --output ../frontend/static/snapshot
```

导出目录只包含公开论文元数据和索引，不包含数据库、备注、令牌或 PDF。快照通过校验后，可以在 `frontend/` 中独立构建和预览；也可以使用 GitHub Pages 工作流发布。

启用自动发布时，需要：

1. 在 `.env` 中设置 `PAGES_REPOSITORY`，并将 GitHub token 保存为 `.secrets/github_token`。
2. 在目标仓库启用 GitHub Pages 的 **GitHub Actions** 来源，并设置仓库变量 `PAGES_DEPLOY_ENABLED=true`。
3. 使用 Pages 覆盖配置启动：

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.pages.yml up -d --build --wait
   ```

发布规则和验收细节见 [ARCHITECTURE.md](ARCHITECTURE.md) 及 [`docs/`](docs/) 中的发布记录。`.env.example` 列出了采集、快照和邮件提醒等可选配置。

## 数据范围与边界

- 默认范围由 [`seeds/venues.csv`](seeds/venues.csv) 控制，只面向配置中的 CCF A/B 来源；不主动扩展到 C 类或目录外来源。
- 方向标签由关键词规则和来源先验生成，允许一篇论文属于多个方向，标签需要结合论文内容理解。
- 来源目录已配置不等于对应年份已经完整采集；上游目录缺失、身份冲突和访问限制会保留为未完成状态。
- 外链指向 DOI、出版方、DBLP 或开放版本页面。本站不代理论文文件，也不保证第三方链接永久可用或无需登录。
- 本地 API 和采集管理接口没有认证，只应绑定回环地址或放在受信任的本机环境中。公开站点只提供静态快照。

安全边界和数据处理规则见 [SECURITY.md](SECURITY.md)。

## 常用验证命令

后端：

```bash
cd backend
python -m ruff check app scripts tests --select F,E9
python -m pytest -o addopts= --disable-warnings
```

前端：

```bash
cd frontend
npm test
npm run build
```

容器冒烟测试和 Pages 快照检查由 GitHub Actions 自动执行，具体流程见 [`.github/workflows/`](.github/workflows/)。

## 项目结构

```text
backend/                 FastAPI、采集器、SQLite/FTS5、维护脚本和测试
frontend/                React/Vite 网站、快照读取器和前端测试
seeds/                   CCF 来源、方向、别名和技术报告种子数据
scripts/                 Pages 构建、快照打包和发布检查脚本
docs/                    发布记录、覆盖审计和维护说明
ARCHITECTURE.md          架构、数据契约和发布边界
SECURITY.md              安全与数据策略
CONTRIBUTING.md          贡献与验证要求
```

## 参与贡献

请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。提交代码前，运行后端测试、前端测试和构建，并确认没有把 `.env`、数据库、备份、PDF、密钥或生成产物加入提交。

## 许可证

本项目使用 [MIT License](LICENSE)。上游目录、论文元数据和外部链接仍受各自来源的使用条款约束。
