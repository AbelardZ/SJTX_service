# Source Generated with Decompyle++
# File: industry.cpython-310.pyc (Python 3.10)

from flask import Blueprint, render_template_string
industry_bp = Blueprint('industry', __name__, url_prefix='/industry')

def index():
    return render_template_string('\n        <h2>行业深度</h2>\n        <p>占位页面：后续将提供行业深度分析和下钻功能。</p>\n        <p><a href="/">返回首页</a></p>\n        ')

index = industry_bp.route('/')(index)
