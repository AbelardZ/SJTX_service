"""涨停分析模块 — Flask 蓝图

将原独立 HTTP 服务器 (server.py) 的逻辑迁移为 Flask 蓝图，
统一集成到主应用 Web/app.py 中。
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_from_directory

limitup_bp = Blueprint(
    "limitup",
    __name__,
    url_prefix="/limitup",
    template_folder=".",
    static_folder=".",
)

_MODULE_DIR = Path(__file__).resolve().parent
DATA_DIR = _MODULE_DIR / "data"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 缓存趋势聚合数据（进程级缓存，避免每次请求都遍历所有CSV）
_trend_cache: dict | None = None
_trend_cache_mtime: float = 0


def _available_dates() -> list[str]:
    if not DATA_DIR.exists():
        return []
    dates = []
    for path in DATA_DIR.glob("*.csv"):
        if DATE_RE.match(path.stem):
            dates.append(path.stem)
    return sorted(dates, reverse=True)


def _read_csv_rows(trade_date: str) -> tuple[list[str], list[dict[str, str]]]:
    if not DATE_RE.match(trade_date):
        raise ValueError("invalid date")

    path = DATA_DIR / f"{trade_date}.csv"
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames or []
        rows = []
        for row in reader:
            rows.append({column: (row.get(column) or "").strip() for column in columns})
    return columns, rows


def _get_trend_data() -> dict:
    """返回所有日期的聚合趋势数据（带缓存）。

    返回格式:
    {
        "dates": ["2026-05-06", ...],
        "total": [{"date": "2026-05-06", "value": 42}, ...],
        "industry": {"电子": [{"date": "2026-05-06", "value": 5}, ...], ...},
        "theme": {"芯片": [{"date": "2026-05-06", "value": 3}, ...], ...}
    }
    """
    global _trend_cache, _trend_cache_mtime

    # 检查缓存是否有效（通过 data 目录的修改时间判断）
    try:
        current_mtime = max(
            (p.stat().st_mtime for p in DATA_DIR.glob("*.csv") if DATE_RE.match(p.stem)),
            default=0,
        )
    except Exception:
        current_mtime = 0

    if _trend_cache is not None and _trend_cache_mtime >= current_mtime:
        return _trend_cache

    dates = _available_dates()
    total_series: list[dict] = []
    industry_map: dict[str, list[dict]] = defaultdict(list)
    theme_map: dict[str, list[dict]] = defaultdict(list)

    for date in dates:
        try:
            _, rows = _read_csv_rows(date)
        except Exception:
            continue

        total_series.append({"date": date, "value": len(rows)})

        # 统计申万一级
        industry_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            ind = (row.get("申万一级") or "").strip()
            if ind:
                industry_counts[ind] += 1
        for ind, count in industry_counts.items():
            industry_map[ind].append({"date": date, "value": count})

        # 统计韭研题材
        theme_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            themes_raw = (row.get("韭研题材") or "").strip()
            if themes_raw:
                for t in re.split(r"[+、，,；;｜|/]", themes_raw):
                    t = t.strip()
                    if t:
                        theme_counts[t] += 1
        for theme, count in theme_counts.items():
            theme_map[theme].append({"date": date, "value": count})

    _trend_cache = {
        "dates": dates,
        "total": total_series,
        "industry": dict(industry_map),
        "theme": dict(theme_map),
    }
    _trend_cache_mtime = current_mtime
    return _trend_cache


# ── 页面路由 ──────────────────────────────────────────────


@limitup_bp.route("/")
def index():
    """涨停分析主页面"""
    return render_template("limitup.html")


# ── API 路由 ───────────────────────────────────────────────


@limitup_bp.route("/api/dates")
def api_dates():
    return jsonify({"dates": _available_dates()})


@limitup_bp.route("/api/trend")
def api_trend():
    """返回所有日期的聚合趋势数据（轻量级，仅统计数量）。

    前端趋势图不再需要加载所有日期的完整CSV，
    只需调用此接口获取每日涨停总数、行业分布、题材分布。
    """
    return jsonify(_get_trend_data())


@limitup_bp.route("/api/data")
def api_data():
    trade_date = request.args.get("date", "")
    try:
        columns, rows = _read_csv_rows(trade_date)
    except ValueError:
        return jsonify({"error": "日期格式不正确"}), 400
    except FileNotFoundError:
        return jsonify({"error": "未找到该日期的 CSV"}), 404

    return jsonify({"date": trade_date, "columns": columns, "rows": rows})


# ── 静态文件 (CSS / JS) ────────────────────────────────────


@limitup_bp.route("/styles.css")
def styles_css():
    return send_from_directory(str(_MODULE_DIR), "styles.css")


@limitup_bp.route("/app.js")
def app_js():
    return send_from_directory(str(_MODULE_DIR), "app.js")
