import os
import json
import shutil
from datetime import datetime
import pymysql
from db_config import get_db_connection

STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'storage')
MAX_RETENTION_DAYS = 30

def ensure_storage_dir(date_str):
    path = os.path.join(STORAGE_DIR, date_str)
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def save_data(data_type, data, date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    date_path = ensure_storage_dir(date_str)
    file_path = os.path.join(date_path, f"{data_type}.json")
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[{datetime.now()}] Saved {len(data)} records for {data_type} to {file_path}")
    clean_old_data()

def load_data(data_type, date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    file_path = os.path.join(STORAGE_DIR, date_str, f"{data_type}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def clean_old_data():
    """Retain only the last MAX_RETENTION_DAYS folders"""
    if not os.path.exists(STORAGE_DIR):
        return
        
    dirs = sorted([d for d in os.listdir(STORAGE_DIR) if os.path.isdir(os.path.join(STORAGE_DIR, d))])
    
    if len(dirs) > MAX_RETENTION_DAYS:
        to_remove = dirs[:-MAX_RETENTION_DAYS]
        for d in to_remove:
            path = os.path.join(STORAGE_DIR, d)
            print(f"[{datetime.now()}] Removing old data: {path}")
            shutil.rmtree(path)

def sync_to_db():
    """Attempt to sync all local data to MySQL"""
    try:
        conn = get_db_connection()
        if not conn:
            print("DB Connection failed, skipping sync.")
            return False
            
        cursor = conn.cursor()
        print("Connected to DB. Starting sync...")
        
        # Iterate all dates in storage
        dates = sorted([d for d in os.listdir(STORAGE_DIR) if os.path.isdir(os.path.join(STORAGE_DIR, d))])
        
        for date_str in dates:
            date_path = os.path.join(STORAGE_DIR, date_str)
            for file_name in os.listdir(date_path):
                if not file_name.endswith('.json'):
                    continue
                    
                data_type = file_name.replace('.json', '')
                file_path = os.path.join(date_path, file_name)
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if not data:
                    continue
                    
                sync_file_data(cursor, data_type, data)
                
        conn.commit()
        print("Sync completed successfully.")
        conn.close()
        return True
        
    except Exception as e:
        print(f"Sync failed: {e}")
        return False

def sync_file_data(cursor, data_type, data):
    """Sync specific data type to DB tables"""
    print(f"Syncing {data_type} ({len(data)} records)...")
    
    if data_type == 'index':
        table_name = 'market_index'
        cols = ['index_code', 'index_name', 'pre_close', 'open', 'close', 'high', 'low', 'volume', 'amount', 'change_percent', 'timestamp']
        sql = f"REPLACE INTO `{table_name}` ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))})"
        values = [[d.get(c) for c in cols] for d in data]
        cursor.executemany(sql, values)
        
    elif data_type == 'limitup':
        table_name = 'limit_up_daily' 
        # Note: Need to match schema with data_fetcher_limitup.py
        # Assuming fetcher output matches DB schema keys.
        if data:
            keys = list(data[0].keys())
            cols = keys # Simple mapping, might need adjustment
            placeholders = ', '.join(['%s'] * len(cols))
            columns = ', '.join([f"`{k}`" for k in cols])
            sql = f"REPLACE INTO `{table_name}` ({columns}) VALUES ({placeholders})"
            values = [[d.get(k) for k in cols] for d in data]
            cursor.executemany(sql, values)

    elif data_type == 'sw_industry':
         table_name = 'sw_industry_daily'
         if data:
            keys = list(data[0].keys())
            cols = keys 
            placeholders = ', '.join(['%s'] * len(cols))
            columns = ', '.join([f"`{k}`" for k in cols])
            sql = f"REPLACE INTO `{table_name}` ({columns}) VALUES ({placeholders})"
            values = [[d.get(k) for k in cols] for d in data]
            cursor.executemany(sql, values)

    # Add other types as needed (short, all_data)
