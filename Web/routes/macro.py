# Source Generated with Decompyle++
# File: macro.cpython-310.pyc (Python 3.10)

from flask import Blueprint, render_template_string
macro_bp = Blueprint('macro', __name__, url_prefix='/macro')

def index():
    return render_template_string('\n        <h2>宏观研究</h2>\n        <p>占位页面：后续将接入宏观研究报告与交互图表。</p>\n        <p><a href="/">返回首页</a></p>\n        ')

index = macro_bp.route('/')(index)
