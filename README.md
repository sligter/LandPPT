# LandPPT - AI驱动的PPT生成平台

[![GitHub stars](https://img.shields.io/github/stars/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/network)
[![GitHub issues](https://img.shields.io/github/issues/sligter/LandPPT?style=flat-square)](https://github.com/sligter/LandPPT/issues)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg?style=flat-square)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/docker-supported-blue.svg?style=flat-square)](https://hub.docker.com/r/bradleylzh/landppt)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/sligter/LandPPT)

---

##  Open to Opportunities

如果你对我的项目感兴趣，欢迎联系我！

[![Email](https://img.shields.io/badge/_Email-ai%40yydsapp.com-blue?style=for-the-badge)](mailto:ai@yydsapp.com)

---


[English](README_EN.md) | **中文**

---

##  目录

- [项目简介](#-项目简介)
- [功能亮点](#-功能亮点)
- [核心功能](#-核心功能)
- [快速开始](#-快速开始)
- [使用指南](#-使用指南)
- [配置说明](#-配置说明)
- [API文档](#-api文档)
- [技术栈](#-技术栈)
- [常见问题](#-常见问题)
- [许可证](#-许可证)

<div align="center">
  <img src="https://img.pub/p/e810c5680509b4f051a5.png" width="180" alt="LandPPT Logo" />
  <p>
    <b>基于大语言模型（LLM）的智能演示文稿生成平台</b>
  </p>
</div>

LandPPT 是一个基于大语言模型（LLM）的智能演示文稿生成平台，能够自动将文档内容转换为专业的PPT演示文稿。平台集成了多种AI模型、智能图像处理、深度研究功能和丰富的模板系统，让用户能够轻松创建高质量的演示文稿

[文档指南](http://landppt-doc.52yyds.top/docs)

### 主界面

![image](https://img.pub/p/3accad83a8b624d7cb19.png)

![image](https://img.pub/p/7d5c3c1a4b625abeb4c1.png)

### 生成大纲

![image](https://img.pub/p/a31e4f94c5d2bd577d8d.png)

### 生成效果

![image](https://img.pub/p/e6cffa89a2b532a8514b.png)

![image](https://img.pub/p/9a38b57c6f5f470ad59b.png)

### 在线编辑
![image](https://img.pub/p/6d357a847626f1a55c13.png)

![image](https://img.pub/p/42f84b07850f5aa4aebb.png)

![image](https://img.pub/p/8dccee74d0b85893bd38.png)

![image](https://img.pub/p/aaf483b2507a57db8b35.png)

### 讲稿生成
![image](https://img.pub/p/c53b752e0a6833c0ee87.png)

### 导出效果
![image](https://img.pub/p/62694101810bfa472db9.png)

### 模板生成
![image](https://img.pub/p/892622b3f3cc0d6ad843.png)

##  功能亮点

- **一键生成**：从主题到完整PPT，全程AI自动化处理
- **智能配图**：AI自动匹配最适合的图像，支持多源获取和参考图片生成
- **TODO 任务板**：全新交互式任务管理界面，实时追踪生成进度，支持复杂动画反馈
- **深度研究**：集成多个搜索引擎，获取最新最全面的信息
- **并行生成**：支持幻灯片内容并行生成，配合增强型 AI 服务显著提升构建速度
- **演讲稿生成**：智能生成配套演讲稿，支持多种导出格式
- **语音讲解与视频导出**：基于 Edge-TTS 生成逐页讲解音频，支持与幻灯片同步播放，并可导出讲解视频（1080p 30/60fps，字幕可嵌入）
- **视觉参考**：AI编辑助手支持图像上传和视觉内容分析
- **多文件上传**：支持同时上传多个文件，批量处理更高效
- **模型自定义**：按功能自定义模型选择，精准控制成本
- **公开分享与全屏播放**：一键生成分享链接，分享页支持公开浏览、全屏放映、讲解音频与字幕联动
- **双路 PPTX 导出**：支持标准 PPTX 导出（Apryse）和图片型 PPTX 导出（复杂 HTML/CSS 样式更高保真）
- **自动化调用**：内置 OpenAI 兼容 API 与项目 REST API，支持 n8n、CI、脚本和 API Key 鉴权调用
- **账号体系**：支持本地账号、GitHub OAuth、Linux Do OAuth、忘记密码、邮件验证码和注册限流
- **备注导出**：支持将演讲稿导出至PPT备注栏
- **图片导出**：支持以图片格式导出PPT页面
- **企业级安全**：支持本地部署，数据安全可控

##  核心功能

###  多AI提供商支持
- **OpenAI GPT系列**：GPT-4o、GPT-4o-mini 等模型
- **OpenAI兼容平台 / 302.AI**：支持 DeepSeek、Moonshot、Qwen 等兼容 OpenAI 协议的模型与中转平台
- **Anthropic Claude**：Claude-4 Sonnet、Claude-4 Haiku 系列模型
- **Google Gemini**：Gemini-2.5 Flash、Gemini-2.5 Pro 系列模型，支持自定义端点配置
- **Azure OpenAI**：企业级AI服务，支持自定义部署
- **Ollama**：本地部署的开源模型，支持 Llama、Mistral 等

###  强大的文件处理能力
- **多格式支持**：PDF、Word、Markdown、TXT、Excel、PowerPoint 等多种格式
- **智能解析**：使用 MinerU 和 MarkItDown 进行高质量内容提取
- **深度研究**：集成 Tavily API 和 SearXNG 的多源研究功能
- **内容增强**：自动网页内容提取和智能摘要生成

###  智能图像处理系统
- **多源图像获取**：本地图库、网络搜索、AI生成三合一
- **网络图像搜索**：支持 Pixabay、Unsplash 等图库
- **AI图像生成**：集成 DALL-E、SiliconFlow、Pollinations、 Openai、Gemini等服务
- **智能图像选择**：AI自动匹配最适合的图像内容
- **图像处理优化**：自动尺寸调整、格式转换、质量优化

###  增强研究功能
- **多引擎搜索**：Tavily 和 SearXNG 双引擎支持
- **深度内容提取**：智能网页内容解析和结构化处理
- **多语言支持**：支持中英文等多语言研究内容
- **实时信息获取**：获取最新的网络信息和数据

###  丰富的模板系统
- **全局主模板**：统一的HTML模板系统，支持响应式设计
- **多样化布局**：AI生成多种创意页面布局和设计风格
- **场景化模板**：通用、旅游、教育等多种专业场景模板
- **项目适配模板**：新增针对项目的适配模板生成
- **参考PPTX提取**：支持上传参考 PPTX 抽取版式/风格并生成模板
- **自由模板模式**：项目级 AI 自适应模板，可结合参考图和主题自动生成专属模板
- **自定义模板**：支持导入和创建个性化模板
- **参考图片生成**：AI模板生成支持参考图片，智能匹配设计风格

###  完整的项目管理
- **四阶段工作流**：需求确认  大纲生成  TODO 进度追踪  PPT生成
- **TODO 任务看板**：集成式任务管理，实时显示生成状态、日志与动画
- **阶段重跑与恢复**：支持从指定阶段重新开始工作流，便于修订大纲或重生成内容
- **公开分享管理**：项目支持生成、停用和查询分享链接，便于外部查看与演示
- **可视化编辑**：直观的大纲编辑器和实时预览
- **批量操作**：支持批量生成和处理多个项目

###  现代化Web界面
- **直观操作**：用户友好的响应式Web界面
- **AI聊天编辑**：侧边栏AI编辑功能，支持实时对话和视觉参考
- **演讲稿生成**：支持单页/多页/全部幻灯片的演讲稿生成，导出为DOCX/Markdown格式
- **全屏放映模式**：支持讲解音频、字幕、自动翻页和分享页播放
- **多格式导出**：PDF/HTML/标准 PPTX/图片型 PPTX/讲稿 DOCX/Markdown 多种格式导出支持
- **实时预览**：16:9 标准比例的实时页面预览

###  平台与运维能力
- **Docker / Docker Compose**：同时提供单容器运行和 `docker-compose.yml` / `docker-compose-dev.yaml` 多服务编排
- **PostgreSQL + Valkey**：生产编排内置数据库与缓存/任务协调服务，适合多用户与后台任务场景
- **后台任务系统**：PDF/PPTX/讲解视频等长任务异步执行，支持任务轮询与多 Worker 容错
- **自动数据库迁移**：应用启动时自动执行迁移，并在首次启动时导入默认模板
- **OpenAI 兼容接口**：提供 `/v1/chat/completions`、`/v1/completions`、`/v1/models`
- **可选商业化模块**：支持积分系统、SMTP/Resend、注册限流与 Cloudflare Turnstile

##  快速开始

### 系统要求
- Python 3.11+
- SQLite 3
- ffmpeg（讲解视频导出需要）
- Docker (可选)

### 数据库迁移（自动）
- 默认启动时会自动检测并执行数据库迁移（与用户无关），可通过环境变量关闭：`LANDPPT_AUTO_MIGRATE_ON_STARTUP=false`
- 本地默认启动使用 SQLite；只有在显式设置 `DATABASE_URL` 时才切换到 PostgreSQL 等外部数据库
- 多容器/多节点共享同一个数据库时，建议关闭自动迁移，改为单独运行一次迁移作业

### 本地安装

#### 方法一：uv（推荐）

```bash
# 克隆项目
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

# 安装uv（如果尚未安装）
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 使用uv同步开发/测试环境
uv sync --extra dev

# 仅运行测试时，也可以只安装测试依赖
# uv sync --extra test

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置你的AI API密钥

# 启动服务（默认监听 8000，默认使用 SQLite + memory cache，无需 PostgreSQL / Valkey）
uv run python run.py

# 运行测试（示例）
uv run --extra dev pytest tests/test_creative_guidance_defaults.py

# 如果是升级版本：启动后执行数据库迁移（包含讲解音频/视频功能）
# 方式一：直接在本机执行（无需HTTP认证）
# python -c "import asyncio; from landppt.database.migrations import migration_manager; asyncio.run(migration_manager.migrate_up())"
# 方式二：通过HTTP接口（需要登录后的 session_id Cookie）
# 1) 获取 session_id: curl -X POST -d "username=YOUR_USER&password=YOUR_PASS" http://localhost:8000/api/auth/login
# 2) 执行迁移: curl -X POST -H "Cookie: session_id=YOUR_SESSION_ID" http://localhost:8000/api/database/migrations/run
```

#### 方法二：传统pip安装

```bash
# 克隆项目
git clone https://github.com/sligter/LandPPT.git
cd LandPPT

# 创建虚拟环境
python -m venv venv
# 激活虚拟环境
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 安装依赖
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置你的AI API密钥

# 启动服务（默认监听 8000，默认使用 SQLite + memory cache，无需 PostgreSQL / Valkey）
python run.py
```

### Docker部署

#### 使用预构建镜像（推荐）

```bash
# 拉取最新镜像
docker pull bradleylzh/landppt:latest

# 运行容器
docker run -d \
  --name landppt \
  -p 8000:8000 \
  -v $(pwd)/.env:/app/.env \
  -v landppt_data:/app/data \
  -v landppt_reports:/app/research_reports \
  -v landppt_cache:/app/temp \
  bradleylzh/landppt:latest

# 查看日志
docker logs -f landppt
```

> **注意**: 确保在运行前创建并配置好 `.env` 文件，包含必要的API密钥。

#### 使用 Docker Compose（推荐生产部署）

仓库内自带 `docker-compose.yml`，会同时启动 `landppt + PostgreSQL + Valkey`，适合多用户、后台任务和长期运行场景。若只是本地单机体验，直接运行 `python run.py` / `uv run python run.py` 即可，默认会使用 SQLite + memory cache，无需额外依赖。

```bash
# 准备配置
cp .env.example .env
# 至少补充 AI Key、SECRET_KEY、POSTGRES_PASSWORD

# 启动生产编排
docker compose up -d --build

# 查看日志
docker compose logs -f landppt
```

默认访问地址：`http://localhost:6003`

#### 开发模式（热重载）

开发编排使用 `docker-compose-dev.yaml`，挂载源码目录并启用热重载，适合本地调试。

```bash
cp .env.example .env
docker compose -f docker-compose-dev.yaml up -d --build
docker compose -f docker-compose-dev.yaml logs -f landppt-dev
```

默认访问地址：`http://localhost:8001`

##  使用指南

### 1. 访问Web界面
启动服务后，访问以下地址：
- **Web界面**: http://localhost:8000
- **API文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

默认不会自动创建管理员账号；如需初始化管理员，请显式配置 `LANDPPT_BOOTSTRAP_ADMIN_ENABLED=true`、`LANDPPT_BOOTSTRAP_ADMIN_USERNAME` 和 `LANDPPT_BOOTSTRAP_ADMIN_PASSWORD`。

### 2. 配置AI提供商
在设置页面配置你的AI API密钥：
- OpenAI API Key(支持openai 兼容model api，例如deepseek、moonshot、qwen等等)
- Anthropic API Key
- Google API Key
- 302.AI API Key
- 或配置本地Ollama服务

### 3. 创建PPT项目
1. **需求确认**：输入主题、选择受众、设置页数范围、选择场景模板
2. **大纲生成**：AI智能生成结构化大纲，支持可视化编辑
3. **内容研究**：可选择启用深度研究功能，获取最新相关信息
4. **图像配置**：配置图像获取方式（本地/网络/AI生成）
5. **PPT生成**：基于大纲生成完整的HTML演示文稿

### 4. 编辑和导出
- 使用AI聊天功能实时编辑内容和样式，支持图像上传进行视觉参考
- 支持图像替换和优化，AI模板生成可参考上传的图片
- 生成配套演讲稿，支持单页/多页/全部幻灯片模式
- 生成逐页讲解音频，支持 Edge-TTS 或 ComfyUI Qwen3-TD，并可上传参考音频
- 导出讲解视频（MP4），支持 1080p、30/60fps 与字幕嵌入
- 导出为PDF、HTML、标准 PPTX、图片型 PPTX、演讲稿 DOCX/Markdown 格式
- 支持一键生成公开分享链接，并在分享页中播放讲解音频与字幕
- 保存项目版本和历史记录
- 支持批量处理和模板复用

### 5. 自动化与开放接口
- 支持通过 API Key 将项目流程接入 n8n、CI、脚本和自定义后端
- 提供 OpenAI 兼容接口：`/v1/chat/completions`、`/v1/completions`、`/v1/models`
- 提供项目级导出/分享/讲稿接口，适合非浏览器自动化工作流

##  配置说明

### 环境变量配置

主要配置项（常用项见 `.env.example`，高级项可参考 `src/landppt/core/config.py`）：

```bash
# AI提供商配置
DEFAULT_AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GOOGLE_API_KEY=your_google_api_key_here
GOOGLE_BASE_URL=https://generativelanguage.googleapis.com  # 自定义Gemini端点

# 角色级模型路由（可选）
OUTLINE_MODEL_PROVIDER=openai
OUTLINE_MODEL_NAME=gpt-4o-mini
SLIDE_GENERATION_MODEL_PROVIDER=openai
SLIDE_GENERATION_MODEL_NAME=gpt-4o
EDITOR_ASSISTANT_MODEL_PROVIDER=openai
TEMPLATE_GENERATION_MODEL_PROVIDER=openai
SPEECH_SCRIPT_MODEL_PROVIDER=openai
SPEECH_SCRIPT_MODEL_NAME=gpt-4o-mini

# 服务器配置
HOST=0.0.0.0
PORT=8000
SECRET_KEY=your-secure-secret-key
WORKERS=2
RELOAD=false

# 研究功能配置
TAVILY_API_KEY=your_tavily_api_key_here        # Tavily 搜索引擎
TAVILY_BASE_URL=https://gateway.example.com/tavily # 可选：自定义 Tavily 网关/代理地址
SEARXNG_HOST=http://localhost:8888             # SearXNG 实例地址
RESEARCH_PROVIDER=tavily                       # 研究提供商：tavily, searxng, both

# 图像服务配置
ENABLE_IMAGE_SERVICE=true                      # 启用图像服务
IMAGE_USER_STORAGE_QUOTA_MB=100                # 单用户图床存储上限(MB)，<=0 表示不限制
PIXABAY_API_KEY=your_pixabay_api_key_here     # Pixabay 图库
UNSPLASH_ACCESS_KEY=your_unsplash_key_here    # Unsplash 图库
SILICONFLOW_API_KEY=your_siliconflow_key_here # AI图像生成
POLLINATIONS_API_KEY=your_pollinations_api_key_here # Pollinations AI (gen.pollinations.ai)

# 自动化鉴权
LANDPPT_API_KEY=replace-with-strong-random-key
LANDPPT_API_KEYS=admin:prod-key,robot:n8n-key
LANDPPT_BOOTSTRAP_ADMIN_ENABLED=false
LANDPPT_ENABLE_API_DOCS=true
LANDPPT_ALLOW_HEADER_SESSION_AUTH=false

# 存储 / 缓存
DATABASE_URL=sqlite:///./landppt.db
CACHE_BACKEND=memory
VALKEY_URL=valkey://localhost:6379
# 生产部署示例：
# DATABASE_URL=postgresql://landppt:password@localhost:5432/landppt
# CACHE_BACKEND=valkey

# 导出功能配置
APRYSE_LICENSE_KEY=your_apryse_key_here       # PPTX导出
COMFYUI_BASE_URL=http://127.0.0.1:8188        # ComfyUI TTS
COMFYUI_TTS_WORKFLOW_PATH=tests/Qwen3-TD-TTS.json

# 注册 / OAuth / 邮件
EMAIL_PROVIDER=smtp
ENABLE_USER_REGISTRATION=true
GITHUB_OAUTH_ENABLED=false
LINUXDO_OAUTH_ENABLED=false
ENABLE_CREDITS_SYSTEM=false
TURNSTILE_ENABLED=false

# 生成参数
MAX_TOKENS=8192
TEMPERATURE=0.7
```

##  API文档

启动服务后访问：
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### 自动化调用鉴权（推荐 API Key）

非浏览器自动化（CI 任务）支持两种方式：
1. 全局 `.env` API Key
2. 用户自定义 API Key（推荐多用户场景）

#### 方式 A：全局 `.env` API Key

在 `.env` 中配置：

```bash
LANDPPT_API_KEY=replace-with-strong-random-key
LANDPPT_API_KEY_USER=admin

# 或者使用多 Key 绑定模式
LANDPPT_API_KEYS=admin:prod-key,robot:workflow-key
```

请求头使用以下任一方式：

- `Authorization: Bearer <LANDPPT_API_KEY>`
- `X-API-Key: <LANDPPT_API_KEY>`

示例：

```bash
curl -X GET "http://localhost:8000/api/projects" \
  -H "Authorization: Bearer replace-with-strong-random-key"
```

#### 方式 B：用户自定义 API Key（后续调用无需登录）

1. 先使用你的管理员账号登录一次获取 `session_id`（管理员可通过 `LANDPPT_BOOTSTRAP_ADMIN_*` 环境变量显式初始化，或在 Web 界面中自行创建）：

```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -d "username=<your-admin-username>" \
  -d "password=<your-admin-password>"
```

2. 创建/轮换当前用户 API Key（支持自定义 key）：

```bash
curl -X POST "http://localhost:8000/api/auth/api-keys" \
  -H "X-Session-Id: <session_id>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"n8n\",\"api_key\":\"your-own-strong-api-key-123456\"}"
```

3. 后续直接用该 key 调受保护接口（无需再登录）：

```bash
curl -X GET "http://localhost:8000/api/projects" \
  -H "Authorization: Bearer your-own-strong-api-key-123456"
```

可用管理接口：
- `GET /api/auth/api-keys`：查看当前用户 API Keys
- `DELETE /api/auth/api-keys/{key_id}`：删除指定 API Key

补充说明：
- `LANDPPT_ALLOW_HEADER_SESSION_AUTH` 默认关闭；只有显式设置为 `true` 时，才支持通过 `X-Session-Id` 头在非浏览器客户端传递会话。
- 全局 Key 适合服务到服务调用；用户自定义 Key 更适合多租户或个人自动化流程。
- `LANDPPT_ENABLE_API_DOCS=true` 时可访问 `/docs`、`/redoc` 和 `/openapi.json`；默认值已开启。

### OpenAI 兼容接口

- `POST /v1/chat/completions`
- `POST /v1/completions`
- `GET /v1/models`

##  技术栈

### 后端技术
- **FastAPI**: 现代化的Python Web框架，支持异步处理
- **SQLAlchemy**: ORM数据库操作，支持多种数据库
- **Pydantic**: 数据验证和序列化，类型安全
- **Uvicorn**: 高性能ASGI服务器
- **PostgreSQL / SQLite**: 兼顾生产部署与本地开发
- **Valkey**: 缓存、任务协调与多 Worker 场景支持

### AI集成
- **OpenAI**: GPT-4o、GPT-4o-mini 等最新模型
- **Anthropic**: Claude-4.5 系列模型
- **Google AI**: Gemini-2.5 系列模型
- **LangChain**: AI应用开发框架和工具链
- **Ollama**: 本地模型部署和管理

### 文件处理
- **MinerU**: 高质量PDF智能解析和结构化提取
- **MarkItDown**: 多格式文档转换（Word、Excel、PowerPoint等）
- **BeautifulSoup4**: HTML/XML解析和处理

### 图像处理
- **Pillow**: 图像处理和格式转换
- **OpenAI DALL-E**: AI图像生成
- **SiliconFlow**: 国产AI图像生成服务
- **Pollinations**: 开源AI图像生成平台

### 研究功能
- **Tavily**: 专业搜索引擎API
- **SearXNG**: 开源元搜索引擎
- **Playwright**: 网页内容提取

### 导出功能
- **Playwright**: HTML转PDF高质量导出
- **Apryse SDK**: 专业PPT生成和转换
- **python-pptx / dom-to-pptx**: 图片型 PPTX 导出与讲稿备注写入
- **Edge-TTS / ComfyUI / FFmpeg**: 讲解音频、字幕与视频导出链路

##  贡献指南

欢迎所有形式的贡献！

### 如何贡献
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

详情请见 [贡献指南](CONTRIBUTING.md)。

### 报告问题
如果你发现了bug或有功能建议，请在 [Issues](https://github.com/sligter/LandPPT/issues) 页面创建新的issue。

## 项目管理流程
项目已补充“阶段可重开（阶段完成后可回到该阶段重新确认并重执行）”流程，适用于 `/app/LandPPT` 的阶段管理与回归控制。详见：[`docs/project-management/stage-reentry-workflow.md`](docs/project-management/stage-reentry-workflow.md)。

##  常见问题

### Q: 支持哪些AI模型？
A: 支持 OpenAI GPT(兼容)、Anthropic Claude、Google Gemini、等模型。可以在配置页面切换不同的AI提供商。

### Q: 如何配置图像功能？
A: 在 `.env` 文件中配置相应的API密钥：
- Pixabay: `PIXABAY_API_KEY`
- Unsplash: `UNSPLASH_ACCESS_KEY`
- AI生成: `SILICONFLOW_API_KEY` 或 `POLLINATIONS_API_KEY`

### Q:在使用反向代理（如Nginx、Apache等）时，如果没有正确配置`base_url`，会出现以下问题：
- 图片链接仍然显示为`localhost:8000`
- 前端无法正确加载图片
- 图片预览、下载等功能异常

A:  通过Web界面配置

1. 访问系统配置页面：`https://your-domain.com/ai-config`
2. 切换到"应用配置"标签页
3. 在"基础URL (BASE_URL)"字段中输入您的代理域名
4. 例如：`https://your-domain.com` 或 `http://your-domain.com:8080`
5. 点击"保存应用配置"

### Q: 研究功能如何使用？
A: 配置 `TAVILY_API_KEY` 或部署 SearXNG 实例，然后在创建PPT时启用研究功能即可自动获取相关信息。

### Q: 支持本地部署吗？
A: 完全支持本地部署，可以使用 Docker 或直接安装。支持 Ollama 本地模型，无需依赖外部API。

### Q: 如何导出PPTX格式？
A: 需要配置 `APRYSE_LICENSE_KEY`，然后在导出选项中选择PPTX格式。

### Q: 如何选择标准 PPTX 和图片型 PPTX？
A: 标准 PPTX 依赖 `APRYSE_LICENSE_KEY`，导出后更适合继续编辑；图片型 PPTX 通过截图嵌入页面，复杂 CSS、图标和特殊排版保真更高，但页内元素通常不可再编辑。

### Q: 如何生成公开分享链接？
A: 可在项目编辑页点击分享，或调用 `POST /api/projects/{project_id}/share/generate`。分享地址格式为 `/share/{share_token}`，需要停用时调用 `share/disable` 即可。

### Q: 如何启用开发模式或生产编排？
A: 生产环境推荐 `docker compose up -d --build` 使用仓库内的 `docker-compose.yml`；开发调试推荐 `docker compose -f docker-compose-dev.yaml up -d --build`，默认启用源码挂载和热重载。

### Q: 讲解音频支持哪些方式？
A: 默认支持 Edge-TTS；也可以配置 ComfyUI Qwen3-TD，并在项目编辑页上传参考音频做语音克隆。

### Q: 并行生成会影响PPT质量吗？
A: 不会。并行生成只是改变了生成顺序，每页的生成逻辑和质量保持不变。

### Q: 所有AI提供商都支持批量生成吗？
A: 大多数AI提供商支持并发请求，但可能有不同的限制。建议查看您使用的AI服务的API文档。

##  许可证

本项目采用 Apache License 2.0 许可证。详情请见 [LICENSE](LICENSE) 文件。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=sligter/LandPPT&type=Date)](https://www.star-history.com/#sligter/LandPPT&Date)

##  联系我们

- **项目主页**: https://github.com/sligter/LandPPT
- **问题反馈**: https://github.com/sligter/LandPPT/issues
- **讨论区**: https://github.com/sligter/LandPPT/discussions

<a href="https://jsd.onmicrosoft.cn/gh/mydracula/image@master/20260413/052dae6fa31246aab7c34ada2ba32a84.jpg">LandPPT</a>
---

<div align="center">

**如果这个项目对你有帮助，请给我们一个  Star！**

Made with  by the LandPPT Team

</div>
