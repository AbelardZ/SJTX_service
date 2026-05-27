import argparse
import datetime
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
project_root = str(Path(__file__).resolve().parents[3])
if project_root not in sys.path:
    sys.path.append(project_root)

from monitor_module.news_monitor.paths import DB_PATH, REPORTS_DIR
from monitor_module.news_monitor.newsagent.llm import MODEL_NAME, build_client, build_cluster_system_prompt, build_cluster_user_prompt
from monitor_module.news_monitor.newsagent.topics import (
    FRONTEND_LABEL_GROUPS,
    cluster_sort_key,
    group_cluster_items,
    report_file_path,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("NewsAgent")

PERIODS = [
    {"name": "overnight", "start": "15:00", "end": "09:30"},   # 跨天：前一天15:00 ~ 当天09:30
    {"name": "morning", "start": "09:30", "end": "11:30"},
    {"name": "noon", "start": "11:30", "end": "13:00"},
    {"name": "afternoon", "start": "13:00", "end": "15:00"},
]

PERIOD_ORDER = [p["name"] for p in PERIODS]


def get_local_db_connection():
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(DB_PATH))
    except Exception as e:
        logger.error(f"Failed to connect to local DB: {e}")
        return None


def _period_time_range(period_name: str, date: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    p_info = next(p for p in PERIODS if p["name"] == period_name)
    start_time_str = p_info["start"]
    end_time_str = p_info["end"]

    if period_name == "overnight":
        # overnight 跨天：前一天 15:00 ~ 当天 09:30，report_date 为当天
        end_dt = datetime.datetime.combine(date, datetime.time.fromisoformat(end_time_str))
        start_dt = datetime.datetime.combine(date - datetime.timedelta(days=1), datetime.time.fromisoformat(start_time_str))
    else:
        start_dt = datetime.datetime.combine(date, datetime.time.fromisoformat(start_time_str))
        end_dt = datetime.datetime.combine(date, datetime.time.fromisoformat(end_time_str))
    return start_dt, end_dt


def _candidate_tables_for_period(cursor: sqlite3.Cursor, date: datetime.date) -> List[str]:
    keys = {
        date.strftime('%Y_%m_%d'),
        (date - datetime.timedelta(days=1)).strftime('%Y_%m_%d'),
        (date + datetime.timedelta(days=1)).strftime('%Y_%m_%d'),
    }
    tables: List[str] = []
    for key in keys:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"telegraph_{key}%",)
        )
        tables.extend([r[0] for r in cursor.fetchall()])
    return sorted(set(tables))


def get_current_period() -> Optional[Dict]:
    now = datetime.datetime.now()
    cur_time = now.strftime("%H:%M")

    if cur_time >= "15:00" or cur_time < "09:30":
        return PERIODS[0]  # overnight

    for p in PERIODS:
        if p["start"] <= cur_time < p["end"]:
            return p
    return None


def get_news_for_period(period_name: str, date: datetime.date) -> List[Dict[str, Any]]:
    conn = get_local_db_connection()
    if not conn:
        return []

    news_list: List[Dict[str, Any]] = []
    start_dt, end_dt = _period_time_range(period_name, date)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor = conn.cursor()
        tables = _candidate_tables_for_period(cursor, date)

        for tbl in tables:
            try:
                cursor.execute(
                    f"""
                    SELECT ctime, title, content, primary_label
                    FROM `{tbl}`
                    WHERE ctime >= ? AND ctime < ? AND segment = ?
                    ORDER BY ctime ASC
                    """,
                    (start_str, end_str, period_name),
                )
                rows = cursor.fetchall()
                for ctime, title, content, primary_label in rows:
                    if isinstance(ctime, str):
                        ctime_str = ctime
                    else:
                        ctime_str = ctime.strftime("%Y-%m-%d %H:%M:%S")
                    news_list.append({
                        "time": ctime_str,
                        "title": title or "",
                        "content": content or "",
                        "primary_label": primary_label or "",
                    })
            except Exception as e:
                logger.warning(f"Error querying table {tbl}: {e}")
    finally:
        conn.close()

    news_list.sort(key=lambda item: item.get("time", ""))
    return news_list


