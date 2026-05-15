from typing import List, Dict, Tuple


# 轻量级关键词规则，可逐步扩展
RULES: Dict[str, List[str]] = {
    "company_news": ["公司", "财报", "回购", "中标", "订单", "投产", "扩产", "股权", "增持", "减持"],
    "policy_news": ["政策", "法规", "意见稿", "通知", "国务院", "发改委", "工信部", "补贴", "税收", "监管"],
    "industry_news": ["行业", "供需", "产业链", "价格", "库存", "产能", "景气", "招标"],
    "market_news": ["股市", "盘面", "资金", "北向资金", "龙虎榜", "大宗交易", "指数"],
    "technology_news": ["科技", "技术", "新品", "专利", "研发", "创新", "量产"],
}

class Taxonomy:
    def __init__(self):
        self.categories = {
            "company_news": [],
            "policy_news": [],
            "industry_news": [],
            "market_news": [],
            "technology_news": [],
            "other": []
        }

    def classify(self, news_item: str) -> str:
        """
        Classify the news item based on its content.
        This is a simple heuristic-based classification.
        """
        # 先按关键词计分
        scores: Dict[str, int] = {k: 0 for k in self.categories.keys()}
        text = news_item or ""
        for label, kws in RULES.items():
            scores[label] = sum(1 for kw in kws if kw in text)

        # 选最高分标签，若全为0则归 other
        if any(scores.values()):
            return max(scores, key=lambda k: scores[k])
        return "other"

    def classify_multi(self, title: str, content: str) -> Tuple[List[str], Dict[str, int]]:
        """多标签简单分类：返回命中标签列表与原始分数。"""
        full = f"{title or ''} {content or ''}"
        scores: Dict[str, int] = {k: 0 for k in self.categories.keys()}
        for label, kws in RULES.items():
            scores[label] = sum(1 for kw in kws if kw in full)
        labels = [k for k, v in scores.items() if v > 0]
        if not labels:
            labels = ["other"]
        return labels, scores

    def add_news_item(self, news_item: str):
        """
        Add a news item to the appropriate category.
        """
        category = self.classify(news_item)
        self.categories[category].append(news_item)

    def get_categories(self) -> Dict[str, List[str]]:
        """
        Get the categorized news items.
        """
        return self.categories

    def clear_categories(self):
        """
        Clear all categorized news items.
        """
        for category in self.categories:
            self.categories[category] = []


# 兼容性方法：提供一个简易函数接口给调用方
def classify_news(text: str) -> str:
    """对单段文本进行主标签分类（兼容 app.py 现有调用）。"""
    tx = Taxonomy()
    return tx.classify(text)