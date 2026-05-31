import csv
import json
from pathlib import Path

import markdown

from flask import Blueprint, Response, abort, jsonify, render_template, render_template_string

industry_bp = Blueprint('industry', __name__, url_prefix='/industry', template_folder='templates')

_MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = _MODULE_DIR.parent
INDUSTRY_CSV_PATH = BASE_DIR / 'industry_module' / 'sw_industry_code_map.csv'
INDUSTRY_DOC_DIR = BASE_DIR / 'industry_module' / 'industry'
STOCKDATA_DIR = BASE_DIR / 'industry_module' / 'stockdata'
REPORTS_DIR = BASE_DIR / 'industry_module' / 'reports'


def _resolve_industry_doc(doc_path: str) -> Path | None:
    if not doc_path:
        return None

    candidate = (INDUSTRY_DOC_DIR / Path(doc_path)).resolve()
    try:
        candidate.relative_to(INDUSTRY_DOC_DIR.resolve())
    except ValueError:
        return None

    if candidate.suffix.lower() not in ('.md', '.markdown'):
        candidate = candidate.with_suffix('.md')

    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _extract_doc_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        text = line.strip().lstrip('#').strip()
        if text:
            return text.strip('*').strip()
    return fallback


def _flatten_toc_tokens(tokens):
    outline = []

    def walk(items, depth=0):
        for item in items or []:
            outline.append({
                'level': item.get('level', depth + 1),
                'name': item.get('name', ''),
                'id': item.get('id', ''),
            })
            children = item.get('children') or []
            if children:
                walk(children, depth + 1)

    walk(tokens or [])
    return outline


@industry_bp.route('/')
def index():
    return render_template_string(
        '\n        <h2>行业深度</h2>\n        <p>占位页面：后续将提供行业深度分析和下钻功能。</p>\n        <p><a href="/industry/homepage">进入申万行业层级页面</a></p>\n        <p><a href="/">返回首页</a></p>\n        '
    )


@industry_bp.route('/homepage')
def homepage():
    return render_template('industry/homepage.html')


@industry_bp.route('/source')
def source():
    if not INDUSTRY_CSV_PATH.exists():
        abort(404, description='sw_industry_code_map.csv not found')

    csv_text = INDUSTRY_CSV_PATH.read_text(encoding='utf-8')
    return Response(csv_text, mimetype='text/csv; charset=utf-8')


@industry_bp.route('/doc/<path:doc_path>')
def doc_view(doc_path):
    doc_file = _resolve_industry_doc(doc_path)
    if not doc_file:
        abort(404, description='industry doc not found')

    content = doc_file.read_text(encoding='utf-8')
    title = _extract_doc_title(content, doc_file.stem)
    md = markdown.Markdown(extensions=['fenced_code', 'tables', 'toc', 'sane_lists', 'nl2br'])
    html = md.convert(content)
    relative_path = str(doc_file.relative_to(INDUSTRY_DOC_DIR)).replace('\\', '/')
    breadcrumb_parts = list(doc_file.relative_to(INDUSTRY_DOC_DIR).parts)
    outline = _flatten_toc_tokens(getattr(md, 'toc_tokens', []))

    return render_template(
        'industry/doc_viewer.html',
        title=title,
        doc_path=relative_path,
        breadcrumb_parts=breadcrumb_parts,
        doc_html=html,
        file_name=doc_file.name,
        outline=outline,
    )


@industry_bp.route('/doc/raw/<path:doc_path>')
def doc_raw(doc_path):
    doc_file = _resolve_industry_doc(doc_path)
    if not doc_file:
        abort(404, description='industry doc not found')

    content = doc_file.read_text(encoding='utf-8')
    return Response(content, mimetype='text/markdown; charset=utf-8')


def _find_latest_stockdata_csv() -> tuple[Path | None, str]:
    """Return (path, date_str) of the newest CSV in stockdata/ by filename date."""
    if not STOCKDATA_DIR.exists():
        return None, ''

    csv_files = sorted(STOCKDATA_DIR.glob('*.csv'))
    if not csv_files:
        return None, ''

    # Pick the file with the latest mtime as tiebreaker; prefer filename date order
    latest = max(csv_files, key=lambda p: (p.stem, p.stat().st_mtime))
    date_str = latest.stem  # e.g. "2026-05-29"
    return latest, date_str


@industry_bp.route('/stockdata/latest')
def stockdata_latest():
    """Return the latest stock data as a JSON map keyed by stock code."""
    csv_path, date_str = _find_latest_stockdata_csv()
    if not csv_path:
        return jsonify({'date': '', 'data': {}, 'error': 'No stock data CSV found'})

    data_map = {}
    try:
        with csv_path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get('股票代码') or '').strip()
                if not code:
                    continue
                data_map[code] = {
                    'market_cap': row.get('市值_亿', '').strip(),
                    'ret_1d': row.get('1日收益率_%', '').strip(),
                    'ret_5d': row.get('5日收益率_%', '').strip(),
                    'ret_10d': row.get('10日收益率_%', '').strip(),
                    'ret_20d': row.get('20日收益率_%', '').strip(),
                    'ret_60d': row.get('60日收益率_%', '').strip(),
                }
    except Exception as e:
        return jsonify({'date': date_str, 'data': {}, 'error': str(e)})

    return jsonify({'date': date_str, 'data': data_map})


@industry_bp.route('/reports')
def list_reports():
    """列出 /reports 目录下的所有研究报告，按修改时间倒序，最多返回 6 篇。"""
    if not REPORTS_DIR.exists():
        return jsonify({'reports': []})

    report_files = []
    for f in REPORTS_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in ('.md', '.markdown'):
            stat = f.stat()
            content = f.read_text(encoding='utf-8')
            # 统计中文字数（去掉标点空格等，只算中文字符+英文单词）
            word_count = count_report_words(content)
            report_files.append({
                'name': f.stem,
                'filename': f.name,
                'mtime': stat.st_mtime,
                'mtime_iso': format_timestamp(stat.st_mtime),
                'size': stat.st_size,
                'word_count': word_count,
            })

    # 按修改时间倒序
    report_files.sort(key=lambda x: x['mtime'], reverse=True)

    # 最多返回 6 篇
    latest = report_files[:6]

    return jsonify({'reports': latest})


@industry_bp.route('/reports/raw/<path:filename>')
def report_raw(filename):
    """返回单篇研究报告的原始 Markdown 内容。"""
    report_file = REPORTS_DIR / filename
    if not report_file.exists() or not report_file.is_file():
        abort(404, description='报告未找到')

    content = report_file.read_text(encoding='utf-8')
    return Response(content, mimetype='text/markdown; charset=utf-8')


def count_report_words(text: str) -> int:
    """统计报告字数：中文字符 + 英文单词数。"""
    import re
    # 匹配中文字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    # 匹配英文单词
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    return chinese_chars + english_words


def format_timestamp(ts: float) -> str:
    """将 Unix 时间戳格式化为 ISO 日期字符串。"""
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
