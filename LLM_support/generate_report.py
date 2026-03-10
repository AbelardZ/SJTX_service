import pymysql
import os
import sys
from datetime import datetime, timedelta
import argparse

# Import config handling both package and script modes
try:
    from .config import get_db_connection
except (ImportError, ValueError):
    # Fallback for script execution or direct import
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from config import get_db_connection

def get_latest_date(cursor):
    try:
        cursor.execute("SHOW TABLES LIKE 'Index_%'")
        tables = cursor.fetchall()
        dates = []
        for table in tables:
            val = list(table.values())[0]
            if val.lower().startswith('index_'):
                dates.append(val[6:])
        
        if dates:
            dates.sort(reverse=True)
            return dates[0]
    except Exception as e:
        print(f"Error finding latest date: {e}")
    return datetime.now().strftime('%Y_%m_%d')

def fetch_data(date_str):
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    data = {}
    
    try:
        # 1. Indices
        index_table = f"Index_{date_str}"
        cursor.execute(f"SELECT * FROM `{index_table}`")
        indices = cursor.fetchall()
        data['indices'] = indices
        
        # Major Index Volume Diff
        major_index = next((i for i in indices if i['index_code'] == '000985'), None)
        if major_index:
            # Find previous date
            cursor.execute("SHOW TABLES LIKE 'Index_%'")
            all_tables = [list(t.values())[0] for t in cursor.fetchall()]
            all_dates = sorted([t[6:] for t in all_tables if t.lower().startswith('index_')], reverse=True)
            if date_str in all_dates:
                curr_idx = all_dates.index(date_str)
                if curr_idx < len(all_dates) - 1:
                    prev_date = all_dates[curr_idx + 1]
                    cursor.execute(f"SELECT amount FROM `Index_{prev_date}` WHERE index_code='000985'")
                    res = cursor.fetchone()
                    if res:
                        major_index['vol_diff'] = major_index['amount'] - res['amount']
        data['major_index'] = major_index

        # 2. Industry
        sw1_table = f"SW1_{date_str}"
        cursor.execute(f"SELECT * FROM `{sw1_table}` ORDER BY change_pct DESC")
        data['sw1'] = cursor.fetchall()
        
        sw2_table = f"SW2_{date_str}"
        cursor.execute(f"SELECT * FROM `{sw2_table}` ORDER BY change_pct DESC")
        data['sw2'] = cursor.fetchall()

        # 3. Limit Up
        limitup_table = f"limitup_{date_str}"
        cursor.execute(f"SELECT * FROM `{limitup_table}`")
        data['limitup'] = cursor.fetchall()
        
        # Limit Up Count Diff
        cursor.execute("SHOW TABLES LIKE 'limitup_%'")
        all_tables = [list(t.values())[0] for t in cursor.fetchall()]
        all_dates = sorted([t[8:] for t in all_tables if t.lower().startswith('limitup_')], reverse=True)
        if date_str in all_dates:
            curr_idx = all_dates.index(date_str)
            if curr_idx < len(all_dates) - 1:
                prev_date = all_dates[curr_idx + 1]
                cursor.execute(f"SELECT COUNT(*) as cnt FROM `limitup_{prev_date}`")
                res = cursor.fetchone()
                data['limitup_prev_count'] = res['cnt']

        # 4. Short Term
        date_dash = date_str.replace('_', '-')
        cursor.execute(f"SELECT * FROM `dailyshort` WHERE date = '{date_dash}'")
        data['short'] = cursor.fetchone()

    except Exception as e:
        print(f"Error fetching data: {e}")
    finally:
        cursor.close()
        conn.close()
    
    return data

def format_money(num):
    if num is None: return '-'
    val = float(num)
    if abs(val) > 100000000:
        return f"{val/100000000:.2f}亿"
    if abs(val) > 10000:
        return f"{val/10000:.2f}万"
    return f"{val:.2f}"

def format_pct(num):
    if num is None: return '-'
    return f"{float(num):.2f}%"

