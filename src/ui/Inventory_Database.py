"""
Real inventory backing for Store; replacement of stand-in.
"""

from __future__ import annotations
from datetime import datetime

import product_id.product_database
from Input_Validation import normalize, entry_values, iso_date, expiry_state
from dataclasses import asdict

from inventory.inventory_db import (
    get_connection, init_db, create_item, get_item as _get_item,
    get_all_items, update_quantity, delete_item as _delete_item,
    update_expiration_date,
)
from app.shared.models import QuantityType

MANUAL_SCHEMA = """
    CREATE TABLE manual_items (
        inventory_id INTEGER PRIMARY KEY,
        item_name TEXT NOT NULL,
        brand_name TEXT NOT NULL,
        item_category TEXT NOT NULL,
        item_weight REAL,
        purchased_on TEXT,
        expires_on TEXT,
        added_at TEXT NOT NULL,
        removed_at TEXT,
        operation_id TEXT NOT NULL UNIQUE
    )
"""


def _row_kind(item):
    return 'barcode' if item.barcode else 'manual'


def _to_ui_row(item):
    """Translate a real InventoryItem into the dict shape the UI expects."""
    return {
        'inventory_id': item.item_id,
        'item_upc': item.barcode,
        'item_name': item.name,
        'brand_name': item.brand_name or '',
        'item_category': item.category,
        'item_weight': item.current_quantity,
        'purchased_on': item.date_added.date().isoformat(),
        'expires_on': item.expiration_date.date().isoformat() if item.expiration_date else None,
        'added_at': item.date_added.isoformat(),
        'kind': _row_kind(item),
    }


def prepare(settings):
    """No separate inventory/manual file setup needed anymore, inventory_db.py
    creates its own schema on first connection. Kept as a no-op so nothing
    that still imports this name breaks."""
    return None


class Store:

    def __init__(self, settings):
        self.settings = settings
        self.products = None
        self.conn = None

    def __enter__(self):
        try:
            self.conn = get_connection()
            init_db(self.conn)
            self.products = product_id.product_database.ProductDatabase(
                self.settings['catalog'], self.settings['products']
            )
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args):
        if self.products is not None:
            self.products.close()
        if self.conn is not None:
            self.conn.close()

    def lookup(self, raw):
        code = normalize(raw)
        matches = [item for item in get_all_items(self.conn) if item.barcode == code]
        if matches:
            latest = matches[0]
            product = {
                'item_upc': latest.barcode, 'brand_name': latest.brand_name,
                'item_name': latest.name, 'item_weight': latest.current_quantity,
                'item_category': latest.category, 'source': 'inventory',
            }
        else:
            found = self.products.find_product(code)
            product = asdict(found) if found else None
        return {'raw': raw.strip(), 'code': code, 'product': product, 'count': len(matches)}

    def count(self):
        return len(get_all_items(self.conn))

    def list_items(self):
        items = get_all_items(self.conn)
        rows = [_to_ui_row(item) for item in items]
        rows.sort(key=lambda row: row['added_at'], reverse=True)
        return rows

    def matching_items(self, barcode=None):
        rows = self.list_items()
        if barcode is None:
            return rows
        code = normalize(barcode)
        return [row for row in rows if row['item_upc'] == code]

    def get_item(self, kind, record_id):
        if type(record_id) is not int or record_id < 1:
            raise ValueError('Choose a valid inventory item.')
        item = _get_item(self.conn, record_id)
        if item is None:
            raise ValueError('This inventory item is no longer active.')
        return _to_ui_row(item)

    def add(self, pending, data):
        values = entry_values(data)
        code = pending.get('code')
        code = normalize(code) if code else None
        learned = False
        if code and pending.get('product') is None:
            cls = product_id.product_database.Product
            self.products.save_product(cls(code, values['brand_name'], values['item_name'], values['item_weight'], values['item_category']))
            learned = True
        ids = []
        try:
            for _ in range(values['quantity']):
                expiration = datetime.fromisoformat(values['expires_on']) if values['expires_on'] else None
                item = create_item(
                    self.conn,
                    name=values['item_name'],
                    quantity_type=QuantityType.WEIGHT,
                    initial_quantity=values['item_weight'] or 0,
                    unit='g',
                    barcode=code,
                    brand_name=values['brand_name'],
                    category=values['item_category'],
                    expiration_date=expiration,
                )
                ids.append(item.item_id)
        except Exception as exc:
            if learned:
                raise RuntimeError(f'Product was saved, but inventory was NOT saved/updated: {exc}. Retry or cancel') from exc
            raise
        return {'ids': ids, 'values': values, 'code': code, 'learned': learned}

    def update_item(self, kind, record_id, data):
        self.get_item(kind, record_id)
        values = entry_values(data)
        if values['quantity'] != 1:
            raise ValueError('update changes existing item')
        update_quantity(self.conn, record_id, values['item_weight'] or 0)
        expiration = datetime.fromisoformat(values['expires_on']) if values['expires_on'] else None
        update_expiration_date(self.conn, record_id, expiration)
        return self.get_item(kind, record_id)

    def dates(self, kind, record_id, purchased_on, expires_on):
        purchased = iso_date(purchased_on, 'Purchase date')
        expires = iso_date(expires_on, 'Expiration date')
        if purchased and expires and expires < purchased:
            raise ValueError('Expiration is before purchase date. Check the dates.')
        expiration = datetime.fromisoformat(expires) if expires else None
        update_expiration_date(self.conn, record_id, expiration)

    def remove(self, kind, record_id):
        self.get_item(kind, record_id)
        _delete_item(self.conn, record_id)

    def report(self, today, warning_days):
        rows = self.list_items()
        alerts = []
        undated = 0
        counts = {}
        for row in rows:
            if row['item_upc']:
                counts[row['item_upc']] = counts.get(row['item_upc'], 0) + 1
            row.update(expiry_state(row['expires_on'], today, warning_days))
            if row['state'] in ('past', 'today', 'soon', 'invalid'):
                alerts.append(row)
            if row['state'] == 'unknown':
                undated += 1
        priority = {'past': 0, 'today': 1, 'soon': 2, 'invalid': 3}
        alerts.sort(key=lambda row: (priority[row['state']], row['expires_on'] or '', row['item_name']))
        return {
            'rows': rows[:200],
            'total': len(rows),
            'alerts': alerts,
            'undated': undated,
            'checked_on': today.isoformat(),
            'warning_days': warning_days,
            'counts': counts,
        }
