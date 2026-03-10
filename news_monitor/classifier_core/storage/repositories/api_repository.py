from typing import List, Dict
import requests

class APIRepository:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def fetch_news(self) -> List[Dict]:
        response = requests.get(f"{self.base_url}/news")
        response.raise_for_status()
        return response.json()

    def categorize_news(self, news_items: List[Dict]) -> Dict[str, List[Dict]]:
        categorized_news = {
            "company_news": [],
            "policy_news": [],
            "industry_news": [],
            "other_news": []
        }

        for item in news_items:
            category = self.determine_category(item)
            categorized_news[category].append(item)

        return categorized_news

    def determine_category(self, news_item: Dict) -> str:
        # Placeholder for category determination logic
        if "公司" in news_item['title']:
            return "company_news"
        elif "政策" in news_item['title']:
            return "policy_news"
        elif "产业" in news_item['title']:
            return "industry_news"
        else:
            return "other_news"