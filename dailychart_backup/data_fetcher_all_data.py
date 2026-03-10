import akshare as ak
import pandas as pd
from datetime import datetime
from db_config import get_db_connection
from proxy_config import enable_proxy, refresh_proxy

# 启用代理（如果已配置）
enable_proxy()

def fetch_and_store_all_data():
    print("开始获取全市场数据...")

    # 检查是否为交易日
    target_date = datetime.now()

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

    today_underscore = target_date.strftime('%Y_%m_%d')

    # 获取全市场数据
    try:
        print("正在获取沪深京A股实时行情数据...")
        stock_spot_df = ak.stock_zh_a_spot()
        save_all_data_to_db(stock_spot_df, today_underscore)
    except Exception as e:
        print(f"获取全市场数据失败: {e}")
        return

# 存储全市场数据到数据库
def save_all_data_to_db(df, date_underscore):
    table_name = f"all_data_{date_underscore}"
    print(f"正在存储全市场数据到表: {table_name} ...")
    conn = get_db_connection()
    cursor = conn.cursor()

    # 映射中文列名到英文数据库列名
    column_mapping = {
        '代码': 'code', '名称': 'name', '最新价': 'price',
        '涨跌幅': 'change_pct', '涨跌额': 'change_amount',
        '买入': 'bid_price', '卖出': 'ask_price',
        '昨收': 'pre_close', '今开': 'open',
        '最高': 'high', '最低': 'low',
        '成交量': 'volume', '成交额': 'amount', '时间戳': 'timestamp'
    }

    # 仅保留存在的列
    rename_dict = {k: v for k, v in column_mapping.items() if k in df.columns}
    df_to_save = df.rename(columns=rename_dict)
    columns_to_save = list(rename_dict.values())
    df_to_save = df_to_save[columns_to_save]

    # 创建表
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_name}` (
        `code` VARCHAR(20) NOT NULL,
        `name` VARCHAR(50),
        `price` FLOAT,
        `change_pct` FLOAT,
        `change_amount` FLOAT,
        `bid_price` FLOAT,
        `ask_price` FLOAT,
        `pre_close` FLOAT,
        `open` FLOAT,
        `high` FLOAT,
        `low` FLOAT,
        `volume` DOUBLE,
        `amount` DOUBLE,
        `timestamp` DATETIME,
        PRIMARY KEY (`code`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    try:
        cursor.execute(create_table_sql)

        # 准备插入数据
        data_values = []
        for _, row in df_to_save.iterrows():
            row_data = []
            for col in columns_to_save:
                val = row[col]
                # 处理 timestamp 字段：如果是时间字符串，添加日期
                if col == 'timestamp' and isinstance(val, str) and len(val) == 8:  # HH:MM:SS 格式
                    date_str = date_underscore.replace('_', '-')
                    val = f"{date_str} {val}"
                # 处理 NaN
                if pd.isna(val):
                    val = None
                row_data.append(val)
            data_values.append(tuple(row_data))

        if data_values:
            placeholders = ', '.join(['%s'] * len(columns_to_save))
            columns_str = ', '.join([f"`{c}`" for c in columns_to_save])
            update_str = ', '.join([f"`{c}` = VALUES(`{c}`)" for c in columns_to_save])
            insert_sql = f"INSERT INTO `{table_name}` ({columns_str}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_str}"

            cursor.executemany(insert_sql, data_values)
            conn.commit()
            print(f"成功存储/更新 {len(data_values)} 条记录到 {table_name}")
        else:
            print("没有数据需要存储")

    except Exception as e:
        print(f"存储全市场数据失败: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    fetch_and_store_all_data()