# -*- coding: utf-8 -*-
import time
import sqlite3
import pymysql
import os
import logging
from monitor_module.news_monitor.config import DB_CONFIG
from monitor_module.news_monitor.db_proxy import HOME_PC_IP, LOCAL_DB_FILE

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_remote_conn():
    remote_config = DB_CONFIG.copy()
    remote_config['host'] = HOME_PC_IP
    remote_config['connect_timeout'] = 5
    return pymysql.connect(**remote_config)

def sync_data():
    """将本地 SQLite 的新数据同步到远程 MySQL"""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOCAL_DB_FILE)
    
    if not os.path.exists(db_path):
        return

    # 1. 连接本地 SQLite
    try:
        local_conn = sqlite3.connect(db_path)
        local_cursor = local_conn.cursor()
    except Exception as e:
        logger.error(f"Failed to connect to local SQLite: {e}")
        return

    # 获取所有表名
    try:
        local_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in local_cursor.fetchall() if t[0].startswith("telegraph_")]
    except Exception as e:
        logger.error(f"Failed to list tables: {e}")
        local_conn.close()
        return

    if not tables:
        local_conn.close()
        return

    # 2. 尝试连接远程 MySQL
    try:
        remote_conn = get_remote_conn()
        logger.info(f"Connected to Remote MySQL ({HOME_PC_IP})")
    except Exception as e:
        # 这个日志可以不用打这么勤
        local_conn.close()
        return

    # 3. 开始同步
    try:
        with remote_conn.cursor() as remote_cursor:
            for table_name in tables:
                # 确保远程表存在 (MySQL 语法)
                create_sql = f"""
                    CREATE TABLE IF NOT EXISTS `{table_name}` (
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
                        scores_json TEXT
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
                remote_cursor.execute(create_sql)

                # 检查 is_synced 列是否存在
                has_synced_col = False
                try:
                    local_cursor.execute(f"PRAGMA table_info(`{table_name}`)")
                    cols = local_cursor.fetchall()
                    has_synced_col = any(c[1] == 'is_synced' for c in cols)
                except: pass

                # 只读取未同步的数据
                query = f"SELECT * FROM `{table_name}`"
                if has_synced_col:
                    query += " WHERE is_synced = 0"
                
                local_cursor.execute(query)
                rows = local_cursor.fetchall()
                
                if not rows:
                    continue

                # 获取列名 (排除 is_synced)
                col_names = [description[0] for description in local_cursor.description]
                data_indices = [i for i, name in enumerate(col_names) if name != 'is_synced']
                target_cols = [col_names[i] for i in data_indices]
                
                cols_str = ", ".join([f"`{c}`" for c in target_cols])
                placeholders = ", ".join(["%s"] * len(target_cols))
                
                # 过滤后的数据行
                filtered_rows = []
                for row in rows:
                    filtered_rows.append(tuple(row[i] for i in data_indices))

                logger.info(f"Syncing {len(filtered_rows)} new rows from table {table_name}...")
                
                insert_sql = f"INSERT IGNORE INTO `{table_name}` ({cols_str}) VALUES ({placeholders})"
                remote_cursor.executemany(insert_sql, filtered_rows)
                remote_conn.commit()
                
                # 更新本地标记
                if has_synced_col:
                    ids = [row[0] for row in filtered_rows] # 假设第一列是 id
                    # SQLite 不支持 executemany 里的复杂 where
                    for _id in ids:
                        local_cursor.execute(f"UPDATE `{table_name}` SET is_synced = 1 WHERE id = ?", (_id,))
                    local_conn.commit()
                    logger.info(f"Marked {len(ids)} rows as synced in {table_name}.")
                
    except Exception as e:
        logger.error(f"Sync Error: {e}")
        remote_conn.rollback()
    finally:
        remote_conn.close()
        local_conn.close()

def prune_local_data(days=3):
    """清理本地 SQLite 缓冲，仅保留最近 X 天的数据"""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOCAL_DB_FILE)
    if not os.path.exists(db_path): return
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cur.fetchall() if t[0].startswith("telegraph_")]
        
        # 解析表名中的时间 telegraph_YYYY_MM_DD_...
        import datetime as dt
        now = dt.datetime.now()
        
        for table in tables:
            try:
                # 提取日期部分
                parts = table.split('_')
                if len(parts) >= 4:
                    date_str = f"{parts[1]}-{parts[2]}-{parts[3]}"
                    table_date = dt.datetime.strptime(date_str, "%Y-%m-%d")
                    if (now - table_date).days >= days:
                        cur.execute(f"DROP TABLE IF EXISTS `{table}`")
                        logger.info(f"Pruned old table: {table}")
            except:
                continue
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Prune Error: {e}")

def start_sync_thread():
    """在后台线程启动同步和清理任务"""
    import threading
    def run():
        logger.info("Background Sync & Prune Worker Started.")
        last_prune = 0
        while True:
            try:
                sync_data()
                # 每 1 小时清理一次旧数据
                if time.time() - last_prune > 3600:
                    prune_local_data(days=3)
                    last_prune = time.time()
            except Exception as e:
                logger.error(f"Sync thread error: {e}")
            time.sleep(60)
    
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    logger.info("Starting Sync Worker in standalone mode...")
    while True:
        sync_data()
        # 每 60 秒检查一次
        time.sleep(60)
