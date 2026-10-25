#Stand in for now

from __future__ import annotations
import product_id.product_database
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from Input_Validation import FIELDS, INVENTORY_FIELDS, DATE_FIELDS, normalize, utc_now, entry_values, iso_date, expiry_state

def open_db(path, mode='ro'):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f'Database not found: {p}. Nothing created.')
    c = sqlite3.connect(p.as_uri() + '?mode=' + mode, uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c

def columns(c, table):
    return {r['name'] for r in c.execute('PRAGMA table_info("' + table.replace('"', '""') + '")')}

def validate_inventory(c, dates=True):
    expected = INVENTORY_FIELDS | (DATE_FIELDS if dates else set())
    if not expected.issubset(columns(c, 'inventory_items')):
        raise ValueError('Inventory schema mismatch or date columns are missing.')
    unique = False
    for r in c.execute('PRAGMA index_list(inventory_items)'):
        if r['unique']:
            idx = r['name'].replace('"', '""')
            unique |= [x['name'] for x in c.execute(f'PRAGMA index_info("{idx}")')] == ['operation_id']
    if not unique:
        raise ValueError('Inventory needs a unique id index.')
MANUAL_SCHEMA = 'CREATE TABLE manual_items (\n  inventory_id INTEGER PRIMARY KEY, item_name TEXT NOT NULL, brand_name TEXT NOT NULL,\n  item_category TEXT NOT NULL, item_weight REAL, purchased_on TEXT, expires_on TEXT,\n  added_at TEXT NOT NULL, removed_at TEXT, operation_id TEXT NOT NULL UNIQUE)'

def prepare(settings):
    for key in ('catalog', 'products', 'inventory'):
        if not settings[key].is_file():
            raise FileNotFoundError(str(settings[key]))
    with closing(open_db(settings['inventory'])) as check:
        validate_inventory(check, dates=False)
    manual_path = settings['manual']
    if manual_path.exists():
        with closing(open_db(manual_path)) as c:
            if not (INVENTORY_FIELDS - {'item_upc'} | DATE_FIELDS).issubset(columns(c, 'manual_items')):
                raise ValueError(f'Keep the existing file: {manual_path}')
    with closing(open_db(settings['inventory'], 'rw')) as c:
        missing = DATE_FIELDS - columns(c, 'inventory_items')
        backup = None
        if missing:
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            backup = settings['inventory'].with_name(settings['inventory'].name + '.before-touch-' + stamp)
            with closing(sqlite3.connect(backup)) as target:
                c.backup(target)
            with c:
                for name in sorted(missing):
                    c.execute(f'ALTER TABLE inventory_items ADD COLUMN {name} TEXT')
    if not manual_path.exists():
        with closing(sqlite3.connect(manual_path)) as c:
            with c:
                c.execute(MANUAL_SCHEMA)
    return backup

from Inventory_Query import InventoryQueries

class Store(InventoryQueries):

    def __init__(self, settings):
        self.settings = settings
        self.products = None
        self.inventory = None
        self.manual = None

    def __enter__(self):
        try:
            self.inventory = open_db(self.settings['inventory'], 'rw')
            validate_inventory(self.inventory)
            self.manual = open_db(self.settings['manual'], 'rw')
            if not (INVENTORY_FIELDS - {'item_upc'} | DATE_FIELDS).issubset(columns(self.manual, 'manual_items')):
                raise ValueError('Manual inventory type differs')
            self.products = product_id.product_database.ProductDatabase(self.settings['catalog'], self.settings['products'])
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args):
        for obj in (self.products, self.inventory, self.manual):
            if obj is not None:
                obj.close()




    def add(self, pending, data):
        values = entry_values(data)
        code = pending.get('code')
        token = pending['token']
        if not isinstance(token, str) or not token:
            raise ValueError('Missing identifier.')
        code = normalize(code) if code else None
        learned = False
        if code and pending.get('product') is None:
            cls = product_id.product_database.Product
            self.products.save_product(cls(code, values['brand_name'], values['item_name'], values['item_weight'], values['item_category']))
            learned = True
        connection = self.inventory if code else self.manual
        table = 'inventory_items' if code else 'manual_items'
        names = [
            'brand_name',
            'item_name',
            'item_weight',
            'item_category',
            'added_at',
            'purchased_on',
            'expires_on',
            'operation_id'
        ]
        now = utc_now()
        ids = []
        try:
            with connection:
                for i in range(values['quantity']):
                    op = f'{token}:{i}'
                    record = [
                        values['brand_name'],
                        values['item_name'],
                        values['item_weight'],
                        values['item_category'],
                        now,
                        values['purchased_on'],
                        values['expires_on'],
                        op
                    ]
                    ns = names
                    if code:
                        ns = ['item_upc'] + names
                        record = [code] + record
                    marks = ','.join(('?' for _ in record))
                    connection.execute(f"INSERT INTO {table} ({','.join(ns)}) VALUES ({marks}) ON CONFLICT(operation_id) DO NOTHING", record)
                    row = connection.execute(f'SELECT * FROM {table} WHERE operation_id=?', (op,)).fetchone()
                    if any((row[key] != values[key] for key in ('item_name', 'brand_name', 'item_category', 'item_weight', 'purchased_on', 'expires_on'))) or (code and row['item_upc'] != code):
                        raise ValueError('Transaction ID already belongs to a different item.')
                    ids.append(row['inventory_id'])
        except Exception as exc:
            if learned:
                raise RuntimeError(f'Product was saved, but inventory was NOT saved/updated: {exc}. Retry or cancel') from exc
            raise
        return {'ids': ids, 'values': values, 'code': code, 'learned': learned}

    #Updates one package
    def update_item(self, kind, record_id, data):
        self.get_item(kind, record_id)
        values = entry_values(data)
        if values['quantity'] != 1:
            raise ValueError('update changes existing item')
        names = ('item_name', 'brand_name', 'item_category', 'item_weight', 'purchased_on', 'expires_on')
        connection, table = self._target(kind)
        with connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {', '.join(name + '=?' for name in names)} "
                'WHERE inventory_id=? AND removed_at IS NULL',
                tuple(values[name] for name in names) + (record_id,)
            )
            if cursor.rowcount != 1:
                raise ValueError('This inventory item is no longer active.')
        return self.get_item(kind, record_id)

    def dates(self, kind, record_id, purchased_on, expires_on):
        connection, table = self._target(kind)
        purchased = iso_date(purchased_on, 'Purchase date')
        expires = iso_date(expires_on, 'Expiration date')
        if purchased and expires and (expires < purchased):
            raise ValueError('Expiration is before purchase date. Check the dates.')
        with connection:
            cursor = connection.execute(f'UPDATE {table} SET purchased_on=?, expires_on=? WHERE inventory_id=? AND removed_at IS NULL', (purchased, expires, record_id))
            if cursor.rowcount != 1:
                raise ValueError('This inventory item is no longer active.')

    def remove(self, kind, record_id):
        connection, table = self._target(kind)
        with connection:
            cursor = connection.execute(f'UPDATE {table} SET removed_at=? WHERE inventory_id=? AND removed_at IS NULL', (utc_now(), record_id))
            if cursor.rowcount != 1:
                raise ValueError('This inventory item is no longer active.')

    def _target(self, kind):
        if kind == 'barcode':
            return (self.inventory, 'inventory_items')
        if kind == 'manual':
            return (self.manual, 'manual_items')
        raise ValueError('Unknown inventory source.')

