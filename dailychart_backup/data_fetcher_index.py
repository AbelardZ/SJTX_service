import akshare as ak
import pandas as pd
from datetime import datetime
from db_config import get_db_connection
from proxy_config import enable_proxy, refresh_proxy

# 启用代理（如果已配置）
enable_proxy()

# 目标指数配置
# 格式: { '代码': '名称' } 或者仅用于过滤的代码列表
TARGET_INDICES_AK1 = {
    '000985': '中证全指',
    '000300': '沪深300',
    '000905': '中证500',
    '000852': '中证1000',
    '932000': '中证2000', 
    '000001': '上证指数',
    '000016': '上证50',
    '399106': '深证综指',
    '000680': '科创综指',
    '000688': '科创50',
    '399006': '创业板指',
    '399673': '创业板50'
}

TARGET_INDICES_AK2 = {
    'HSI': '恒生指数',
    'NDX': '纳斯达克',
    'SPX': '标普500',
    'TWII': '台湾加权',
    'UDI': '美元指数',
    'N225': '日经225',
    'KS11': '韩国KOSPI',
    'GDAXI': '德国DAX30',
    'MCX': '英国富时250'   
}

def safe_float(value):
    try:
        if pd.isna(value) or value == "":
            return None
        return round(float(value), 2)
    except (ValueError, TypeError):
        return None

def fetch_and_store_index_data():
    print("Starting Index Data Fetch...")
    
    today_str = datetime.now().strftime('%Y_%m_%d')
    table_name = f"Index_{today_str}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 确保表存在
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        index_code VARCHAR(20),
        index_name VARCHAR(50),
        pre_close FLOAT,
        open FLOAT,
        close FLOAT,
        high FLOAT,
        low FLOAT,
        volume FLOAT,
        amount FLOAT,
        change_percent FLOAT,
        timestamp DATETIME,
        PRIMARY KEY (index_code)
    );
    """
    try:
        cursor.execute(create_table_sql)
        conn.commit()
        print(f"Table {table_name} checked/created.")
    except Exception as e:
        print(f"Error creating table: {e}")
    
    data_to_insert = []

    # 1. 获取 akshare1 数据 (全球指数)
    # 增加重试机制
    df1 = pd.DataFrame()
    for attempt in range(3):
        try:
            print(f"Fetching akshare1 data (Attempt {attempt+1})...")
            df1 = ak.index_global_spot_em()
            if not df1.empty:
                break
        except Exception as e:
            print(f"Error fetching akshare1: {e}")
            refresh_proxy()

    try:
        for _, row in df1.iterrows():
            code = str(row['代码'])
            # 修正：全球指数接口应该匹配全球指数列表 (AK2)
            if code in TARGET_INDICES_AK2: 
                # 映射字段
                record = {
                    'index_code': code,
                    'index_name': row['名称'],
                    'pre_close': safe_float(row.get('昨收价')),
                    'open': safe_float(row.get('开盘价')),
                    'close': safe_float(row.get('最新价')),
                    'high': safe_float(row.get('最高价')),
                    'low': safe_float(row.get('最低价')),
                    'volume': 0, # 全球指数接口似乎没有成交量
                    'amount': 0, # 全球指数接口似乎没有成交额
                    'change_percent': safe_float(row.get('涨跌幅')),
                    'timestamp': row.get('最新行情时间', datetime.now())
                }
                data_to_insert.append(record)
                
    except Exception as e:
        print(f"Error processing akshare1 data: {e}")

    # 刷新代理，确保 IP 存活
    refresh_proxy()

    # 2. 获取 akshare2 数据 (A股指数)
    # 增加重试机制
    df2 = pd.DataFrame()
    for attempt in range(3):
        try:
            print(f"Fetching akshare2 data (Attempt {attempt+1})...")
            df2 = ak.stock_zh_index_spot_em("沪深重要指数")
            if not df2.empty:
                break
        except Exception as e:
            print(f"Error fetching akshare2: {e}")
            refresh_proxy()

    try:
        current_time = datetime.now()

        for _, row in df2.iterrows():
            code = str(row['代码'])
            # 修正：A股指数接口应该匹配A股指数列表 (AK1)
            # 另外保留 932000 (中证2000) 的检查，假设它在 A 股接口中
            if code in TARGET_INDICES_AK1 or code in ['932000']:
                # 映射字段
                record = {
                    'index_code': code,
                    'index_name': row['名称'],
                    'pre_close': safe_float(row.get('昨收')),
                    'open': safe_float(row.get('今开')),
                    'close': safe_float(row.get('最新价')),
                    'high': safe_float(row.get('最高')),
                    'low': safe_float(row.get('最低')),
                    'volume': safe_float(row.get('成交量')),
                    'amount': safe_float(row.get('成交额')),
                    'change_percent': safe_float(row.get('涨跌幅')),
                    'timestamp': current_time # A股指数接口似乎没有时间戳，使用当前时间
                }
                data_to_insert.append(record)
                
    except Exception as e:
        print(f"Error processing akshare2 data: {e}")

    # 3. 插入数据库
    if data_to_insert:
        print(f"Inserting {len(data_to_insert)} records into {table_name}...")
        # 使用 REPLACE INTO 避免重复主键报错
        insert_query = f"""
        REPLACE INTO `{table_name}` 
        (index_code, index_name, pre_close, open, close, high, low, volume, amount, change_percent, timestamp)
        VALUES 
        (%(index_code)s, %(index_name)s, %(pre_close)s, %(open)s, %(close)s, %(high)s, %(low)s, %(volume)s, %(amount)s, %(change_percent)s, %(timestamp)s)
        """
        try:
            cursor.executemany(insert_query, data_to_insert)
            conn.commit()
            print("Insertion successful.")
        except Exception as e:
            print(f"Error inserting data: {e}")
            conn.rollback()
    else:
        print("No data to insert.")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    fetch_and_store_index_data()
