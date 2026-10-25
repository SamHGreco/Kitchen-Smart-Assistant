"""Create only empty writable databases beside an existing, validated catalog."""
from __future__ import annotations
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from Input_Validation import load_config
from Inventory_Database import MANUAL_SCHEMA, Store
from product_Database import ProductDatabase, open_readonly, validate_catalog

INVENTORY_SCHEMA = '''CREATE TABLE inventory_items (
    inventory_id INTEGER PRIMARY KEY,
    item_upc TEXT NOT NULL CHECK(length(item_upc)=14),
    brand_name TEXT NOT NULL, item_name TEXT NOT NULL, item_weight REAL,
    item_category TEXT NOT NULL, added_at TEXT NOT NULL, removed_at TEXT,
    operation_id TEXT NOT NULL UNIQUE, purchased_on TEXT, expires_on TEXT)'''


def initialize(settings, *, apply=False):
    with closing(open_readonly(settings['catalog'])) as catalog:
        validate_catalog(catalog)
    targets = [Path(settings[name]) for name in ('products', 'inventory', 'manual')]
    resolved = [path.resolve() for path in targets]
    if len(set(resolved + [Path(settings['catalog']).resolve()])) != 4:
        raise ValueError('Catalog, products, inventory, and manual paths must all be different.')
    for path in targets:
        if path.exists():
            raise FileExistsError(f'Keep existing data: {path}. Use Prepare_Data.py for existing inventory (if redoing builds).')
    if not apply:
        return targets
    created = []
    try:
        for path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=False)
            created.append(path)
        with ProductDatabase(settings['catalog'], settings['products']):
            pass
        for name, schema in (('inventory', INVENTORY_SCHEMA), ('manual', MANUAL_SCHEMA)):
            with closing(sqlite3.connect(settings[name])) as connection:
                with connection:
                    connection.execute(schema)
        with Store(settings) as store:
            if store.count() != 0:
                raise RuntimeError('New inventory validation failed.')
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).resolve().parent / 'config.pi.json'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    paths = initialize(load_config(args.config), apply=args.apply)
    for path in paths:
        print(('Created: ' if args.apply else 'Would create: ') + str(path))
    print('Existing catalog unchanged. ' + ('Ready.' if args.apply else 'Add --apply to create these empty stores.'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Initialization stopped: ' + str(exc))
