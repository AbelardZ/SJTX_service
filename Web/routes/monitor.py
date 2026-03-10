from flask import Blueprint, render_template, request, Response, jsonify
from queue import Queue
import json
import time
import threading
import pymysql
import datetime
import akshare as ak

monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor')

# ======================== 配置 ========================
POLL_INTERVAL = 5      # 轮询间隔秒
LATEST_LIMIT = 10000    # 当日全量缓存上限（安全阈值，避免前端过载）
# 新版 BERT 模型标签分组
LABEL_GROUPS = [
    {"name": "市场金融", "tags": ["交易提示", "公司公告", "机构观点和策略", "金融部门事务"]},
    {"name": "行业科技", "tags": ["行业消息", "行业数据", "重要主体动态", "科学技术前沿动态"]},
    {"name": "国内政策", "tags": ["国内政治动态", "国内一般指导", "国内一般政策", "国内政府动向"]},
    {"name": "国际事务", "tags": ["一般国际事务", "国际一般政策", "国际金融政策", "重要国家内政", "地缘政治动态"]},
    {"name": "宏观数据", "tags": ["国内宏观数据", "国际宏观数据"]},
    {"name": "事件其它", "tags": ["自然事件", "社会事件", "新闻集合", "其它"]}
]

# 展开所有标签用于校验
LABEL_OPTIONS = ["全部"] + [tag for group in LABEL_GROUPS for tag in group["tags"]]

# 分类数据库配置（请与 news_monitor/config.py 保持同步）
_DB_CFG = {
    "host": "localhost",
    "user": "inv_zhy",
    "password": "zhy20050112",
    "database": "NewsDB",
    "charset": "utf8mb4"
}

# ======================== 内存结构 ========================
_telegraph_queue: Queue = Queue(maxsize=1000)   # 实时新增推送队列
_latest_cache = []                              # 最近 LATEST_LIMIT 条（已分类且过滤“其他”）
_last_seen_ids = set()                          # 去重集合
_poll_thread_started = False

def _normalize_label(label: str | None) -> str:
    if not label:
        return "全部"
    label = str(label).strip()
    return label if label in LABEL_OPTIONS else "全部"

# ======================== DB 辅助 ========================

def _get_conn():
    return pymysql.connect(**_DB_CFG)

def _get_historical_data(date_str):
    """获取指定日期的历史数据"""
    try:
        # 解析日期
        y, m, d = map(int, date_str.split('-'))
        target_date = datetime.date(y, m, d)

        conn = _get_conn()
        cursor = conn.cursor()

        # 查找所有可能的表（当前日期和前后几天的表，以确保找到所有相关数据）
        possible_dates = [
            target_date - datetime.timedelta(days=1),  # 前一天
            target_date,  # 当天
            target_date + datetime.timedelta(days=1),  # 后一天
        ]

        all_tables = []
        for check_date in possible_dates:
            date_str_formatted = f"{check_date.year}_{check_date.month:02d}_{check_date.day:02d}"
            candidates = [f"telegraph_{date_str_formatted}_trade", f"telegraph_{date_str_formatted}_nontrade"]
            for candidate in candidates:
                cursor.execute("SHOW TABLES LIKE %s", (candidate,))
                if cursor.fetchone():
                    all_tables.append(candidate)

        if not all_tables:
            return []

        # 从所有相关表中查询trading_date等于目标日期的记录
        result = []
        for table_name in all_tables:
            cursor.execute(f"""
                SELECT id, title, content, primary_label, labels_json, ctime, trading_date, is_trading_day, segment
                FROM `{table_name}`
                WHERE trading_date = %s
                ORDER BY ctime DESC
            """, (target_date,))

            rows = cursor.fetchall()
            for row in rows:
                id_val, title, content, primary_label, labels_json, ctime, trading_date, is_trading_day, segment = row

                # 标准化标签
                if primary_label in (None, '', '未分类', '其他', 'other'):
                    primary_label = '其它'

                result.append({
                    'id': id_val,
                    'title': title or '',
                    'content': content or '',
                    'primary_label': primary_label,
                    'labels': json.loads(labels_json) if labels_json else [],
                    'ctime': int(ctime.timestamp()) if hasattr(ctime, 'timestamp') else int(ctime),
                    'source_table': table_name,
                    'trading_date': trading_date.strftime('%Y-%m-%d') if hasattr(trading_date, 'strftime') else str(trading_date),
                    'is_trading_day': bool(is_trading_day),
                    'segment': segment
                })

        # 按时间倒序排序
        result.sort(key=lambda x: x['ctime'], reverse=True)

        conn.close()
        return result

    except Exception as e:
        print(f"获取历史数据失败: {e}")
        return []

