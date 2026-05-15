# -*- coding: utf-8 -*-
import logging
import datetime
from typing import List, Dict, Union

from src.classifier import classify_single
from src.storage.repositories.sqlite_repository import SQLiteRepository
from src.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def classify_stream(news_items: List[Union[str, Dict]], db_url: str = None) -> List[Dict[str, str]]:
    """
    流式处理新闻分类并入库
    
    参数:
        news_items: 新闻列表，可以是字符串列表(仅内容)或字典列表({'title':..., 'content':...})
        db_url: 数据库链接，默认为 settings.DATABASE_URL
    """
    if db_url is None:
        db_url = settings.DATABASE_URL
        
    # 初始化存储库
    try:
        repo = SQLiteRepository(db_url)
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        repo = None

    classified_results = []
    
    for item in news_items:
        # 解析输入
        if isinstance(item, str):
            title = item[:20] + "..." if len(item) > 20 else item
            content = item
            timestamp = datetime.datetime.now().isoformat()
        else:
            title = item.get("title", "")
            content = item.get("content", "")
            timestamp = item.get("timestamp", datetime.datetime.now().isoformat())
            
        # 调用 BERT 模型分类
        # classify_single 内部调用 BERT
        category = classify_single(title, content)
        
        # 记录结果
        result_entry = {
            "title": title,
            "content": content, 
            "category": category,
            "timestamp": timestamp
        }
        classified_results.append(result_entry)
        
        logger.info(f"Classified: [{category}] {title}")
        
        # 入库
        if repo:
            try:
                repo.add_news_item(
                    title=title,
                    content=content,
                    category=category,
                    timestamp=timestamp
                )
            except Exception as e:
                logger.error(f"Failed to save to DB: {e}")

    return classified_results

if __name__ == "__main__":
    # 测试代码
    example_news_items = [
        "贵州茅台发布2025年财报，净利润同比增长15%",
        "央行宣布降准0.5个百分点，释放长期资金约1万亿元",
        "宁德时代发布麒麟电池，续航里程突破1000公里"
    ]
    
    print("Starting stream classification...")
    results = classify_stream(example_news_items)
    print("Results:", results)
