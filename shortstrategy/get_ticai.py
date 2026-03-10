import os
import requests
import json
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pymongo
import akshare as ak

try:
    from db_config import MONGO_CONFIG
except ImportError:
    # Fallback if run from different dir
    from .db_config import MONGO_CONFIG

# --- Cloud & Local Storage Config ---
LOCAL_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloud_data")
if not os.path.exists(LOCAL_DATA_DIR):
    os.makedirs(LOCAL_DATA_DIR)

# --- Home PC IP for Cloud Sync ---
HOME_PC_IP = "100.75.180.70"

# --- Mongo Logic ---

def get_mongo_collection():
    # Try multiple hosts for robustness (Localhost and Tailscale Home PC)
    hosts = ["localhost", HOME_PC_IP]
    
    for host in hosts:
        try:
            print(f"Attempting to connect to MongoDB at {host}...")
            client = pymongo.MongoClient(
                host=host, 
                port=MONGO_CONFIG['port'],
                serverSelectionTimeoutMS=2000
            )
            client.admin.command('ping')
            db = client[MONGO_CONFIG['database']]
            collection = db[MONGO_CONFIG['collection']]
            print(f"Successfully connected to MongoDB at {host}")
            return collection
        except Exception as e:
            print(f"Failed to connect to MongoDB at {host}: {e}")
    
    return None

def get_last_updated_date(collection):
    if collection is None:
        return None
    # Find the latest date in the collection
    latest_doc = collection.find_one(sort=[("date", pymongo.DESCENDING)])
    if latest_doc:
        return latest_doc['date']
    return None

