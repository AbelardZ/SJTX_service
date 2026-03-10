from flask import Blueprint, request, jsonify, render_template
import datetime
import pymongo
# from .db_config import STOCK_DATA_DB_CONFIG, THEME_DB_CONFIG # Assuming these exist or handle error

short_strategy_bp = Blueprint('short_strategy', __name__)

# Placeholder config
THEME_DB_CONFIG = {
    'host': 'localhost',
    'port': 27017,
    'db_name': 'stock_themes',
    'collection_name': 'themes'
}

def get_mongo_collection():
    try:
        client = pymongo.MongoClient(THEME_DB_CONFIG['host'], THEME_DB_CONFIG['port'])
        db = client[THEME_DB_CONFIG['db_name']]
        collection = db[THEME_DB_CONFIG['collection_name']]
        return collection, client
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        return None, None

def get_theme_doc(date, collection):
    if collection is None:
        return None
    try:
        result = collection.find_one({'date': date})
        if result and '_id' in result:
             result['_id'] = str(result['_id'])
        return result
    except:
        return None

@short_strategy_bp.route('/')
def index():
    try:
        return render_template('short_strategy_index.html')
    except:
        return "Template not found", 404

@short_strategy_bp.route('/api/stocks/search')
def search_stocks():
    query = request.args.get('q', '').strip()
    # Stub implementation
    return jsonify([])

@short_strategy_bp.route('/api/data', methods=['GET'])
def get_data():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date is required'}), 400
    
    collection, client = get_mongo_collection()
    doc = get_theme_doc(date, collection)
    if client:
        client.close()
    
    if doc:
        return jsonify(doc)
    return jsonify({})

@short_strategy_bp.route('/api/theme_data')
def get_theme_data_api():
    # Reuse get_data logic or implement specific logic
    return get_data()

@short_strategy_bp.route('/api/save_data', methods=['POST'])
def save_data():
    data = request.json
    date = data.get('date')
    themes = data.get('themes')
    
    if not date or themes is None:
        return jsonify({'error': 'Invalid data'}), 400
        
    collection, client = get_mongo_collection()
    if not collection:
        return jsonify({'error': 'Database error'}), 500

    try:
        collection.update_one(
            {'date': date},
            {'$set': {'themes': themes}},
            upsert=True
        )
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if client:
            client.close()
