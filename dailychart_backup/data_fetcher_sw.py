import akshare as ak
import pandas as pd
from datetime import datetime
import time
from db_config import get_db_connection
from proxy_config import enable_proxy, refresh_proxy

# 启用代理
enable_proxy()

def safe_float(val):
    try:
        if pd.isna(val) or val == "":
            return 0.0
        return float(val)
    except:
        return 0.0

def get_latest_and_previous_trading_dates():
    """
    获取最近一个交易日(T)和上一个交易日(T-1)
    """
    try:
        df = ak.tool_trade_date_hist_sina()
        trade_dates = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d').tolist()
        today_str = datetime.now().strftime('%Y%m%d')
        
        # 找到 T (<= Today 的最大交易日)
        valid_dates = [d for d in trade_dates if d <= today_str]
        if not valid_dates:
            return None, None
        
        T = valid_dates[-1]
        
        # 找到 T-1
        idx = trade_dates.index(T)
        if idx > 0:
            T_minus_1 = trade_dates[idx-1]
        else:
            T_minus_1 = None
            
        return T, T_minus_1
    except Exception as e:
        print(f"Error getting trade dates: {e}")
        return None, None

def fetch_and_process_sw_data(symbol, table_prefix):
    """
    symbol: "一级行业" 或 "二级行业"
    table_prefix: "SW1" 或 "SW2"
    """
    print(f"Processing {symbol} ({table_prefix})...")
    
    # 1. 获取日期 T 和 T-1
    T_str, prev_date_str = get_latest_and_previous_trading_dates()
    if not T_str or not prev_date_str:
        print("Could not determine trading dates.")
        return

    # 格式化 T 为数据库表名后缀 YYYY_MM_DD
    T_date = datetime.strptime(T_str, '%Y%m%d')
    table_date_suffix = T_date.strftime('%Y_%m_%d')
    table_name = f"{table_prefix}_{table_date_suffix}"

    print(f"Data Date (T): {T_str}, Previous Trading Day (T-1): {prev_date_str}")
    print(f"Target Table: {table_name}")

    # 2. 获取实时数据 (akshare1) - 假设对应 T
    try:
        print(f"Fetching realtime data for {symbol}...")
        df_realtime = ak.index_realtime_sw(symbol=symbol)
        if df_realtime.empty:
            print("Realtime data is empty.")
            return
    except Exception as e:
        print(f"Error fetching realtime data: {e}")
        return

    # 刷新代理以防超时
    refresh_proxy()

    # 3. 获取昨日数据 (akshare2) - 对应 T-1
    try:
        print(f"Fetching historical data for {symbol} on {prev_date_str}...")
        df_history = ak.index_analysis_daily_sw(symbol=symbol, start_date=prev_date_str, end_date=prev_date_str)
        if df_history.empty:
            print("Historical data is empty.")
        # else:
            # print(f"Historical data columns: {df_history.columns.tolist()}")
    except Exception as e:
        print(f"Error fetching historical data: {e}")
        df_history = pd.DataFrame()

    # 4. 数据处理与合并
    # 建立 index_code 到 history row 的映射
    history_map = {}
    if not df_history.empty:
        for _, row in df_history.iterrows():
            code = str(row['指数代码'])
            history_map[code] = row

    # 计算总流通市值 (用于 mc_pct)
    # 注意：这里使用的是昨日(T-1)的流通市值，根据README公式
    total_float_mv = 0.0
    if not df_history.empty:
        # 确保 '流通市值' 列存在且为数字
        if '流通市值' in df_history.columns:
            total_float_mv = df_history['流通市值'].apply(safe_float).sum()

    data_to_insert = []
    
    for _, row in df_realtime.iterrows():
        code = str(row['指数代码'])
        name = row['指数名称']
        
        # akshare1 数据 (单位转换: 百万 -> 亿, 除以 100)
        volume_raw = safe_float(row['成交量']) # 百万
        amount_raw = safe_float(row['成交额']) # 百万
        
        volume = volume_raw / 100.0 # 亿股
        amount = amount_raw / 100.0 # 亿元
        
        pre_close = safe_float(row['昨收盘'])
        open_price = safe_float(row['今开盘'])
        close = safe_float(row['最新价'])
        high = safe_float(row['最高价'])
        low = safe_float(row['最低价'])
        
        # 获取昨日数据
        hist_row = history_map.get(code, {})
        
        # 流通市值 (亿元) - 来自昨日数据
        float_mv = safe_float(hist_row.get('流通市值', 0))
        
        # 昨日换手率 (%)
        lst_turnover_rate = safe_float(hist_row.get('换手率', 0))
        
        # 计算字段
        
        # lst_amount: 昨日成交额 = 昨日换手率 * 昨日流通市值 * 0.01
        lst_amount = lst_turnover_rate * float_mv * 0.01
        
        # turnover_rate: 今日换手率 = 今日成交额 / 昨日流通市值 * 100
        turnover_rate = (amount / float_mv * 100) if float_mv > 0 else 0.0
        
        # mc_pct: 市值占比 = 流通市值 / 总流通市值 * 100
        mc_pct = (float_mv / total_float_mv * 100) if total_float_mv > 0 else 0.0
        
        # change_amount: 量能变化
        change_amount = amount - lst_amount
        
        # change_amount_pct: 量能变化率
        change_amount_pct = (change_amount / lst_amount * 100) if lst_amount > 0 else 0.0
        
        # change_pct: 涨跌幅
        change_pct = ((close - pre_close) / pre_close * 100) if pre_close > 0 else 0.0
        
        # change_contribution_pct: 涨跌贡献度
        change_contribution_pct = change_pct * mc_pct * 0.01
        
        # change_contribution_amount_pct: 量能变化贡献度
        change_contribution_amount_pct = change_amount_pct * mc_pct * 0.01
        
        data_to_insert.append({
            'index_code': code,
            'index_name': name,
            'pre_close': round(pre_close, 2),
            'open': round(open_price, 2),
            'close': round(close, 2),
            'high': round(high, 2),
            'low': round(low, 2),
            'volume': round(volume, 2),
            'amount': round(amount, 2),
            'float_market_capital': round(float_mv, 2),
            'lst_amount': round(lst_amount, 2),
            'turnover_rate': round(turnover_rate, 2),
            'mc_pct': round(mc_pct, 2),
            'change_amount': round(change_amount, 2),
            'change_amount_pct': round(change_amount_pct, 2),
            'change_pct': round(change_pct, 2),
            'change_contribution_pct': round(change_contribution_pct, 2),
            'change_contribution_amount_pct': round(change_contribution_amount_pct, 2),
            'timestamp': T_date # 使用数据日期 T
        })

    # 5. 存入数据库
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        create_sw_table(cursor, table_name)
        
        insert_sql = f"""
        REPLACE INTO `{table_name}` 
        (index_code, index_name, pre_close, open, close, high, low, volume, amount, 
        float_market_capital, lst_amount, turnover_rate, mc_pct, change_amount, 
        change_amount_pct, change_pct, change_contribution_pct, change_contribution_amount_pct, timestamp)
        VALUES 
        (%(index_code)s, %(index_name)s, %(pre_close)s, %(open)s, %(close)s, %(high)s, %(low)s, %(volume)s, %(amount)s, 
        %(float_market_capital)s, %(lst_amount)s, %(turnover_rate)s, %(mc_pct)s, %(change_amount)s, 
        %(change_amount_pct)s, %(change_pct)s, %(change_contribution_pct)s, %(change_contribution_amount_pct)s, %(timestamp)s)
        """
        
        if data_to_insert:
            print(f"Inserting {len(data_to_insert)} records into {table_name}...")
            cursor.executemany(insert_sql, data_to_insert)
            conn.commit()
            print("Insertion successful.")
        else:
            print("No data to insert.")
            
    except Exception as e:
        print(f"Error inserting data into {table_name}: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def create_sw_table(cursor, table_name):
    sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
        `index_code` VARCHAR(20) NOT NULL,
        `index_name` VARCHAR(50),
        `pre_close` FLOAT,
        `open` FLOAT,
        `close` FLOAT,
        `high` FLOAT,
        `low` FLOAT,
        `volume` FLOAT COMMENT '成交量(亿股)',
        `amount` FLOAT COMMENT '成交额(亿元)',
        `float_market_capital` FLOAT COMMENT '流通市值(亿元)',
        `lst_amount` FLOAT COMMENT '昨日成交额',
        `turnover_rate` FLOAT COMMENT '换手率(%)',
        `mc_pct` FLOAT COMMENT '市值占比(%)',
        `change_amount` FLOAT COMMENT '量能变化',
        `change_amount_pct` FLOAT COMMENT '量能变化率(%)',
        `change_pct` FLOAT COMMENT '涨跌幅(%)',
        `change_contribution_pct` FLOAT COMMENT '涨跌贡献度(%)',
        `change_contribution_amount_pct` FLOAT COMMENT '量能变化贡献度(%)',
        `timestamp` DATETIME,
        PRIMARY KEY (`index_code`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cursor.execute(sql)

def main():
    print("Starting Shenwan Industry Data Fetch...")
    
    # 处理一级行业
    fetch_and_process_sw_data("一级行业", "SW1")
    
    # 刷新代理
    refresh_proxy()
    
    # 处理二级行业
    fetch_and_process_sw_data("二级行业", "SW2")
    
    print("All done.")

if __name__ == "__main__":
    main()
