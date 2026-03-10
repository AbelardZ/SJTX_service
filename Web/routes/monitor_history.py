from flask import Blueprint, render_template, request, jsonify
# from flask_login import login_required
import time
import datetime
import pymysql
import sys
import os
import sqlite3
import re

monitor_history_bp = Blueprint('monitor_history', __name__, url_prefix='/monitor')

HOME_PC_IP = '100.75.180.70'
_HOME_DB_CFG = {
    'host': HOME_PC_IP,
    'user': 'inv_zhy',
    'password': 'zhy20050112',
    'database': 'NewsDB',
    'charset': 'utf8mb4',
    'connect_timeout': 3
}

LABEL_GROUPS = [
    {'name': '市场金融', 'tags': ['交易提示', '公司公告', '机构观点和策略', '金融部门事务']},
    {'name': '行业科技', 'tags': ['行业消息', '行业数据', '重要主体动态', '科学技术前沿动态']},
    {'name': '国内政策', 'tags': ['国内政治动态', '国内一般指导', '国内一般政策', '国内政府动向']},
    {'name': '国际事务', 'tags': ['一般国际事务', '国际一般政策', '国际金融政策', '重要国家内政', '地缘政治动态']},
    {'name': '宏观数据', 'tags': ['国内宏观数据', '国际宏观数据']},
    {'name': '事件其它', 'tags': ['自然事件', '社会事件', '新闻集合', '其它']}
]
LABEL_OPTIONS = ['全部'] + [tag for group in LABEL_GROUPS for tag in group['tags']]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQLITE_DB_PATH = os.path.join(BASE_DIR, 'news_monitor', 'news_buffer.db')

def _get_conn():
    try:
        return pymysql.connect(**_HOME_DB_CFG)
    except:
        return None

def _normalize_label(label):
    if not label or label == 'all':
        return '全部'
    if label in LABEL_OPTIONS:
        return label
    return '全部'

def _get_sqlite_conn():
    if not os.path.exists(SQLITE_DB_PATH):
        return None
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _to_unix_ts(value):
    if value is None:
        return int(time.time())
    if isinstance(value, datetime.datetime):
        return int(value.timestamp())
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

def _extract_table_date(table_name):
    match = re.match(r"^telegraph_(\d{4}_\d{2}_\d{2})(?:_.*)?$", table_name or "")
    if not match:
        return None
    return match.group(1).replace('_', '-')

def _list_tables_for_date(conn, target_date):
    date_key = target_date.strftime('%Y_%m_%d')
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES LIKE %s", (f"telegraph_{date_key}%",))
    rows = cursor.fetchall()
    return [r[0] if isinstance(r, (list, tuple)) else list(r.values())[0] for r in rows]

def _list_historical_rows(target_date, label_filter, limit):
    conn = _get_conn()
    if not conn:
        return []

    try:
        tables = _list_tables_for_date(conn, target_date)
        if not tables:
            return []

        rows = []
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        for table_name in tables:
            cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
            columns = {col['Field'] for col in cursor.fetchall()}
            has_primary_label = 'primary_label' in columns

            if has_primary_label:
                if label_filter == '全部':
                    sql = f"SELECT id, title, content, ctime, primary_label FROM `{table_name}` ORDER BY id DESC LIMIT %s"
                    cursor.execute(sql, (limit,))
                else:
                    sql = f"SELECT id, title, content, ctime, primary_label FROM `{table_name}` WHERE primary_label=%s ORDER BY id DESC LIMIT %s"
                    cursor.execute(sql, (label_filter, limit))

                for r in cursor.fetchall():
                    rows.append(r)
            else:
                if label_filter not in ('全部', '其它'):
                    continue

                sql = f"SELECT id, title, content, ctime FROM `{table_name}` ORDER BY id DESC LIMIT %s"
                cursor.execute(sql, (limit,))
                for r in cursor.fetchall():
                    r['primary_label'] = '其它'
                    rows.append(r)

        rows.sort(key=lambda item: _to_unix_ts(item.get('ctime')), reverse=True)
        return rows[:limit]
    except Exception:
        return []
    finally:
        conn.close()

@monitor_history_bp.route('/history')
def history():
    initial = _normalize_label(request.args.get('label'))
    selected_date = request.args.get('date')
    if not selected_date:
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        selected_date = yesterday.strftime('%Y-%m-%d')
    # Unordered args matching template signature if needed
    return render_template('history.html', 
                           label_groups=LABEL_GROUPS, 
                           labels=LABEL_OPTIONS, 
                           initial=initial, 
                           selected_date=selected_date)

@monitor_history_bp.route('/history/data')
@monitor_history_bp.route('/api/history')
def history_data():
    date_str = request.args.get('date')
    label_filter = _normalize_label(request.args.get('label'))
    limit = int(request.args.get('limit', 1000))
    limit = max(1, min(limit, 5000))
    
    if not date_str:
        return jsonify({'error': '日期参数不能为空'}), 400
        
    try:
        query_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': '日期格式错误'}), 400

    rows = _list_historical_rows(query_date, label_filter, limit)
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
        'date': date_str
    })

@monitor_history_bp.route('/history/dates')
def available_dates():
    conn = _get_conn()
    if not conn:
        return jsonify([])

    try:
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES LIKE 'telegraph_%'")
        table_rows = cursor.fetchall()
        table_names = [r[0] if isinstance(r, (list, tuple)) else list(r.values())[0] for r in table_rows]

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
