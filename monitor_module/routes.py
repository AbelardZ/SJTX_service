from flask import Blueprint, render_template, request, Response, jsonify
import queue
import json
import time
import threading
import datetime
import os
import sqlite3
import glob
import re
from pathlib import Path

from monitor_module.news_monitor.paths import REPORTS_DIR

# ============================================================
# monitor_bp — 实时电报直播 (SQLite)
# ============================================================
monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor', template_folder='templates')

POLL_INTERVAL = 5
LATEST_LIMIT = 500

_MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = _MODULE_DIR.parent
SQLITE_DB_PATH = str(_MODULE_DIR / 'news_monitor' / 'news_buffer.db')

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
_MAX_SEEN_IDS = 100000  # 防止内存无限增长
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
        'primary_label': item.get('primary_label') or '其它',
        'segment': item.get('segment') or ''
    }


def _list_recent_tables(cursor, days=3):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%' ORDER BY name DESC")
    table_names = [r[0] for r in cursor.fetchall()]
    if not table_names:
        return []

    selected = []
    date_keys = []
    for name in table_names:
        parts = name.split('_')
        if len(parts) < 4:
            continue
        date_key = '_'.join(parts[1:4])
        if date_key not in date_keys:
            date_keys.append(date_key)
        if len(date_keys) > days:
            break
        selected.append(name)
    return selected


def _list_tables_for_date(cursor, date_str):
    date_key = date_str.replace('-', '_')
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ? ORDER BY name DESC",
        (f"telegraph_{date_key}%",)
    )
    return [r[0] for r in cursor.fetchall()]


def _list_available_dates(cursor, limit=30):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%' ORDER BY name DESC")
    table_names = [r[0] for r in cursor.fetchall()]
    dates = []
    for name in table_names:
        parts = name.split('_')
        if len(parts) < 4:
            continue
        ds = f"{parts[1]}-{parts[2]}-{parts[3]}"
        if ds not in dates:
            dates.append(ds)
        if len(dates) >= limit:
            break
    return dates


