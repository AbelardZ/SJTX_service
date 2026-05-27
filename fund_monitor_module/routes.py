from flask import Blueprint, render_template, send_from_directory, jsonify, request
from pathlib import Path
import csv
import os

fund_bp = Blueprint('fund', __name__, url_prefix='/fund')

_MODULE_DIR = Path(__file__).resolve().parent


@fund_bp.route('/')
def index():
    """公募基金重仓股跟踪主页"""
    # 直接返回模块目录下的 index.html
    return send_from_directory(str(_MODULE_DIR), 'index.html')


@fund_bp.route('/<path:filename>')
def static_files(filename):
    """提供模块内的静态文件（CSS, JS, CSV 数据等）"""
    return send_from_directory(str(_MODULE_DIR), filename)


@fund_bp.route('/data/<path:filename>')
def data_files(filename):
    """提供 data 目录下的 CSV 文件"""
    data_dir = str(_MODULE_DIR / 'data')
    return send_from_directory(data_dir, filename)
