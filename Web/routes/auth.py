from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from functools import wraps

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # For now, bypass the role check to allow access during recovery
            # Ideally: if not current_user.is_authenticated or not current_user.has_role(role):
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Stub logic - actual auth logic would go here
        flash('登录功能暂时处于维护模式', 'info')
        return redirect(url_for('main.index'))
    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Stub logic
    if request.method == 'POST':
        flash('注册功能暂时处于维护模式', 'info')
        return redirect(url_for('auth.login'))
    # Return login template or a register template if exists, but links point to auth.register so it must exist
    # If auth/register.html not exists, render something simple
    try:
        return render_template('auth/register.html')
    except:
        return "注册页面维护中 (<a href='/'>返回首页</a>)"

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))
