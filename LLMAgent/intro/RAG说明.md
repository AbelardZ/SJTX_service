# 本地向量化 RAG 工作原理（当前项目）

## 1) 你现在这套最小链路做了什么

`local_rag.py` 提供两个命令：

- `build`：读取 `data/代码+股票名称/{report,announcement}` 下的文件，做文本切片并向量化，保存本地索引。
- `query`：把你的问题向量化，与本地 chunk 向量做余弦相似度检索，返回 Top-K 片段。

针对 PDF，已经加入 **自动OCR兜底**：

- 先做普通文本抽取（`pypdf`）
- 若文本覆盖率太低（例如大部分页面字符很少），自动触发 OCR
- OCR 文本更长时，优先采用 OCR 结果入库

这就是 RAG 的核心：

1. **离线阶段**：文档 -> chunk -> embedding -> 本地向量库
2. **在线阶段**：query -> embedding -> 相似检索 -> 把命中片段喂给大模型生成答案

---

## 2) 当前数据存储结构

以 `600536中国软件` 为例：

```text
data/
  600536中国软件/
    report/                # 财报原始文件（PDF等）
    announcement/          # 公告原始文件（PDF等）
    rag/
      chunks.jsonl         # 切片后的文本与元信息
      embeddings.npy       # 与 chunks 对齐的向量矩阵
      meta.json            # 构建参数和统计信息
```

说明：

- `chunks.jsonl` 每行一个 chunk，包含 `chunk_id/source_path/doc_type/text`。
- `embeddings.npy` 第 N 行向量对应 `chunks.jsonl` 第 N 行。
- `meta.json` 记录模型名、chunk参数、文档数、chunk数、向量维度等。

---

## 3) 关键参数怎么理解

- `chunk_size`：每段文本长度，默认 `700`。
- `overlap`：相邻 chunk 重叠，默认 `120`，减少关键信息被切断。
- `model`：Embedding 模型，默认 `BAAI/bge-small-zh-v1.5`（中文场景常用）。
- `--ocr auto|on|off`：OCR 模式（默认 `auto`）。
- `--ocr-min-chars-page`：自动OCR阈值，单页字符过少视为低覆盖。
- `--ocr-min-avg-chars`：自动OCR阈值，平均每页字符过少触发OCR。

经验：

- 财报长文档可把 `chunk_size` 调到 `900~1200`。
- 公告短文档通常 `500~800` 足够。

---

## 4) 如何运行

安装依赖（最小）

```bash
pip install pypdf sentence-transformers numpy
```

如果要启用 OCR（`auto/on`）：

```bash
pip install pymupdf rapidocr-onnxruntime
```

先构建：

```bash
python local_rag.py build --stock-folder 600536中国软件
```

强制 OCR 构建：

```bash
python local_rag.py build --stock-folder 600536中国软件 --ocr on
```

再检索：

```bash
python local_rag.py query --stock-folder 600536中国软件 --q "最近一年业绩变化和主要风险" --top-k 5
```

---

## 5) 下一步如何接入你的股票分析主流程

在 `stock_analyzer.py` 中，调用 `query_rag(...)` 拿到 Top-K 片段，拼成“证据上下文”，再和你的分层 Prompt 一起发给大模型。

建议拼接结构：

1. 用户问题
2. RAG命中片段（带来源文件）
3. 你的模块提示词（基本面/宏观/资金面/策略）

这样能显著减少“空口判断”，并提升可追溯性。
