"""行业轮动模块 — Flask 蓝图

将原独立 HTTP 服务器 (server.py) 的逻辑迁移为 Flask 蓝图，
统一集成到主应用 Web/app.py 中。
"""

import csv
import json
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_from_directory

industryrotation_bp = Blueprint(
    "industryrotation",
    __name__,
    url_prefix="/industryrotation",
    template_folder=".",
    static_folder=None,  # 禁用默认静态路由，手动处理
)

_MODULE_DIR = Path(__file__).resolve().parent
DATA_DIR = _MODULE_DIR / "data"


def _available_dates() -> list[str]:
    if not DATA_DIR.exists():
        return []
    dates: set[str] = set()
    for path in DATA_DIR.glob("*.csv"):
        stem = path.stem
        if len(stem) >= 10:
            dates.add(stem[:10])
    return sorted(dates, reverse=True)


def _read_csv_rows(trade_date: str, level: str) -> list[dict[str, str]]:
    file_path = DATA_DIR / f"{trade_date}-{level}.csv"
    if not file_path.exists():
        raise FileNotFoundError(f"数据文件不存在：{file_path.name}")
    with file_path.open("r", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------

@industryrotation_bp.route("/")
def index():
    """行业轮动分析主页面"""
    return render_template("industryrotation.html")


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

@industryrotation_bp.route("/api/dates")
def api_dates():
    """返回所有可用日期"""
    return jsonify(_available_dates())


@industryrotation_bp.route("/api/data")
def api_data():
    """返回指定日期和层级的数据"""
    trade_date = request.args.get("date")
    level = request.args.get("level", "sw1")

    if not trade_date or level not in ("sw1", "sw2"):
        return jsonify({"error": "缺少 date 或 level 参数"}), 400

    try:
        rows = _read_csv_rows(trade_date, level)
        return jsonify(rows)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# 静态文件路由 (手动处理，避免 importlib 动态加载时 static_folder 解析问题)
# ---------------------------------------------------------------------------

@industryrotation_bp.route("/<path:filename>")
def static_files(filename):
    """提供模块内的静态文件 (CSS, JS 等)"""
    return send_from_directory(str(_MODULE_DIR), filename)
