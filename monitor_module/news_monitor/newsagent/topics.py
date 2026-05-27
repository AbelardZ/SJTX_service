from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Dict, Iterable, List

# ============================================================
# 提示词 md 路径
# ============================================================
PROMPT_DOC_PATH = Path(__file__).resolve().parents[1] / "prompt" / "newsagent_prompts.md"

# ============================================================
# BERT 模型输出的 22 个一级标签（不可修改，来自 label_map.json）
# ============================================================
BERT_LABELS = [
    "新闻集合",
    "机构观点和策略",
    "国内一般政策",
    "自然事件",
    "交易提示",
    "重要主体动态",
    "公司公告",
    "国内政府动向",
    "行业数据",
    "金融部门事务",
    "地缘政治动态",
    "一般国际事务",
    "国际金融政策",
    "社会事件",
    "国内一般指导",
    "国际宏观数据",
    "科学技术前沿动态",
    "重要国家内政",
    "行业消息",
    "国内宏观数据",
    "国内政治动态",
    "国际一般政策",
]

# ============================================================
# 二级聚类：每个二级聚类包含若干个一级标签
# 前端可以按一级标签单独筛选，也可以按二级聚类标题筛选
# AI 研报按二级聚类生成
# ============================================================
CLUSTER_DEFINITIONS = [
    {
        "name": "交易与公告",
        "tags": ["交易提示", "公司公告"],
    },
    {
        "name": "市场金融",
        "tags": ["机构观点和策略", "金融部门事务"],
    },
    {
        "name": "产业科技",
        "tags": ["行业消息", "行业数据", "重要主体动态", "科学技术前沿动态"],
    },
    {
        "name": "国内政策",
        "tags": ["国内政治动态", "国内一般指导", "国内一般政策", "国内政府动向"],
    },
    {
        "name": "国际地缘金融",
        "tags": ["地缘政治动态", "国际金融政策"],
    },
    {
        "name": "国际事务",
        "tags": ["一般国际事务", "国际一般政策", "重要国家内政"],
    },
    {
        "name": "宏观数据",
        "tags": ["国内宏观数据", "国际宏观数据"],
    },
    {
        "name": "事件风险",
        "tags": ["自然事件", "社会事件"],
    },
    {
        "name": "新闻集合",
        "tags": ["新闻集合"],
    },
    {
        "name": "综合",
        "tags": ["综合"],
    },
]

# ============================================================
# 前端展示用：二级聚类分组 + 一级标签列表
# 综合不单独列出，只在"全部"时用于 AI 研报
# ============================================================
FRONTEND_LABEL_GROUPS = [
    {"name": c["name"], "tags": c["tags"]} for c in CLUSTER_DEFINITIONS if c["name"] != "综合"
]

FRONTEND_LABEL_OPTIONS = ["全部"] + [tag for c in CLUSTER_DEFINITIONS if c["name"] != "综合" for tag in c["tags"]]

# ============================================================
# 一级标签 -> 二级聚类 映射
# ============================================================
LABEL_TO_CLUSTER: Dict[str, str] = {}
for cluster in CLUSTER_DEFINITIONS:
    for tag in cluster["tags"]:
        LABEL_TO_CLUSTER[tag] = cluster["name"]

# ============================================================
# 前端样式 class 映射（一级标签 -> CSS class）
# ============================================================
LABEL_STYLE_CLASS_MAP = {
    "交易提示": "cluster-trading",
    "公司公告": "cluster-company",
    "机构观点和策略": "cluster-market",
    "金融部门事务": "cluster-market",
    "行业消息": "cluster-industry",
    "行业数据": "cluster-industry",
    "重要主体动态": "cluster-industry",
    "科学技术前沿动态": "cluster-industry",
    "国内政治动态": "cluster-policy",
    "国内一般指导": "cluster-policy",
    "国内一般政策": "cluster-policy",
    "国内政府动向": "cluster-policy",
    "地缘政治动态": "cluster-international-high",
    "国际金融政策": "cluster-international-high",
    "一般国际事务": "cluster-international",
    "国际一般政策": "cluster-international",
    "重要国家内政": "cluster-international",
    "国内宏观数据": "cluster-macro",
    "国际宏观数据": "cluster-macro",
    "自然事件": "cluster-event",
    "社会事件": "cluster-event",
    "新闻集合": "cluster-digest",
    "综合": "cluster-overview",
}

# ============================================================
# 提示词加载（从 md 文件读取，不存在则用空字符串）
# ============================================================
DEFAULT_BASE_SYSTEM_PROMPT = ""
DEFAULT_CLUSTER_PROMPTS = {c["name"]: "" for c in CLUSTER_DEFINITIONS}


