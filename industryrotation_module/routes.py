"""行业轮动模块 — Flask 蓝图

将原独立 HTTP 服务器 (server.py) 的逻辑迁移为 Flask 蓝图，
统一集成到主应用 Web/app.py 中。
"""

import csv
import json
from pathlib import Path

import pandas as pd
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
TA_DIR = _MODULE_DIR / "Technical Analysis"
L1_DIR = _MODULE_DIR / "L1_day"
L2_DIR = _MODULE_DIR / "L2_day"
L3_DIR = _MODULE_DIR / "L3_day"
CSV_MAP_PATH = _MODULE_DIR / "sw_industry_code_map.csv"


def _available_dates() -> list[str]:
    dates: set[str] = set()
    for d in (DATA_DIR, TA_DIR):
        if not d.exists():
            continue
        for path in d.glob("*.csv"):
            stem = path.stem
            # stem format: "2026-01-05-sw1"
            if len(stem) >= 10:
                dates.add(stem[:10])
    return sorted(dates, reverse=True)


def _available_dates_for_level(level: str) -> list[str]:
    """Return dates that have data for the given level."""
    dates: set[str] = set()
    for d in (DATA_DIR, TA_DIR):
        if not d.exists():
            continue
        for path in d.glob(f"*-{level}.csv"):
            stem = path.stem
            if len(stem) >= 10:
                dates.add(stem[:10])
    return sorted(dates, reverse=True)


def _read_csv_rows(trade_date: str, level: str) -> list[dict[str, str]]:
    # Try data/ first, then Technical Analysis/
    for d in (DATA_DIR, TA_DIR):
        file_path = d / f"{trade_date}-{level}.csv"
        if file_path.exists():
            with file_path.open("r", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                return list(reader)
    raise FileNotFoundError(f"数据文件不存在：{trade_date}-{level}.csv")


def _read_ta_csv_rows(trade_date: str, level: str) -> list[dict[str, str]]:
    """Read from Technical Analysis directory (supports sw1/sw2/sw3)."""
    file_path = TA_DIR / f"{trade_date}-{level}.csv"
    if not file_path.exists():
        raise FileNotFoundError(f"数据文件不存在：{file_path.name}")
    with file_path.open("r", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def _build_industry_tree() -> list[dict]:
    """Build L1->L2->L3 industry tree from sw_industry_code_map.csv."""
    if not CSV_MAP_PATH.exists():
        return []
    l1_map: dict[str, dict] = {}
    with CSV_MAP_PATH.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            l1 = (row.get("新版一级行业") or "").strip()
            l2 = (row.get("新版二级行业") or "").strip()
            l3 = (row.get("新版三级行业") or "").strip()
            if not l1 or not l2 or not l3:
                continue
            if l1 not in l1_map:
                l1_map[l1] = {"name": l1, "children": {}}
            l2_map = l1_map[l1]["children"]
            if l2 not in l2_map:
                l2_map[l2] = {"name": l2, "children": {}}
            l3_map = l2_map[l2]["children"]
            if l3 not in l3_map:
                l3_map[l3] = {"name": l3}

    result = []
    for l1_name in sorted(l1_map.keys()):
        l1_node = l1_map[l1_name]
        l2_list = []
        for l2_name in sorted(l1_node["children"].keys()):
            l2_node = l1_node["children"][l2_name]
            l3_list = [{"name": name} for name in sorted(l2_node["children"].keys())]
            l2_list.append({"name": l2_name, "children": l3_list})
        result.append({"name": l1_name, "children": l2_list})
    return result


def _get_kline_data(level: str, name: str) -> list[dict]:
    """Get OHLCV kline data from parquet files.
    Matches by: full name (e.g. '农林牧渔-种植业-种子'), stock_code (e.g. '110101'),
    or partial name (e.g. '种子').
    """
    dir_map = {"sw1": L1_DIR, "sw2": L2_DIR, "sw3": L3_DIR}
    data_dir = dir_map.get(level)
    if not data_dir:
        return []

    for f in data_dir.glob("*.parquet"):
        stem = f.stem
        if level == "sw3":
            # L3 files: "110101_农林牧渔-种植业-种子"
            parts = stem.split("_", 1)
            code = parts[0] if parts else ""
            full_name = parts[1] if len(parts) > 1 else stem
            # Match by code, full name, or the last segment (三级行业名)
            l3_name = full_name.rsplit("-", 1)[-1] if "-" in full_name else full_name
            if name in (code, full_name, l3_name, stem):
                return _read_parquet_kline(f)
        elif level == "sw2":
            # L2 files: "一般零售" or "交通运输-物流"
            if stem == name or name.endswith("-" + stem):
                return _read_parquet_kline(f)
        else:
            # L1 files: "医药生物"
            if stem == name:
                return _read_parquet_kline(f)
    return []


def _read_parquet_kline(filepath: Path) -> list[dict]:
    """Read OHLCV data from a parquet file."""
    try:
        df = pd.read_parquet(filepath)
        df = df.sort_values("date")
        records = df[["date", "open", "high", "low", "close", "amount", "volume"]].to_dict(orient="records")
        for r in records:
            for k, v in r.items():
                if hasattr(v, "item"):
                    r[k] = v.item()
        return records
    except Exception:
        return []


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
    """返回所有可用日期，可选 level 参数过滤"""
    level = request.args.get("level", "")
    if level in ("sw1", "sw2", "sw3"):
        return jsonify(_available_dates_for_level(level))
    return jsonify(_available_dates())


@industryrotation_bp.route("/api/data")
def api_data():
    """返回指定日期和层级的数据 (sw1/sw2 from data/, sw3 from Technical Analysis/)"""
    trade_date = request.args.get("date")
    level = request.args.get("level", "sw1")

    if not trade_date or level not in ("sw1", "sw2", "sw3"):
        return jsonify({"error": "缺少 date 或 level 参数"}), 400

    try:
        if level == "sw3":
            rows = _read_ta_csv_rows(trade_date, level)
        else:
            rows = _read_csv_rows(trade_date, level)
        return jsonify(rows)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404


@industryrotation_bp.route("/api/tree")
def api_tree():
    """返回行业层级树 L1->L2->L3"""
    return jsonify(_build_industry_tree())


@industryrotation_bp.route("/api/kline")
def api_kline():
    """返回指定行业层级的K线数据"""
    level = request.args.get("level", "sw1")
    name = request.args.get("name", "")
    if not name or level not in ("sw1", "sw2", "sw3"):
        return jsonify({"error": "缺少 level 或 name 参数"}), 400
    data = _get_kline_data(level, name)
    return jsonify(data)


# ---------------------------------------------------------------------------
# 静态文件路由 (手动处理，避免 importlib 动态加载时 static_folder 解析问题)
# ---------------------------------------------------------------------------

@industryrotation_bp.route("/<path:filename>")
def static_files(filename):
    """提供模块内的静态文件 (CSS, JS 等)"""
    return send_from_directory(str(_MODULE_DIR), filename)
