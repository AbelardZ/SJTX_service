"""涨停分析模块 — Flask 蓝图

将原独立 HTTP 服务器 (server.py) 的逻辑迁移为 Flask 蓝图，
统一集成到主应用 Web/app.py 中。
"""

import csv
import re
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


# ── 页面路由 ──────────────────────────────────────────────


@limitup_bp.route("/")
def index():
    """涨停分析主页面"""
    return render_template("limitup.html")


# ── API 路由 ───────────────────────────────────────────────


@limitup_bp.route("/api/dates")
def api_dates():
    return jsonify({"dates": _available_dates()})


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
