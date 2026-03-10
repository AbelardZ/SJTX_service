import mysql.connector
from mysql.connector import errorcode
import sys
from config import ADMIN_DB_CONFIG, DB_CONFIG

def create_database():
    print("正在尝试连接 MySQL (root)...")
    
    try:
        cnx = mysql.connector.connect(**ADMIN_DB_CONFIG)
    except mysql.connector.Error as err:
        print(f"无法连接到MySQL root用户: {err}")
        print("请确保MySQL正在运行且密码正确。")
        return

    cursor = cnx.cursor()
    
    # Create Database
    db_name = DB_CONFIG['database']
    try:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} DEFAULT CHARACTER SET 'utf8mb4'")
        print(f"数据库 {db_name} 创建成功 (或已存在)")
    except mysql.connector.Error as err:
        print(f"创建数据库失败: {err}")
        return

    # Create User and Grant Privileges
    user = DB_CONFIG['user']
    password = DB_CONFIG['password']
    # Assuming the user is connecting from the same host defined in config, usually localhost
    # But for user creation, we often specify 'localhost' or '%'
    # Let's use 'localhost' as hardcoded before, or extract from config if it's there.
    # DB_CONFIG has 'host': 'localhost'
    host = DB_CONFIG.get('host', 'localhost')

    try:
        # Check if user exists
        cursor.execute(f"SELECT User FROM mysql.user WHERE User='{user}'")
        result = cursor.fetchone()
        if not result:
            # Create user if not exists
            cursor.execute(f"CREATE USER '{user}'@'{host}' IDENTIFIED BY '{password}'")
            print(f"用户 {user} 创建成功")
        else:
            print(f"用户 {user} 已存在")
        
        cursor.execute(f"GRANT ALL PRIVILEGES ON {db_name}.* TO '{user}'@'{host}'")
        cursor.execute("FLUSH PRIVILEGES")
        print("权限授予成功")
        
    except mysql.connector.Error as err:
        print(f"创建用户或授权失败: {err}")
        
    cursor.close()
    cnx.close()

if __name__ == "__main__":
    create_database()
