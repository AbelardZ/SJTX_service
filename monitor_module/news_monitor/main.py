import time
import random
import json
import re
import datetime
import threading
import os
import sys
import sqlite3
import pymysql
import traceback
from collections import deque

# Ensure project root and classifier modules path are available
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # SJTX_service/
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Import fetcher
try:
    from monitor_module.news_monitor.fetcher import fetch_latest_telegraphs
except ImportError:
    print("[ERROR] Could not import fetcher. Make sure fetcher.py serves fetch_latest_telegraphs.")
    def fetch_latest_telegraphs(): return []

# Import utils
try:
    from monitor_module.news_monitor.utils import get_table_name, get_segment, get_trading_date, is_trading_day
except ImportError:
    # Fallback utils
    def get_trading_date(dt): 
        if isinstance(dt, (int, float)): dt = datetime.datetime.fromtimestamp(dt)
        return dt.date()
    def is_trading_day(d): return True
    def get_segment(dt): return "Morning"
    def get_table_name(dt): return f"telegraph_{dt.strftime('%Y%m%d')}"

HOME_PC_IP = "100.75.180.70"
DB_PATH = os.path.join(current_dir, "news_buffer.db")
TABLE_DATE_RE = re.compile(r"^telegraph_(\d{4})_(\d{2})_(\d{2})(?:_.*)?$")
TABLE_DATE_RE_COMPACT = re.compile(r"^telegraph_(\d{8})(?:_.*)?$")

# Initialize classifier lazily
_classifier = None
def get_classifier():
    global _classifier
    if _classifier is None:
        try:
            from monitor_module.news_monitor.classifier_core.classifier import Classifier
            print("[INIT] Loading BERT Classifier...")
            _classifier = Classifier()
            print("[INIT] Classifier loaded.")
        except Exception as e:
            print(f"[ERROR] Failed to load classifier: {e}")
            # Ensure we don't retry immediately if it fails hard
            class DummyClassifier:
                def classify_multi(self, t, c): return [], {}, '其它'
            _classifier = DummyClassifier()
    return _classifier

seen_ids = set()
seen_id_queue = deque()
MAX_SEEN_IDS = 300000


def remember_seen_id(item_id):
    """记录已处理 ID，并限制内存占用。"""
    if item_id in seen_ids:
        return
    seen_ids.add(item_id)
    seen_id_queue.append(item_id)

    while len(seen_id_queue) > MAX_SEEN_IDS:
        old_id = seen_id_queue.popleft()
        seen_ids.discard(old_id)

def _map_to_other(label):
    if not label: return '其它'
    l = str(label).strip()
    if l.lower() in ('未分类', '其他', '其它', 'other', 'unknown'):
        return '其它'
    return l

def process_items(items):
    enriched = []
    clf = get_classifier()
    
    for item in items:
        title = item.get('title', '')
        content = item.get('content', '')
        
        # Ensure content exists
        if not content: content = ''
        item['content'] = content
        
        primary = '其它'
        labels = []
        scores = {}
        
        if clf:
            try:
                # classify_multi usage might vary, assuming it returns (labels, scores, primary)
                res = clf.classify_multi(title, content)
                if isinstance(res, tuple):
                    if len(res) == 3: labels, scores, primary = res
                    elif len(res) == 2: labels, scores = res; primary = labels[0] if labels else '其它'
            except Exception as e:
                print(f"[Classify Error] {e}")
                
        primary = _map_to_other(primary)
        labels = [_map_to_other(x) for x in (labels or [])]
        if '其它' not in labels and primary == '其它':
            labels.append('其它')
            
        item['primary_label'] = primary
        item['labels'] = labels
        item['scores'] = scores
        item['is_synced'] = 0 
        
        enriched.append(item)
    return enriched

