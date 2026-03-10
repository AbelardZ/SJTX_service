from flask import Blueprint, render_template, request, jsonify
from datetime import datetime
import lib.qimen.qimen as qimen_lib
from routes.auth import role_required

qimen_bp = Blueprint('qimen', __name__, url_prefix='/qimen')

@qimen_bp.route('/')
# @role_required('vip')
def index():
    # 获取请求参数
    date_str = request.args.get('date')
    time_str = request.args.get('time')
    
    # 解析日期时间
    if date_str and time_str:
        try:
            # 处理可能的 ISO 格式
            if 'T' in date_str:
                date = datetime.fromisoformat(date_str)
            else:
                date = datetime.fromisoformat(f'{date_str}T{time_str}')
        except ValueError:
             date = datetime.now()
    elif date_str:
        try:
            date = datetime.fromisoformat(date_str)
        except ValueError:
            date = datetime.now()
    else:
        date = datetime.now()

    # 计算奇门盘
    method = request.args.get('method', '时家')
    options = {
        'type': '四柱',
        'method': method,
        'purpose': '综合',
        'location': '默认位置'
    }

    try:
        qimen_pan = qimen_lib.calculate(date, options)

        # 初始化缺失的属性，确保模板不会报错
        if 'jiuGongAnalysis' not in qimen_pan:
            qimen_pan['jiuGongAnalysis'] = {}

        # 确保每个宫位都有基本属性
        for i in range(1, 10):
            gong_str = str(i)
            if gong_str not in qimen_pan['jiuGongAnalysis']:
                qimen_pan['jiuGongAnalysis'][gong_str] = {
                    'direction': '',
                    'gongName': '',
                    'jiXiong': 'ping'
                }

        # 检查是否请求 JSON 格式
        if request.args.get('format') == 'json':
            return jsonify(qimen_pan)

        # 传递常量给视图
        return render_template('qimen/index.html', qimen=qimen_pan,
                             JIU_GONG=qimen_lib.JIU_GONG,
                             JIU_XING=qimen_lib.JIU_XING,
                             BA_MEN=qimen_lib.BA_MEN,
                             BA_SHEN=qimen_lib.BA_SHEN)
    except Exception as error:
        print(f'排盘错误: {error}')
        return f'排盘错误: {str(error)}', 500

@qimen_bp.route('/custom')
def custom():
    # 获取请求参数
    type_param = request.args.get('type', '四柱')
    method = request.args.get('method', '时家')
    date_str = request.args.get('date')
    time_str = request.args.get('time')
    location = request.args.get('location', '默认位置')
    purpose = request.args.get('purpose', '综合')

    # 解析日期时间
    if date_str and time_str:
        try:
            date = datetime.fromisoformat(f'{date_str}T{time_str}')
        except ValueError:
             return '无效的日期时间格式', 400
    else:
        date = datetime.now()

    # 检查日期是否有效
    if date is None:
        return '无效的日期时间', 400

    try:
        # 计算奇门盘
        options = {
            'type': type_param,
            'method': method,
            'purpose': purpose,
            'location': location
        }

        qimen_pan = qimen_lib.calculate(date, options)

        # 初始化缺失的属性，确保模板不会报错
        if 'jiuGongAnalysis' not in qimen_pan:
            qimen_pan['jiuGongAnalysis'] = {}

        # 确保每个宫位都有基本属性
        for i in range(1, 10):
            gong_str = str(i)
            if gong_str not in qimen_pan['jiuGongAnalysis']:
                qimen_pan['jiuGongAnalysis'][gong_str] = {
                    'direction': '',
                    'gongName': '',
                    'jiXiong': 'ping'
                }

        # 检查是否请求 JSON 格式
        if request.args.get('format') == 'json':
            return jsonify(qimen_pan)

        # 传递常量给视图
        return render_template('qimen/index.html', qimen=qimen_pan,
                             JIU_GONG=qimen_lib.JIU_GONG,
                             JIU_XING=qimen_lib.JIU_XING,
                             BA_MEN=qimen_lib.BA_MEN,
                             BA_SHEN=qimen_lib.BA_SHEN)
    except Exception as error:
        print(f'排盘错误: {error}')
        return f'排盘错误: {str(error)}', 500
