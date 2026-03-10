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

# Ensure classifier modules path is available
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Import fetcher
try:
    from fetcher import fetch_latest_telegraphs
except ImportError:
    print("[ERROR] Could not import fetcher. Make sure fetcher.py serves fetch_latest_telegraphs.")
    def fetch_latest_telegraphs(): return []

# Import utils
try:
    from utils import get_table_name, get_segment, get_trading_date, is_trading_day
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

# Initialize classifier lazily
_classifier = None
def get_classifier():
    global _classifier
    if _classifier is None:
        try:
            from classifier_core.classifier import Classifier
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
                            seen_ids.add(item['id'])
                            
                    except Exception as e:
                        print(f"[SAVE ERROR] Item {item.get('id')}: {e}")
                        
                conn.commit()
                conn.close()
                if saved_count > 0:
                    print(f"[STORE] Saved {saved_count} new items to SQLite.")
            
            time.sleep(random.randint(20, 40))
            
        except Exception as e:
            traceback.print_exc()
            time.sleep(10)

if __name__ == "__main__":
    main()
