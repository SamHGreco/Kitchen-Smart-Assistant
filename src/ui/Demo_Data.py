#To complete testing. Just dummy data for now

import sqlite3
import tempfile
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from product_id.product_database import ProductDatabase
from Input_Validation import utc_now
from Inventory_Database import MANUAL_SCHEMA
DEMO_PRODUCTS = (
    ('00123456789012', 'Example Pantry', 'Example Spaghetti', '500', 'Pasta - Spaghetti'),
    ('00123456789029', 'Example Kitchen', 'Example Tomato sauce', '400', 'Tomato sauce'),
    ('00123456789036', 'Example Farm', 'Example Strawberries', '454', 'Fruit')
)

def create_demo():
    temporary = tempfile.TemporaryDirectory(prefix='grocery-demo-')
    folder = Path(temporary.name)
    settings = {key: folder / (key + '.sqlite') for key in ('catalog', 'products', 'inventory', 'manual')}
    with closing(sqlite3.connect(settings['catalog'])) as connection:
        connection.execute('CREATE TABLE items (item_upc TEXT, brand_name TEXT, item_name TEXT, item_weight TEXT, item_category TEXT)')
        connection.executemany('INSERT INTO items VALUES (?,?,?,?,?)', DEMO_PRODUCTS)
        connection.commit()
    with ProductDatabase(settings['catalog'], settings['products']):
        pass
    with closing(sqlite3.connect(settings['inventory'])) as connection:
        connection.execute('CREATE TABLE inventory_items(\n            inventory_id INTEGER PRIMARY KEY, item_upc TEXT NOT NULL CHECK(length(item_upc)=14),\n            brand_name TEXT NOT NULL, item_name TEXT NOT NULL, item_weight REAL,\n            item_category TEXT NOT NULL, added_at TEXT NOT NULL, removed_at TEXT,\n            operation_id TEXT NOT NULL UNIQUE, purchased_on TEXT, expires_on TEXT)')
        for index, product in enumerate(DEMO_PRODUCTS):
            due = (date.today() + timedelta(days=(2, 0, -1)[index])).isoformat()
            connection.execute('INSERT INTO inventory_items(item_upc,brand_name,item_name,item_weight,item_category,added_at,operation_id,expires_on) VALUES(?,?,?,?,?,?,?,?)', (*product, utc_now(), f'seed:{index}', due))
        connection.commit()
    with closing(sqlite3.connect(settings['manual'])) as connection:
        connection.execute(MANUAL_SCHEMA)
        connection.commit()
    return (temporary, settings)
