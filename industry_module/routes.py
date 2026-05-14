from pathlib import Path

import markdown

from flask import Blueprint, Response, abort, render_template, render_template_string

industry_bp = Blueprint('industry', __name__, url_prefix='/industry', template_folder='templates')

_MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = _MODULE_DIR.parent
INDUSTRY_CSV_PATH = BASE_DIR / 'industry_module' / 'sw_industry_code_map.csv'
INDUSTRY_DOC_DIR = BASE_DIR / 'industry_module' / 'industry'


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
