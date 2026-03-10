# Source Generated with Decompyle++
# File: fund.cpython-310.pyc (Python 3.10)

from flask import Blueprint, render_template_string
fund_bp = Blueprint('fund', __name__, url_prefix='/fund')

def index():
    return render_template_string('\n        <h2>资金研究</h2>\n        <p>占位页面：后续将实现资金流向与成交结构分析。</p>\n        <p><a href="/">返回首页</a></p>\n        ')

index = fund_bp.route('/')(index)
