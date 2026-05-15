from src.ingestion.cailianshe_adapter import fetch_news
from src.preprocessing.text_cleaning import clean_text
from src.classifiers.taxonomy import classify_news
from src.storage.repositories.sqlite_repository import save_classified_news

def backfill_classify():
    # Fetch historical news data from Cailianshe
    news_data = fetch_news()

    for news_item in news_data:
        # Clean the news text
        cleaned_text = clean_text(news_item['content'])

        # Classify the cleaned news text
        category = classify_news(cleaned_text)

        # Save the classified news item to the database
        save_classified_news({
            'title': news_item['title'],
            'content': cleaned_text,
            'category': category,
            'timestamp': news_item['timestamp']
        })

if __name__ == "__main__":
    backfill_classify()