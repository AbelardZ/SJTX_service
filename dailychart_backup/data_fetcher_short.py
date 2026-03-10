import akshare as ak
import pandas as pd
import pymysql
from datetime import datetime, timedelta
from db_config import get_db_connection
from proxy_config import enable_proxy, refresh_proxy

# 启用代理（如果已配置）
enable_proxy()

def get_stocks_by_change(date_underscore, change_threshold=5):
    try:
        # 从数据库读取全市场数据
        table_name = f"all_data_{date_underscore}"
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM `{table_name}`")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        stock_spot_df = pd.DataFrame(rows, columns=columns)
        cursor.close()
        conn.close()
        
        if stock_spot_df.empty:
            print(f"错误: 表 {table_name} 为空或不存在。")
            return 0, 0
        
        # 确保change_pct列存在
        if 'change_pct' not in stock_spot_df.columns:
            print("错误: 数据库中缺少change_pct列。")
            return 0, 0
        
        stock_spot_df['change_pct'] = pd.to_numeric(stock_spot_df['change_pct'], errors='coerce')
        stock_spot_cleaned = stock_spot_df.dropna(subset=['change_pct']).copy()
        
        up_stocks = stock_spot_cleaned[stock_spot_cleaned['change_pct'] > change_threshold]
        down_stocks = stock_spot_cleaned[stock_spot_cleaned['change_pct'] < -change_threshold]
        
        return len(up_stocks), len(down_stocks)
    except Exception as e:
        print(f"Error in get_stocks_by_change: {e}")
        return 0, 0

