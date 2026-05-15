# storage_mysql.py
import pymysql
import json
import time
from datetime import datetime
from monitor_module.news_monitor.utils import get_segment, get_table_name, is_trading_day, get_trading_date
from monitor_module.news_monitor.config import DB_CONFIG
from monitor_module.news_monitor.db_proxy import get_smart_connection

def get_connection():
    # 使用智能连接代理
    conn, mode = get_smart_connection()
    return conn

def _clean_content_title(title: str, content: str) -> str:
    """简化版内容清理：只清除【】格式的标题前缀。"""
    if not title or not content:
        return content
    title = title.strip()
    if not title:
        return content
    # 简化的清理逻辑：如果内容以【标题】开始，只保留【】之后的内容
    bracketed_title = f'【{title}】'
    if content.startswith(bracketed_title):
        remaining = content[len(bracketed_title):].lstrip()
        return remaining if remaining else content
    return content

def save_to_database(items):
    """
    保存条目到 NewsDB。
    items 应当包含 classification 字段 (primary_label, labels_json 等)，如果未分类则为 None。
    """
    conn = get_connection()
    cursor = conn.cursor()

    for item in items:
        ctime_ts = item.get('ctime')
        if not isinstance(ctime_ts, (int, float)):
             ctime_ts = time.time()
        ctime = datetime.fromtimestamp(ctime_ts)
        
        table = get_table_name(ctime)
        segment = get_segment(ctime)
        trading_date = get_trading_date(ctime)
        trading_flag = is_trading_day(trading_date)

        title = item.get('title', '')
        content = item.get('content', '')
        if not content.strip():
            content = item.get('brief', '')
        cleaned_content = _clean_content_title(title, content)

        # 确保表存在，包含分类字段和同步标记字段
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS `{table}` (
                id BIGINT PRIMARY KEY,
                title TEXT,
                content TEXT,
                brief TEXT,
                ctime DATETIME,
                trading_date DATE,
                is_trading_day TINYINT(1),
                segment VARCHAR(20),
                primary_label VARCHAR(64),
                labels_json TEXT,
                scores_json TEXT,
                is_synced TINYINT(1) DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        cursor.execute(create_sql)
        
        # 简单的列检查与补全 (SQLite 不支持在一行 ADD 多列)
        columns_to_add = [
            ("primary_label", "VARCHAR(64)"),
            ("labels_json", "TEXT"),
            ("scores_json", "TEXT"),
            ("is_synced", "TINYINT(1) DEFAULT 0")
        ]
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"SELECT `{col_name}` FROM `{table}` LIMIT 1")
            except Exception:
                try:
                    cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col_name}` {col_type}")
                except Exception:
                    pass

        # 准备数据
        # 如果上游在 main.py 里已经做了分类，item 里会有 primary_label 等
        # 如果没有，则为 None
        primary_label = item.get('primary_label')
        labels_json = json.dumps(item.get('labels', []), ensure_ascii=False) if item.get('labels') else None
        scores_json = json.dumps(item.get('scores', {}), ensure_ascii=False) if item.get('scores') else None

        cursor.execute(f"""
            INSERT INTO `{table}`
            (id, title, content, ctime, trading_date, is_trading_day, segment, primary_label, labels_json, scores_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                title=VALUES(title),
                content=VALUES(content),
                ctime=VALUES(ctime), 
                primary_label=VALUES(primary_label),
                labels_json=VALUES(labels_json),
                scores_json=VALUES(scores_json)
        """, (
            item['id'],
            title,
            cleaned_content,
            ctime,
            trading_date,
            int(trading_flag),
            segment,
            primary_label,
            labels_json,
            scores_json
        ))

    conn.commit()
    conn.close()
