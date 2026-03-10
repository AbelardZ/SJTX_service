import akshare as ak
import pandas as pd
import pymysql
from datetime import datetime, time
import sys
import os
from db_config import get_db_connection

# Database Configuration
# Using db_config.py for connection details

# def get_db_connection():
#     return get_db_connection1()

def get_type1(row):
    """
    Calculate Type 1 based on last_limit_time and open_number
    """
    if row['炸板次数'] > 0:
        return None
    
    # Parse time string HHMMSS
    time_str = str(row['最后封板时间']).zfill(6)
    try:
        t = datetime.strptime(time_str, '%H%M%S').time()
    except ValueError:
        return None

    # Define time ranges
    t_930 = time(9, 30)
    t_933 = time(9, 33)
    t_1000 = time(10, 0)
    t_1030 = time(10, 30)
    t_1100 = time(11, 0)
    t_1130 = time(11, 30)
    t_1300 = time(13, 0)
    t_1330 = time(13, 30)
    t_1400 = time(14, 0)
    t_1430 = time(14, 30)
    t_1500 = time(15, 0)

    if t < t_930:
        return "一字板"
    elif t_930 <= t < t_933:
        return "秒板"
    elif t_933 <= t < t_1000:
        return "一等兵"
    elif t_1000 <= t < t_1030:
        return "二等兵"
    elif t_1030 <= t < t_1100:
        return "三等兵"
    elif t_1100 <= t < t_1130:
        return "四等兵"
    elif t_1300 <= t < t_1330:
        return "五等兵"
    elif t_1330 <= t < t_1400:
        return "六等兵"
    elif t_1400 <= t < t_1430:
        return "七等兵"
    elif t_1430 <= t <= t_1500:
        return "八等兵"
    
    return None

def get_type2(row):
    """
    Calculate Type 2 based on open_number
    """
    if row['炸板次数'] > 3:
        return "烂板"
    return None

def fetch_and_store_data(date_str=None):
    """
    Fetch data from akshare and store to MySQL
    date_str: 'YYYYMMDD'
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    
    print(f"Fetching data for {date_str}...")
    
    try:
        df = ak.stock_zt_pool_em(date=date_str)
        if df is None or df.empty:
            print("No data found for this date.")
            return
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    # Process Data
    # Rename columns to match DB fields roughly or just use index
    # Columns: 序号, 代码, 名称, 涨跌幅, 最新价, 成交额, 流通市值, 总市值, 换手率, 封板资金, 首次封板时间, 最后封板时间, 炸板次数, 涨停统计, 连板数, 所属行业
    
    # Calculate fields
    # SF: sealing_amount / float_market_capital * 100
    # SA: sealing_amount / amount * 100
    
    data_to_insert = []
    
    for _, row in df.iterrows():
        stock_code = row['代码']
        stock_name = row['名称']
        change_pct = row['涨跌幅']
        price = row['最新价']
        amount = row['成交额']
        float_cap = row['流通市值']
        total_cap = row['总市值']
        turnover = row['换手率']
        sealing_amount = row['封板资金']
        first_limit_time = str(row['首次封板时间']).zfill(6)
        last_limit_time = str(row['最后封板时间']).zfill(6)
        open_number = row['炸板次数']
        limit_stats = row['涨停统计']
        continuous_limit = row['连板数']
        industry = row['所属行业']
        
        # Calculations
        sf = round((sealing_amount / float_cap * 100), 2) if float_cap else 0
        sa = round((sealing_amount / amount * 100), 2) if amount else 0
        
        type1 = get_type1(row)
        type2 = get_type2(row)
        
        data_to_insert.append((
            stock_code, stock_name, round(change_pct, 2), round(price, 2), round(amount, 2), 
            round(float_cap, 2), round(total_cap, 2), round(turnover, 2), round(sealing_amount, 2),
            sf, sa, first_limit_time, last_limit_time, 
            open_number, limit_stats, continuous_limit, industry,
            type1, type2
        ))

    # Database Operations
    # init_db() - Database assumed to exist
    conn = get_db_connection()
    cursor = conn.cursor()
    
    table_name = f"`limitup_{date_str[:4]}_{date_str[4:6]}_{date_str[6:]}`"
    
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INT AUTO_INCREMENT PRIMARY KEY,
        stock_code VARCHAR(20),
        stock_name VARCHAR(50),
        change_pct FLOAT,
        price FLOAT,
        amount DOUBLE,
        float_market_capital DOUBLE,
        market_capital DOUBLE,
        turnover_rate FLOAT,
        sealing_amount DOUBLE,
        SF FLOAT,
        SA FLOAT,
        first_limit_time VARCHAR(20),
        last_limit_time VARCHAR(20),
        open_number INT,
        limit_number_statistics VARCHAR(50),
        continuous_limit_number INT,
        industry VARCHAR(50),
        type1 VARCHAR(20),
        type2 VARCHAR(20),
        main_concept VARCHAR(100),
        illustration TEXT
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """
    
    cursor.execute(create_table_sql)
    
    # Ensure table is utf8mb4 (in case it existed with different charset)
    try:
        cursor.execute(f"ALTER TABLE {table_name} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    except Exception as e:
        print(f"Warning: Could not alter table charset: {e}")

    # Clear existing data for this date to avoid duplicates if re-running
    cursor.execute(f"TRUNCATE TABLE {table_name}")
    
    insert_sql = f"""
    INSERT INTO {table_name} (
        stock_code, stock_name, change_pct, price, amount, 
        float_market_capital, market_capital, turnover_rate, sealing_amount,
        SF, SA, first_limit_time, last_limit_time, 
        open_number, limit_number_statistics, continuous_limit_number, industry,
        type1, type2
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    cursor.executemany(insert_sql, data_to_insert)
    conn.commit()
    print(f"Successfully stored {len(data_to_insert)} records into {table_name}")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    # Check if date argument is provided
    if len(sys.argv) > 1:
        fetch_and_store_data(sys.argv[1])
    else:
        fetch_and_store_data()
