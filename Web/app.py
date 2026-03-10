from flask import Flask
from pathlib import Path
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

try:
    from routes.main import main_bp
    app.register_blueprint(main_bp)
except Exception as e: print(f"Failed to load main_bp: {e}")

try:
    from routes.reports import reports_bp
    app.register_blueprint(reports_bp)
except Exception as e: print(f"Failed to load reports_bp: {e}")

try:
    from routes.monitor2 import monitor_bp
    app.register_blueprint(monitor_bp)
except Exception as e: print(f"Failed to load monitor_bp: {e}")

try:
    from routes.monitor_history import monitor_history_bp
    app.register_blueprint(monitor_history_bp)
except Exception as e: print(f"Failed to load monitor_history_bp: {e}")

try:
    from routes.macro import macro_bp
    app.register_blueprint(macro_bp)
except Exception as e: print(f"Failed to load macro_bp: {e}")

try:
    from routes.fund import fund_bp
    app.register_blueprint(fund_bp)
except Exception as e: print(f"Failed to load fund_bp: {e}")

try:
    from routes.industry import industry_bp
    app.register_blueprint(industry_bp)
except Exception as e: print(f"Failed to load industry_bp: {e}")

try:
    from routes.contribution import contribution_bp
    app.register_blueprint(contribution_bp)
except Exception as e: print(f"Failed to load contribution_bp: {e}")

try:
    from routes.callauction import callauction_bp
    app.register_blueprint(callauction_bp)
except Exception as e: print(f"Failed to load callauction_bp: {e}")

try:
    from routes.dailychart import dailychart_bp
    app.register_blueprint(dailychart_bp)
except Exception as e: print(f"Failed to load dailychart_bp: {e}")

try:
    from routes.qimen import qimen_bp
    app.register_blueprint(qimen_bp)
except Exception as e: print(f"Failed to load qimen_bp: {e}")

try:
    from routes.auth import auth_bp
    app.register_blueprint(auth_bp)
except Exception as e: print(f"Failed to load auth_bp: {e}")

try:
    from routes.liuyao import liuyao_bp
    app.register_blueprint(liuyao_bp)
except Exception as e: print(f"Failed to load liuyao_bp: {e}")

try:
    from routes.short_strategy import short_strategy_bp
    app.register_blueprint(short_strategy_bp)
except Exception as e: print(f"Failed to load short_strategy_bp: {e}")

try:
    from routes.aiagent import aiagent_bp
    app.register_blueprint(aiagent_bp)
except Exception as e: print(f"Failed to load aiagent_bp: {e}")

if __name__ == '__main__':
    host = '0.0.0.0'
    port = 5005
    print(f'启动 Flask...')
    print(f'访问地址（本机）: http://{host}:{port}')
    print('若需要外部访问，请使用内网穿透工具；或修改 host 为 0.0.0.0（注意安全）。')
    print('贡献度分析使用数据库存储')
    app.run(host=host, port=port, debug=False)