def get_sqlite_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cleanup_sqlite_retention(conn, keep_days=5):
    """仅保留最近 keep_days 个交易逻辑日的 telegraph_* 表。"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%'")
    table_names = [r[0] for r in cur.fetchall()]
    if not table_names:
        return []

    date_to_tables = {}
    for name in table_names:
        m = TABLE_DATE_RE.match(name)
        if m:
            d = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m2 = TABLE_DATE_RE_COMPACT.match(name)
            if not m2:
                continue
            compact = m2.group(1)
            d = f"{compact[0:4]}-{compact[4:6]}-{compact[6:8]}"
        date_to_tables.setdefault(d, []).append(name)

    if len(date_to_tables) <= keep_days:
        return []

    sorted_dates = sorted(date_to_tables.keys(), reverse=True)
    keep_set = set(sorted_dates[:keep_days])
    drop_tables = []
    for d, tables in date_to_tables.items():
        if d not in keep_set:
            drop_tables.extend(tables)

    for t in drop_tables:
        cur.execute(f"DROP TABLE IF EXISTS `{t}`")

    # 同步清理 AI 报告缓存表（若存在）
    try:
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='news_agent_reports'")
        if cur.fetchone():
            keep_dates_csv = ",".join([f"'{d}'" for d in sorted_dates[:keep_days]])
            cur.execute(f"DELETE FROM news_agent_reports WHERE report_date NOT IN ({keep_dates_csv})")
    except Exception as e:
        print(f"[CLEANUP WARN] news_agent_reports cleanup failed: {e}")

    conn.commit()
    return drop_tables

def sync_worker():
    """Background worker to sync from local SQLite to remote MySQL"""
    print("[SYNC] Worker started.")
    while True:
        try:
            conn_sqlite = get_sqlite_conn()
            cursor_sqlite = conn_sqlite.cursor()
            
            # Identify tables
            cursor_sqlite.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%'")
            tables = [r[0] for r in cursor_sqlite.fetchall()]
            
            if not tables:
                conn_sqlite.close()
                time.sleep(10)
                continue

            # Connect to MySQL
            conn_mysql = None
            try:
                conn_mysql = pymysql.connect(
                    host=HOME_PC_IP,
                    user='inv_zhy',
                    password='zhy20050112',
                    database='NewsDB',
                    charset='utf8mb4',
                    connect_timeout=3
                )
            except Exception:
                # Remote not available
                conn_sqlite.close()
                time.sleep(30)
                continue
                
            remote_cursor = conn_mysql.cursor()
            synced_count = 0
            
            for table in tables:
                try:
                    # Get unsynced
                    cursor_sqlite.execute(f"SELECT * FROM `{table}` WHERE is_synced=0 LIMIT 50")
                    rows = cursor_sqlite.fetchall()
                    if not rows: continue
                    
                    # Columns
                    col_names = list(rows[0].keys())
                    
                    for row in rows:
                        row_dict = dict(row)
                        
                        # Prepare MySQL create table
                        create_sql = f"""CREATE TABLE IF NOT EXISTS `{table}` (
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
                            is_synced TINYINT(1) DEFAULT 1
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"""
                        remote_cursor.execute(create_sql)
                        
                        # Prepare insert
                        target_cols = ['id', 'title', 'content', 'brief', 'ctime', 'trading_date', 
                                     'is_trading_day', 'segment', 'primary_label', 'labels_json', 'scores_json']
                        
                        vals = []
                        valid_row = True
                        for c in target_cols:
                            v = row_dict.get(c)
                            if c == 'is_trading_day': 
                                v = int(v) if v is not None else 0
                            elif c == 'brief' and v is None:
                                v = ''
                            vals.append(v)
                            
                        placeholders = ','.join(['%s'] * len(target_cols))
                        # Use INSERT IGNORE to avoid key errors if sync retries
                        insert_sql = f"INSERT IGNORE INTO `{table}` ({','.join(target_cols)}, is_synced) VALUES ({placeholders}, 1)"
                        
                        try:
                            # If row exists, we update nothing or update title? Let's just ignore
                            remote_cursor.execute(insert_sql, vals)
                            
                            # Mark synced in SQLite
                            cursor_sqlite.execute(f"UPDATE `{table}` SET is_synced=1 WHERE id=?", (row_dict['id'],))
                            synced_count += 1
                        except Exception as e:
                            print(f"[SYNC INSERT ERROR] {e}")
                            
                    conn_mysql.commit()
                    conn_sqlite.commit()
                    
                except Exception as e:
                    print(f"[SYNC TABLE ERROR] {table}: {e}")
                    
            conn_sqlite.close()
            conn_mysql.close()
            
            if synced_count > 0:
                print(f"[SYNC] Synced {synced_count} items.")
                
        except Exception as e:
            print(f"[SYNC WORKER ERROR] {e}")
            
        time.sleep(5)

def main():
    print("[SYSTEM] Starting News Monitor (Fetch->Classify->SQLite->Sync)...")
    
    # Start sync thread
    t = threading.Thread(target=sync_worker, daemon=True)
    t.start()
    last_cleanup_at = 0
    
    while True:
        try:
            # 1. Fetch
            items = fetch_latest_telegraphs()
            
            # 2. Process
            processed_items = []
            if items:
                new_batch = [i for i in items if i['id'] not in seen_ids]
                
                if new_batch:
                    print(f"[FETCH] Got {len(new_batch)} new items.")
                    processed_items = process_items(new_batch)
            
            # 3. Save to SQLite
            if processed_items:
                conn = get_sqlite_conn()
                cursor = conn.cursor()
                saved_count = 0
                
                for item in processed_items:
                    try:
                        ctime_ts = item.get('ctime')
                        if not isinstance(ctime_ts, (int, float)): ctime_ts = time.time()
                        ctime = datetime.datetime.fromtimestamp(ctime_ts)
                        
                        table_name = get_table_name(ctime)
                        
                        # Create Table
                        create_sql = f"""CREATE TABLE IF NOT EXISTS `{table_name}` (
                            id INTEGER PRIMARY KEY,
                            title TEXT,
                            content TEXT,
                            brief TEXT,
                            ctime TIMESTAMP,
                            trading_date TEXT,
                            is_trading_day INTEGER,
                            segment TEXT,
                            primary_label TEXT,
                            labels_json TEXT,
                            scores_json TEXT,
                            is_synced INTEGER DEFAULT 0
                        )"""
                        cursor.execute(create_sql)
                        
                        sql = f"""INSERT OR IGNORE INTO `{table_name}` 
                                (id, title, content, brief, ctime, trading_date, is_trading_day, segment, primary_label, labels_json, scores_json, is_synced)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)"""
                                
                        td = get_trading_date(ctime)
                        itd = 1 if is_trading_day(td) else 0
                        
                        cursor.execute(sql, (
                            item['id'],
                            item.get('title',''),
                            item.get('content',''),
                            '',
                            ctime,
                            str(td),
                            itd,
                            get_segment(ctime),
                            item.get('primary_label'),
                            json.dumps(item.get('labels')),
                            json.dumps(item.get('scores'))
                        ))
                        
                        if cursor.rowcount > 0:
                            saved_count += 1
                            remember_seen_id(item['id'])
                            
                    except Exception as e:
                        print(f"[SAVE ERROR] Item {item.get('id')}: {e}")
                        
                conn.commit()
                conn.close()
                if saved_count > 0:
                    print(f"[STORE] Saved {saved_count} new items to SQLite.")

            # 4. Retention cleanup: 自动只保留最近5天
            now_ts = time.time()
            if now_ts - last_cleanup_at > 1800:
                try:
                    conn = get_sqlite_conn()
                    dropped = cleanup_sqlite_retention(conn, keep_days=5)
                    conn.close()
                    if dropped:
                        print(f"[CLEANUP] Dropped old tables: {len(dropped)}")
                except Exception as ce:
                    print(f"[CLEANUP ERROR] {ce}")
                last_cleanup_at = now_ts
            
            time.sleep(random.randint(20, 40))
            
        except Exception as e:
            traceback.print_exc()
            time.sleep(10)

if __name__ == "__main__":
    # Start NewsAgent worker thread
    try:
        from monitor_module.news_monitor.newsagent.agent_worker import run_job
        def agent_monitor_loop():
            # Initial Run
            try:
                print("[AIAGENT] Initializing NewsAI Agent...")
                run_job() # Initial run for current/last period
            except Exception as ae:
                print(f"[AIAGENT INIT ERROR] {ae}")

            # 记录当日每个触发点是否已执行，避免跨天被错误去重
            triggered_keys = set()

            # 触发点: 在报告期结束时触发对应报告
            trigger_points = [
                ("09:30", "overnight"),
                ("11:30", "morning"),
                ("13:00", "noon"),
                ("15:00", "afternoon"),
            ]

            print("[AIAGENT] NewsAI Agent monitor thread started.")
            while True:
                now = datetime.datetime.now()

                # 清理两天前的 key，防止集合无限增长
                if len(triggered_keys) > 40:
                    today = now.date()
                    keep = set()
                    for key in triggered_keys:
                        try:
                            d = datetime.datetime.strptime(key.split("|")[0], "%Y-%m-%d").date()
                            if (today - d).days <= 1:
                                keep.add(key)
                        except Exception:
                            pass
                    triggered_keys = keep

                for hhmm, period in trigger_points:
                    h, m = map(int, hhmm.split(":"))
                    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    delta = (now - target).total_seconds()

                    # 在触发点后的 0~89 秒内执行一次，避免线程漂移错过
                    if 0 <= delta < 90:
                        key = f"{now.date().isoformat()}|{period}|{hhmm}"
                        if key not in triggered_keys:
                            try:
                                print(f"[AIAGENT] Triggering job for {period} at {hhmm}")
                                run_job(period)
                            except Exception as ae:
                                print(f"[AIAGENT ERROR] {ae}")
                            triggered_keys.add(key)

                time.sleep(10)
        
        agent_thread = threading.Thread(target=agent_monitor_loop, daemon=True)
        agent_thread.start()
    except Exception as e:
        print(f"[AIAGENT SETUP ERROR] {e}")

    main()
