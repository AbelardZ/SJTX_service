from flask import Flask
from pathlib import Path
import sys
import importlib.util
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

from extensions import login_manager
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

class DummyUser:
    def __init__(self, user_id):
        self.id = user_id
    @property
    def is_authenticated(self): return True
    @property
    def is_active(self): return True
    @property
    def is_anonymous(self): return False
    def get_id(self): return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    return DummyUser(user_id)


BASE_DIR = Path(__file__).parent.parent
REPORT_DIR = BASE_DIR / 'Daily-Frequency General Analysis' / 'Contribution Analysis'

# ============================================================
# 蓝图注册 — 各业务模块前后端放在各自子文件夹中
# ============================================================

# --- Web 内部路由 (首页、报告渲染) ---
try:
    from routes.main import main_bp
    app.register_blueprint(main_bp)
except Exception as e: print(f"Failed to load main_bp: {e}")

try:
    from routes.reports import reports_bp
    app.register_blueprint(reports_bp)
except Exception as e: print(f"Failed to load reports_bp: {e}")

# --- 独立模块 (前后端一体，放在项目根目录) ---
_MODULES = [
    ('aiagent_module', 'aiagent_bp'),
    ('monitor_module', 'monitor_bp'),
    ('monitor_module', 'monitor_history_bp'),
    ('industry_module', 'industry_bp'),
]

for module_dir, bp_attr in _MODULES:
    try:
        routes_path = BASE_DIR / module_dir / 'routes.py'
        spec = importlib.util.spec_from_file_location(
            f'{module_dir}.routes', str(routes_path)
        )
        mod = importlib.util.module_from_spec(spec)
        # Add module dir to sys.path temporarily for internal imports
        mod_dir_str = str(BASE_DIR / module_dir)
        if mod_dir_str not in sys.path:
            sys.path.insert(0, mod_dir_str)
        spec.loader.exec_module(mod)
        bp = getattr(mod, bp_attr)
        app.register_blueprint(bp)
    except Exception as e:
        print(f"Failed to load {bp_attr} from {module_dir}: {e}")

if __name__ == '__main__':
    host = '0.0.0.0'
    port = 5005
    print(f'启动 Flask...')
    print(f'访问地址（本机）: http://{host}:{port}')
    print('若需要外部访问，请使用内网穿透工具；或修改 host 为 0.0.0.0（注意安全）。')
    print('贡献度分析使用数据库存储')
    app.run(host=host, port=port, debug=False)