def _load_prompt_sections(doc_path: Path) -> Dict[str, str]:
    if not doc_path.exists():
        return {}

    sections: Dict[str, List[str]] = {}
    current_name: str | None = None
    current_lines: List[str] = []

    for raw_line in doc_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        match = re.match(r"^#{1,3}\s+(.*)$", line)
        if match:
            if current_name is not None:
                sections[current_name] = current_lines[:]
            current_name = match.group(1).strip()
            current_lines = []
            continue
        if current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        sections[current_name] = current_lines[:]

    return {
        name: "\n".join(lines).strip()
        for name, lines in sections.items()
        if "\n".join(lines).strip()
    }


_PROMPT_SECTIONS = _load_prompt_sections(PROMPT_DOC_PATH)
BASE_SYSTEM_PROMPT = _PROMPT_SECTIONS.get("全局提示词", DEFAULT_BASE_SYSTEM_PROMPT)
CLUSTER_PROMPTS = {
    key: _PROMPT_SECTIONS.get(key, default_text)
    for key, default_text in DEFAULT_CLUSTER_PROMPTS.items()
}

# ============================================================
# 分类函数：只认 BERT 标签，不做关键词兜底
# ============================================================
def normalize_cluster_label(label: str | None) -> str:
    """把一级标签映射到二级聚类名。不在映射表里的返回空字符串。"""
    if not label:
        return ""
    value = str(label).strip()
    return LABEL_TO_CLUSTER.get(value, "")


def classify_news_cluster(raw_label: str | None, title: str | None = None, content: str | None = None) -> str:
    """返回二级聚类名。只依赖入库时的 primary_label。"""
    return normalize_cluster_label(raw_label)


def group_cluster_items(items: Iterable[Dict]) -> Dict[str, List[Dict]]:
    """按二级聚类分组。没有映射到任何聚类的条目会被跳过。"""
    grouped: Dict[str, List[Dict]] = {}
    for item in items:
        cluster = normalize_cluster_label(item.get("primary_label"))
        if not cluster:
            continue
        grouped.setdefault(cluster, []).append(item)
    return grouped


def cluster_sort_key(cluster: str) -> int:
    order = [c["name"] for c in CLUSTER_DEFINITIONS]
    try:
        return order.index(cluster)
    except ValueError:
        return len(order)

# ============================================================
# 提示词构建
# ============================================================
def build_system_prompt(cluster_name: str) -> str:
    base = BASE_SYSTEM_PROMPT
    extra = CLUSTER_PROMPTS.get(cluster_name, "")
    if cluster_name == "综合":
        return f"{base}\n\n你将收到同一时间段的多份聚类研报 Markdown，请只综合这些研报，不要回到原始新闻。\n{extra}".strip()
    if extra:
        return f"{base}\n\n当前研报聚类：{cluster_name}\n{extra}".strip()
    return f"{base}\n\n当前研报聚类：{cluster_name}".strip()


def build_user_prompt(cluster_name: str, period_name: str, date: datetime.date, content: str) -> str:
    return (
        f"日期: {date.isoformat()}\n"
        f"时间段: {period_name}\n"
        f"聚类: {cluster_name}\n\n"
        f"{content.strip()}\n"
    ).strip()

# ============================================================
# 报表路径
# ============================================================
def report_root_path(root: Path, report_date: datetime.date, period_name: str) -> Path:
    return Path(root) / report_date.isoformat() / period_name


def report_file_path(root: Path, report_date: datetime.date, period_name: str, cluster_name: str) -> Path:
    return report_root_path(root, report_date, period_name) / f"{cluster_name}.md"


def report_file_glob(root: Path, report_date: str | None = None, period_name: str | None = None, cluster_name: str | None = None) -> List[Path]:
    base = Path(root)
    if report_date and period_name:
        exact = base / report_date / period_name / f"{cluster_name or '综合'}.md"
        return [exact] if exact.exists() else []

    patterns: List[Path] = []
    if report_date:
        if cluster_name:
            patterns = list(base.glob(f"{report_date}/*/{cluster_name}.md"))
        else:
            patterns = list(base.glob(f"{report_date}/*/*.md"))
    elif period_name:
        if cluster_name:
            patterns = list(base.glob(f"*/{period_name}/{cluster_name}.md"))
        else:
            patterns = list(base.glob(f"*/{period_name}/*.md"))
    else:
        if cluster_name:
            patterns = list(base.glob(f"*/*/{cluster_name}.md"))
        else:
            patterns = list(base.glob("*/*/*.md"))

    return sorted(patterns, key=lambda p: p.stat().st_mtime, reverse=True)


def latest_report_file(root: Path, period_name: str | None = None, cluster_name: str | None = None) -> Path | None:
    candidates = report_file_glob(root, None, period_name, cluster_name)
    return candidates[0] if candidates else None