def _load_messages_from_tables(cursor, tables, period='all', limit=5000):
    messages = []
    seen_ids = set()
    for table_name in tables:
        try:
            if period and period != 'all':
                cursor.execute(
                    f"SELECT * FROM `{table_name}` WHERE segment=? ORDER BY ctime DESC LIMIT ?",
                    (period, limit)
                )
            else:
                cursor.execute(f"SELECT * FROM `{table_name}` ORDER BY ctime DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            for r in rows:
                d = dict(r)
                row_id = d.get('id')
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                messages.append(_row_to_message(d))
        except Exception as e:
            print(f"Table read failed: {table_name}, {e}")
            continue

    messages.sort(key=lambda x: x.get('ctime', 0), reverse=True)
    return messages[:limit]


def _period_end_ts(now=None):
    now = now or datetime.datetime.now()
    t = now.time()
    d = now.date()
    if t < datetime.time(9, 30):
        return int(datetime.datetime.combine(d, datetime.time(9, 30)).timestamp())
    if t < datetime.time(11, 30):
        return int(datetime.datetime.combine(d, datetime.time(11, 30)).timestamp())
    if t < datetime.time(13, 0):
        return int(datetime.datetime.combine(d, datetime.time(13, 0)).timestamp())
    if t < datetime.time(15, 0):
        return int(datetime.datetime.combine(d, datetime.time(15, 0)).timestamp())
    return int(datetime.datetime.combine(d + datetime.timedelta(days=1), datetime.time(9, 30)).timestamp())

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
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%' ORDER BY name DESC LIMIT 1")
            row = cursor.fetchone()
            
            if row:
                target_table = row[0]
                
                cursor.execute(f"SELECT * FROM `{target_table}` ORDER BY id DESC LIMIT 50")
                rows = cursor.fetchall()
                
                new_items = []
                for r in rows:
                    item = dict(r)
                    if item['id'] not in _last_seen_ids:
                        # 防止 _last_seen_ids 无限增长导致内存泄漏
                        if len(_last_seen_ids) >= _MAX_SEEN_IDS:
                            _last_seen_ids.clear()
                        _last_seen_ids.add(item['id'])
                        new_items.append(item)
                
                if new_items:
                    new_items.sort(key=lambda x: x['id'])
                    
                    for item in new_items:
                        msg = _row_to_message(item)
                        announcer.announce(msg)
                        _latest_cache.insert(0, msg)
                        
                    if len(_latest_cache) > LATEST_LIMIT:
                        _latest_cache = _latest_cache[:LATEST_LIMIT]
            
            conn.close()
            time.sleep(3)
            
        except Exception as e:
            print(f"Polling Error: {e}")
            time.sleep(5)

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
    date_str = request.args.get('date', '').strip()
    days = request.args.get('days', '3')
    period = request.args.get('period', 'all')
    try:
        days = max(1, min(int(days), 7))
    except Exception:
        days = 3

    conn = _get_sqlite_conn()
    if not conn:
        return jsonify([])

    try:
        cursor = conn.cursor()
        if date_str:
            target_tables = _list_tables_for_date(cursor, date_str)
        else:
            target_tables = _list_recent_tables(cursor, days=days)
        if not target_tables:
            return jsonify([])

        messages = _load_messages_from_tables(cursor, target_tables, period=period, limit=5000)

        if period == 'all':
            end_ts = _period_end_ts()
            messages = [m for m in messages if m.get('ctime', 0) <= end_ts]

        with _lock:
            global _latest_cache
            _latest_cache = messages[:LATEST_LIMIT]

        return jsonify(messages)
    except Exception as e:
        print(f"Init Query Error: {e}")
        return jsonify([])
    finally:
        conn.close()


@monitor_bp.route('/telegraph/dates')
def telegraph_dates():
    conn = _get_sqlite_conn()
    if not conn:
        return jsonify([])
    try:
        cursor = conn.cursor()
        return jsonify(_list_available_dates(cursor, limit=30))
    except Exception:
        return jsonify([])
    finally:
        conn.close()


@monitor_bp.route('/telegraph/report')
def telegraph_report():
    date_str = request.args.get('date', '').strip()
    period = request.args.get('period', '').strip().lower()
    if period not in ('morning', 'noon', 'afternoon', 'overnight', ''):
        return jsonify({'ok': False, 'msg': 'invalid period'})

    reports_dir = str(REPORTS_DIR)
    if not os.path.isdir(reports_dir):
        return jsonify({'ok': False, 'msg': 'report dir not found'})

    if date_str:
        compact = date_str.replace('-', '')
    else:
        compact = ''

    if period and compact:
        pattern = f'report_{compact}_{period}.md'
        files = sorted(glob.glob(os.path.join(reports_dir, pattern)), key=os.path.getmtime, reverse=True)
    elif period:
        files = sorted(glob.glob(os.path.join(reports_dir, f'report_*_{period}.md')), key=os.path.getmtime, reverse=True)
    elif compact:
        files = sorted(glob.glob(os.path.join(reports_dir, f'report_{compact}_*.md')), key=os.path.getmtime, reverse=True)
    else:
        files = sorted(glob.glob(os.path.join(reports_dir, 'report_*.md')), key=os.path.getmtime, reverse=True)

    if not files:
        return jsonify({'ok': False, 'msg': 'No report found'})

    latest = files[0]
    try:
        with open(latest, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except Exception as e:
        return jsonify({'ok': False, 'msg': f'read report failed: {e}'})

    detected_period = os.path.basename(latest).split('_')[-1].replace('.md', '')
    return jsonify({'ok': True, 'report': content, 'period': detected_period})

@monitor_bp.route('/telegraph/stream')
def telegraph_stream():
    def stream():
        messages = announcer.listen()
        while True:
            try:
                msg = messages.get(timeout=5)
                yield f'data: {json.dumps(msg)}\n\n'
            except queue.Empty:
                yield f'data: {json.dumps({"ping": time.time()})}\n\n'
            except GeneratorExit:
                break
    return Response(stream(), mimetype='text/event-stream')


# ============================================================
# monitor_history_bp — 历史消息库 (MySQL + SQLite fallback)
# ============================================================
monitor_history_bp = Blueprint('monitor_history', __name__, url_prefix='/monitor', template_folder='templates')

HOME_PC_IP = '100.75.180.70'
_HOME_DB_CFG = {
    'host': HOME_PC_IP,
    'user': 'inv_zhy',
    'password': 'zhy20050112',
    'database': 'NewsDB',
    'charset': 'utf8mb4',
    'connect_timeout': 3
}

def _get_conn():
    try:
        import pymysql
        return pymysql.connect(**_HOME_DB_CFG)
    except:
        return None

def _normalize_label_hist(label):
    if not label or label == 'all':
        return '全部'
    if label in LABEL_OPTIONS:
        return label
    return '全部'

def _get_sqlite_conn_hist():
    if not os.path.exists(SQLITE_DB_PATH):
        return None
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _get_history_backend_conn():
    conn = _get_conn()
    if conn:
        return 'mysql', conn

    conn = _get_sqlite_conn_hist()
    if conn:
        return 'sqlite', conn

    return None, None

def _extract_table_date(table_name):
    match = re.match(r"^telegraph_(\d{4}_\d{2}_\d{2})(?:_.*)?$", table_name or "")
    if not match:
        return None
    return match.group(1).replace('_', '-')


def _date_range(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += datetime.timedelta(days=1)

def _list_tables_for_date_hist(conn, backend, target_date):
    date_key = target_date.strftime('%Y_%m_%d')
    cursor = conn.cursor()
    if backend == 'mysql':
        cursor.execute("SHOW TABLES LIKE %s", (f"telegraph_{date_key}%",))
    else:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?", (f"telegraph_{date_key}%",))
    rows = cursor.fetchall()
    return [r[0] for r in rows]


def _fetch_rows_from_table(conn, backend, table_name, label_filter, limit):
    cursor = conn.cursor()

    if backend == 'mysql':
        placeholder = '%s'
    else:
        placeholder = '?'

    cursor.execute(f"PRAGMA table_info(`{table_name}`)" if backend == 'sqlite' else f"SHOW COLUMNS FROM `{table_name}`")
    if backend == 'sqlite':
        columns = {col[1] for col in cursor.fetchall()}
        has_primary_label = 'primary_label' in columns
    else:
        columns = {col[0] for col in cursor.fetchall()}
        has_primary_label = 'primary_label' in columns

    rows = []
    if has_primary_label:
        if label_filter == '全部':
            sql = f"SELECT id, title, content, ctime, primary_label FROM `{table_name}` ORDER BY id DESC LIMIT {placeholder}"
            cursor.execute(sql, (limit,))
        else:
            sql = f"SELECT id, title, content, ctime, primary_label FROM `{table_name}` WHERE primary_label={placeholder} ORDER BY id DESC LIMIT {placeholder}"
            cursor.execute(sql, (label_filter, limit))

        cols = [d[0] for d in cursor.description]
        for raw in cursor.fetchall():
            rows.append(dict(zip(cols, raw)))
    else:
        if label_filter not in ('全部', '其它'):
            return []

        sql = f"SELECT id, title, content, ctime FROM `{table_name}` ORDER BY id DESC LIMIT {placeholder}"
        cursor.execute(sql, (limit,))
        cols = [d[0] for d in cursor.description]
        for raw in cursor.fetchall():
            r = dict(zip(cols, raw))
            r['primary_label'] = '其它'
            rows.append(r)

    return rows

def _list_historical_rows(target_date, label_filter, limit):
    backend, conn = _get_history_backend_conn()
    if not conn:
        return []

    try:
        tables = _list_tables_for_date_hist(conn, backend, target_date)
        if not tables:
            return []

        rows = []
        for table_name in tables:
            rows.extend(_fetch_rows_from_table(conn, backend, table_name, label_filter, limit))

        rows.sort(key=lambda item: _to_unix_ts(item.get('ctime')), reverse=True)
        return rows[:limit]
    except Exception:
        return []
    finally:
        conn.close()


def _list_historical_rows_in_range(start_date, end_date, label_filter, limit):
    backend, conn = _get_history_backend_conn()
    if not conn:
        return []

    try:
        rows = []
        for target_date in _date_range(start_date, end_date):
            tables = _list_tables_for_date_hist(conn, backend, target_date)
            for table_name in tables:
                rows.extend(_fetch_rows_from_table(conn, backend, table_name, label_filter, limit))

        rows.sort(key=lambda item: _to_unix_ts(item.get('ctime')), reverse=True)
        return rows[:limit]
    finally:
        conn.close()

@monitor_history_bp.route('/history')
def history():
    initial = _normalize_label_hist(request.args.get('label'))
    selected_date = request.args.get('date')
    if not selected_date:
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        selected_date = yesterday.strftime('%Y-%m-%d')
    return render_template('history.html', 
                           label_groups=LABEL_GROUPS, 
                           labels=LABEL_OPTIONS, 
                           initial=initial, 
                           selected_date=selected_date)

@monitor_history_bp.route('/history/data')
@monitor_history_bp.route('/api/history')
def history_data():
    date_str = request.args.get('date')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    label_filter = _normalize_label_hist(request.args.get('label'))
    limit = int(request.args.get('limit', 1000))
    limit = max(1, min(limit, 5000))
    
    try:
        if start_date_str and end_date_str:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            rows = _list_historical_rows_in_range(start_date, end_date, label_filter, limit)
            date_label = f'{start_date.strftime("%Y-%m-%d")} ~ {end_date.strftime("%Y-%m-%d")}'
        else:
            if not date_str:
                return jsonify({'error': '日期参数不能为空'}), 400
            query_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            rows = _list_historical_rows(query_date, label_filter, limit)
            date_label = date_str
    except ValueError:
        return jsonify({'error': '日期格式错误'}), 400
    items = []
    for row in rows:
        ts = _to_unix_ts(row.get('ctime'))
        items.append({
            'id': row.get('id'),
            'title': row.get('title') or '',
            'content': row.get('content') or '',
            'primary_label': row.get('primary_label') or '其它',
            'ctime': ts,
            'time_str': datetime.datetime.fromtimestamp(ts).strftime('%m-%d %H:%M:%S')
        })
        
    return jsonify({
        'items': items,
        'count': len(items),
        'date': date_label,
        'mode': 'range' if start_date_str and end_date_str else 'single'
    })

@monitor_history_bp.route('/history/dates')
def available_dates():
    backend, conn = _get_history_backend_conn()
    if not conn:
        return jsonify([])

    try:
        cursor = conn.cursor()
        if backend == 'mysql':
            cursor.execute("SHOW TABLES LIKE 'telegraph_%'")
        else:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'telegraph_%'")
        table_rows = cursor.fetchall()
        table_names = [r[0] for r in table_rows]

        dates = set()
        for table_name in table_names:
            date_str = _extract_table_date(table_name)
            if date_str:
                dates.add(date_str)

        return jsonify(sorted(dates, reverse=True))
    except Exception:
        return jsonify([])
    finally:
        conn.close()
