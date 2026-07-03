# KickRSS - 智能自进化 PWA RSS 阅读器

**KickRSS** 是一款专为极客打造的、具备 AI 自动摘要、阅读行为追踪和智能自进化抽屉分类的渐进式 Web 应用 (PWA) RSS 阅读器。它采用极具科技感的赛博朋克玻璃拟物化 (Cyberpunk Glassmorphism) 视觉设计，支持全平台独立安装与手势操作。

---

## 🌟 核心特性

- **🤖 智能自进化分类**：基于大语言模型（LLM）对订阅源文章进行智能分类，随着您的阅读自动合并、重组或提升高频子主题为独立的分类抽屉。
- **📝 AI 自动摘要 & 对照翻译**：文章详情页支持一键/自动生成 AI 概要，并提供排版优雅的段落级中英/多语对照翻译与 AI 聊天对话。
- **📊 个人阅读画像可视化**：
  - **活跃度热力图**：直观展示您在不同时间段的阅读频次。
  - **12周趋势图**：跟踪您在不同话题上的兴趣随时间的变化。
  - **标签云**：多维度展示您的阅读偏好及关注强度。
- **📱 极致的 PWA 体验**：
  - 支持添加到主屏幕作为独立 App 运行，离线可用。
  - 顺滑的手势操作（如未读卡片向左划动直接标记已读）。
  - 下拉刷新订阅源列表和文章列表。
- **🛡️ 隐私至上**：您的阅读 dwell 时间、滚动比例、点击原文等行为数据仅加密存储在本地 SQLite 数据库中，不上传至任何第三方服务器。

---

## 🛠️ 技术栈

- **后端 (Backend)**: Python 3.11+ / FastAPI / SQLite / APScheduler / Trafilatura (网页正文提取)
- **前端 (Frontend)**: 原生 HTML5 / 现代 JS (ES6+) / 赛博朋克拟物 CSS3 / Service Worker (PWA 离线缓存)
- **AI 引擎 (AI Engine)**: 支持任何 OpenAI 兼容接口（如 Ollama 本地模型、DeepSeek、GPT 等）

---

## 🚀 快速开始

### 方式一：使用 Docker Compose / Portainer Stack 部署（推荐 ⭐）

我们提供了预编译托管镜像，可实现开箱即用、一键拉取部署，无需本地下载源码或编译。

1. **创建配置文件和挂载目录**：
   在宿主机上创建数据持久化目录（例如 `/home/bemoon/kickRSS/data` 或您自定义的路径）：
   ```bash
   mkdir -p /home/bemoon/kickRSS/data
   ```

2. **编写 docker-compose.yml**：
   在部署目录（或 Portainer Stack 编辑器）中写入以下配置：
   ```yaml
   version: '3.8'
   services:
     kickrss:
       image: ghcr.io/bemoons/kickrss:latest  # 直接使用云端自动构建的预编译镜像
       container_name: kickrss
       network_mode: host
       restart: unless-stopped
       volumes:
         - /home/bemoon/kickRSS/data:/app/data
       environment:
         - PORT=8888
         - TZ=Asia/Shanghai
   ```

3. **启动容器**：
   直接运行以下命令（或在 Portainer 界面点击 Deploy Stack）：
   ```bash
   docker compose up -d
   ```
   *首次启动时，系统会自动在挂载的 `data` 目录下初始化生成 `config.yaml` 配置文件及 `myrss.db` 数据库。*

4. **修改配置**：
   编辑挂载目录下的 `config.yaml` 配置文件（参考下文配置 AI 密钥），然后重启容器即可生效：
   ```bash
   docker compose restart
   ```

5. **访问服务**：
   在浏览器中打开 `http://<您的服务器IP>:8888` 即可开始使用。

---

### 方式二：本地直接运行 (开发调试)

1. **克隆项目并进入目录**：
   ```bash
   git clone <你的仓库地址>
   cd myRSS
   ```

2. **创建并激活虚拟环境**：
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windows 下使用: .venv\Scripts\activate
   ```

3. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```

4. **准备配置文件**：
   将配置模板复制为本地配置文件：
   ```bash
   cp config.yaml.example config.yaml
   ```
   然后打开 `config.yaml` 填写您的 AI 端点地址和 API Key。

5. **启动应用**：
   ```bash
   python main.py
   ```

---

## ⚙️ 配置文件说明 (`config.yaml`)

打开 `config.yaml` 或 `./data/config.yaml`，核心可配置项如下：

```yaml
# 数据库路径 (Docker 下请保持为 data/myrss.db 以持久化)
db_path: myrss.db

# 服务监听端口
port: 8888

# 订阅源抓取周期 (分钟)
fetch_interval_minutes: 15

# 🤖 默认 AI 大模型接口配置
ai:
  default:
    base_url: https://api.openai.com/v1   # API 端点地址 (支持 Ollama 或任意 OpenAI 兼容服务)
    api_key: your-api-key-here           # 您的 API Key
    model: gpt-4o-mini                    # 使用的 AI 模型名称
  pregenerate: false                      # 是否在后台精读文章时预生成摘要
  stream: true                            # 是否流式打字输出摘要和聊天内容
  auto_summary: true                      # 点击文章时是否自动开始生成摘要
  summary_language: zh                    # 摘要和翻译的目标语言 (zh/en/ja等)

# 🧠 全文判定和分类阈值
fulltext:
  min_text_chars: 200                     # 判定为全文的最小字符长度
classify:
  promote_threshold: 5                    # 未归类主题自动提升为独立分类抽屉的频次门槛

interest_profile_enabled: true            # 是否开启个性化阅读画像提炼 (每日自动消耗 Token 分析阅读偏好)
```

---

## 📂 项目文件组织结构

```text
.
├── main.py                  # FastAPI 主程序及 API 端点
├── db.py                    # 数据库初始化及连接池
├── crud.py                  # 数据库增删改查操作
├── maintenance.py           # 每日自动清理、自进化分类与画像计算任务
├── ingester.py              # RSS/Atom 抓取器
├── extractor.py             # 网页正文提取器
├── classifier.py            # AI 分桶及分级引擎
├── config.py                # 环境变量与 YAML 配置管理器
├── static/                  # 前端静态资源 (HTML, CSS, JS, Service Worker)
├── Dockerfile               # Docker 镜像构建文件
├── docker-entrypoint.sh     # Docker 初始化入口脚本
├── docker-compose.yml       # Docker 容器编排配置
├── config.yaml.example      # 配置文件模板 (供发布 GitHub)
└── .gitignore               # Git 忽略文件配置
```

---

## 🛡️ 开源协议

本项目采用 MIT 协议开源。欢迎提交 Issue 和 Pull Request！
