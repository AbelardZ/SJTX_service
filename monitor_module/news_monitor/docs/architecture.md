# News Monitor 架构说明

这个模块现在按四层拆分，正式入口只有一个：`monitor_module/news_monitor/data/newsagent_reports/`。

## 1. 抓取层

`fetcher.py` 负责从上游抓取原始快讯。
`main.py` 负责调度抓取流程，并把原始数据写入本地 SQLite 缓存。

## 2. 存储层

`storage.py`、`db_proxy.py`、`paths.py` 负责本地持久化边界。
其中 `paths.py` 是唯一的路径来源，当前关键路径只有两个：

- `DB_PATH`：快讯和新闻的 SQLite 缓存。
- `REPORTS_DIR`：NewsAgent 简报的正式输出目录。

以后所有 AI 报告都只写到 `monitor_module/news_monitor/data/newsagent_reports/`。

## 3. 分类层

`classifier_core/` 负责 BERT 分类、文本清洗、接入适配和仓储 schema。
这一层只做“分类”和“标准化”，不负责报表存储，也不负责页面展示。

## 4. 报告层

`newsagent/agent_worker.py` 从 SQLite 读取已缓存新闻，调用 `newsagent/llm.py` 生成分时段报告，再写入 `REPORTS_DIR`。

`newsagent/llm.py` 现在只做 LLM 配置和客户端构造，不应该在 import 阶段执行重活。

## 正式入口

当前正式入口是：`monitor_module/news_monitor/data/newsagent_reports/`

页面和接口读取报告时，也应该统一从这个目录取数据。

## 运行链路

1. 抓取原始新闻。
2. 写入 SQLite。
3. 分类并补充标签。
4. 生成分时段 AI 报告。
5. 写入 `data/newsagent_reports/`。

## 旧目录说明

以下目录属于历史遗留输出，不再作为正式入口：

- `monitor_module/news_monitor/newsagent/saved_reports/`
- `news_monitor/newsagent/saved_reports/`

这些旧目录里的文件如果已经同步到正式目录，就可以删除或只作为临时兼容残留保留，不应再由代码写入。