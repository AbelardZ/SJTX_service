# 神机天象 (SJTX Service) - 量化全栈投资研究系统

神机天象是一个集自动化数据采集、多因子策略研究、舆情监控及大语言模型 (LLM) 深度分析于一体的量化投资全栈研究平台。系统旨在通过技术手段提升投资决策的客观性与效率。

---

## 🛠️ 技术栈

- **核心语言**: Python 3.8+
- **Web 架构**: Flask / Docker / Nginx
- **数据库系统**: MySQL (持久化行情与交易数据), SQLite (轻量级缓存与中间态)
- **人工智能**: 
  - **LLM**: 集成豆包、DeepSeek、GPT 等主流大模型 API
  - **NLP**: 基于 BERT 的新闻语义分类与情感极性分析
  - **RAG**: 基于本地向量库的行业研究论文与公告检索
- **基础设施**: Docker Compose 一键化部署

---

## 🧩 核心功能模块

### 1. 智能投研助手 (`aiagent_module/`)
- **功能**: 实现个股的深度研究报告自动化生成。
- **逻辑**: 通过分布式爬虫获取巨潮资讯公告与研报等源数据，利用 RAG (检索增强生成) 架构，将相关公告或研报段落喂给 LLM 进行逻辑梳理，最终输出结构化的深度调研报告（涵盖商业基本面、大/小级别技术分析、资金面、投资建议等维度）。

### 2. 多源舆情监控系统 (`news_monitor/`)
- **功能**: 全天候监控财联社等平台的实时快讯（电报）。
- **逻辑**: 采用异步 Fetcher 模式抓取多渠道新闻流，通过预训练的 BERT 模型 (`classifier_core/`) 对新闻进行多标签业务分类，并实时推送至前端展示。

### 3. AI 新闻简报 (`news_monitor/newsagent/`)
- **功能**: 定时自动生成 A 股投资研究简报。
- **逻辑**: 按早盘、午间、收盘及隔夜等固定时段，自动筛选新闻流并调用 DeepSeek 等大模型生成结构化 Markdown 报告。

### 4. 行业深度研究 (`industry_module/`)
- **功能**: 申万行业层级结构展示及各细分行业的深度研究文档浏览。
- **逻辑**: 基于申万行业编码体系，提供 Markdown 格式的行业研报渲染与目录导航。

### 5. 实时快讯看板 (`monitor_module/`)
- **功能**: A 股实时快讯直播展示，支持分类标签过滤与历史回顾。
- **逻辑**: 通过 SSE / 轮询从 SQLite 数据库读取 `news_monitor` 生产的分类快讯数据，提供前端实时展示。

---

## 📁 目录结构

```text
SJTX_service/
├── Web/                          # Flask 主入口、首页渲染、蓝图路由聚合
│   ├── app.py                    # 应用入口，统一注册所有模块蓝图
│   ├── extensions.py             # Flask 扩展初始化
│   ├── routes/                   # 内部路由 (main, reports)
│   ├── templates/                # 首页及公共模板
│   └── static/                   # 公共 CSS/JS 静态资源
├── aiagent_module/               # 智能投研助手模块
│   ├── routes.py                 # Flask 蓝图，个股深度研究 API
│   └── LLMAgent/                 # AI Agent 核心
│       ├── stock_deep_research.py # 深度研究主逻辑
│       ├── cninfo_crawler.py      # 巨潮资讯爬虫
│       ├── cninfo_announcements_crawler.py
│       ├── cninfo_reports_crawler.py
│       ├── local_rag.py           # 本地 RAG 向量检索
│       ├── api_server.py          # API 服务
│       ├── prompt/                # LLM 提示词模板 (6 个分析维度)
│       ├── data/                  # 个股向量库数据
│       ├── reports/               # 生成的研究报告
│       └── intro/                 # RAG 与部署说明文档
├── news_monitor/                  # 舆情监控核心
│   ├── main.py                    # 系统入口，启动抓取/分类/同步
│   ├── config.py                  # 数据库与 API 配置
│   ├── fetcher.py                 # 财联社等平台数据抓取
│   ├── storage.py                 # 数据持久化
│   ├── sync_worker.py             # 云端同步
│   ├── db_proxy.py                # 数据库代理
│   ├── classifier_core/           # BERT 分类器引擎
│   │   ├── app.py                 # 分类服务入口
│   │   ├── classifier.py          # 模型加载与预测
│   │   └── ...                    # 预处理/存储/配置等子模块
│   ├── newsagent/                 # AI 新闻简报
│   │   ├── agent_worker.py        # 定时报告生成逻辑
│   │   ├── llm.py                 # LLM API 封装
│   │   └── saved_reports/         # 生成的简报存档
│   └── bert_model_output/         # 预训练 BERT 模型权重
├── industry_module/               # 行业研究模块
│   ├── routes.py                  # Flask 蓝图，行业文档浏览
│   ├── sw_industry_code_map.csv   # 申万行业编码映射
│   └── industry/                  # 按行业分类的 Markdown 研报
├── monitor_module/                # 实时快讯展示模块
│   ├── routes.py                  # Flask 蓝图，快讯 SSE/轮询接口
│   └── templates/                 # 快讯与历史页面模板
├── nginx.conf                     # Nginx 反向代理配置 (SSE 优化)
└── docker-compose.yml             # Docker 容器化编排 (Host 网络模式)
```

---

## 🚀 部署方法

### 环境要求
- 已安装 Docker 及 Docker Compose
- 已配置 Git 访问权限

### 部署步骤

1. **获取代码**
   ```bash
   git clone https://github.com/AbelardZ/SJTX_service.git
   cd SJTX_service
   ```

2. **配置文件准备**
   由于安全原因，敏感配置文件（如数据库密码、API Key）不包含在项目中。请根据各模块模板手动创建以下文件：
   - `news_monitor/config.py`

3. **一键启动**
   ```bash
   sudo docker-compose up -d --build
   ```
   该命令将启动 Nginx 反向代理、Web 服务及 `news_monitor` 后台数据处理容器。系统采用 Host 网络模式，方便配合 Tailscale 等内网穿透工具使用。

---

*Last Updated: 2026-05-14*
