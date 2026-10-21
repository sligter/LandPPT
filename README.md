# LandPPT - AI 驱动的 PPT 生成平台

[![GitHub stars](https://img.shields.io/github/stars/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/network)
[![GitHub issues](https://img.shields.io/github/issues/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/issues)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg?style=flat-square)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-supported-blue.svg?style=flat-square)](https://hub.docker.com/r/bradleylzh/landppt)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/sligter/LandPPT)

**中文** | [English](README_EN.md)

当前版本：**0.4.0**。

<div align="center">
  <img src="https://img.pub/p/e810c5680509b4f051a5.png" width="160" alt="LandPPT Logo" />
  <p><b>主题 / 文档 → 大纲 → HTML PPT → 讲稿 / 配音 / 导出</b></p>
</div>

**一句话：** LandPPT 是基于大语言模型的智能演示文稿平台——输入主题或上传文档，自动生成可编辑的专业 PPT，并支持讲稿、讲解视频与多格式导出。

**核心能力：**

| 能力 | 说明 |
|------|------|
| 一键生成 | 主题到完整 PPT，支持并行生成 |
| 快速模式 | AI 生成内容，自动匹配可复用模板包版式并填充 SVG |
| 智能配图 | 本地图库 / 网络图库 / AI 生成三源融合 |
| 深度研究 | Parallel / Tavily / SearXNG，实时抓取并摘要网络信息 |
| 讲稿与视频 | 演讲稿 + Edge-TTS 逐页讲解，可导出 1080p 视频 |
| 多格式导出 | PDF / HTML / PPTX / 图片 / DOCX / Markdown |
| 自动化 | OpenAI 兼容 API + REST API，支持 API Key 鉴权 |

[文档指南](http://landppt-doc.52yyds.top/docs) · [Docker Hub](https://hub.docker.com/r/bradleylzh/landppt) · [Issues](https://github.com/sligter/LandPPT/issues)

---

## ❤️ 赞助商

<div align="center">

<table width="100%">
  <tr>
    <td align="center" valign="top">
      <a href="https://www.aiyoyoo.com/register?aff=YH2FW34DTFPH" target="_blank">
        <img src="assets/sponsors/crazytoken-zh.png" alt="CrazyToken | 全模型服务，最高省 99%" width="100%"/>
      </a>
      <div align="left">
        <br/>
        ❤️ 感谢 <a href="https://www.aiyoyoo.com/register?aff=YH2FW34DTFPH" target="_blank"><strong>CrazyToken</strong></a> 对 LandPPT 的赞助支持！
        <br/><br/>
        <strong>CrazyToken | 接入全球主流大模型，让资料更快变成精彩演示，倍率低至 0.05x，最高省 99%</strong>
        <br/><br/>
        CrazyToken 提供 Claude、GPT、Gemini、Kimi、GLM、DeepSeek、Qwen、Grok 等主流模型 API，为文档要点提炼、大纲规划、逐页内容生成与演讲稿撰写提供模型支持。从工作汇报、教学课件到产品介绍，按不同制作环节选择合适的模型，让内容组织更高效。
        <br/><br/>
        💰 <strong>最低 0.05×，降低 PPT 制作成本</strong>：模型价格低至官方价格的 5%，Token 级账单透明可查，让长文档整理、多页生成与反复修改更省成本。<br/>
        ✨ <strong>官方原生通道</strong>：不掺水、不混模、不压缩长上下文，为梳理资料重点、组织演示逻辑和保持内容连贯提供模型支持。<br/>
        ⚡ <strong>稳定高速，高并发不限流</strong>：为多页内容生成和多任务处理提供稳定的 API 服务，减少制作过程中的调用等待。<br/>
        🎁 <strong>新用户注册赠送 $20</strong>：通过<a href="https://www.aiyoyoo.com/register?aff=YH2FW34DTFPH" target="_blank">专属链接</a>注册即送 <strong>$20 体验额度</strong>，充值额外加赠；提供 <strong>1 对 1 远程配置服务</strong>，真人协助完成模型 API 配置。
        <br/><br/>
        👉 <a href="https://www.aiyoyoo.com/register?aff=YH2FW34DTFPH" target="_blank">立即体验 CrazyToken，注册即领 $20 体验额度</a>
      </div>
    </td>
  </tr>
</table>

</div>

---

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [界面预览](#界面预览)
- [依赖与能力边界](#依赖与能力边界)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
- [快速模式与模板包](#5-快速模式与模板包)
- [配置说明](#配置说明)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)
- [联系我们](#联系我们)

---

## 项目简介

LandPPT 将「写大纲 → 做版式 → 配图 → 写讲稿 → 导出」整合成一条 AI 工作流：

1. **输入**：主题描述，或 PDF / Word / Markdown / Excel / PPT 等文档  
2. **规划**：生成可编辑大纲，可选深度研究补充最新信息  
3. **生成**：并行产出 HTML 幻灯片，支持模板与 AI 自适应布局  
4. **打磨**：侧边栏 AI 对话编辑、换图、视觉参考  
5. **交付**：导出多格式，或生成公开分享链接（含讲解音频与字幕）

**本地默认：** SQLite + 内存缓存，一条命令即可试用，无需 PostgreSQL / Valkey。  
**生产推荐：** `docker compose` 编排 Web + Worker + PostgreSQL + Valkey + MinIO + PPTX 渲染器。

---

## 功能特性

### 多 AI 提供商

- OpenAI GPT、Anthropic Claude、Google Gemini、Azure OpenAI  
- 兼容 DeepSeek、Moonshot、Qwen 等 OpenAI 协议接口  
- 支持 Ollama 本地模型；按角色（大纲 / 幻灯片 / 编辑 / 模板 / 讲稿）路由模型，便于控成本  

### 文件处理与深度研究

- 多格式：PDF / Word / Markdown / TXT / Excel / PowerPoint  
- MinerU + MarkItDown 高质量解析  
- Parallel / Tavily / SearXNG 检索与网页摘要

### 智能图像

- 三源：本地图库 / Pixabay、Unsplash / DALL·E、SiliconFlow、Pollinations、OpenAI、Gemini  
- AI 自动匹配；尺寸、格式与质量自动处理  
- 图像服务默认关闭，按需开启（`ENABLE_IMAGE_SERVICE`）  

### 模板与项目

- 全局主模板 + 场景模板（通用 / 旅游 / 教育等）  
- 上传参考 PPTX 抽取版式；项目级 AI 自适应模板  
- 四阶段工作流：需求确认 → 大纲 → 任务追踪 → PPT 生成  
- 阶段重跑与恢复；可视化大纲；一键公开分享  

### 快速模式模板包

- 同一模板包包含封面、目录、正文、图文、总结等版式；AI 生成内容后自动匹配并填充 SVG 组件。
- 支持添加内置包、导入模板包文件、从 PPTX 创建和 AI 创建；PPTX 导入可选“视觉复刻”或“保留原稿底图”。
- 模板包名称和描述可编辑；工作区支持单页新增、复制、移动、删除、AI 修改，以及整包 AI 多轮编辑和流式回复。
- 草稿校验后发布，项目固定使用已选版本；修改已发布包会创建新草稿，已有项目继续使用原版本。
- 项目可修改结构化内容、切换版式、替换图片和锁定页面；决策模型支持 Jev / TypeSafe 或 OpenAI 兼容协议，也可使用现有模型或规则选择版式。

使用步骤和能力边界见下方 [快速模式与模板包](#5-快速模式与模板包)，模块说明见 [模板包文档](src/landppt/services/template_package/README.md)。

### 平台与运维

- Docker 单容器 / Compose 多服务；后台任务（PDF / PPTX / 讲解视频）异步执行  
- 本地账号支持用户名或邮箱配合密码登录；GitHub / Linux Do OAuth、邮件验证、注册限流
- 可选积分系统、SMTP / Resend、Cloudflare Turnstile  
- CI/CD 同时发布应用与 PPTX 渲染器镜像；Helm 提供共享存储和渲染器网络隔离，Argo CD 完整同步先迁移数据库再更新应用。

---

## 界面预览

### 主界面

![主界面](https://img.pub/p/3accad83a8b624d7cb19.png)

### 大纲与生成效果

![大纲](https://img.pub/p/a31e4f94c5d2bd577d8d.png)

![生成效果](https://img.pub/p/e6cffa89a2b532a8514b.png)

<details>
<summary><b>更多截图（在线编辑 / 讲稿 / 导出 / 模板）</b></summary>

#### 主界面（备选）

![主界面 2](https://img.pub/p/7d5c3c1a4b625abeb4c1.png)

#### 生成效果（备选）

![生成效果 2](https://img.pub/p/9a38b57c6f5f470ad59b.png)

#### 在线编辑

![编辑 1](https://img.pub/p/6d357a847626f1a55c13.png)

![编辑 2](https://img.pub/p/42f84b07850f5aa4aebb.png)

![编辑 3](https://img.pub/p/8dccee74d0b85893bd38.png)

![编辑 4](https://img.pub/p/aaf483b2507a57db8b35.png)

#### 讲稿生成

![讲稿](https://img.pub/p/c53b752e0a6833c0ee87.png)

#### 导出效果

![导出](https://img.pub/p/62694101810bfa472db9.png)

#### 模板生成

![模板](https://img.pub/p/892622b3f3cc0d6ad843.png)

</details>

---

## 依赖与能力边界

请先分清「最小可跑」和「完整能力」，避免跑通后才发现缺 Key。

| 能力 | 依赖 | 说明 |
|------|------|------|
| 基础生成（大纲 / HTML PPT） | 至少一个 AI Provider Key | **必需** |
| 本地模型 | Ollama 等 | 可选，可完全离线推理 |
| 演示文稿研究 | Parallel Search MCP（无需密钥）、Tavily 或 SearXNG | 可选；[提供商配置](RESEARCH_PROVIDERS.md) |
| 网络 / AI 配图 | 对应图库或生图 Key + `ENABLE_IMAGE_SERVICE=true` | 可选，默认关闭 |
| 从 PPTX 创建模板包 | 独立 LibreOffice 渲染器 + 模板生成模型 | Compose 已包含渲染器；视觉复刻需要支持图片输入的模型 |
| **标准可编辑 PPTX** | **`APRYSE_LICENSE_KEY`（商业许可）** | **可选但导出可编辑 PPTX 时必需** |
| 图片型 PPTX | 无 Apryse | 保真高，页内元素通常不可再编辑 |
| 讲解视频 | `ffmpeg`；可选 ComfyUI TTS | 可选 |
| 生产多用户 / 后台任务 | PostgreSQL + Valkey + MinIO + Worker | 推荐 Compose 一键起 |

> **安全提示（生产必读）**  
> - 修改 `SECRET_KEY`、管理员密码，勿使用默认 `admin` / `admin123`  
> - 生产编排默认关闭管理员自动初始化；首次部署再显式打开 `LANDPPT_BOOTSTRAP_ADMIN_ENABLED`  
> - 配置强随机 `LANDPPT_API_KEY` / `LANDPPT_API_KEYS`  
> - 勿将真实密钥提交到 Git  

---

## 快速开始

### 系统要求

- Python 3.11+  
- SQLite 3（本地默认）  
- ffmpeg（讲解视频导出需要）  
- Docker（可选）  

### 数据库迁移

- 默认启动时自动检测并执行迁移；可用 `LANDPPT_AUTO_MIGRATE_ON_STARTUP=false` 关闭  
- 本地默认 SQLite；仅在设置 `DATABASE_URL` 时切换到 PostgreSQL 等  
- 多节点共享同一数据库时，建议关闭自动迁移，改为单独跑一次迁移作业  

升级到模板包功能需要迁移 `019`，它会为旧模板补充类型字段并创建包版本等表，保留已有模板。仅创建表不能更新已有表的字段。关闭启动迁移时，请在启动新版本前执行：

```bash
uv run python -m landppt.cli migrate
# 已运行的 Compose 部署：
# docker compose exec landppt python -m landppt.cli migrate
```

仓库的 Argo CD 配置会先准备数据库与配置，再执行迁移 Job，成功后才更新 Web / Worker；请使用完整应用同步。迁移失败排查及 Helm 配置见 [部署说明](deploy/README.md#helm-and-argo-cd)。

### 方式一：uv（推荐本地）

```bash
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

# 安装 uv（如未安装）
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 前端需要 Node.js 22.12+；先编译 Ant Design 页面资源
npm ci --prefix frontend
npm run build --prefix frontend

uv sync --extra dev
cp .env.example .env
# 编辑 .env，至少配置一个 AI API Key

# 默认 :8000，SQLite + 内存缓存
uv run python run.py
```

### 方式二：pip

```bash
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

python -m venv venv
# Windows: venv\Scripts\activate
# macOS / Linux: source venv/bin/activate

npm ci --prefix frontend
npm run build --prefix frontend
pip install -e .
cp .env.example .env
# 编辑 .env，配置 AI API Key

python run.py
```

### 方式三：Docker 单容器

```bash
docker pull bradleylzh/landppt:latest

docker run -d \
  --name landppt \
  -p 8000:8000 \
  -v $(pwd)/.env:/app/.env \
  -v landppt_data:/app/data \
  -v landppt_uploads:/app/uploads \
  -v landppt_reports:/app/research_reports \
  -v landppt_cache:/app/temp \
  -v landppt_lib:/app/lib \
  bradleylzh/landppt:latest

docker logs -f landppt
```

> 运行前请先创建并配置 `.env`（至少包含 AI API Key）。

### 方式四：Docker Compose（推荐生产）

仓库内 `docker-compose.yml` 会启动 **landppt（Web）+ worker + PostgreSQL + Valkey + MinIO + pptx-renderer**（`minio-init` 自动建桶），适合多用户与后台任务。本地轻量体验仍推荐直接 `python run.py`。

```bash
cp .env.example .env
# 至少配置：AI Key、SECRET_KEY、POSTGRES_PASSWORD

docker compose up -d
docker compose logs -f landppt
```

- 访问：`http://localhost:8000`（可用 `LANDPPT_PORT` 修改）  
- MinIO 控制台：`http://localhost:9001`  
- 生产默认关闭管理员自动初始化；首次部署请设置 `LANDPPT_BOOTSTRAP_ADMIN_ENABLED=true` 及对应账号密码  
- 镜像默认 `bradleylzh/landppt:latest`，可用 `LANDPPT_IMAGE` 覆盖  
- PPTX 渲染镜像可用 `LANDPPT_PPTX_RENDERER_IMAGE` 覆盖；匹配版本与 Helm/Argo CD 配置见 [部署说明](deploy/README.md)。

Web、Worker 和渲染器通过共享目录交换 PPTX 渲染任务，渲染器无需开放 HTTP 端口。生产 Compose 使用已发布镜像，开发 Compose 本地构建渲染器。源码或单容器部署需要另行启动 [独立渲染器](docker-compose-pptx-renderer.yaml)，让应用的 `LANDPPT_PPTX_RENDER_SPOOL` 指向同一目录，并对齐目录权限和容器用户。

### 方式五：开发热重载

```bash
cp .env.example .env

# 开发编排挂载本地源码，需要本地编译前端资源（Node.js 22.12+）
npm ci --prefix frontend
npm run build --prefix frontend
docker compose -f docker-compose-dev.yaml up -d --build
docker compose -f docker-compose-dev.yaml logs -f landppt
```

开发编排基于本地 Dockerfile 构建，挂载源码并热重载；默认初始化管理员 `admin` / `admin123`。

Ant Design 前端源码位于 `frontend/`，通过 Vite 编译到 `src/landppt/web/static/antd/`。修改前端时可运行 `npm run dev --prefix frontend` 持续编译，刷新浏览器查看变化。生成资源、依赖和回归截图不提交到 Git；Docker 在构建阶段自动编译，运行镜像不需要 Node.js。发布 Python wheel/sdist 前先执行前端构建，发布包会包含编译资源。

前端回归使用隔离的 API 数据，不写入真实项目、账户或积分；先构建资源并安装 Chromium，然后执行：

```bash
uv run --extra dev python -m playwright install chromium
uv run --extra dev pytest tests/test_app_ui.py tests/test_antd_ui.py tests/test_antd_projects_ui.py tests/test_antd_account_ui.py tests/test_antd_admin_ui.py tests/test_antd_admin_management_ui.py tests/test_antd_community_ui.py tests/test_antd_images_ui.py tests/test_antd_templates_ui.py tests/test_antd_creation_research_ui.py tests/test_antd_home_generator_ui.py tests/test_antd_presentation_ui.py tests/test_antd_todo_ui.py tests/test_antd_editor_ui.py tests/test_antd_remaining_ui.py tests/test_template_package_workspace_ui.py -q
```

---

## 使用指南

### 1. 访问服务

启动后：

| 入口 | 地址 |
|------|------|
| Web 界面 | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

本地 / 开发环境常会自动初始化管理员（`admin` / `admin123`），由 `LANDPPT_BOOTSTRAP_ADMIN_*` 控制。**生产请务必改密或关闭自动初始化。**

### 2. 配置 AI 提供商

在设置页或 `.env` 中配置：

- OpenAI API Key（兼容 DeepSeek、Moonshot、Qwen 等 OpenAI 协议接口）  
- Anthropic / Google API Key  
- 或本地 Ollama  

### 3. 创建 PPT 项目

1. **需求确认**：主题、受众、页数、场景模板  
2. **大纲生成**：结构化大纲 + 可视化编辑  
3. **内容研究**（可选）：深度研究补充最新信息  
4. **图像配置**（可选）：本地 / 网络 / AI 生成  
5. **PPT 生成**：基于大纲生成 HTML 演示文稿  

### 4. 编辑与导出

- 侧边栏 AI 对话改内容与样式，可上传图像作视觉参考  
- 生成演讲稿（DOCX / Markdown / PPT 备注）  
- 逐页讲解音频：Edge-TTS 或 ComfyUI Qwen3-TD（可上传参考音频）  
- 导出讲解视频（MP4，1080p，30/60fps，可选字幕）  
- 导出 PDF、HTML、**标准 PPTX**、**图片型 PPTX**、讲稿等  
- 一键公开分享（分享页支持讲解音频与字幕）  

### 5. 快速模式与模板包

1. 打开“模板管理 → 快速模式模板包”，或访问 `/global-master-templates?tab=packages`。
2. 添加内置包、导入已有包，或通过“从 PPTX 创建”“AI 创建模板包”制作草稿。
3. 在工作区预览、编辑名称和描述、调整页面，或用 AI 修改单页及整包；校验通过后发布。
4. 创建项目并确认大纲，在模板选择页选择“快速模式生成”和已发布版本，设置配图与图片上限，点击“使用此模板包快速生成”。
5. 生成后在编辑器中通过“内容与版式”修改文字、切换组件或替换图片，再使用现有导出和分享入口。

PPTX 的“视觉复刻”由 AI 参考原页图片重建可编辑版式，可能调整拥挤布局或简化装饰；“保留原稿底图”将复杂图形保留为固定背景，只替换确认的内容槽位。两种方式都需要提取到的可编辑文字，不保证对扫描图片或嵌入图表进行完整 OCR。当前支持 `.pptx` / `.potx` / `.ppsx`，文件最大 50 MB，每次最多选择 40 页。

### 6. 自动化接口

- API Key 鉴权，便于接入 CI、脚本、n8n 等  
- OpenAI 兼容：`/v1/chat/completions`、`/v1/completions`、`/v1/models`  
- 项目级导出 / 分享 / 讲稿接口，适合非浏览器工作流  

---

## 配置说明

完整变量见 [`.env.example`](.env.example)，高级项见 `src/landppt/core/config.py`。下面只列**最小可跑**与**生产必改**。

### 最小可跑（本地）

```bash
# 至少一个 AI 提供商
DEFAULT_AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
# 或 ANTHROPIC_API_KEY / GOOGLE_API_KEY / 本地 Ollama

HOST=0.0.0.0
PORT=8000

# 本地默认（可省略）
# DATABASE_URL=sqlite:///./landppt.db
# CACHE_BACKEND=memory
```

### 生产必改 / 强烈建议

```bash
SECRET_KEY=replace-with-long-random-string
POSTGRES_PASSWORD=replace-with-strong-password   # Compose 生产栈

LANDPPT_BOOTSTRAP_ADMIN_ENABLED=false            # 或 true + 自定义账号密码
# LANDPPT_BOOTSTRAP_ADMIN_USERNAME=...
# LANDPPT_BOOTSTRAP_ADMIN_PASSWORD=...

LANDPPT_API_KEY=replace-with-strong-random-key
# 或多密钥：LANDPPT_API_KEYS=admin:prod-key,robot:n8n-key

# 生产存储示例
# DATABASE_URL=postgresql://landppt:password@localhost:5432/landppt
# CACHE_BACKEND=valkey
# VALKEY_URL=valkey://localhost:6379
```

### 按需开启

```bash
# 角色级模型路由（控成本）
OUTLINE_MODEL_NAME=gpt-4o-mini
SLIDE_GENERATION_MODEL_NAME=gpt-4o
SPEECH_SCRIPT_MODEL_NAME=gpt-4o-mini

# 演示文稿研究（Parallel 无需密钥）
RESEARCH_PROVIDER=auto   # auto | parallel | tavily | searxng | both
# TAVILY_API_KEY=...
# SEARXNG_HOST=http://localhost:8888

# 图像服务（默认关闭）
ENABLE_IMAGE_SERVICE=true
PIXABAY_API_KEY=...
UNSPLASH_ACCESS_KEY=...
SILICONFLOW_API_KEY=...

# 标准可编辑 PPTX（商业许可）
APRYSE_LICENSE_KEY=...

# 讲解 TTS（可选 ComfyUI）
# COMFYUI_BASE_URL=http://127.0.0.1:8188
# COMFYUI_TTS_WORKFLOW_PATH=tests/Qwen3-TD-TTS.json

# 注册 / OAuth / 邮件 / 积分 / Turnstile
# ENABLE_USER_REGISTRATION=true
# GITHUB_OAUTH_ENABLED=false
# ENABLE_CREDITS_SYSTEM=false
```

**补充说明：**

- **标准 PPTX** 依赖 `APRYSE_LICENSE_KEY`；**图片型 PPTX**（`/api/projects/{project_id}/export/pptx-images`）不依赖 Apryse，更适合复杂 CSS/图标保真。  
- 反向代理后图片仍指向 `localhost` 时，请在 Web「应用配置」中设置正确的 **BASE_URL**，详见 [docs/base_url_configuration.md](docs/base_url_configuration.md)。  
- 讲解视频需要本机 / 容器内可用的 `ffmpeg`。  

---

## 常见问题

### Q: 支持哪些 AI 模型？

OpenAI GPT（及兼容接口）、Anthropic Claude、Google Gemini、Azure OpenAI、Ollama 本地模型等，可在配置页切换提供商。

### Q: 如何配置图像功能？

在 `.env` 中开启 `ENABLE_IMAGE_SERVICE=true`，并配置：

- Pixabay：`PIXABAY_API_KEY`  
- Unsplash：`UNSPLASH_ACCESS_KEY`  
- AI 生成：`SILICONFLOW_API_KEY` 或 `POLLINATIONS_API_KEY` 等  

### Q: 反向代理后图片链接异常？

未配置 `BASE_URL` 时，链接可能仍是 `localhost:8000`。

1. 打开 `https://your-domain.com/ai-config`  
2. 「应用配置」→「基础 URL (BASE_URL)」填入对外域名  
3. 保存  

### Q: 研究功能怎么用？

创建 PPT 时启用联网研究即可。新安装默认使用 `RESEARCH_PROVIDER=auto`：优先保留已配置的 Tavily / SearXNG，否则使用无需账号或 API Key 的免费 Parallel Search MCP。已有研究提供商选择保持不变；详见[提供商配置](RESEARCH_PROVIDERS.md)。

### Q: 支持纯本地部署吗？

支持。可用 Docker 或源码安装；推理侧可接 Ollama，无需外部大模型 API（研究 / 网络配图等能力仍可能需要外网）。

### Q: 标准 PPTX 和图片型 PPTX 怎么选？

| 类型 | 依赖 | 特点 |
|------|------|------|
| 标准 PPTX | `APRYSE_LICENSE_KEY` | 适合继续在 PowerPoint 中编辑 |
| 图片型 PPTX | 无 Apryse | 复杂版式保真更好，页内元素通常不可编辑 |

### Q: 快速模式需要单独配置 Jev 吗？

不需要。快速模式仍使用配置的 AI 模型生成内容，版式选择可使用现有模型或规则。需要专门的决策模型时，在“系统配置 → 决策模型配置”中设置协议、完整端点 URL、模型和密钥，并测试连接。

### Q: 升级后模板列表或模板包接口报 500？

先查看应用日志和迁移 Job 日志，确认迁移 `019` 已完成。旧库缺少 `template_kind` 等字段时，普通模板和模板包查询都会失败；按 [数据库迁移](#数据库迁移) 执行迁移，再重试接口。Argo CD 部署需要完整同步以执行迁移 hook，具体命令见 [部署说明](deploy/README.md#helm-and-argo-cd)。

### Q: 如何生成公开分享链接？

项目编辑页点击分享，或调用 `POST /api/projects/{project_id}/share/generate`。地址形如 `/share/{share_token}`；停用调用 `share/disable`。

### Q: 生产与开发编排如何选？

- **生产：** `docker compose up -d`（预构建镜像 + Web/Worker/Postgres/Valkey/MinIO/PPTX 渲染器）
- **开发：** `docker compose -f docker-compose-dev.yaml up -d --build`（本地构建 + 热重载）  

### Q: 讲解音频支持哪些方式？

默认 Edge-TTS；也可配置 ComfyUI Qwen3-TD，并在编辑页上传参考音频。

### Q: 并行生成会影响质量吗？

不会。并行只改变调度顺序，单页生成逻辑与质量不变。多数提供商支持并发，但受各自限流约束。

---

## 贡献指南

欢迎 Issue、PR 与文档改进。

1. Fork 本仓库  
2. 创建分支：`git checkout -b feature/AmazingFeature`  
3. 提交：`git commit -m 'Add some AmazingFeature'`  
4. 推送并开启 Pull Request  

问题反馈：[Issues](https://github.com/sligter/LandPPT/issues)

---

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。

> 导出标准 PPTX 所依赖的 Apryse 等第三方组件，遵循其各自许可条款；使用前请自行确认合规。

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=sligter/LandPPT&type=Date)](https://www.star-history.com/#sligter/LandPPT&Date)

---

## 联系我们

- **项目主页**：https://github.com/sligter/LandPPT  
- **问题反馈**：https://github.com/sligter/LandPPT/issues  
- **讨论区**：https://github.com/sligter/LandPPT/discussions  
- **邮件**： [ai@yydsapp.com](mailto:ai@yydsapp.com)  

---

<div align="center">

**如果这个项目对你有帮助，请点一个 :star:！**

Made with :heart: by the LandPPT Team

</div>