def fetch_and_store_short_data():
    print("开始获取短线数据...")
    
    # 检查是否为交易日
    target_date = datetime.now() # 默认为今天

    try:
        print("正在检查交易日信息...")
        trade_date_df = ak.tool_trade_date_hist_sina()
        trade_dates = pd.to_datetime(trade_date_df['trade_date']).dt.date.tolist()
        current_date_obj = datetime.now().date()
        
        if current_date_obj not in trade_dates:
            print(f"提示: 今天 ({current_date_obj}) 不是交易日。")
            # 寻找上一个交易日
            past_trade_dates = [d for d in trade_dates if d < current_date_obj]
            if past_trade_dates:
                last_trading_day = max(past_trade_dates)
                # 询问用户是否运行上一个交易日
                user_input = input(f"是否抓取上一个交易日 ({last_trading_day}) 的数据？(y/n): ")
                if user_input.strip().lower() == 'y':
                    target_date = datetime(last_trading_day.year, last_trading_day.month, last_trading_day.day)
                    print(f"目标日期已切换为: {target_date.strftime('%Y-%m-%d')}")
                else:
                    print("用户取消，程序停止运行。")
                    return
            else:
                print("无法确定上一个交易日，程序停止运行。")
                return
        else:
            print(f"确认今天 ({current_date_obj}) 是交易日。")
            
    except Exception as e:
        print(f"无法验证交易日信息 (可能是网络问题): {e}")
        print("将尝试继续执行 (默认使用今天)...")

    today_dash = target_date.strftime('%Y-%m-%d')
    today_underscore = target_date.strftime('%Y_%m_%d')
    table_name = "DailyShort"
    
    # 1. 获取 akshare1 数据
    print("正在获取 akshare1 数据 (市场活跃度)...")
    try:
        df_activity = ak.stock_market_activity_legu()
        # df_activity 列名: item, value
        # Items: 上涨, 涨停, 真实涨停, st st*涨停, 下跌, 跌停, 真实跌停, st st*跌停, 平盘, 停牌, 活跃度, 统计日期
        
        activity_map = dict(zip(df_activity['item'], df_activity['value']))
        
        advancing_number = int(activity_map.get('上涨', 0))
        declining_number = int(activity_map.get('下跌', 0))
        unchanged_number = int(activity_map.get('平盘', 0))
        limitup_number = int(activity_map.get('涨停', 0))
        limitdown_number = int(activity_map.get('跌停', 0))
        
        total_number = advancing_number + declining_number + unchanged_number
        ad_ratio = (advancing_number / declining_number * 100) if declining_number > 0 else 0
        
    except Exception as e:
        print(f"Error fetching akshare1: {e}")
        return

    # 刷新代理，确保 IP 存活
    refresh_proxy()

    # 2. 获取 akshare2 数据
    print("正在获取 akshare2 数据 (涨跌幅 > 5%)...")
    gaining_more_5, losing_more_5 = get_stocks_by_change(today_underscore, 5)
    gaining_more_5_rate = (gaining_more_5 / total_number * 100) if total_number > 0 else 0

    # 3. 从 DailyChartDB (LimitUp Data) 计算
    print("正在从 DailyChartDB (LimitUp Data) 计算...")
    conn_limitup = get_db_connection()
    cursor_limitup = conn_limitup.cursor()
    
    # 初始化变量
    limitup_stable_rate = 0
    limitup_nonstability = 0
    limitup_timing = 0
    limitup_capital = 0
    limitup_com_strength = 0
    one_to_two_rate = 0
    two_to_three_rate = 0
    three_to_four_rate = 0
    total_successive_rate = 0
    relay_sentiment_strength = 0
    highest = 0
    highest_stock = ""
    com_short_index = 0

    try:
        # 检查 DailyChartDB 中是否存在今天的 LimitUp 表
        limitup_table_today = f"limitup_{today_underscore}"
        cursor_limitup.execute(f"SHOW TABLES LIKE '{limitup_table_today}'")
        if not cursor_limitup.fetchone():
            print(f"严重错误: DailyChartDB 中不存在表 {limitup_table_today}。无法继续。")
            return

        # 从 DailyChartDB 获取 LimitUp 数据
        cursor_limitup.execute(f"SELECT * FROM `{limitup_table_today}`")
        rows = cursor_limitup.fetchall()
        # 获取列名以确保 DataFrame 列名正确
        columns = [desc[0] for desc in cursor_limitup.description]
        df_limitup = pd.DataFrame(rows, columns=columns)
        
        if df_limitup.empty:
            print(f"严重错误: 表 {limitup_table_today} 为空。无法继续。")
            return

        # 基础统计
        stable_count = len(df_limitup[df_limitup['open_number'] == 0])
        limitup_stable_rate = (stable_count / limitup_number * 100) if limitup_number > 0 else 0
        
        total_open_num = df_limitup['open_number'].sum()
        limitup_nonstability = (total_open_num / limitup_number * 100) if limitup_number > 0 else 0
        
        # 时间 (假设 first_limit_time 是 HH:MM:SS 字符串)
        # 过滤有效时间
        timing_count = 0
        for t in df_limitup['first_limit_time']:
            if t and str(t) < '10:00:00':
                timing_count += 1
        limitup_timing = (timing_count / limitup_number * 100) if limitup_number > 0 else 0
        
        # 资金
        total_sealing = df_limitup['sealing_amount'].sum()
        total_float_cap = df_limitup['float_market_capital'].sum()
        limitup_capital = (total_sealing / total_float_cap * 100) if total_float_cap > 0 else 0
        
        # 综合强度
        limitup_com_strength = ((limitup_stable_rate * 0.2) + (limitup_nonstability * 0.2) + 
                                (limitup_timing * 0.3) + (limitup_capital * 0.3)) * limitup_number * 0.01
        
        # 市场高度
        if 'continuous_limit_number' in df_limitup.columns:
            highest = df_limitup['continuous_limit_number'].max()
            highest_stock_row = df_limitup.loc[df_limitup['continuous_limit_number'].idxmax()]
            highest_stock = highest_stock_row['stock_name']
        
        # 连板率 (需要上一个交易日的数据)
        # 使用交易日列表找到正确的上一个交易日
        previous_trading_day = None
        try:
            # 重新获取交易日列表（确保数据最新）
            trade_date_df = ak.tool_trade_date_hist_sina()
            trade_dates = pd.to_datetime(trade_date_df['trade_date']).dt.date.tolist()
            
            # 找到当前交易日在列表中的位置
            target_date_only = target_date.date()
            if target_date_only in trade_dates:
                current_idx = trade_dates.index(target_date_only)
                if current_idx > 0:
                    previous_trading_day = trade_dates[current_idx - 1]
                    print(f"找到上一个交易日: {previous_trading_day}")
                else:
                    print("警告: 这是第一个交易日，无法计算连板率")
            else:
                print(f"警告: 目标日期 {target_date_only} 不在交易日列表中")
        except Exception as e:
            print(f"获取上一个交易日失败: {e}")
        
        # 如果找到了上一个交易日，查询对应的表
        if previous_trading_day:
            yesterday_underscore = previous_trading_day.strftime('%Y_%m_%d')
            limitup_table_yesterday = f"limitup_{yesterday_underscore}"
            
            cursor_limitup.execute(f"SHOW TABLES LIKE '{limitup_table_yesterday}'")
            if cursor_limitup.fetchone():
                cursor_limitup.execute(f"SELECT stock_code, continuous_limit_number FROM `{limitup_table_yesterday}`")
                rows_yest = cursor_limitup.fetchall()
                # 同样获取昨天的列名
                columns_yest = [desc[0] for desc in cursor_limitup.description]
                df_yest = pd.DataFrame(rows_yest, columns=columns_yest)
                
                if not df_yest.empty:
                    # 数据清洗：确保类型一致
                    df_yest['continuous_limit_number'] = pd.to_numeric(df_yest['continuous_limit_number'], errors='coerce')
                    df_limitup['continuous_limit_number'] = pd.to_numeric(df_limitup['continuous_limit_number'], errors='coerce')
                    
                    # 转换为集合 (Set) 以提高效率和容错 (去除空格，统一转为字符串)
                    yest_1_codes = set(df_yest[df_yest['continuous_limit_number'] == 1]['stock_code'].astype(str).str.strip())
                    yest_2_codes = set(df_yest[df_yest['continuous_limit_number'] == 2]['stock_code'].astype(str).str.strip())
                    yest_3_codes = set(df_yest[df_yest['continuous_limit_number'] == 3]['stock_code'].astype(str).str.strip())
                    yest_all_codes = set(df_yest['stock_code'].astype(str).str.strip())

                    today_2_codes = set(df_limitup[df_limitup['continuous_limit_number'] == 2]['stock_code'].astype(str).str.strip())
                    today_3_codes = set(df_limitup[df_limitup['continuous_limit_number'] == 3]['stock_code'].astype(str).str.strip())
                    today_4_codes = set(df_limitup[df_limitup['continuous_limit_number'] == 4]['stock_code'].astype(str).str.strip())
                    today_all_codes = set(df_limitup['stock_code'].astype(str).str.strip())

                    # 1->2 (昨日1板，今日2板)
                    promoted_1_to_2 = today_2_codes.intersection(yest_1_codes)
                    one_to_two_rate = (len(promoted_1_to_2) / len(yest_1_codes) * 100) if len(yest_1_codes) > 0 else 0
                    print(f"  [连板详情] 1进2: 上个交易日首板{len(yest_1_codes)}家 -> 今日二板晋级{len(promoted_1_to_2)}家 (成功率 {one_to_two_rate:.2f}%)")
                    
                    # 2->3 (昨日2板，今日3板)
                    promoted_2_to_3 = today_3_codes.intersection(yest_2_codes)
                    two_to_three_rate = (len(promoted_2_to_3) / len(yest_2_codes) * 100) if len(yest_2_codes) > 0 else 0
                    print(f"  [连板详情] 2进3: 上个交易日二板{len(yest_2_codes)}家 -> 今日三板晋级{len(promoted_2_to_3)}家 (成功率 {two_to_three_rate:.2f}%)")
                    
                    # 3->4 (昨日3板，今日4板)
                    promoted_3_to_4 = today_4_codes.intersection(yest_3_codes)
                    three_to_four_rate = (len(promoted_3_to_4) / len(yest_3_codes) * 100) if len(yest_3_codes) > 0 else 0
                    print(f"  [连板详情] 3进4: 上个交易日三板{len(yest_3_codes)}家 -> 今日四板晋级{len(promoted_3_to_4)}家 (成功率 {three_to_four_rate:.2f}%)")
                    
                    # 总连板率 (昨日涨停，今日继续涨停)
                    continued_stocks = today_all_codes.intersection(yest_all_codes)
                    total_successive_rate = (len(continued_stocks) / len(yest_all_codes) * 100) if len(yest_all_codes) > 0 else 0
                    print(f"  [连板详情] 总连板: 上个交易日涨停{len(yest_all_codes)}家 -> 今日续板{len(continued_stocks)}家 (成功率 {total_successive_rate:.2f}%)")
                    
                    # 接力情绪强度
                    relay_sentiment_strength = (one_to_two_rate * 0.2) + (two_to_three_rate * 0.3) + (three_to_four_rate * 0.5)
                else:
                    print("上个交易日的涨停数据为空")
            else:
                print(f"上个交易日的涨停表 {limitup_table_yesterday} 不存在")
        else:
            print("无法找到上一个交易日的数据，连板率计算跳过")

    except Exception as e:
        print(f"Error querying DailyChartDB (LimitUp Data): {e}")
    finally:
        cursor_limitup.close()
        conn_limitup.close()

    # 4. 最终计算
    # com_short_index = (Highest/4) * ((relay_sentiment_strength * 0.3) + (limitup_com_strength * 0.3) + (gaining>5%_rate *0.4) ) * (A/D)
    # A/D 即 ad_ratio
    try:
        com_short_index = (highest / 4) * ((relay_sentiment_strength * 0.3) + (limitup_com_strength * 0.3) + (gaining_more_5_rate * 0.4)) * ad_ratio
    except:
        com_short_index = 0

    # 5. 插入 DailyChartDB
    conn = get_db_connection()
    cursor = conn.cursor()
    
    insert_query = f"""
    INSERT INTO `{table_name}` 
    (date, advancing_number, declining_number, AD_ratio, unchanged_number, total_number, 
    limitup_number, limitdown_number, gaining_more_5_number, losing_more_5_number, gaining_more_5_rate,
    limitup_stable_rate, limitup_nonstability, limitup_timing, limitup_capital, limitup_com_strength,
    one_to_two_rate, two_to_three_rate, three_to_four_rate, total_successive_rate, relay_sentiment_strength,
    Highest, Higheststock, com_short_index)
    VALUES 
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    advancing_number=VALUES(advancing_number), declining_number=VALUES(declining_number), AD_ratio=VALUES(AD_ratio),
    unchanged_number=VALUES(unchanged_number), total_number=VALUES(total_number), limitup_number=VALUES(limitup_number),
    limitdown_number=VALUES(limitdown_number), gaining_more_5_number=VALUES(gaining_more_5_number),
    losing_more_5_number=VALUES(losing_more_5_number), gaining_more_5_rate=VALUES(gaining_more_5_rate),
    limitup_stable_rate=VALUES(limitup_stable_rate), limitup_nonstability=VALUES(limitup_nonstability),
    limitup_timing=VALUES(limitup_timing), limitup_capital=VALUES(limitup_capital),
    limitup_com_strength=VALUES(limitup_com_strength), one_to_two_rate=VALUES(one_to_two_rate),
    two_to_three_rate=VALUES(two_to_three_rate), three_to_four_rate=VALUES(three_to_four_rate),
    total_successive_rate=VALUES(total_successive_rate), relay_sentiment_strength=VALUES(relay_sentiment_strength),
    Highest=VALUES(Highest), Higheststock=VALUES(Higheststock), com_short_index=VALUES(com_short_index)
    """
    
    values = (
        today_dash, # date
        advancing_number, declining_number, round(ad_ratio, 2), unchanged_number, total_number,
        limitup_number, limitdown_number, gaining_more_5, losing_more_5, round(gaining_more_5_rate, 2),
        round(limitup_stable_rate, 2), round(limitup_nonstability, 2), round(limitup_timing, 2), round(limitup_capital, 2), round(limitup_com_strength, 2),
        round(one_to_two_rate, 2), round(two_to_three_rate, 2), round(three_to_four_rate, 2), round(total_successive_rate, 2), round(relay_sentiment_strength, 2),
        highest, highest_stock, round(com_short_index, 2)
    )
    
    try:
        cursor.execute(insert_query, values)
        conn.commit()
        print(f"已将短线数据插入 {table_name}。")
    except Exception as e:
        print(f"插入短线数据时出错: {e}")
        conn.rollback()
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    fetch_and_store_short_data()