def _format_news_items(news: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for idx, item in enumerate(news, start=1):
        lines.append(
            f"[{idx}] 时间: {item['time']} | 原始分类: {item.get('primary_label', '')}\n"
            f"标题: {item['title']}\n"
            f"内容: {item['content']}\n"
        )
    return "\n".join(lines).strip()


def _format_report_bundle(report_items: List[Dict[str, Any]]) -> str:
    chunks: List[str] = []
    for item in report_items:
        chunks.append(
            f"## {item['cluster']}\n"
            f"{item['content'].strip()}\n"
        )
    return "\n\n".join(chunks).strip()


def generate_report_md(cluster_name: str, period_name: str, report_date: datetime.date, prompt_body: str) -> str:
    if not prompt_body.strip():
        return f"# {cluster_name}\n\n在 {report_date.isoformat()} 的 {period_name} 时段内未收到相关新闻。"

    client = build_client()
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": build_cluster_system_prompt(cluster_name)},
                {"role": "user", "content": build_cluster_user_prompt(cluster_name, period_name, report_date, prompt_body)},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM API Error ({cluster_name}/{period_name}/{report_date}): {e}")
        return f"# {cluster_name}\n\n生成报告失败: {e}"


def _write_report_file(report_date: datetime.date, period_name: str, cluster_name: str, content: str) -> Path:
    path = report_file_path(REPORTS_DIR, report_date, period_name, cluster_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def save_report_to_db(period_name: str, report_date: datetime.date, cluster_name: str, report_content: str):
    try:
        file_path = _write_report_file(report_date, period_name, cluster_name, report_content)
        logger.info(f"Report saved: {file_path}")
    except Exception as e:
        logger.error(f"Failed to save report file for {report_date} {period_name} {cluster_name}: {e}")


def build_and_save_period_reports(report_date: datetime.date, period_name: str):
    news = get_news_for_period(period_name, report_date)
    if not news:
        summary = generate_report_md("综合", period_name, report_date, "")
        save_report_to_db(period_name, report_date, "综合", summary)
        return

    grouped = group_cluster_items(news)
    ordered_clusters = sorted(grouped.keys(), key=cluster_sort_key)

    if not ordered_clusters:
        summary = generate_report_md("综合", period_name, report_date, "")
        save_report_to_db(period_name, report_date, "综合", summary)
        return

    cluster_reports: List[Dict[str, Any]] = []
    for cluster_name in ordered_clusters:
        cluster_items = grouped.get(cluster_name, [])
        prompt_body = _format_news_items(cluster_items)
        report_md = generate_report_md(cluster_name, period_name, report_date, prompt_body)
        save_report_to_db(period_name, report_date, cluster_name, report_md)
        cluster_reports.append({"cluster": cluster_name, "content": report_md})
        # 每个聚类之间间隔 3 秒，防止 API 限流和 CPU 尖峰
        time.sleep(3)

    overview_body = _format_report_bundle(cluster_reports)
    overview_md = generate_report_md("综合", period_name, report_date, overview_body)
    save_report_to_db(period_name, report_date, "综合", overview_md)


def run_job(target_period_name: str = None, target_date: Optional[datetime.date] = None, run_all_periods: bool = False):
    now = datetime.datetime.now()
    report_date = target_date or now.date()

    if run_all_periods:
        periods = PERIOD_ORDER
    elif target_period_name:
        periods = [target_period_name]
    else:
        cur_time = now.strftime("%H:%M")
        if "09:30" <= cur_time < "11:35":
            periods = ["overnight"]
        elif "11:30" <= cur_time < "13:05":
            periods = ["morning"]
        elif "13:00" <= cur_time < "15:05":
            periods = ["noon"]
        elif "15:00" <= cur_time < "15:30":
            periods = ["afternoon"]
        else:
            periods = ["overnight"]

    for period_name in periods:
        logger.info(f"Starting NewsAgent job for date={report_date} period={period_name}")
        build_and_save_period_reports(report_date, period_name)
        logger.info(f"NewsAgent job finished for date={report_date} period={period_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", help="Specify period (morning, noon, afternoon, overnight, all)")
    parser.add_argument("--date", help="Specify target date in YYYY-MM-DD format")
    parser.add_argument("--init", action="store_true", help="Initial run")
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()

    if args.init:
        now = datetime.datetime.now()
        cur_time = now.strftime("%H:%M")
        init_period = "overnight"
        if cur_time > "11:30":
            init_period = "morning"
        if cur_time > "13:00":
            init_period = "noon"
        if cur_time > "15:00":
            init_period = "afternoon"
        run_job(init_period, target_date=target_date)
    elif args.period:
        if args.period.lower() == "all":
            run_job(run_all_periods=True, target_date=target_date)
        else:
            run_job(args.period, target_date=target_date)
    else:
        logger.info("NewsAgent Monitor Mode started...")
        last_triggered_period = None
        while True:
            now = datetime.datetime.now()
            cur_time = now.strftime("%H:%M")
            trigger_map = {
                "11:30": "morning",
                "13:00": "noon",
                "15:00": "afternoon",
                "09:30": "overnight",
            }

            if cur_time in trigger_map and last_triggered_period != trigger_map[cur_time]:
                run_job(trigger_map[cur_time])
                last_triggered_period = trigger_map[cur_time]

            time.sleep(30)