def generate_markdown(date_str, data):
    lines = []
    lines.append(f"# A股复盘报告 - {date_str.replace('_', '-')}")
    lines.append("")
    
    # 1. 市场总览
    lines.append("## 1. 市场总览")
    major = data.get('major_index')
    if major:
        vol_status = "放量" if major.get('vol_diff', 0) > 0 else "缩量"
        vol_diff_str = format_money(abs(major.get('vol_diff', 0)))
        lines.append(f"**中证全指 (000985)**: 收盘 {major['close']:.2f} ({format_pct(major['change_percent'])})")
        lines.append(f"- 成交额: {format_money(major['amount'])} ({vol_status} {vol_diff_str})")
    
    lines.append("\n### 主要指数表现")
    lines.append("| 指数 | 名称 | 涨跌幅 | 成交额 |")
    lines.append("|---|---|---|---|")
    
    target_codes = ['000001', '399006', '000688', '000300', '000905', '000852', '932000', '000016', '399673']
    indices = data.get('indices', [])
    for code in target_codes:
        idx = next((i for i in indices if i['index_code'] == code), None)
        if idx:
            lines.append(f"| {idx['index_code']} | {idx['index_name']} | {format_pct(idx['change_percent'])} | {format_money(idx['amount'])} |")
            
    # 2. 短线情绪
    lines.append("\n## 2. 短线情绪")
    short = data.get('short')
    if short:
        lines.append(f"- **短线情绪指数**: {short['com_short_index']}")
        lines.append(f"- **市场高度**: {int(short['Highest'])}板 ({short['Higheststock']})")
        lines.append(f"- **涨跌家数**: 上涨 {int(short['advancing_number'])} / 下跌 {int(short['declining_number'])}")
        lines.append(f"- **涨停/跌停**: 涨停 {len(data.get('limitup', []))} / 跌停 {int(short['limitdown_number'])}")
        lines.append(f"- **大幅涨跌**: 涨幅>5% {int(short['gaining_more_5_number'])} / 跌幅>5% {int(short['losing_more_5_number'])}")
        lines.append(f"- **连板率**: 一进二 {format_pct(short['one_to_two_rate'])}, 二进三 {format_pct(short['two_to_three_rate'])}, 总连板 {format_pct(short['total_successive_rate'])}")
        lines.append(f"- **封板率**: {format_pct(short['limitup_stable_rate'])}")
    
    # 3. 行业板块
    lines.append("\n## 3. 行业板块")
    lines.append("### 3.1 申万一级 (领涨)")
    sw1 = data.get('sw1', [])
    for item in sw1[:5]:
        # SW1 amount is likely in 100 millions (Yi) already
        amt = item.get('amount', 0)
        amt_str = f"{float(amt):.2f}亿" if amt is not None else "-"
        lines.append(f"- **{item['index_name']}**: {format_pct(item['change_pct'])} (成交额: {amt_str})")
    
    lines.append("\n### 3.2 申万一级 (领跌)")
    for item in sw1[-5:][::-1]:
        lines.append(f"- **{item['index_name']}**: {format_pct(item['change_pct'])}")

    lines.append("\n### 3.3 申万二级 (领涨)")
    sw2 = data.get('sw2', [])
    for item in sw2[:5]:
        amt = item.get('amount', 0)
        amt_str = f"{float(amt):.2f}亿" if amt is not None else "-"
        lines.append(f"- **{item['index_name']}**: {format_pct(item['change_pct'])} (成交额: {amt_str})")

    # 4. 涨停梯队
    lines.append("\n## 4. 涨停梯队")
    limitup_list = data.get('limitup', [])
    limitup_list.sort(key=lambda x: x['continuous_limit_number'], reverse=True)
    
    # Group by limit number
    buckets = {}
    for item in limitup_list:
        num = item['continuous_limit_number']
        if num not in buckets: buckets[num] = []
        buckets[num].append(item)
    
    sorted_keys = sorted(buckets.keys(), reverse=True)
    for k in sorted_keys:
        stocks = buckets[k]
        if k >= 3:
            lines.append(f"- **{k}连板**:")
            for s in stocks:
                concept = s.get('main_concept')
                if concept:
                    lines.append(f"  - **{s['stock_name']}** ({s['industry']}): {concept}")
                else:
                    lines.append(f"  - **{s['stock_name']}** ({s['industry']})")
        else:
            names = [f"{s['stock_name']}({s['industry']})" for s in stocks]
            lines.append(f"- **{k}连板**: {', '.join(names)}")

    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description='Generate Daily Chart Report')
    parser.add_argument('--date', type=str, help='Date in YYYY_MM_DD format')
    args = parser.parse_args()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    date_str = args.date
    if not date_str:
        date_str = get_latest_date(cursor)
    
    print(f"Generating report for {date_str}...")
    data = fetch_data(date_str)
    
    report_content = generate_markdown(date_str, data)
    
    # Save
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    output_file = os.path.join(output_dir, f"Report_{date_str}.md")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    print(f"Report saved to {output_file}")

if __name__ == "__main__":
    main()
