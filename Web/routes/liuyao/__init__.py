from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user
from datetime import datetime
from .divination import perform_divination, create_wapp
from .config import LOCAL_DB_CONFIG, CLOUD_SQLITE_PATH
import mysql.connector as mysql
import re
import uuid
import os
import sqlite3

liuyao_bp = Blueprint('liuyao', __name__, url_prefix='/liuyao')

TIANGAN = ['', '甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
DIZHI = ['', '子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
YAO_TEXT_TO_CODE = {'少阳': '1', '少阴': '2', '老阳': '3', '老阴': '4'}
YAO_CODE_TO_TEXT = {'1': '少阳', '2': '少阴', '3': '老阳', '4': '老阴'}


def _get_cloud_sqlite_conn():
    db_path = CLOUD_SQLITE_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_cloud_table(conn):
    cursor = conn.cursor()
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS liuyao_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year_table TEXT NOT NULL,
            record_uuid TEXT NOT NULL UNIQUE,
            起卦方式 TEXT,
            时间 TEXT,
            月干 TEXT,
            月支 TEXT,
            日干 TEXT,
            日支 TEXT,
            初爻 TEXT,
            二爻 TEXT,
            三爻 TEXT,
            四爻 TEXT,
            五爻 TEXT,
            上爻 TEXT,
            标的 TEXT,
            用户 TEXT,
            备注 TEXT,
            已同步本地 INTEGER DEFAULT 0,
            同步错误 TEXT,
            更新时间 TEXT
        )
        '''
    )
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_liuyao_year_time ON liuyao_records(year_table, 时间)')
    conn.commit()
    cursor.close()


def _upsert_cloud_record(values, table_name, synced_local, sync_error=''):
    conn = _get_cloud_sqlite_conn()
    try:
        _ensure_cloud_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO liuyao_records (
                year_table, record_uuid, 起卦方式, 时间, 月干, 月支, 日干, 日支,
                初爻, 二爻, 三爻, 四爻, 五爻, 上爻, 标的, 用户, 备注,
                已同步本地, 同步错误, 更新时间
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_uuid) DO UPDATE SET
                year_table=excluded.year_table,
                起卦方式=excluded.起卦方式,
                时间=excluded.时间,
                月干=excluded.月干,
                月支=excluded.月支,
                日干=excluded.日干,
                日支=excluded.日支,
                初爻=excluded.初爻,
                二爻=excluded.二爻,
                三爻=excluded.三爻,
                四爻=excluded.四爻,
                五爻=excluded.五爻,
                上爻=excluded.上爻,
                标的=excluded.标的,
                用户=excluded.用户,
                备注=excluded.备注,
                已同步本地=excluded.已同步本地,
                同步错误=excluded.同步错误,
                更新时间=excluded.更新时间
            ''',
            (
                table_name,
                values['record_uuid'],
                values['mode_cn'],
                values['time_formatted'],
                values['month_gan'],
                values['month_zhi'],
                values['day_gan'],
                values['day_zhi'],
                values['yaos'][0],
                values['yaos'][1],
                values['yaos'][2],
                values['yaos'][3],
                values['yaos'][4],
                values['yaos'][5],
                values['subject'],
                values['user_name'],
                values['remarks'],
                1 if synced_local else 0,
                sync_error,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        )
        cloud_id = cursor.lastrowid
        conn.commit()

        if cloud_id == 0:
            cursor.execute('SELECT id FROM liuyao_records WHERE record_uuid = ?', (values['record_uuid'],))
            row = cursor.fetchone()
            cloud_id = row['id'] if row else 0

        cursor.close()
        return cloud_id
    finally:
        conn.close()


def _ensure_table_schema(cursor, table_name):
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
        id INT AUTO_INCREMENT PRIMARY KEY,
        起卦方式 VARCHAR(20),
        时间 VARCHAR(20),
        月干 VARCHAR(10),
        月支 VARCHAR(10),
        日干 VARCHAR(10),
        日支 VARCHAR(10),
        初爻 CHAR(1),
        二爻 CHAR(1),
        三爻 CHAR(1),
        四爻 CHAR(1),
        五爻 CHAR(1),
        上爻 CHAR(1),
        标的 VARCHAR(255),
        用户 VARCHAR(255),
        备注 TEXT,
        记录UUID VARCHAR(36),
        云同步 TINYINT(1) DEFAULT 0,
        UNIQUE KEY uniq_record_uuid (记录UUID)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cursor.execute(create_sql)

    cursor.execute(f"SHOW COLUMNS FROM `{table_name}` LIKE %s", ('记录UUID',))
    if cursor.fetchone() is None:
        cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN 记录UUID VARCHAR(36)")

    cursor.execute(f"SHOW COLUMNS FROM `{table_name}` LIKE %s", ('云同步',))
    if cursor.fetchone() is None:
        cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN 云同步 TINYINT(1) DEFAULT 0")

    cursor.execute(f"SHOW INDEX FROM `{table_name}` WHERE Key_name = %s", ('uniq_record_uuid',))
    if cursor.fetchone() is None:
        try:
            cursor.execute(f"ALTER TABLE `{table_name}` ADD UNIQUE KEY uniq_record_uuid (记录UUID)")
        except Exception:
            pass


def _insert_or_update_record(cnx, table_name, values, cloud_synced):
    cursor = cnx.cursor()
    _ensure_table_schema(cursor, table_name)

    insert_sql = f"""
    INSERT INTO `{table_name}`
    (起卦方式, 时间, 月干, 月支, 日干, 日支, 初爻, 二爻, 三爻, 四爻, 五爻, 上爻, 标的, 用户, 备注, 记录UUID, 云同步)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      起卦方式 = VALUES(起卦方式),
      时间 = VALUES(时间),
      月干 = VALUES(月干),
      月支 = VALUES(月支),
      日干 = VALUES(日干),
      日支 = VALUES(日支),
      初爻 = VALUES(初爻),
      二爻 = VALUES(二爻),
      三爻 = VALUES(三爻),
      四爻 = VALUES(四爻),
      五爻 = VALUES(五爻),
      上爻 = VALUES(上爻),
      标的 = VALUES(标的),
      用户 = VALUES(用户),
      备注 = VALUES(备注),
      云同步 = VALUES(云同步)
    """

    sql_values = (
        values['mode_cn'], values['time_formatted'],
        values['month_gan'], values['month_zhi'], values['day_gan'], values['day_zhi'],
        values['yaos'][0], values['yaos'][1], values['yaos'][2], values['yaos'][3], values['yaos'][4], values['yaos'][5],
        values['subject'], values['user_name'], values['remarks'], values['record_uuid'],
        1 if cloud_synced else 0
    )
    cursor.execute(insert_sql, sql_values)
    local_id = cursor.lastrowid
    cnx.commit()
    cursor.close()
    return local_id


def _sync_cloud_to_local(limit_rows=300):
    try:
        conn_cloud = _get_cloud_sqlite_conn()
        _ensure_cloud_table(conn_cloud)
        cur_cloud = conn_cloud.cursor()

        cur_cloud.execute(
            '''
            SELECT *
            FROM liuyao_records
            WHERE 已同步本地 = 0
            ORDER BY id ASC
            LIMIT ?
            ''',
            (limit_rows,)
        )
        rows = cur_cloud.fetchall()
        if not rows:
            cur_cloud.close()
            conn_cloud.close()
            return 0

        local_cnx = mysql.connect(**LOCAL_DB_CONFIG)
        synced = 0
        for row in rows:
            table_name = row['year_table']
            values = {
                'mode_cn': row['起卦方式'],
                'time_formatted': row['时间'],
                'month_gan': row['月干'],
                'month_zhi': row['月支'],
                'day_gan': row['日干'],
                'day_zhi': row['日支'],
                'yaos': [row['初爻'], row['二爻'], row['三爻'], row['四爻'], row['五爻'], row['上爻']],
                'subject': row['标的'],
                'user_name': row['用户'],
                'remarks': row['备注'] or '',
                'record_uuid': row['record_uuid']
            }
            _insert_or_update_record(local_cnx, table_name, values, cloud_synced=True)
            cur_cloud.execute(
                "UPDATE liuyao_records SET 已同步本地=1, 同步错误='', 更新时间=? WHERE id=?",
                (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), row['id'])
            )
            synced += 1

        local_cnx.close()
        conn_cloud.commit()
        cur_cloud.close()
        conn_cloud.close()
        return synced
    except Exception as e:
        try:
            conn_cloud = _get_cloud_sqlite_conn()
            _ensure_cloud_table(conn_cloud)
            cur_cloud = conn_cloud.cursor()
            cur_cloud.execute(
                "UPDATE liuyao_records SET 同步错误=?, 更新时间=? WHERE 已同步本地=0",
                (str(e)[:500], datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn_cloud.commit()
            cur_cloud.close()
            conn_cloud.close()
        except Exception:
            pass
        print(f'Cloud->Local sync failed: {e}')
        return 0


def _map_mod_to_code(mod):
    if mod == 0:
        return '4'
    if mod == 1:
        return '1'
    if mod == 2:
        return '2'
    return '3'


def _parse_yao_codes(form):
    input_mode = form.get('input_mode', 'manual')

    if input_mode == 'manual':
        top_to_bottom = [form.get(f'yao_{i}', '少阳') for i in range(6)]
        bottom_to_top = list(reversed(top_to_bottom))
        return [YAO_TEXT_TO_CODE.get(v, '1') for v in bottom_to_top]

    if input_mode == 'random':
        top_to_bottom_codes = []
        for i in range(6):
            raw = form.get(f'random_val_{i}', '').strip()
            if not raw:
                raise ValueError('随机数模式需填写6个数字')
            val = int(raw)
            if val <= 10:
                raise ValueError('随机数模式每个数字必须大于10')
            top_to_bottom_codes.append(_map_mod_to_code(val % 4))
        return list(reversed(top_to_bottom_codes))

    if input_mode == 'single':
        raw = form.get('single_random_val', '').strip()
        if not re.match(r'^\d{6}$', raw):
            raise ValueError('单随机模式需填写6位数字')
        digits = [int(ch) for ch in raw]
        if any(d < 1 or d > 8 for d in digits):
            raise ValueError('单随机模式每位需在1-8之间')
        top_to_bottom_codes = [_map_mod_to_code(d % 4) for d in digits]
        return list(reversed(top_to_bottom_codes))

    raise ValueError('未知起卦模式')


def _get_available_years():
    years = set()
    try:
        conn = _get_cloud_sqlite_conn()
        _ensure_cloud_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT year_table FROM liuyao_records")
        for (table_name,) in cursor.fetchall():
            match = re.match(r'^(\d{4})年$', table_name or '')
            if match:
                years.add(match.group(1))
        cursor.close()
        conn.close()
    except Exception as e:
        print(f'Error fetching liuyao years from cloud sqlite: {e}')
    return sorted(list(years), reverse=True)


@liuyao_bp.route('/', methods=['GET', 'POST'])
def index():
    now = datetime.now()
    context = {
        'tiangan': TIANGAN,
        'dizhi': DIZHI,
        'input_mode': request.form.get('input_mode', 'manual') if request.method == 'POST' else 'manual',
        'subject': request.form.get('subject', ''),
        'date_str': request.form.get('date', now.strftime('%Y-%m-%d')),
        'hour': int(request.form.get('hour', now.hour) or now.hour),
        'minute': int(request.form.get('minute', now.minute) or now.minute),
        'month_gan': request.form.get('month_gan', ''),
        'month_zhi': request.form.get('month_zhi', ''),
        'day_gan': request.form.get('day_gan', ''),
        'day_zhi': request.form.get('day_zhi', ''),
        'result_data': None,
        'result': '',
        'ganzhi_info': {},
        'ygua_codes': [],
        'yao_list': None,
        'is_history': False,
        'remarks': ''
    }

    if request.method == 'POST':
        try:
            subject = (request.form.get('subject') or '').strip()
            if not subject:
                raise ValueError('占测事项不能为空')

            date_str = request.form.get('date', now.strftime('%Y-%m-%d'))
            hour = int(request.form.get('hour', now.hour))
            minute = int(request.form.get('minute', now.minute))
            dt = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=hour, minute=minute)

            month_gan = request.form.get('month_gan', '').strip()
            month_zhi = request.form.get('month_zhi', '').strip()
            day_gan = request.form.get('day_gan', '').strip()
            day_zhi = request.form.get('day_zhi', '').strip()

            gz_month = f'{month_gan}{month_zhi}' if month_gan and month_zhi else None
            gz_day = f'{day_gan}{day_zhi}' if day_gan and day_zhi else None

            ygua_codes = _parse_yao_codes(request.form)
            wapp, result = perform_divination(
                subject,
                ygua_codes,
                dt.year,
                dt.month,
                dt.day,
                dt.hour,
                dt.minute,
                None,
                gz_month,
                gz_day,
                None
            )

            context.update({
                'subject': subject,
                'date_str': date_str,
                'hour': dt.hour,
                'minute': dt.minute,
                'month_gan': month_gan,
                'month_zhi': month_zhi,
                'day_gan': day_gan,
                'day_zhi': day_zhi,
                'result_data': wapp.get_paipan_data(),
                'result': result,
                'ganzhi_info': {
                    'month_gan': month_gan,
                    'month_zhi': month_zhi,
                    'day_gan': day_gan,
                    'day_zhi': day_zhi
                },
                'ygua_codes': ygua_codes,
                'yao_list': [YAO_CODE_TO_TEXT.get(code, '少阳') for code in reversed(ygua_codes)]
            })
        except Exception as e:
            return f'排盘失败: {e}', 500

    return render_template('liuyao/index.html', **context)


@liuyao_bp.route('/save', methods=['POST'])
def save_result():
    try:
        data = request.json or {}
        date_str_full = data.get('date_str')
        dt = datetime.strptime(date_str_full, '%Y-%m-%d %H:%M')
        year = dt.year
        table_name = f'{year}年'

        yaos = data.get('yaos') or []
        if len(yaos) != 6:
            return jsonify({'status': 'error', 'message': '六爻数据不完整'}), 400

        input_mode = data.get('input_mode', 'manual')
        mode_map = {'manual': '指定', 'random': '多随机', 'single': '单随机'}
        mode_cn = mode_map.get(input_mode, input_mode)

        month_gan = data.get('month_gan', '')
        month_zhi = data.get('month_zhi', '')
        day_gan = data.get('day_gan', '')
        day_zhi = data.get('day_zhi', '')
        subject = data.get('subject', '')
        remarks = data.get('remarks', '')

        user_name = getattr(current_user, 'username', None) or getattr(current_user, 'id', None) or 'guest'
        time_formatted = dt.strftime('%Y-%m-%d %H:%M')

        values = {
            'mode_cn': mode_cn,
            'time_formatted': time_formatted,
            'month_gan': month_gan,
            'month_zhi': month_zhi,
            'day_gan': day_gan,
            'day_zhi': day_zhi,
            'yaos': yaos,
            'subject': subject,
            'user_name': str(user_name),
            'remarks': remarks,
            'record_uuid': str(uuid.uuid4())
        }

        _upsert_cloud_record(values, table_name, synced_local=False, sync_error='待同步本地')
        synced = _sync_cloud_to_local(limit_rows=500)

        msg = '保存成功（云端已存储，已同步本地）' if synced > 0 else '保存成功（云端已存储，本地待同步）'
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e:
        print(e)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@liuyao_bp.route('/history')
def history():
    _sync_cloud_to_local(limit_rows=500)
    available_years = _get_available_years()
    current_year = datetime.now().strftime('%Y')

    year_table = request.args.get('year_table', current_year)
    search_date = request.args.get('search_date', '')
    search_subject = request.args.get('search_subject', '')
    search_user = request.args.get('search_user', '')

    results = []
    if year_table in available_years:
        table_name = f'{year_table}年'
        try:
            conn = _get_cloud_sqlite_conn()
            _ensure_cloud_table(conn)
            cursor = conn.cursor()

            query = 'SELECT * FROM liuyao_records WHERE year_table = ?'
            params = [table_name]
            if search_date:
                query += ' AND 时间 LIKE ?'
                params.append(f'{search_date}%')
            if search_subject:
                query += ' AND 标的 LIKE ?'
                params.append(f'%{search_subject}%')
            if search_user:
                query += ' AND 用户 LIKE ?'
                params.append(f'%{search_user}%')
            query += ' ORDER BY id DESC'

            cursor.execute(query, params)
            rows = cursor.fetchall()
            for row in rows:
                yaos_str = f"{row['初爻']}{row['二爻']}{row['三爻']}{row['四爻']}{row['五爻']}{row['上爻']}"
                results.append({
                    'id': row['id'],
                    'time': row['时间'],
                    'user': row['用户'],
                    'subject': row['标的'],
                    'mode': row['起卦方式'],
                    'month_gz': f"{row['月干']}{row['月支']}",
                    'day_gz': f"{row['日干']}{row['日支']}",
                    'yaos': yaos_str
                })

            cursor.close()
            conn.close()
        except Exception as e:
            print(f'Error querying cloud sqlite history: {e}')

    return render_template(
        'liuyao/history.html',
        results=results,
        available_years=available_years,
        current_year=year_table,
        search_date=search_date,
        search_subject=search_subject,
        search_user=search_user
    )


@liuyao_bp.route('/history/view/<year_table>/<int:record_id>')
def view_history(year_table, record_id):
    if not re.match(r'^\d{4}$', year_table):
        return 'Invalid year', 400

    table_name = f'{year_table}年'
    try:
        conn = _get_cloud_sqlite_conn()
        _ensure_cloud_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM liuyao_records WHERE year_table = ? AND id = ?',
            (table_name, record_id)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return 'Record not found', 404

        time_str = row['时间']
        try:
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
        except ValueError:
            dt = datetime.now()

        ygua_codes = [str(row['初爻']), str(row['二爻']), str(row['三爻']), str(row['四爻']), str(row['五爻']), str(row['上爻'])]
        gz_month = f"{row['月干']}{row['月支']}"
        gz_day = f"{row['日干']}{row['日支']}"

        wapp = create_wapp(
            subject=row['标的'],
            ygua=ygua_codes,
            year=dt.year,
            month=dt.month,
            day=dt.day,
            hour=dt.hour,
            minute=dt.minute,
            gz_year=None,
            gz_month=gz_month,
            gz_day=gz_day,
            gz_hour=None
        )

        result_data = wapp.get_paipan_data()
        ganzhi_info = {
            'month_gan': row['月干'],
            'month_zhi': row['月支'],
            'day_gan': row['日干'],
            'day_zhi': row['日支']
        }

        return render_template(
            'liuyao/index.html',
            result_data=result_data,
            result=wapp.get_paipan_string(),
            subject=row['标的'],
            user=row['用户'],
            remarks=row.get('备注', ''),
            year_table=year_table,
            record_id=record_id,
            date_str=dt.strftime('%Y-%m-%d'),
            hour=dt.hour,
            minute=dt.minute,
            ganzhi_info=ganzhi_info,
            ygua_codes=ygua_codes,
            yao_list=[YAO_CODE_TO_TEXT.get(code, '少阳') for code in reversed(ygua_codes)],
            month_gan=row['月干'],
            month_zhi=row['月支'],
            day_gan=row['日干'],
            day_zhi=row['日支'],
            input_mode='manual',
            is_history=True,
            tiangan=TIANGAN,
            dizhi=DIZHI
        )
    except Exception as e:
        print(f'Error viewing history: {e}')
        return f'Error: {e}', 500


@liuyao_bp.route('/update_remarks', methods=['POST'])
def update_remarks():
    try:
        data = request.json or {}
        year_table = data.get('year_table')
        record_id = data.get('record_id')
        remarks = data.get('remarks')

        if not year_table or not record_id:
            return jsonify({'status': 'error', 'message': 'Missing parameters'}), 400

        table_name = f'{year_table}年'
        conn = _get_cloud_sqlite_conn()
        _ensure_cloud_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT record_uuid FROM liuyao_records WHERE year_table = ? AND id = ?',
            (table_name, record_id)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return jsonify({'status': 'error', 'message': '记录不存在'}), 404

        cursor.execute(
            'UPDATE liuyao_records SET 备注 = ?, 已同步本地 = 0, 同步错误 = ?, 更新时间 = ? WHERE year_table = ? AND id = ?',
            (remarks, '备注变更待同步本地', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), table_name, record_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        synced = _sync_cloud_to_local(limit_rows=500)
        msg = '备注更新成功（已同步本地）' if synced > 0 else '备注更新成功（本地待同步）'
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e:
        print(e)
        return jsonify({'status': 'error', 'message': str(e)}), 500
