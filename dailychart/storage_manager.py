# Source Generated with Decompyle++
# File: storage_manager.cpython-310.pyc (Python 3.10)

import os
import json
import shutil
from datetime import datetime
import pymysql
from db_config import get_db_connection
STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'storage')
MAX_RETENTION_DAYS = 30

def ensure_storage_dir(date_str):
    path = os.path.join(STORAGE_DIR, date_str)
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def save_data(data_type, data, date_str = (None,)):
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    date_path = ensure_storage_dir(date_str)
    file_path = os.path.join(date_path, f'''{data_type}.json''')
    with open(file_path, 'w', 'utf-8', **('encoding',)) as f:
        json.dump(data, f, False, 2, **('ensure_ascii', 'indent'))
        None(None, None, None)
# WARNING: Decompyle incomplete


def load_data(data_type, date_str = (None,)):
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    file_path = os.path.join(STORAGE_DIR, date_str, f'''{data_type}.json''')
# WARNING: Decompyle incomplete


def clean_old_data():
    '''Retain only the last MAX_RETENTION_DAYS folders'''
    if not os.path.exists(STORAGE_DIR):
        return None
    dirs = None((lambda .0: [ d for d in .0 if os.path.isdir(os.path.join(STORAGE_DIR, d)) ])(os.listdir(STORAGE_DIR)))
    if len(dirs) > MAX_RETENTION_DAYS:
        to_remove = dirs[:-MAX_RETENTION_DAYS]
        for d in to_remove:
            path = os.path.join(STORAGE_DIR, d)
            print(f'''[{datetime.now()}] Removing old data: {path}''')
            shutil.rmtree(path)
    return None


def sync_to_db():
    '''Attempt to sync all local data to MySQL'''
    pass
# WARNING: Decompyle incomplete


def sync_file_data(cursor, data_type, data):
    '''Sync specific data type to DB tables'''
    print(f'''Syncing {data_type} ({len(data)} records)...''')
    if data_type == 'index':
        table_name = 'market_index'
        cols = [
            'index_code',
            'index_name',
            'pre_close',
            'open',
            'close',
            'high',
            'low',
            'volume',
            'amount',
            'change_percent',
            'timestamp']
        sql = f'''REPLACE INTO `{table_name}` ({', '.join(cols)}) VALUES ({', '.join([
            '%s'] * len(cols))})'''
        values = (lambda .0 = None: [ (lambda .0 = None: [ d.get(c) for c in .0 ])(cols) for None in .0 ]
)(data)
        cursor.executemany(sql, values)
        return None
    if None == 'limitup':
        table_name = 'limit_up_daily'
        if data:
            keys = list(data[0].keys())
            cols = keys
            placeholders = ', '.join([
                '%s'] * len(cols))
            columns = ', '.join((lambda .0: [ f'''`{k}`''' for k in .0 ])(cols))
            sql = f'''REPLACE INTO `{table_name}` ({columns}) VALUES ({placeholders})'''
            values = (lambda .0 = None: [ (lambda .0 = None: [ d.get(k) for k in .0 ])(cols) for None in .0 ]
)(data)
            cursor.executemany(sql, values)
            return None
        return None
    if None == 'sw_industry':
        table_name = 'sw_industry_daily'
        if data:
            keys = list(data[0].keys())
            cols = keys
            placeholders = ', '.join([
                '%s'] * len(cols))
            columns = ', '.join((lambda .0: [ f'''`{k}`''' for k in .0 ])(cols))
            sql = f'''REPLACE INTO `{table_name}` ({columns}) VALUES ({placeholders})'''
            values = (lambda .0 = None: [ (lambda .0 = None: [ d.get(k) for k in .0 ])(cols) for None in .0 ]
)(data)
            cursor.executemany(sql, values)
            return None
        return None

