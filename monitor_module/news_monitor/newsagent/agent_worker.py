import datetime
import json
import logging
import os
import sqlite3
import time
from typing import List, Dict, Any, Optional

import pymysql
from openai import OpenAI

# 导入配置
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from monitor_module.news_monitor.config import DB_CONFIG
from monitor_module.news_monitor.db_proxy import HOME_PC_IP, LOCAL_DB_FILE

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("NewsAgent")

# AI 配置 (从 llm.py 迁移/引用)
API_KEY = 'sk-epawyaxfrulzqtpwanuabiytcbdewibpuxbwgrjsbobpuhhx'
MODEL_NAME = "deepseek-ai/DeepSeek-V3.2"
BASE_URL = "https://api.siliconflow.cn/v1"

System_Prompt = '''
你是我的A股投资研究团队的一员，专门负责追踪和分析新闻消息，
你将24小时不间断地收到来自其它部门推送的新闻消息，这些新闻按照一定的逻辑被分类:
    {'name': '市场金融', 'tags': ['交易提示', '公司公告', '机构观点和策略', '金融部门事务']},
    {'name': '行业科技', 'tags': ['行业消息', '行业数据', '重要主体动态', '科学技术前沿动态']},
    {'name': '国内政策', 'tags': ['国内政治动态', '国内一般指导', '国内一般政策', '国内政府动向']},
    {'name': '国际事务', 'tags': ['一般国际事务', '国际一般政策', '国际金融政策', '重要国家内政', '地缘政治动态']},
    {'name': '宏观数据', 'tags': ['国内宏观数据', '国际宏观数据']},
    {'name': '事件其它', 'tags': ['自然事件', '社会事件', '新闻集合', '其它']}
你需要认真阅读、分析和总结，每隔一段时间向我报告。你的报告应该包括：报告期内市场上值得引起交易关注的重大事件和解读（可能引起哪个板块、概念或者个股的变动）；市场上发生的重大交易状况等。
报告期包括：
morning 9:30-11:30
noon 11:30-13:00
afternoon 13:00-15:00
overnight 15:00-9:30 四个部分。
'''

# 报告期定义
PERIODS = [
    {"name": "morning", "start": "09:30", "end": "11:30"},
    {"name": "noon", "start": "11:30", "end": "13:00"},
    {"name": "afternoon", "start": "13:00", "end": "15:00"},
    {"name": "overnight", "start": "15:00", "end": "09:30"} # 跨天处理
]

def get_db_connection():
    """获取云端数据库连接"""
    try:
        return pymysql.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"Failed to connect to cloud DB: {e}")
        return None

def get_local_db_connection():
    """获取本地 SQLite 连接"""
    db_path = os.path.join(project_root, LOCAL_DB_FILE)
    try:
        return sqlite3.connect(db_path)
    except Exception as e:
        logger.error(f"Failed to connect to local DB: {e}")
        return None


def _period_time_range(period_name: str, date: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    """返回指定报告期对应的时间范围。"""
    p_info = next(p for p in PERIODS if p["name"] == period_name)
    start_time_str = p_info["start"]
    end_time_str = p_info["end"]

    if period_name == "overnight":
        end_dt = datetime.datetime.combine(date, datetime.time.fromisoformat(end_time_str))
        start_dt = datetime.datetime.combine(date - datetime.timedelta(days=1), datetime.time.fromisoformat(start_time_str))
    else:
        start_dt = datetime.datetime.combine(date, datetime.time.fromisoformat(start_time_str))
        end_dt = datetime.datetime.combine(date, datetime.time.fromisoformat(end_time_str))
    return start_dt, end_dt


def _candidate_tables_for_period(cursor: sqlite3.Cursor, date: datetime.date) -> List[str]:
    """按交易日表命名规则挑选候选表。"""
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
    # 去重并排序，保证输出稳定
    return sorted(set(tables))

def get_current_period() -> Optional[Dict]:
    """根据当前时间判断处于哪个报告期"""
    now = datetime.datetime.now()
    cur_time = now.strftime("%H:%M")
    
    # 特殊处理 overnight 跨天
    if cur_time >= "15:00" or cur_time < "09:30":
        return PERIODS[3] # overnight
    
    for p in PERIODS:
        if p["start"] <= cur_time < p["end"]:
            return p
    return None

def get_news_for_period(period_name: str, date: datetime.date) -> List[Dict]:
    """获取指定日期和报告期的新闻（优先 SQLite 缓存）。"""
    conn = get_local_db_connection()
    if not conn:
        return []

    news_list: List[Dict] = []
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
                        "label": primary_label or "其它",
                    })
            except Exception as e:
                logger.warning(f"Error querying table {tbl}: {e}")
    finally:
        conn.close()

    return news_list

