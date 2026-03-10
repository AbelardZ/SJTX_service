# Source Generated with Decompyle++
# File: reports.cpython-310.pyc (Python 3.10)

from flask import Blueprint, render_template_string, send_file, url_for
from pathlib import Path
import markdown
import re
reports_bp = Blueprint('reports', __name__, url_prefix='/reports')
REPORT_DIR = Path(__file__).parent.parent.parent / 'Daily-Frequency General Analysis' / 'Contribution Analysis'

def _parse_title_from_md(content, default):
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('#'):
            return line.lstrip('#').strip()
        return default


def _find_related_csv(report_name):
    stem = Path(report_name).stem
    candidates = list(REPORT_DIR.glob(stem + '*.csv'))
    if candidates:
        return candidates[0]
    prefix = None
    if '_Report' in stem:
        prefix = stem.split('_Report')[0]
    else:
        prefix = stem.split('_')[0]
    for p in REPORT_DIR.glob('*.csv'):
        if prefix and prefix in p.stem:
            return p
        return None


def view_report(report_name):
    report_path = REPORT_DIR / report_name
    if not report_path.exists():
        return (f'''报告 {report_name} 不存在''', 404)
    if None.suffix.lower() not in ('.md', '.markdown'):
        return (f'''不支持的报告格式：{report_path.suffix}''', 400)
    with open(report_path, 'r', 'utf-8', **('encoding',)) as f:
        content = f.read()
        None(None, None, None)
# WARNING: Decompyle incomplete

view_report = reports_bp.route('/<report_name>')(view_report)