def _today_base_date_ts():
    """返回按15:00切换日的基准时间戳（秒）与日期字符串。
    15点前归当天，15点后归下一天。
    """
    now = time.localtime()
    # 若在 15:00 之前，算作当天；否则算作下一天
    is_before_15 = (now.tm_hour < 15) or (now.tm_hour == 15 and now.tm_min == 0)
    if is_before_15:
        # 15点前：当天
        base = now
    else:
        # 15点后：下一天
        base = time.localtime(time.time() + 86400)
    y, m, d = base.tm_year, base.tm_mon, base.tm_mday
    return int(time.mktime(base)), f"{y}_{m:02d}_{d:02d}"

def _get_today_table_name(cur):
    """推断当日表名：优先 trade，不存在则使用 nontrade；若都无则返回 None。"""
    _, ds = _today_base_date_ts()
    candidates = [f"telegraph_{ds}_trade", f"telegraph_{ds}_nontrade"]
    for name in candidates:
        cur.execute("SHOW TABLES LIKE %s", (name,))
        if cur.fetchone():
            return name
    # 兼容仅按日期未加后缀的旧表
    fallback = f"telegraph_{ds}%"
    cur.execute("SHOW TABLES LIKE %s", (fallback,))
    row = cur.fetchone()
    return row[0] if row else None

def _list_today_rows(limit=None):
    """读取当日（按15点-15点归属）的分表记录，全量返回（可选上限）。"""
    conn = _get_conn(); cur = conn.cursor()
    table = _get_today_table_name(cur)
    rows = []
    if table:
        try:
            if limit:
                cur.execute(f"SELECT id,title,content,primary_label,labels_json,UNIX_TIMESTAMP(ctime) as uts FROM `{table}` ORDER BY ctime DESC LIMIT %s", (limit,))
            else:
                cur.execute(f"SELECT id,title,content,primary_label,labels_json,UNIX_TIMESTAMP(ctime) as uts FROM `{table}` ORDER BY ctime DESC")
            rows = [(table,) + r for r in cur.fetchall()]
        except Exception:
            rows = []
    conn.close()
    return rows

def _get_overnight_count(date_str):
    """获取指定日期的overnight系列数量"""
    try:
        conn = _get_conn()
        cursor = conn.cursor()

        # 查找对应的表
        table_name = None
        candidates = [f"telegraph_{date_str}_trade", f"telegraph_{date_str}_nontrade"]
        for candidate in candidates:
            cursor.execute("SHOW TABLES LIKE %s", (candidate,))
            if cursor.fetchone():
                table_name = candidate
                break

        if not table_name:
            return 0

        # 查询overnight系列的数量
        cursor.execute(f"SELECT COUNT(*) FROM `{table_name}` WHERE segment = 'overnight'")
        count = cursor.fetchone()[0]

        conn.close()
        return count
    except:
        return 0

def _get_current_period_status():
    """获取当前时间段的状态"""
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute
    current_minutes = hour * 60 + minute

    # 时间段定义（分钟）
    overnight_start = 15 * 60  # 15:00
    morning_start = 9 * 60 + 15  # 9:15
    noon_start = 11 * 60 + 30  # 11:30
    afternoon_start = 13 * 60  # 13:00
    afternoon_end = 15 * 60  # 15:00

    if current_minutes >= afternoon_end or current_minutes < morning_start:
        return "Overnight"
    elif current_minutes < noon_start:
        return "Morning"
    elif current_minutes < afternoon_start:
        return "Noon"
    else:
        return "Afternoon"

