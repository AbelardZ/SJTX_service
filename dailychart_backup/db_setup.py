import pymysql
from datetime import datetime
from db_config import get_root_connection, DB_USER, DB_PASSWORD

def create_databases_and_user():
    conn = get_root_connection()
    cursor = conn.cursor()

    # Create Databases
    cursor.execute("CREATE DATABASE IF NOT EXISTS DailyChartDB DEFAULT CHARACTER SET utf8mb4")
    # LimitUpDB is assumed to exist as per user instructions

    # Create User and Grant Privileges
    cursor.execute(f"CREATE USER IF NOT EXISTS '{DB_USER}'@'localhost' IDENTIFIED BY '{DB_PASSWORD}'")
    cursor.execute(f"GRANT ALL PRIVILEGES ON DailyChartDB.* TO '{DB_USER}'@'localhost'")
    # LimitUpDB privileges are assumed to exist for this user
    cursor.execute("FLUSH PRIVILEGES")

    conn.commit()
    cursor.close()
    conn.close()
    print("Databases and user setup completed.")

def create_tables_for_date(date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime('%Y_%m_%d')
    
    # Connect to DailyChartDB
    conn = pymysql.connect(
        host='localhost',
        user=DB_USER,
        password=DB_PASSWORD,
        database='DailyChartDB',
        charset='utf8mb4'
    )
    cursor = conn.cursor()

    # 1. Create Index Table
    index_table_name = f"Index_{date_str}"
    create_index_table_query = f"""
    CREATE TABLE IF NOT EXISTS `{index_table_name}` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `index_code` VARCHAR(20),
        `index_name` VARCHAR(50),
        `pre_close` FLOAT,
        `open` FLOAT,
        `close` FLOAT,
        `high` FLOAT,
        `low` FLOAT,
        `volume` DOUBLE,
        `amount` DOUBLE,
        `change_percent` FLOAT,
        `timestamp` DATETIME
    )
    """
    cursor.execute(create_index_table_query)
    print(f"Table {index_table_name} created in DailyChartDB.")

    # 2. Create Short-term Review Table
    # Table Name: DailyShort (Stores multiple days, one row per day)
    short_table_name = "DailyShort"
    create_short_table_query = f"""
    CREATE TABLE IF NOT EXISTS `{short_table_name}` (
        `date` DATE PRIMARY KEY,
        `advancing_number` INT,
        `declining_number` INT,
        `AD_ratio` FLOAT,
        `unchanged_number` INT,
        `total_number` INT,
        `limitup_number` INT,
        `limitdown_number` INT,
        `gaining_more_5_number` INT,
        `losing_more_5_number` INT,
        `gaining_more_5_rate` FLOAT,
        `limitup_stable_rate` FLOAT,
        `limitup_nonstability` FLOAT,
        `limitup_timing` FLOAT,
        `limitup_capital` FLOAT,
        `limitup_com_strength` FLOAT,
        `one_to_two_rate` FLOAT,
        `two_to_three_rate` FLOAT,
        `three_to_four_rate` FLOAT,
        `total_successive_rate` FLOAT,
        `relay_sentiment_strength` FLOAT,
        `Highest` INT,
        `Higheststock` VARCHAR(50),
        `com_short_index` FLOAT,
        `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(create_short_table_query)
    print(f"Table {short_table_name} created/checked in DailyChartDB.")
    
    # 3. Create SW Industry Tables (Placeholder based on README)
    sw1_table_name = f"SW1_{date_str}"
    sw2_table_name = f"SW2_{date_str}"
    # Assuming generic structure for now as details were empty in README snippet
    # But I should create them to avoid errors if referenced later.
    # Since README didn't specify columns for SW tables, I will skip or create a dummy one.
    # I'll skip SW tables for now as the user only asked for "Index" and "Short-term" parts.
    
    conn.commit()
    cursor.close()
    conn.close()

if __name__ == "__main__":
    create_databases_and_user()
    create_tables_for_date()

