from flask import Blueprint, render_template, request, Response, jsonify
import queue
import json
import time
import threading
import pymysql
import datetime
import os
import sqlite3

monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor')

POLL_INTERVAL = 5
LATEST_LIMIT = 500

# Fix the DB Path to work inside Docker container (mapped to /app) or locally
# Assuming Web/routes/monitor2.py -> ../../news_monitor/news_buffer.db
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQLITE_DB_PATH = os.path.join(BASE_DIR, 'news_monitor', 'news_buffer.db')

LABEL_GROUPS = [
    {'name': '市场金融', 'tags': ['交易提示', '公司公告', '机构观点和策略', '金融部门事务']},
    {'name': '行业科技', 'tags': ['行业消息', '行业数据', '重要主体动态', '科学技术前沿动态']},
    {'name': '国内政策', 'tags': ['国内政治动态', '国内一般指导', '国内一般政策', '国内政府动向']},
    {'name': '国际事务', 'tags': ['一般国际事务', '国际一般政策', '国际金融政策', '重要国家内政', '地缘政治动态']},
    {'name': '宏观数据', 'tags': ['国内宏观数据', '国际宏观数据']},
    {'name': '其它事件', 'tags': ['自然事件', '社会事件', '新闻集合', '其它']}
]
LABEL_OPTIONS = ['全部'] + [tag for group in LABEL_GROUPS for tag in group['tags']]

_latest_cache = []
_last_seen_ids = set()
_lock = threading.Lock()

class MessageAnnouncer:
    def __init__(self):
        self.listeners = []

    def listen(self):
        q = queue.Queue(maxsize=100)
        self.listeners.append(q)
        return q

    def announce(self, msg):
        for i in reversed(range(len(self.listeners))):
            try:
                self.listeners[i].put_nowait(msg)
            except queue.Full:
                del self.listeners[i]

announcer = MessageAnnouncer()

def _to_unix_ts(value):
    if value is None:
        return int(time.time())
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return int(datetime.datetime.strptime(value, fmt).timestamp())
            except ValueError:
                continue
        try:
            return int(datetime.datetime.fromisoformat(value).timestamp())
        except ValueError:
            return int(time.time())
    return int(time.time())

def _row_to_message(item):
    labels_raw = item.get('labels_json')
    try:
        labels = json.loads(labels_raw) if labels_raw else []
    except Exception:
        labels = []

    return {
        'id': item.get('id'),
        'title': item.get('title') or '',
        'content': item.get('content') or '',
        'ctime': _to_unix_ts(item.get('ctime')),
        'labels': labels,
        'primary_label': item.get('primary_label') or '其它'
    }

def _get_sqlite_conn():
    try:
        if not os.path.exists(SQLITE_DB_PATH):
            print(f"SQLite DB not found at: {SQLITE_DB_PATH}")
            return None
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"SQLite Connect Error: {e}")
        return None

def _poll_function():
    global _latest_cache
    
    while True:
        try:
            conn = _get_sqlite_conn()
            if not conn:
                time.sleep(5)
                continue
                
            cursor = conn.cursor()
            
            # Find latest table in SQLite
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%' ORDER BY name DESC LIMIT 1")
            row = cursor.fetchone()
            
            if row:
                target_table = row[0]
                
                # Fetch new items > last_seen_id? Or just fetch latest 20 and diff
                # Since multiple clients might connect, we just keep a server-side cache of "latest"
                # But actually SSE pushes updates.
                
                # Fetch recent items
                cursor.execute(f"SELECT * FROM `{target_table}` ORDER BY id DESC LIMIT 50")
                rows = cursor.fetchall()
                
                new_items = []
                for r in rows:
                    item = dict(r)
                    if item['id'] not in _last_seen_ids:
                        _last_seen_ids.add(item['id'])
                        new_items.append(item)
                
                if new_items:
                    # Sort by id asc to announce in order
                    new_items.sort(key=lambda x: x['id'])
                    
                    for item in new_items:
                        msg = _row_to_message(item)
                        announcer.announce(msg)
                        _latest_cache.insert(0, msg)
                        
                    # Trim cache
                    if len(_latest_cache) > LATEST_LIMIT:
                        _latest_cache = _latest_cache[:LATEST_LIMIT]
            
            conn.close()
            time.sleep(3)
            
        except Exception as e:
            print(f"Polling Error: {e}")
            time.sleep(5)

# Start background thread
t = threading.Thread(target=_poll_function, daemon=True)
t.start()

def _normalize_label(label=None):
    if not label: return '全部'
    if label in LABEL_OPTIONS: return label
    return '全部'

@monitor_bp.route('/')
def index():
    return render_template('monitor_index.html')

@monitor_bp.route('/telegraph')
def telegraph_live():
    initial = _normalize_label(request.args.get('label'))
    return render_template('telegraph.html', 
        label_groups=LABEL_GROUPS, 
        labels=LABEL_OPTIONS,
        initial=initial,
        trading_status='Trading')

@monitor_bp.route('/telegraph/init')
def telegraph_init():
    conn = _get_sqlite_conn()
    if not conn:
        return jsonify([])

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%' ORDER BY name DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return jsonify([])

        target_table = row[0]
        cursor.execute(f"SELECT * FROM `{target_table}` ORDER BY id DESC LIMIT 200")
        rows = cursor.fetchall()
        messages = [_row_to_message(dict(r)) for r in rows]

        with _lock:
            global _latest_cache
            _latest_cache = messages[:LATEST_LIMIT]

        return jsonify(messages)
    except Exception as e:
        print(f"Init Query Error: {e}")
        return jsonify([])
    finally:
        conn.close()

@monitor_bp.route('/telegraph/stream')
def telegraph_stream():
    def stream():
        messages = announcer.listen()  # Get a queue for this client
        while True:
            try:
                msg = messages.get(timeout=5)  # Block until message
                yield f'data: {json.dumps(msg)}\n\n'
            except queue.Empty:
                yield f'data: {json.dumps({"ping": time.time()})}\n\n' # Keepalive
            except GeneratorExit:
                break
    return Response(stream(), mimetype='text/event-stream')

