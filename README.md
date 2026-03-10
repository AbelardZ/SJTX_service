# SJTX Service - 量化与金融研究支撑系统

SJTX Service 是一个综合性的金融量化研究、自动化数据抓取、监控及智能分析系统。该系统集成了行情获取、策略研究、舆情监控以及 LLM (大语言模型) 深度分析等功能模块。

## 🚀 项目模块概览

本仓库包含以下核心子系统：

| 模块名称 | 描述 |
| :--- | :--- |
| **`Web/`** | 基于 Flask 的前端展示与管理后台。 |
| **`LLMAgent/`** | 智能研究助手。包含爬虫、RAG (检索增强生成) 知识库及个股深度研究逻辑。 |
| **`LLM_support/`** | 大模型支持模块，负责生成各类分析报告及 Prompt 管理。 |
| **`news_monitor/`** | 舆情/新闻实时监控与分类系统，集成 BERT 模型进行分类。 |
| **`dailychart/`** | 每日行情的抓取、存储、持久化管理及定时调度。 |
| **`shortstrategy/`** | 短线策略相关数据获取与分析工具。 |
| **`liuyao/`** | 传统文化分析实用工具 (六爻排盘及自动化分析)。 |
| **`user_management/`** | 用户中心与权限管理逻辑。 |

## 🛠️ 技术栈

- **后端**: Python, Docker
- **前端**: Flask (Web 模块)
- **数据库**: MySQL, SQLite
- **AI/NLP**: LLM (豆包/DeepSeek/OpenAI), RAG, BERT (舆情分类)
- **部署**: Docker Compose, Nginx

## 📦 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/AbelardZ/SJTX_service.git
cd SJTX_service
```

### 2. 配置环境
根据系统设计的 `.gitignore`，敏感配置文件未在版本库中。你需要手动根据各目录下的配置模板创建以下文件：
- `dailychart/db_config.py`
- `LLM_support/config.py`
- `news_monitor/config.py`

### 3. 使用 Docker 部署
系统已配置 `docker-compose.yml`，可一键启动核心服务（如 `Web` 端、数据库、Nginx 等）：
```bash
sudo docker-compose up -d
```

## 📂 目录结构说明

```text
SJTX_service/
├── Web/                # 控制台/Web 界面
├── LLMAgent/           # 智能助手与 RAG 核心
├── LLM_support/        # LLM 接口及报告生成逻辑
├── news_monitor/       # 新闻监听与语义分类
├── dailychart/         # 每日行情定时任务
├── shortstrategy/      # 短线分析工具集
├── nginx.conf          # Nginx 反向代理配置
└── docker-compose.yml  # Docker 容器编排
```

## 📖 相关文档

- [RAG 系统说明](LLMAgent/intro/RAG说明.md)
- [公网部署说明](LLMAgent/intro/公网部署说明.md)

---
*Last Updated: 2026-03-10*
