DATABASE_URL = "sqlite:///news_monitor.db"
CLASSIFICATION_CATEGORIES = [
    "公司新闻",
    "政策新闻",
    "产业新闻",
    "市场动态",
    "科技新闻",
    "国际新闻"
]
DEFAULT_CATEGORY = "未分类"
LOGGING_LEVEL = "INFO"
MODEL_PATH = "src/classifiers/ml/model.pkl"
TEXT_CLEANING_CONFIG = {
    "remove_stopwords": True,
    "lowercase": True,
    "remove_punctuation": True
}