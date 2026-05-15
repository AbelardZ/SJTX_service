from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class NewsItem(Base):
    __tablename__ = 'news_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)
    source = Column(String(100), nullable=False)
    published_at = Column(DateTime, nullable=False)

    def __repr__(self):
        return f"<NewsItem(id={self.id}, title={self.title}, category={self.category}, published_at={self.published_at})>"