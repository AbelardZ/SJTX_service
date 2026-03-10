# 神机天象 (SJTX Service) - 量化全栈投资研究系统

神机天象是一个集自动化数据采集、多因子策略研究、舆情监控及大语言模型 (LLM) 深度分析于一体的量化投资全栈研究平台。系统旨在通过技术手段提升投资决策的客观性与效率。

---

## 🛠️ 技术栈

- **核心语言**: Python 3.8+
- **Web 架构**: Flask / Docker / Nginx
- **数据库系统**: MySQL (持久化行情与交易数据), SQLite (轻量级缓存与中间态)
- **人工智能**: 
  - **LLM**: 集成豆包、DeepSeek、GPT 等主流大模型 api
  - **NLP**: 基于 BERT 的新闻语义分类与情感极性分析
  - **RAG**: 基于本地向量库的行业研究论文与公告检索
- **基础设施**: Docker Compose 一键化部署

---

## 🧩 核心功能模块

### 1. 智能投研助手 (LLMAgent)
- **功能**: 实现个股的深度研究报告自动化生成及行业动态实时跟进。
- **逻辑**: 通过分布式爬虫获取巨潮资讯、研报等源数据，利用 RAG (检索增强生成) 架构，将相关公告或研报段落喂给 LLM 进行逻辑梳理，最终输出结构化的深度调研报告。

### 2. 多源舆情监控系统 (news_monitor)
- **功能**: 全天候监控全网金融新闻与实时资讯。
- **逻辑**: 采用异步 Fetcher 模式抓取多渠道新闻流，通过预训练的 BERT 模型对新闻进行 14 类业务标签分类（如：利好、利空、定增、减持等），并实时推送至交易终端或数据库。

### 3. 行情流水线与调度 (dailychart)
- **功能**: 自动采集日 K 线、盘后个股数据及各类指数变动。
- **逻辑**: 基于 Python Scheduler 的定时任务，对接多种金融 API 接口，实现数据的多级存储（本地文件存储 + 关系型数据库同步）。具备完善的备份机制，确保研究数据的历史连续性。

### 4. 辅助交易决策 (shortstrategy & liuyao)
- **功能**: 提供短线策略因子计算与传统博弈模型参考。
- **逻辑**: `shortstrategy` 模块实现基于动量与缩量逻辑的选股算法；`liuyao` 模块结合传统概率分析模型，为投资提供差异化的博弈视角参考。

---

## � 目录结构预览

### 核心目录概览

| 目录 | 功能描述 |
|:---|:---|
| **`Web/`** | 系统的可视化控制台，负责策略展示、用户鉴权及后台管理。 |
| **`LLMAgent/`** | 智能 Agent 核心，集成 RAG 知识库、爬虫及个股深度研究逻辑。 |
| **`LLM_support/`** | 大模型底层支持，包含 Prompt 模板管理及报告生成公共逻辑。 |
| **`news_monitor/`** | 实时新闻流获取与基于 BERT 模型的语义分类组件。 |
| **`dailychart/`** | 日线级行情数据获取、存储管理及自动化任务调度中心。 |
| **`shortstrategy/`** | 短线交易策略实现、选股系统及数据回测工具集。 |
| **`liuyao/`** | 结合传统博弈模型的辅助决策工具。 |
| **`user_management/`** | 用户中心与统一权限管理系统。 |

### 详细目录树

```text
SJTX_service/
├── Web/                # 基于 Flask 的前端展示与管理后台
├── LLMAgent/           # 智能助手、RAG 核心及调研数据存储
├── LLM_support/        # LLM 接口封装与分析报告导出
├── news_monitor/       # 舆情监听、BERT 分类核心及缓存
├── dailychart/         # 每日行情的抓取与持久化逻辑
├── dailychart_backup/  # 历史行情数据备份与冗余处理
├── shortstrategy/      # 短线分析算法与策略因子库
├── liuyao/             # 决策辅助工具
├── data/               # 共享数据存储目录
├── user_management/    # 用户鉴权与管理模块
├── nginx.conf          # Nginx 反向代理配置
└── docker-compose.yml  # Docker 容器化编排文件
```

---

## �🚀 部署方法

### 环境预要求
- 已安装 Docker 及 Docker Compose。
- 已配置 Git 访问权限。

### 部署步骤
1. **获取代码**
   ```bash
   git clone https://github.com/AbelardZ/SJTX_service.git
   cd SJTX_service
   ```

2. **配置文件准备**
   由于安全原因，敏感配置文件（如数据库密码、API Key）不包含在项目中。请根据各模块模板手动创建以下文件：
   - `dailychart/db_config.py`
   - `LLM_support/config.py`
   - `news_monitor/config.py`

3. **一键启动**
   ```bash
   sudo docker-compose up -d --build
   ```
   该命令将启动 Nginx 反向代理、Web 服务及相关数据处理容器。

---

*Last Updated: 2026-03-10*
