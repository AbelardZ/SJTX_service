# Source Generated with Decompyle++
# File: user.cpython-310.pyc (Python 3.10)

from flask_login import UserMixin
from extensions import db, login_manager
from datetime import datetime

class User(UserMixin):
    
    def __init__(self, user_data):
        self.id = str(user_data.get('_id'))
        self.username = user_data.get('username')
        self.email = user_data.get('email')
        self.role = user_data.get('role', 'normal')
        self.phone = user_data.get('phone')
        self.password = user_data.get('password')

    
    def create_user(username, password, email, role, phone = ('normal', None)):
        user_data = {
            'username': username,
            'password': password,
            'email': email,
            'role': role,
            'phone': phone,
            'created_at': datetime.now() }
        result = db.users.insert_one(user_data)
        user_data['_id'] = result.inserted_id
        return User(user_data)

    create_user = staticmethod(create_user)
    
    def get_by_username(username):
        user_data = db.users.find_one({
            'username': username })
        if user_data:
            return User(user_data)

    get_by_username = staticmethod(get_by_username)
    
    def get_by_id(user_id):
        ObjectId = ObjectId
        import bson.objectid
        
        try:
            user_data = db.users.find_one({
                '_id': ObjectId(user_id) })
            if user_data:
                pass
        finally:
            return None
            return None
            return None


    get_by_id = staticmethod(get_by_id)
    
    def check_password(self, password):
        return self.password == password

    
    def is_admin(self):
        return self.role == 'admin'

    is_admin = property(is_admin)
    
    def is_vip(self):
        return self.role in ('vip', 'admin')

    is_vip = property(is_vip)


def load_user(user_id):
    return User.get_by_id(user_id)

load_user = login_manager.user_loader(load_user)
