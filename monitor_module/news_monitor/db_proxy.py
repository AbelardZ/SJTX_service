# -*- coding: utf-8 -*-
import pymysql
import sqlite3
import os
import re
import logging
from monitor_module.news_monitor.config import DB_CONFIG
from monitor_module.news_monitor.paths import DB_PATH

# --- 配置区 ---
# 请修改为你的 Tailscale IP
HOME_PC_IP = "100.75.180.70" 
LOCAL_DB_FILE = os.path.join("data", "news_buffer.db")

class SQLiteCursorWrapper:
    """让 SQLite 游标兼容 PyMySQL 的 %s 语法"""
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = -1
        self.lastrowid = None

    def execute(self, sql, args=None):
        # 1. 将 PyMySQL 的 %s 替换为 SQLite 的 ?
        sql = sql.replace('%s', '?')
        
        # 2. 处理 MySQL 的 CREATE TABLE 引擎和字符集 (SQLite 不支持)
        if "CREATE TABLE" in sql.upper():
            # 移除 ENGINE=InnoDB, DEFAULT CHARSET=utf8mb4 等
            sql = re.split(r'ENGINE\s*=', sql, flags=re.IGNORECASE)[0]
            # 移除结尾可能的分号重新处理 (split 已经去掉了部分内容)
            sql = sql.strip().rstrip(';')

        # 3. 处理 MySQL 的 ON DUPLICATE KEY UPDATE 语法
        # SQLite 不支持这个语法，改用 INSERT OR REPLACE INTO (因为数据通常包含全部列)
        if "ON DUPLICATE KEY UPDATE" in sql.upper():
            sql = re.split(r'ON\s+DUPLICATE', sql, flags=re.IGNORECASE)[0]
            # 将 INSERT INTO 替换为 INSERT OR REPLACE INTO
            sql = re.sub(r'INSERT\s+INTO', 'INSERT OR REPLACE INTO', sql, flags=re.IGNORECASE)

        if args is None:
            return self.cursor.execute(sql)
        else:
            return self.cursor.execute(sql, args)

    def executemany(self, sql, args):
        sql = sql.replace('%s', '?')
        if "CREATE TABLE" in sql.upper():
            sql = re.split(r'ENGINE\s*=', sql, flags=re.IGNORECASE)[0]
            sql = sql.strip().rstrip(';')

        if "ON DUPLICATE KEY UPDATE" in sql.upper():
            sql = re.split(r'ON\s+DUPLICATE', sql, flags=re.IGNORECASE)[0]
            sql = re.sub(r'INSERT\s+INTO', 'INSERT OR REPLACE INTO', sql, flags=re.IGNORECASE)
        return self.cursor.executemany(sql, args)

    def fetchall(self):
        return self.cursor.fetchall()

    def fetchone(self):
        return self.cursor.fetchone()

    def close(self):
        self.cursor.close()

    def __getattr__(self, name):
        return getattr(self.cursor, name)

class SQLiteConnectionWrapper:
    """让 SQLite 连接看起来像 PyMySQL 连接"""
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return SQLiteCursorWrapper(self.connection.cursor())

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()
    
    def rollback(self):
        self.connection.rollback()

def get_local_sqlite_conn():
    """获取本地 SQLite 连接 (云端 3 日缓存)"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    return SQLiteConnectionWrapper(conn)

def get_home_mysql_conn():
    """获取家里/本机的 MySQL 连接"""
    remote_config = DB_CONFIG.copy()
    remote_config['host'] = HOME_PC_IP
    remote_config['connect_timeout'] = 3
    # 这里不需要 try-except，让调用者处理异常显示“数据库未连接”
    return pymysql.connect(**remote_config)

def get_smart_connection():
    """
    智能获取数据库连接：
    云端优先使用 SQLite 记录 (3日缓存)。
    """
    try:
        return get_local_sqlite_conn(), "LOCAL"
    except Exception as e:
        print(f">>> [DB] Local SQLite Error: {e}")
        return None, "ERROR"
