#!/usr/bin/env python3
"""
统一数据抓取启动器
按顺序依次启动五个数据抓取程序：
1. index (指数数据)
2. limitup (涨停数据)
3. sw (申万行业数据)
4. all_data (全市场数据)
5. short (短线分析数据)

每个程序必须在前一个成功完成后才能启动。
"""

import subprocess
import sys
import os
from datetime import datetime

# 定义脚本路径和名称
SCRIPTS = [
    ('data_fetcher_index.py', '指数数据'),
    ('data_fetcher_limitup.py', '涨停数据'),
    ('data_fetcher_sw.py', '申万行业数据'),
    ('data_fetcher_all_data.py', '全市场数据'),
    ('data_fetcher_short.py', '短线分析数据')
]

def run_script(script_name, description):
    """
    运行单个脚本并检查是否成功
    """
    script_path = os.path.join(os.path.dirname(__file__), script_name)

    if not os.path.exists(script_path):
        print(f"错误: 脚本文件 {script_path} 不存在")
        return False

    print(f"\n{'='*50}")
    print(f"开始执行: {description} ({script_name})")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('='*50)

    try:
        # 使用 subprocess.run 执行脚本
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )

        # 打印输出
        if result.stdout:
            print("标准输出:")
            print(result.stdout)

        if result.stderr:
            print("错误输出:")
            print(result.stderr)

        # 检查退出码
        if result.returncode == 0:
            print(f"✅ {description} 执行成功")
            return True
        else:
            print(f"❌ {description} 执行失败 (退出码: {result.returncode})")
            return False

    except subprocess.TimeoutExpired:
        print(f"❌ {description} 执行超时")
        return False
    except Exception as e:
        print(f"❌ {description} 执行异常: {str(e)}")
        return False

def main():
    """
    主函数：按顺序执行所有脚本
    """
    print("🚀 开始统一数据抓取流程")
    print(f"总共需要执行 {len(SCRIPTS)} 个脚本")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    success_count = 0

    for script_name, description in SCRIPTS:
        if run_script(script_name, description):
            success_count += 1
        else:
            print(f"\n❌ 流程中断: {description} 执行失败")
            print("请检查错误信息并修复后重新运行")
            break

    print(f"\n{'='*50}")
    print("执行结果统计:")
    print(f"- 成功: {success_count}/{len(SCRIPTS)}")
    print(f"- 结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if success_count == len(SCRIPTS):
        print("🎉 所有数据抓取任务完成！")
        return 0
    else:
        print("⚠️ 部分任务失败，请检查日志")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)