def generate_report(period_name: str, news: List[Dict]) -> str:
    """调用 LLM 生成报告"""
    if not news:
        return f"在 {period_name} 报告期内未收到重要新闻。"

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    
    # 格式化新闻流
    news_text = ""
    for idx, item in enumerate(news):
        news_text += f"[{idx+1}] 时间: {item['time']} | 分类: {item['label']}\n标题: {item['title']}\n内容: {item['content']}\n\n"

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": System_Prompt},
                {"role": "user", "content": f"以下是 {period_name} 报告期的新闻流：\n\n{news_text}\n请根据以上内容生成分析报告。"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM API Error: {e}")
        return f"生成报告失败: {e}"

def save_report_to_db(period_name: str, date: datetime.date, report_content: str):
    """
    将报告存储到数据库。
    存储逻辑：
    1. 本地文件: 保存到 newsagent/saved_reports
    2. 云端 MySQL: 可选写入 news_agent_reports 表
    """
    # 1) 先写本地文件（按需求，不再写 SQLite 报告表）
    local_path = "/home/ubuntu/SJTX_service/news_monitor/newsagent/saved_reports"
    try:
        os.makedirs(local_path, exist_ok=True)
        filename = f"report_{date.strftime('%Y%m%d')}_{period_name}.md"
        file_path = os.path.join(local_path, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Report for {date} {period_name} saved to file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to save report file for {date} {period_name}: {e}")
        return

    # 2) 可选写入 MySQL（存在则写，不存在不阻塞）
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS `news_agent_reports` (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        report_date DATE,
                        period VARCHAR(20),
                        content TEXT,
                        created_at DATETIME,
                        is_synced TINYINT(1) DEFAULT 0,
                        UNIQUE KEY `idx_date_period` (report_date, period)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
                cursor.execute("""
                    INSERT INTO `news_agent_reports` (report_date, period, content, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE content = VALUES(content), created_at = VALUES(created_at), is_synced = 0
                """, (date, period_name, report_content, datetime.datetime.now()))
                conn.commit()
                logger.info(f"Report for {date} {period_name} saved to Cloud DB.")
        finally:
            conn.close()

    # 触发同步逻辑 (如果 sync_worker 稍后改造能涵盖这个文件夹，或者手动调用)
    sync_report_to_home(date, period_name, report_content)

def sync_report_to_home(date, period_name, content):
    """尝试将报告同步到本地电脑（通过 Tailscale IP）"""
    # 用户要求：一旦能够连接到本地电脑则及时同步。
    # 这里可以尝试通过 SSH 或者 远程 MySQL 同步。
    # 鉴于 sync_worker.py 已经有远程连接逻辑，我们可以借用。
    remote_config = DB_CONFIG.copy()
    remote_config['host'] = HOME_PC_IP
    remote_config['connect_timeout'] = 3
    
    try:
        remote_conn = pymysql.connect(**remote_config)
        with remote_conn.cursor() as cursor:
             # 在远程也创建同样的表
             cursor.execute("""
                    CREATE TABLE IF NOT EXISTS `news_agent_reports` (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        report_date DATE,
                        period VARCHAR(20),
                        content TEXT,
                        created_at DATETIME,
                        UNIQUE KEY `idx_date_period` (report_date, period)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
             cursor.execute("""
                    INSERT INTO `news_agent_reports` (report_date, period, content, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE content = VALUES(content), created_at = VALUES(created_at)
                """, (date, period_name, content, datetime.datetime.now()))
             remote_conn.commit()
             logger.info(f"Report for {date} {period_name} synced to Home PC.")
        remote_conn.close()
    except Exception as e:
        logger.info(f"Home PC not reachable or sync failed: {e}")

def run_job(target_period_name: str = None):
    """执行任务：获取新闻 -> 生成报告 -> 存储"""
    now = datetime.datetime.now()
    date = now.date()
    
    # 如果没指定，则自动判断当前应该结束的那个报告期
    # (实际上定时器应该在 11:30, 13:00, 15:00, 09:30 触发)
    if not target_period_name:
        cur_time = now.strftime("%H:%M")
        if "09:30" <= cur_time < "11:35": target_period_name = "overnight" # 注意 09:30 触发的是 overnight
        elif "11:30" <= cur_time < "13:05": target_period_name = "morning"
        elif "13:00" <= cur_time < "15:05": target_period_name = "noon"
        elif "15:00" <= cur_time < "15:30": target_period_name = "afternoon"
        else: target_period_name = "overnight"

    logger.info(f"Starting NewsAgent job for period: {target_period_name}")
    news = get_news_for_period(target_period_name, date)
    if not news:
        logger.warning(f"No news found for {target_period_name}")
        # 即使没新闻也记录一下？或者跳过
    
    report = generate_report(target_period_name, news)
    save_report_to_db(target_period_name, date, report)
    logger.info(f"NewsAgent job finished for {target_period_name}")

if __name__ == "__main__":
    # 初始化执行：执行最近的一个报告期
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", help="Specify period (morning, noon, afternoon, overnight)")
    parser.add_argument("--init", action="store_true", help="Initial run")
    args = parser.parse_args()

    if args.init:
        # 初始化时，获取当前所属期（或者前一个期）进行总结
        # 简单起见，直接获取当前状态
        now = datetime.datetime.now()
        cur_time = now.strftime("%H:%M")
        # 根据当前时间推测要初始化的那个期
        init_period = "overnight"
        if cur_time > "11:30": init_period = "morning"
        if cur_time > "13:00": init_period = "noon"
        if cur_time > "15:00": init_period = "afternoon"
        
        run_job(init_period)
    elif args.period:
        run_job(args.period)
    else:
        # 定时监控模式：每个报告期结束执行一次
        # 由于我们可能用外部 cron，这里可以写一个简单的 loop
        logger.info("NewsAgent Monitor Mode started...")
        last_triggered_period = None
        while True:
            now = datetime.datetime.now()
            cur_time = now.strftime("%H:%M")
            
            # 检查触发点
            trigger_map = {
                "11:30": "morning",
                "13:00": "noon",
                "15:00": "afternoon",
                "09:30": "overnight"
            }
            
            if cur_time in trigger_map and last_triggered_period != trigger_map[cur_time]:
                run_job(trigger_map[cur_time])
                last_triggered_period = trigger_map[cur_time]
            
            time.sleep(30) # 每 30 秒查一次
