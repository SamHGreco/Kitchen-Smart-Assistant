"""Prepare the CURRENT integrated schemas without overwriting existing data.

--empty-catalog creates a real, empty catalog only when missing. It contains no
product data; unknown scans must be entered by hand until a catalog is supplied.
"""
from __future__ import annotations
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/ui')]
from Input_Validation import load_config
from product_id.product_database import ProductDatabase
from inventory.inventory_db import get_connection, init_db


def bootstrap(settings, *, empty_catalog=False):
    catalog = Path(settings['catalog'])
    if not catalog.exists():
        if not empty_catalog:
            raise FileNotFoundError('Catalog missing. Copy your catalog or explicitly use --empty-catalog.')
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.touch(exist_ok=False)
        with closing(sqlite3.connect(catalog)) as conn:
            conn.execute('CREATE TABLE items (item_upc TEXT, brand_name TEXT, '
                         'item_name TEXT, item_weight TEXT, item_category TEXT)')
            conn.commit()
        print('Created EMPTY catalog: enter product names manually for unknown scans.')
    with ProductDatabase(catalog, settings['products']):
        pass
    inventory = Path(settings['inventory'])
    inventory.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection(inventory)) as conn:
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(inventory_items)')}
        if columns and not {'item_id', 'barcode', 'name', 'quantity_type', 'current_quantity'}.issubset(columns):
            raise ValueError('Legacy/incompatible inventory schema. Back up and migrate it; do not overwrite it.')
        init_db(conn)
    print('Catalog:', catalog)
    print('Products:', settings['products'])
    print('Inventory:', inventory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'src/ui/config.pi.json'))
    parser.add_argument('--empty-catalog', action='store_true')
    args = parser.parse_args()
    bootstrap(load_config(args.config), empty_catalog=args.empty_catalog)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Data setup stopped: ' + str(exc))