def _get_trading_status(date_str=None):
    """获取交易状态信息，可指定日期"""
    if date_str:
        # 解析指定日期
        try:
            y, m, d = map(int, date_str.split('-'))
            display_date = datetime.date(y, m, d)
            display_date_str = f"{y}_{m:02d}_{d:02d}"
        except:
            # 如果解析失败，使用当前日期
            _, display_date_str = _today_base_date_ts()
            y, m, d = map(int, display_date_str.split('_'))
            display_date = datetime.date(y, m, d)
    else:
        # 使用当前日期
        now = time.localtime()
        _, display_date_str = _today_base_date_ts()
        y, m, d = map(int, display_date_str.split('_'))
        display_date = datetime.date(y, m, d)

    # 判断是否为交易日
    is_trading = display_date in list(ak.tool_trade_date_hist_sina()['trade_date'])

    # 获取overnight系列数量
    overnight_count = _get_overnight_count(display_date_str)

    # 格式化日期显示
    date_display = f"交易纪日 {y}年{m}月{d}日"

    # 确定状态
    today = datetime.date.today()
    if display_date == today:
        # 今天，根据当前时间确定状态
        if not is_trading:
            status = "Break"
            status_color = "#6b7280"
        else:
            status = _get_current_period_status()
            status_color = "#10b981"
    else:
        # 历史日期
        if not is_trading:
            status = "Break"
            status_color = "#6b7280"
        else:
            status = "Trading"
            status_color = "#10b981"

    full_display = f"{status}"

    return {
        'date': date_display,
        'status': full_display,
        'status_color': status_color,
        'is_trading': is_trading,
        'overnight_count': overnight_count
    }

# ======================== 轮询线程 ========================

def _poll_loop():
    global _latest_cache, _last_seen_ids
    while True:
        try:
            # 仅拉取“当日表”的记录（全量，带安全上限）
            rows = _list_today_rows(limit=LATEST_LIMIT)
            cleaned = []
            for tbl, _id, title, content, primary_label, labels_json, uts in rows:
                # 将不可用/未分类/其他统一映射到“其它”
                if primary_label in (None, '', '未分类', '其他', 'other'):
                    primary_label = '其它'
                item = {
                    'id': _id,
                    'title': title or '',
                    'content': content or '',
                    'primary_label': primary_label,
                    'labels': json.loads(labels_json) if labels_json else [],
                    'ctime': int(uts) if uts else int(time.time()),
                    'source_table': tbl
                }
                cleaned.append(item)
            cleaned.sort(key=lambda x: x['ctime'], reverse=True)
            _latest_cache = cleaned
            for item in cleaned:
                _id = item['id']
                if _id in _last_seen_ids:
                    continue
                _last_seen_ids.add(_id)
                if len(_last_seen_ids) > 5000:
                    _last_seen_ids = set(list(_last_seen_ids)[-3000:])
                try:
                    _telegraph_queue.put_nowait(item)
                except Exception:
                    try:
                        _telegraph_queue.get_nowait()
                        _telegraph_queue.put_nowait(item)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)

def _ensure_poll_thread():
    global _poll_thread_started
    if not _poll_thread_started:
        t = threading.Thread(target=_poll_loop, name='telegraph-poll', daemon=True)
        t.start()
        _poll_thread_started = True

# 应用加载即启动轮询
_ensure_poll_thread()

# ======================== 路由 ========================

@monitor_bp.route('/')
def index():
    return render_template('monitor_index.html')

@monitor_bp.route('/telegraph')
def telegraph_live():
    initial = _normalize_label(request.args.get('label'))
    trading_status = _get_trading_status(None)
    return render_template('telegraph.html', 
                         label_groups=LABEL_GROUPS,
                         labels=LABEL_OPTIONS, 
                         initial=initial,
                         trading_status=trading_status)

@monitor_bp.route('/telegraph/category/<label>')
def telegraph_by_label(label: str):
    # 允许直接用中文标签访问：内部使用 query 参数重用逻辑
    return telegraph_live()

@monitor_bp.route('/telegraph/stream')
def telegraph_stream():
    def _gen():
        last_heartbeat = time.time()
        while True:
            try:
                try:
                    item = _telegraph_queue.get(timeout=5)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except Exception:
                    if time.time() - last_heartbeat > 15:
                        yield f"data: {json.dumps({'type':'heartbeat','ts':int(time.time())}, ensure_ascii=False)}\n\n"
                        last_heartbeat = time.time()
            except GeneratorExit:
                break
    return Response(_gen(), mimetype='text/event-stream')

@monitor_bp.route('/telegraph/init')
def telegraph_init():
    date_param = request.args.get('date')

    if date_param:
        # 返回指定日期的历史数据
        historical_data = _get_historical_data(date_param)
        return jsonify(historical_data)
    else:
        # 返回当日实时数据
        for it in _latest_cache:
            _last_seen_ids.add(it['id'])
        return jsonify(_latest_cache)
