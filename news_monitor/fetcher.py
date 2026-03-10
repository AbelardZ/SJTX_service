# fetcher.py
import requests

URL = "https://www.cls.cn/nodeapi/telegraphList?app=CailianpressWeb&last_time=0&os=web&sv=7.7.5"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.cls.cn/telegraph"
}

def fetch_latest_telegraphs():
    """抓取最新的电报信息"""
    res = requests.get(URL, headers=HEADERS, timeout=10)
    data = res.json()
    return data.get('data', {}).get('roll_data', [])
