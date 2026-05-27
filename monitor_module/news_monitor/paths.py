from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_ROOT / "data"
DB_PATH = PACKAGE_ROOT / "news_buffer.db"
REPORTS_DIR = DATA_DIR / "newsagent_reports"
