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
from monitor_module.news_monitor.newsagent.topics import (
    FRONTEND_LABEL_GROUPS,
    FRONTEND_LABEL_OPTIONS,
    LABEL_STYLE_CLASS_MAP,
    classify_news_cluster,
    latest_report_file,
    report_file_glob,
)

# ============================================================
# monitor_bp — 实时电报直播 (SQLite)
# ============================================================
monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor', template_folder='templates')

POLL_INTERVAL = 5
LATEST_LIMIT = 500

_MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = _MODULE_DIR.parent
SQLITE_DB_PATH = str(_MODULE_DIR / 'news_monitor' / 'news_buffer.db')

LABEL_GROUPS = FRONTEND_LABEL_GROUPS
LABEL_OPTIONS = FRONTEND_LABEL_OPTIONS

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

    source_label = item.get('primary_label') or ''
    cluster_label = classify_news_cluster(source_label)

    return {
        'id': item.get('id'),
        'title': item.get('title') or '',
        'content': item.get('content') or '',
        'ctime': _to_unix_ts(item.get('ctime')),
        'labels': labels,
        'primary_label': source_label,
        'cluster_label': cluster_label,
        'cluster_class': LABEL_STYLE_CLASS_MAP.get(source_label, 'cluster-digest'),
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


def _load_messages_from_tables(cursor, tables, period='all', label_filter='全部', limit=5000):
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
                msg = _row_to_message(d)
                if label_filter and label_filter != '全部':
                    if isinstance(label_filter, list):
                        if msg.get('primary_label') not in label_filter and msg.get('cluster_label') not in label_filter:
                            continue
                    elif msg.get('primary_label') != label_filter and msg.get('cluster_label') != label_filter:
                        continue
                seen_ids.add(row_id)
                messages.append(msg)
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


def _resolve_report_path(date_str: str = '', period: str = '', cluster: str = '综合'):
    cluster = cluster or '综合'
    if date_str:
        date_dir = Path(REPORTS_DIR) / date_str
        if period and period != 'all':
            exact = date_dir / period / f'{cluster}.md'
            if exact.exists():
                return exact
            candidates = report_file_glob(Path(REPORTS_DIR), date_str, period, cluster)
            return candidates[0] if candidates else None

        candidates = report_file_glob(Path(REPORTS_DIR), date_str, None, cluster)
        return candidates[0] if candidates else None

    if period and period != 'all':
        latest = latest_report_file(Path(REPORTS_DIR), period, cluster)
        return latest

    latest = latest_report_file(Path(REPORTS_DIR), None, cluster)
    return latest

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
    search = request.args.get('search', '').strip()
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
        elif period and period != 'all':
            # 指定了具体时段但未选日期：只查最新一天，避免跨天混杂
            target_tables = _list_recent_tables(cursor, days=1)
        else:
            target_tables = _list_recent_tables(cursor, days=days)
        if not target_tables:
            return jsonify([])

        messages = _load_messages_from_tables(cursor, target_tables, period=period, label_filter=request.args.get('label', '全部'), limit=5000)

        if period == 'all' and not date_str:
            # 仅在实时模式（未指定日期）下，按当前时段截断消息
            end_ts = _period_end_ts()
            messages = [m for m in messages if m.get('ctime', 0) <= end_ts]

        # 关键字搜索过滤
        if search:
            kw = search.lower()
            messages = [m for m in messages if
                        kw in (m.get('title') or '').lower() or
                        kw in (m.get('content') or '').lower()]

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


@monitor_bp.route('/telegraph/latest_date')
def telegraph_latest_date():
    """返回数据库中最新有数据的日期"""
    conn = _get_sqlite_conn()
    if not conn:
        return jsonify({'date': ''})
    try:
        cursor = conn.cursor()
        dates = _list_available_dates(cursor, limit=1)
        return jsonify({'date': dates[0] if dates else ''})
    except Exception:
        return jsonify({'date': ''})
    finally:
        conn.close()


@monitor_bp.route('/telegraph/report')
def telegraph_report():
    date_str = request.args.get('date', '').strip()
    period = request.args.get('period', '').strip().lower()
    cluster = request.args.get('cluster', '综合').strip() or '综合'
    if period not in ('morning', 'noon', 'afternoon', 'overnight', 'all', ''):
        return jsonify({'ok': False, 'msg': 'invalid period'})

    reports_dir = str(REPORTS_DIR)
    if not os.path.isdir(reports_dir):
        return jsonify({'ok': False, 'msg': 'report dir not found'})

    if period == 'all':
        period = ''

    latest = _resolve_report_path(date_str, period, cluster)
    if not latest or not latest.exists():
        return jsonify({'ok': False, 'msg': 'No report found'})

    try:
        with open(latest, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    except Exception as e:
        return jsonify({'ok': False, 'msg': f'read report failed: {e}'})

    detected_period = latest.parent.name
    detected_cluster = latest.stem
    return jsonify({'ok': True, 'report': content, 'period': detected_period, 'cluster': detected_cluster})

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
