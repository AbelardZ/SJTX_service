from typing import List, Dict
import requests

class CailiansheAdapter:
    def __init__(self, api_url: str):
        self.api_url = api_url

    def fetch_news(self) -> List[Dict]:
        response = requests.get(self.api_url)
        response.raise_for_status()
        return response.json()

    def classify_news(self, news_item: Dict) -> str:
        # Placeholder for classification logic
        if '政策' in news_item['title']:
            return '政策新闻'
        elif '公司' in news_item['title']:
            return '公司新闻'
        elif '产业' in news_item['title']:
            return '产业新闻'
        else:
            return '其他'

    def process_news(self) -> List[Dict]:
        news_items = self.fetch_news()
        classified_news = []

        for item in news_items:
            category = self.classify_news(item)
            item['category'] = category
            classified_news.append(item)

        return classified_news