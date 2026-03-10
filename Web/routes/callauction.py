# Source Generated with Decompyle++
# File: callauction.cpython-310.pyc (Python 3.10)

from flask import Blueprint, request, jsonify, render_template
import mysql.connector as mysql
from datetime import datetime
import json
import os
from pathlib import Path
BASE_DIR = Path(__file__).parent.parent.parent
CALLAUCTION_DIR = BASE_DIR / 'CallAution'
callauction_bp = Blueprint('callauction', __name__, url_prefix='/callauction')

def get_db_connection():
    '''获取数据库连接 - 使用现有的数据库配置'''
    return mysql.connector.connect('localhost', 'root', '123456', 'CallAuctionDB', **('host', 'user', 'password', 'database'))


def create_table_for_today():
    '''创建当天的表（如果不存在）'''
    pass
# WARNING: Decompyle incomplete


def index():
    '''集合竞价数据展示页面'''
    return render_template('callauction.html')

index = callauction_bp.route('/')(index)

def get_data():
    '''获取集合竞价数据API'''
    concept = request.args.get('concept')
    stock_code = request.args.get('stock_code')
    stock_name = request.args.get('stock_name')
    today = datetime.now().strftime('%Y_%m_%d')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = f'''\n    SELECT t1.* FROM `{today}` t1\n    INNER JOIN (\n        SELECT stock_code, MAX(timestamp) as max_timestamp\n        FROM `{today}`\n        GROUP BY stock_code\n    ) t2 ON t1.stock_code = t2.stock_code AND t1.timestamp = t2.max_timestamp\n    WHERE 1=1\n    '''
    params = []
    if concept:
        query += ' AND t1.concept = %s'
        params.append(concept)
    if stock_code:
        query += ' AND t1.stock_code = %s'
        params.append(stock_code)
    if stock_name:
        query += ' AND t1.stock_name LIKE %s'
        params.append(f'''%{stock_name}%''')
# WARNING: Decompyle incomplete

get_data = callauction_bp.route('/api/data', methods=['GET'])(get_data)

def get_concepts():
    '''获取所有可用的概念列表'''
    concepts = set()
    today = datetime.now().strftime('%Y_%m_%d')
    conn = get_db_connection()
    cursor = conn.cursor()
# WARNING: Decompyle incomplete

get_concepts = callauction_bp.route('/api/concepts', methods=['GET'])(get_concepts)

def get_stocks():
    '''获取股票配置'''
    config_path = CALLAUCTION_DIR / 'stocks_config.json'
# WARNING: Decompyle incomplete

get_stocks = callauction_bp.route('/api/stocks', methods=['GET'])(get_stocks)

def update_stocks():
    '''更新股票配置'''
    data = request.get_json()
    config_path = CALLAUCTION_DIR / 'stocks_config.json'
    with open(config_path, 'w', 'utf-8', **('encoding',)) as f:
        json.dump(data, f, 4, False, **('indent', 'ensure_ascii'))
        None(None, None, None)
# WARNING: Decompyle incomplete

update_stocks = callauction_bp.route('/api/stocks', methods=['POST'])(update_stocks)
