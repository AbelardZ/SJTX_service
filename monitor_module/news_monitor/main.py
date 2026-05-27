import time
import random
import json
import re
import datetime
import threading
import os
import sys
import sqlite3
import traceback
from collections import deque
from pathlib import Path
import gc

try:
    import ctypes
except Exception:
    ctypes = None

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
MAX_SEEN_IDS = 50000


def _trim_memory():
    """尽量把 Python 和 libc 层已经释放的内存还给系统。"""
    try:
        gc.collect()
    except Exception:
        pass

    if ctypes is None or os.name != "posix":
        return

    try:
        libc = ctypes.CDLL("libc.so.6")
        if hasattr(libc, "malloc_trim"):
            libc.malloc_trim(0)
    except Exception:
        pass


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

def main():
    print("[SYSTEM] Starting News Monitor (Fetch->Classify->SQLite)...")
    
    last_cleanup_at = 0
    last_trim_at = 0
    
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

            if now_ts - last_trim_at > 300:
                _trim_memory()
                last_trim_at = now_ts
            
            time.sleep(random.randint(20, 40))
            
        except Exception as e:
            traceback.print_exc()
            _trim_memory()
            time.sleep(10)

if __name__ == "__main__":
    # Start NewsAgent worker thread
    try:
        import subprocess as _subprocess
        from monitor_module.news_monitor.newsagent.agent_worker import REPORTS_DIR

        # 用文件标记已完成的 job，崩溃重启后不会遗漏也不会重复
        def _job_done_marker_path(report_date, period_name):
            return Path(REPORTS_DIR) / report_date.isoformat() / period_name / ".done"

        def _job_doing_marker_path(report_date, period_name):
            return Path(REPORTS_DIR) / report_date.isoformat() / period_name / ".doing"

        def _is_job_done(report_date, period_name):
            return _job_done_marker_path(report_date, period_name).exists()

        def _is_job_doing(report_date, period_name):
            return _job_doing_marker_path(report_date, period_name).exists()

        def _mark_job_done(report_date, period_name):
            p = _job_done_marker_path(report_date, period_name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(datetime.datetime.now().isoformat())
            # 清理 .doing 锁
            dp = _job_doing_marker_path(report_date, period_name)
            if dp.exists():
                dp.unlink()

        def _run_job_in_subprocess(period, report_date):
            """在独立子进程中执行 run_job，避免 LLM 调用 OOM 拖垮主进程。"""
            # 写入 .doing 锁，防止并发
            dp = _job_doing_marker_path(report_date, period)
            dp.parent.mkdir(parents=True, exist_ok=True)
            dp.write_text(str(os.getpid()))

            script = str(Path(__file__).resolve().parent / "newsagent" / "agent_worker.py")
            cmd = [
                sys.executable, script,
                "--period", period,
                "--date", report_date.isoformat(),
            ]
            print(f"[AIAGENT] Launching subprocess: {' '.join(cmd)}")
            try:
                proc = _subprocess.Popen(cmd, cwd=str(project_root))
                ret = proc.wait()
                if ret != 0:
                    raise RuntimeError(f"Subprocess exited with code {ret}")
            finally:
                # 无论成功失败都清理 .doing 锁
                if dp.exists():
                    dp.unlink()
            print(f"[AIAGENT] Subprocess done: {period} (date={report_date})")

        def agent_monitor_loop():
            # 触发点: 时段结束后 60 秒触发，确保该时段数据已完整入库
            # (触发时间, 对应时段, 数据所属日期偏移)
            trigger_points = [
                ("09:31", "overnight", 0),    # overnight 属于当天 00:00-09:30
                ("11:31", "morning", 0),
                ("13:01", "noon", 0),
                ("15:01", "afternoon", 0),
            ]

            print("[AIAGENT] NewsAI Agent monitor thread started (post-period trigger mode, subprocess).")
            while True:
                now = datetime.datetime.now()

                for hhmm, period, date_offset in trigger_points:
                    h, m = map(int, hhmm.split(":"))
                    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    delta = (now - target).total_seconds()

                    report_date = (now + datetime.timedelta(days=date_offset)).date()

                    # 触发点已过 且 未完成 且 未在执行中 → 执行（含崩溃后补跑）
                    if delta >= 0 and not _is_job_done(report_date, period) and not _is_job_doing(report_date, period):
                        try:
                            print(f"[AIAGENT] Triggering job for {period} (date={report_date}) at {now.strftime('%H:%M:%S')}")
                            _run_job_in_subprocess(period, report_date)
                            _mark_job_done(report_date, period)
                            print(f"[AIAGENT] Job marked done: {period} (date={report_date})")
                        except Exception as ae:
                            print(f"[AIAGENT ERROR] {ae}")
                            import traceback
                            traceback.print_exc()

                time.sleep(15)
        
        agent_thread = threading.Thread(target=agent_monitor_loop, daemon=True)
        agent_thread.start()
    except Exception as e:
        print(f"[AIAGENT SETUP ERROR] {e}")
        import traceback
        traceback.print_exc()

    main()
