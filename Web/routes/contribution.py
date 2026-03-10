# Source Generated with Decompyle++
# File: contribution.cpython-310.pyc (Python 3.10)

from flask import Blueprint, render_template, jsonify
import datetime
import mysql.connector as mysql
contribution_bp = Blueprint('contribution', __name__, url_prefix='/contribution')
DB_CONFIG = {
    'host': 'localhost',
    'user': 'inv_zhy',
    'password': 'zhy20050112',
    'database': 'DailyIndustryCADB' }

def get_db_connection():
    '''获取数据库连接'''
    pass
# WARNING: Decompyle incomplete


def get_latest_contribution_data():
    '''获取最新的贡献度分析数据'''
    pass
# WARNING: Decompyle incomplete


def index():
    '''贡献度分析主页'''
    (sw1_data, sw2_data, date_str) = get_latest_contribution_data()
    return render_template('contribution.html', sw1_data, sw2_data, date_str, **('sw1_data', 'sw2_data', 'date'))

index = contribution_bp.route('/')(index)

def get_data():
    '''获取贡献度分析数据API'''
    (sw1_data, sw2_data, date_str) = get_latest_contribution_data()
    if not sw1_data:
        pass
    if not sw2_data:
        pass
    return jsonify({
        'sw1': [],
        'sw2': [],
        'date': date_str })

get_data = contribution_bp.route('/api/data')(get_data)

def get_sw1_data():
    '''获取申万一级行业贡献度数据'''
    (sw1_data, _, _) = get_latest_contribution_data()
    if not sw1_data:
        pass
    return jsonify([])

get_sw1_data = contribution_bp.route('/api/sw1')(get_sw1_data)

def get_sw2_data():
    '''获取申万二级行业贡献度数据'''
    (_, sw2_data, _) = get_latest_contribution_data()
    if not sw2_data:
        pass
    return jsonify([])

get_sw2_data = contribution_bp.route('/api/sw2')(get_sw2_data)