def save_local_data(date_str, data):
    """Save data to local JSON and keep only last 30 trading days"""
    file_path = os.path.join(LOCAL_DATA_DIR, f"{date_str}.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    # Prune to last 30 files
    files = sorted([f for f in os.listdir(LOCAL_DATA_DIR) if f.endswith(".json")])
    if len(files) > 30:
        for old_file in files[:-30]:
            os.remove(os.path.join(LOCAL_DATA_DIR, old_file))
            print(f"Pruned old local file: {old_file}")

def sync_local_to_mongo(collection):
    """Sync all files in LOCAL_DATA_DIR to MongoDB if not already present"""
    if collection is None:
        return
    
    files = sorted([f for f in os.listdir(LOCAL_DATA_DIR) if f.endswith(".json")])
    for filename in files:
        date_str = filename.replace(".json", "")
        # Check if already in Mongo
        if not collection.find_one({"date": date_str}):
            with open(os.path.join(LOCAL_DATA_DIR, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
                save_to_mongo(collection, date_str, data)
                print(f"Synced {date_str} from local to MongoDB.")

def save_to_mongo(collection, date_str, data):
    if collection is None:
        print(f"Skipping MongoDB save for {date_str} (No Connection).")
        return
    doc = {
        "date": date_str,
        "themes": data,
        "updated_at": datetime.now()
    }
    collection.replace_one({"date": date_str}, doc, upsert=True)
    print(f"Saved data for {date_str} to MongoDB.")

def get_trading_days(start_date, end_date):
    try:
        if start_date > end_date:
            return []
        df = ak.tool_trade_date_hist_sina()
        df['trade_date'] = df['trade_date'].astype(str)
        mask = (df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)
        days = df.loc[mask, 'trade_date'].tolist()
        return days
    except Exception as e:
        print(f"Error fetching trading days: {e}")
        return []

# --- Parsing Logic ---

def split_js_vals(s):
    vals = []
    current = []
    in_string = False
    quote_char = None
    escape = False
    depth = 0
    
    for char in s:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == '\\':
            current.append(char)
            escape = True
            continue
        if char in ("'", '"'):
            if not in_string:
                in_string = True
                quote_char = char
                current.append(char)
            elif char == quote_char:
                in_string = False
                quote_char = None
                current.append(char)
            else:
                current.append(char)
            continue
        if not in_string:
            if char == '[': depth += 1
            if char == ']': depth -= 1
            if char == '{': depth += 1
            if char == '}': depth -= 1
            if char == ',' and depth == 0:
                vals.append("".join(current).strip())
                current = []
                continue
        current.append(char)
    
    if current:
        vals.append("".join(current).strip())
    return vals

def decode_js_val(v):
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        val = v[1:-1]
        try:
            if '\\' in val:
                val = val.replace('\\"', '"').replace("\\'", "'").replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
                val = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), val)
            return val
        except:
            return val
    return v

def resolve_val(val, mapping):
    """Recursively resolve value from mapping if applicable"""
    val = val.strip()
    if val in mapping:
        return mapping[val]
    
    if val.startswith('{') and val.endswith('}'):
        return extract_obj_properties(val, mapping)
    
    if val.startswith('[') and val.endswith(']'):
        return parse_nuxt_list(val, mapping)
        
    return decode_js_val(val)

def extract_obj_properties(obj_str, mapping):
    """Parse a JS object string {key:val, ...} and return a dict"""
    obj_str = obj_str.strip()
    if obj_str.startswith('{') and obj_str.endswith('}'):
        obj_str = obj_str[1:-1]
    
    props = {}
    # Simple regex to find key:value pairs. 
    # Warning: nested objects are tricky with regex. 
    # We assume 'expound' and relevant fields don't have nested complex objects that break this simple scan often for the fields we need.
    # Actually, iterate split_js_vals logic but for key:value
    
    current = []
    in_string = False
    quote_char = None
    escape = False
    depth = 0
    parts = []
    
    for char in obj_str:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == '\\':
            current.append(char)
            escape = True
            continue
        if char in ("'", '"'):
            if not in_string:
                in_string = True
                quote_char = char
            elif char == quote_char:
                in_string = False
                quote_char = None
            current.append(char)
            continue
        if not in_string:
            if char == '[': depth += 1
            if char == ']': depth -= 1
            if char == '{': depth += 1
            if char == '}': depth -= 1
            if char == ',' and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
        
    for part in parts:
        if ':' in part:
            # unexpected key with colon? e.g. title:"foo:bar"
            # find first colon
            idx = part.find(':')
            key = part[:idx].strip()
            val = part[idx+1:].strip()
            props[key] = resolve_val(val, mapping)
            
    return props

def parse_nuxt_list(list_str, mapping):
    """Parse the list of objects from NUXT data string"""
    # Remove outer brackets
    list_str = list_str.strip()
    if list_str.startswith('[') and list_str.endswith(']'):
        list_str = list_str[1:-1]
        
    # Split items
    items = split_js_vals(list_str)
    parsed_items = []
    
    for item in items:
        # Each item is a JS object string {code:..., name:...}
        props = extract_obj_properties(item, mapping)
        parsed_items.append(props)
        
    return parsed_items

def parse_content(content):
    soup = BeautifulSoup(content, 'html.parser')
    themes = []
    
    # 1. Extract and Map NUXT data (GLOBAL + BODY)
    mapping = {}
    nuxt_body = ""
    interface_marker = 'window.__NUXT__=(function('
    
    nuxt_data_extracted = False
    
    if interface_marker in content:
        try:
            # Capture body as well
            match = re.search(r'window\.__NUXT__=\(function\((?P<args>.*?)\)\{(?P<body>.*)\}\((?P<vals>.*)\)\);', content, re.DOTALL)
            if match:
                args_str = match.group('args')
                vals_str = match.group('vals')
                nuxt_body = match.group('body')
                
                args = [a.strip() for a in args_str.split(',')]
                vals = split_js_vals(vals_str)
                if len(args) <= len(vals):
                    for a, v in zip(args, vals):
                        mapping[a] = decode_js_val(v)
                    nuxt_data_extracted = True
        except Exception as e:
            print(f"Error parsing NUXT: {e}")

    # 2. Extract Theme Metadata from HTML (The Source of Truth for ID -> Name/Reason)
    # Map: field_id (without 'f' prefix) -> { theme: "...", reason: "..." }
    field_map = {}
    
    modules = soup.select('li.module')
    if modules:
        for module in modules:
            # Structure: <div id="f..." class="...">
            inner_div = module.select_one('div[id^="f"]')
            if not inner_div:
                continue
            
            html_id = inner_div.get('id')
            if not html_id or not html_id.startswith('f'):
                continue
            
            # Raw ID is html_id[1:] (e.g., fc725... -> c725...)
            raw_id = html_id[1:]
            
            theme_name_el = module.select_one('.fs18-bold')
            theme_name = theme_name_el.text.strip() if theme_name_el else "Uncategorized"
            
            reason_el = module.select_one('.mtb8.fs16.text-justify')
            theme_reason = ""
            if reason_el:
                # Get text, strip "题材：" prefix
                full_text = reason_el.get_text(strip=True)
                if full_text.startswith("题材："):
                    theme_reason = full_text[3:].strip()
                else:
                    theme_reason = full_text
            
            field_map[raw_id] = {
                "theme": theme_name,
                "reason": theme_reason
            }
    
    print(f"Found {len(field_map)} themes in HTML.")
    
    # 3. Scan NUXT Body for Assignments (Link Variables to IDs and Lists)
    if nuxt_data_extracted and nuxt_body:
        print("Scanning NUXT body for assignments...")
        
        # Step 3.1: Find which variable corresponds to which action_field_id
        # Pattern: varName.action_field_id=val
        vars_with_id = {}
        
        assignments = re.finditer(r'(?P<var>\w+)\.action_field_id=(?P<val>\w+);', nuxt_body)
        for m in assignments:
            var_name = m.group('var')
            val_ref = m.group('val')
            
            # Resolve value reference (e.g. 'v') to actual ID string
            field_id = resolve_val(val_ref, mapping)
            # Clean up if it returned a quoted string (though resolve_val usually cleans it)
            if isinstance(field_id, str):
                field_id = field_id.strip('"\'')
            
            if field_id in field_map:
                vars_with_id[var_name] = field_id
            else:
                # Store unmapped ones too just in case? No, strict mapping is safer.
                pass
        
        print(f"Linked {len(vars_with_id)} NUXT variables to HTML themes.")
        
        # Step 3.2: Extract Lists for these variables
        for var_name, field_id in vars_with_id.items():
            # Pattern: varName.list=[...] or varName.recommendActionList=[...]
            pattern = re.escape(var_name) + r'\.(?:list|recommendActionList)=\[(?P<list>.*?)\];'
            match_list = re.search(pattern, nuxt_body, re.DOTALL)
            
            stocks = []
            if match_list:
                list_content = match_list.group('list')
                parsed_items = parse_nuxt_list(list_content, mapping)
                
                for item in parsed_items:
                    code = item.get('code', '')
                    name = item.get('name', '')
                    
                    # Extract interpretation (expound)
                    expound = ""
                    # Path: article -> action_info -> expound
                    # Items might be deep or flat depending on how extract_obj_properties parsed them
                    # parse_nuxt_list calls extract_obj_properties
                    
                    action_info = {}
                    if 'article' in item and isinstance(item['article'], dict):
                        action_info = item['article'].get('action_info', {})
                    elif 'action_info' in item and isinstance(item['action_info'], dict):
                        action_info = item['action_info']
                    
                    if action_info:
                        expound = action_info.get('expound', '')
                    else:
                        expound = item.get('expound', '')
                        
                    stocks.append({
                        "code": code,
                        "name": name,
                        "interpretation": expound
                    })
            
            # Add to result
            theme_data = field_map[field_id]
            themes.append({
                "theme": theme_data['theme'],
                "count": str(len(stocks)),
                "reason": theme_data['reason'],
                "stocks": stocks
            })
            
    # If no NUXT data or extraction failed, return just metadata (count 0)
    if not themes and field_map:
         print("Warning: NUXT stock extraction failed, returning metadata only.")
         for fid, v in field_map.items():
             themes.append({
                 "theme": v['theme'],
                 "count": "0",
                 "reason": v['reason'],
                 "stocks": []
             })
             
    return themes


# --- Downloading Logic ---

def download_and_parse(date_str):
    local_file = f"{date_str}_full.html"
    content = ""
    
    if os.path.exists(local_file):
        print(f"Using local file {local_file}")
        with open(local_file, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        url = f"https://www.jiuyangongshe.com/action/{date_str}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.jiuyangongshe.com/action'
        }
        print(f"\n--- Downloading {date_str} ---")
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                print(f"Failed to download {date_str}: Status {response.status_code}")
                return None
            content = response.text
            if "window.__NUXT__" not in content:
                print(f"Skipping {date_str}: Data not found (missing NUXT).")
                return None
                
            with open(local_file, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"Error downloading {date_str}: {e}")
            # If download fails, maybe delete the file?
            # But here we write only on success
            return None

    data = parse_content(content)
    
    # Clean up local file after parsing
    if os.path.exists(local_file):
        os.remove(local_file)
        
    return data

def main(manual=False):
    collection = get_mongo_collection()
    is_connected = collection is not None
    
    if is_connected:
        print("Connected to MongoDB. Syncing local data...")
        sync_local_to_mongo(collection)
    else:
        print("Running in cloud mode (Local MongoDB not connected).")

    # 1. Determine Date Range
    # Get last 30 trading days for local storage logic
    try:
        all_trading_days = ak.tool_trade_date_hist_sina()['trade_date'].astype(str).tolist()
    except Exception as e:
        print(f"Failed to fetch trading days list: {e}")
        return
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # If not connected, we only care about the last 30 trading days
    last_30_days = all_trading_days[-30:] if len(all_trading_days) >= 30 else all_trading_days
    
    # Decide where to start fetching from
    last_db_date = get_last_updated_date(collection) if is_connected else None
    
    # Files in local storage
    local_files = sorted([f.replace(".json", "") for f in os.listdir(LOCAL_DATA_DIR) if f.endswith(".json")])
    last_local_date = local_files[-1] if local_files else None
    
    start_date = "2026-01-01" # Default start
    if is_connected and last_db_date:
        last_dt = datetime.strptime(last_db_date, "%Y-%m-%d")
        start_date = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    elif last_local_date:
        last_dt = datetime.strptime(last_local_date, "%Y-%m-%d")
        start_date = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"Fetching data from {start_date} to {today_str}...")
    
    days_to_fetch = get_trading_days(start_date, today_str)
    
    if not days_to_fetch:
        print("No new trading days found to fetch.")
    else:
        print(f"Target days: {days_to_fetch}")
        for day in days_to_fetch:
            # Check if this day is outside last 30 days and DB is not connected
            if not is_connected and day not in last_30_days:
                print(f"Warning: {day} is outside the 30-day window and MongoDB is not connected. This data might be lost or skipped.")
                # We still try to fetch it if it's a target day, but Requirement 4 says "提示未连接"
                # Actually, if it's the cloud and it's catching up, it should still fetch if it can.
                # But Requirement 4 specifically says "对30个交易日以外的日期提示未连接"
                # Let's just print the message as requested.
                
            data = download_and_parse(day)
            if data:
                save_local_data(day, data)
                if is_connected:
                    save_to_mongo(collection, day, data)
            else:
                print(f"No data parsed for {day}")
            
            time.sleep(2)

    print(f"Task completion check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def run_scheduler():
    print("Scheduler started. Will check every hour for 16:00 (4 PM) on trading days.")
    last_run_date = None
    
    while True:
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        
        # Requirement: Each trading day at 4 PM
        # Check if it's a trading day
        is_trading_day = False
        try:
            # Use akshare or a simple check if today is in the trading days list
            # For efficiency we could cache this, but let's keep it simple
            df = ak.tool_trade_date_hist_sina()
            if current_date in df['trade_date'].astype(str).tolist():
                is_trading_day = True
        except:
            # Fallback to weekday check if akshare fails
            if now.weekday() < 5:
                is_trading_day = True
        
        if is_trading_day and now.hour >= 16 and last_run_date != current_date:
            print(f"It's after 16:00 on trading day {current_date}. Starting fetch...")
            main()
            last_run_date = current_date
            print(f"Run completed for {current_date}. Next check in 1 hour.")
        
        # Sleep for 30 minutes before next check
        time.sleep(1800)

if __name__ == "__main__":
    # If run with --now argument, run immediately, else start scheduler
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        main(manual=True)
    else:
        # For first run, try to catch up
        main()
        run_scheduler()
