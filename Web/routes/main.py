# Source Generated with Decompyle++
# File: main.cpython-310.pyc (Python 3.10)

from flask import Blueprint, render_template, url_for, redirect
from pathlib import Path
main_bp = Blueprint('main', __name__)

def index():
    BASE_DIR = Path(__file__).parent.parent.parent
    REPORT_DIR = BASE_DIR / 'Daily-Frequency General Analysis' / 'Contribution Analysis'
    reports = []
    if REPORT_DIR.exists():
        for p in sorted(REPORT_DIR.iterdir(), reverse=True):
            if p.suffix.lower() in ('.md', '.markdown') and 'Report' in p.name:
                name = p.name
                display = name.replace('_', ' ').rsplit('.', 1)[0]
                reports.append({
                    'filename': p.name,
                    'display': display,
                    'ext': p.suffix.lower() })
    return render_template('index.html', reports=reports)

index = main_bp.route('/')(index)

def limitup_redirect():
    return redirect(url_for('dailychart.limitup'))

limitup_redirect = main_bp.route('/limitup/')(limitup_redirect)

def limitup_admin_redirect():
    return redirect(url_for('dailychart.limitup_admin'))

limitup_admin_redirect = main_bp.route('/limitup/admin')(limitup_admin_redirect)
