from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class NewsItem(Base):
    __tablename__ = 'news_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    timestamp = Column(String, nullable=False)

class SQLiteRepository:
    def __init__(self, db_url):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def add_news_item(self, title, content, category, timestamp):
        session = self.Session()
        news_item = NewsItem(title=title, content=content, category=category, timestamp=timestamp)
        session.add(news_item)
        session.commit()
        session.close()

    def get_news_items(self, category=None):
        session = self.Session()
        if category:
            items = session.query(NewsItem).filter_by(category=category).all()
        else:
            items = session.query(NewsItem).all()
        session.close()
        return items

    def delete_news_item(self, news_id):
        session = self.Session()
        item = session.query(NewsItem).filter_by(id=news_id).first()
        if item:
            session.delete(item)
            session.commit()
        session.close()