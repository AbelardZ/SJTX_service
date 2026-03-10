# Source Generated with Decompyle++
# File: extensions.cpython-310.pyc (Python 3.10)

from flask_login import LoginManager
from pymongo import MongoClient
login_manager = LoginManager()
mongo_client = MongoClient('mongodb://localhost:27017/')
db = mongo_client['A-share']
