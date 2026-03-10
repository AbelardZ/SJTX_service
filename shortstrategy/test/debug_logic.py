import os
import sys
import json
import re
from datetime import datetime

# Mock configurations and paths
BASE_DIR = "/home/ubuntu/SJTX_service"
CLOUD_DATA_DIR = os.path.join(BASE_DIR, "shortstrategy/cloud_data")
DAILYCHART_STORAGE_DIR = os.path.join(BASE_DIR, "dailychart/storage")

def get_limitup_data(date_str):
    json_path = os.path.join(DAILYCHART_STORAGE_DIR, date_str, "limitup.json")
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            result = {}
            for row in data:
                code = row.get('code') or row.get('stock_code') or ''
                match = re.search(r'\d{6}', code)
                if match: result[match.group(0)] = row
            return result
    return {}

def get_theme_doc(date_str):
    json_path = os.path.join(CLOUD_DATA_DIR, f"{date_str}.json")
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            return {"date": date_str, "themes": json.load(f)}
    return None

def test_logic(date_str):
    print(f"Testing logic for {date_str}...")
    
    # Simulate trade_dates (just the last few including today)
    trade_dates = sorted([f.replace('.json', '') for f in os.listdir(CLOUD_DATA_DIR) if f.endswith('.json')])
    if date_str not in trade_dates:
        print(f"Error: {date_str} not in cloud_data files")
        return

    end_idx = trade_dates.index(date_str)
    lookback_days = 10
    start_idx = max(0, end_idx - lookback_days + 1)
    extended_dates = trade_dates[start_idx : end_idx + 1]
    
    print(f"Lookback dates: {extended_dates}")

    concept_presence = {}
    daily_data = {}

    for d in extended_dates:
        limit_up_cache = get_limitup_data(d)
        doc = get_theme_doc(d)
        counts = {}
        if doc and 'themes' in doc:
            for theme in doc['themes']:
                concept = theme.get('theme', 'Uncategorized')
                if not concept: continue
                if concept not in concept_presence: concept_presence[concept] = set()
                concept_presence[concept].add(d)
                
                lu_count = 0
                for s in theme.get('stocks', []):
                    code = s.get('code') or ''
                    match = re.search(r'\d{6}', code)
                    if match and match.group(0) in limit_up_cache:
                        lu_count += 1
                counts[concept] = lu_count
        daily_data[d] = counts

    current_day = date_str
    prev_1 = trade_dates[end_idx-1] if end_idx > 0 else None
    prev_2 = trade_dates[end_idx-2] if end_idx > 1 else None
    
    print(f"Current: {current_day}, Prev1: {prev_1}, Prev2: {prev_2}")

    qualified = set()
    for concept, presence in concept_presence.items():
        # Rule 1
        r1 = (current_day in presence and prev_1 in presence and prev_2 in presence)
        # Rule 2
        r2 = (daily_data.get(current_day, {}).get(concept, 0) >= 5)
        # Rule 3
        apps = sum(1 for d in extended_dates if d in presence)
        r3 = (apps >= 6)
        
        if r1 or r2 or r3:
            qualified.add(concept)
            print(f"MATCH: {concept} (R1:{r1}, R2:{r2}, R3:{r3}, LU_Count:{daily_data.get(current_day, {}).get(concept, 0)}, Apps:{apps})")

    print(f"Qualified concepts: {list(qualified)}")

if __name__ == '__main__':
    test_logic('2026-02-27')
