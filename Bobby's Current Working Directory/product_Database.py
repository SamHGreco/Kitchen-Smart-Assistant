#Stand in for now
#Searches database
from __future__ import annotations
import argparse
import json
import math
import re
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG = ROOT / 'data' / 'catalog.sqlite'
DEFAULT_PRODUCTS = ROOT / 'data' / 'barcodes.db'
CATALOG_TABLE = 'items'
CATALOG_COLUMNS = {'item_upc', 'brand_name', 'item_name', 'item_weight', 'item_category'}
PRODUCT_COLUMNS = {'item_upc', 'brand_name', 'item_name', 'item_weight', 'item_category', 'updated_at'}

class BarcodeError(ValueError):
    pass

class DatabaseSchemaError(RuntimeError):
    pass

@dataclass(frozen=True)
class Product:
    item_upc: str
    brand_name: str
    item_name: str
    item_weight: float | None
    item_category: str
    source: str = 'manual'

def normalize_barcode(value: str) -> str:
    if not isinstance(value, str):
        raise BarcodeError('Pass a barcode as text, not a number; keep leading zeros.')
    code = value.strip()
    if len(code) not in (8, 12, 13, 14) or re.fullmatch('[0-9]+', code) is None:
        raise BarcodeError('Expected 8, 12, 13 or 14 ASCII digits, including the check digit. UPC-E, PLUs, URLs and packed QR data are not supported here.')
    total = sum((int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(reversed(code[:-1]))))
    expected = -total % 10
    if int(code[-1]) != expected:
        raise BarcodeError(f'Invalid check digit: expected {expected}. Check scanner settings; do not automatically replace the printed digit.')
    return code.zfill(14)

def validate_weight(value: float | str | None) -> float | None:
    if value is None or (isinstance(value, str) and (not value.strip())):
        return None
    if isinstance(value, bool):
        raise ValueError('Weight must be a number in grams, not True/False.')
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Enter a number in grams, such as 500 or 125.5.') from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError('Weight must be greater than zero and finite, or left blank.')
    return number

def validate_product(product: Product) -> Product:
    code = normalize_barcode(product.item_upc)
    for field in ('item_name', 'brand_name', 'item_category'):
        value = getattr(product, field)
        if not isinstance(value, str):
            raise ValueError(f'{field} must be text.')
        if value.strip().lower() in ('/cancel', '\\cancel'):
            raise ValueError('Use the Cancel button, not cancellation text.')
        if len(value) > 1000 or any((ord(c) < 32 for c in value)):
            raise ValueError(f'{field} has invalid characters or is too long.')
    name = product.item_name.strip()
    if not name:
        raise ValueError('An item name is required.')
    return replace(
        product,
        item_upc=code,
        item_name=name,
        brand_name=product.brand_name.strip(),
        item_category=product.item_category.strip() or 'Unclassified',
        item_weight=validate_weight(product.item_weight)
    )

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def same_file(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    return left.exists() and right.exists() and left.samefile(right)

def open_readonly(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Database not found: {path}. Supply your existing catalog path.')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection

def table_names(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

def validate_catalog(connection: sqlite3.Connection) -> None:
    columns_info = list(connection.execute(f'PRAGMA table_info({CATALOG_TABLE})'))
    columns = {row[1] for row in columns_info}
    if not CATALOG_COLUMNS.issubset(columns):
        raise DatabaseSchemaError(f'The catalog must contain {CATALOG_TABLE}(item_upc, brand_name, item_name, item_weight, item_category). Actual {CATALOG_TABLE} columns: {sorted(columns)}.')
    types = {row[1]: (row[2] or '').upper() for row in columns_info}
    non_text = [name for name in CATALOG_COLUMNS if types.get(name) != 'TEXT']
    if non_text:
        raise DatabaseSchemaError('These catalog columns should be TEXT: ' + ', '.join(sorted(non_text)))

def _catalog_barcode_candidates(value: str) -> tuple[str, ...]:
    raw = value.strip()
    normalized = normalize_barcode(raw)
    candidates: list[str] = []

    def add(candidate: str) -> None:
        if candidate in candidates:
            return
        try:
            if normalize_barcode(candidate) == normalized:
                candidates.append(candidate)
        except BarcodeError:
            pass
    add(raw)
    add(normalized)
    for length in (13, 12, 8):
        add(normalized[-length:])
    return tuple(candidates)

def _catalog_weight(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return validate_weight(text)
    except ValueError:
        return None

class ProductDatabase:

    def __init__(self, catalog_path: str | Path, local_path: str | Path=DEFAULT_PRODUCTS):
        self.catalog_path = Path(catalog_path).expanduser().resolve()
        self.local_path = Path(local_path).expanduser().resolve()
        self.catalog: sqlite3.Connection | None = None
        self.local: sqlite3.Connection | None = None
        if same_file(self.catalog_path, self.local_path):
            raise ValueError('The read-only catalog and writable barcodes.db must be different files.')
        try:
            self.catalog = open_readonly(self.catalog_path)
            validate_catalog(self.catalog)
            self.local_path.parent.mkdir(parents=True, exist_ok=True)
            self.local = sqlite3.connect(self.local_path, timeout=5)
            self.local.row_factory = sqlite3.Row
            self.create_tables()
        except BaseException:
            self.close()
            raise

    def create_tables(self) -> None:
        assert self.local is not None
        tables = table_names(self.local)
        if tables:
            columns = {row[1] for row in self.local.execute('PRAGMA table_info(products)')}
            if not PRODUCT_COLUMNS.issubset(columns) or not tables.issubset({'products', 'app_metadata'}):
                raise DatabaseSchemaError(f"Not this application's database: {self.local_path}.")
            key = next((row for row in self.local.execute('PRAGMA table_info(products)') if row[1] == 'item_upc'))
            if key[2].upper() != 'TEXT' or not key[5]:
                raise DatabaseSchemaError('Manually entered products need an item_upc TEXT key.')
            return
        with self.local:
            self.local.execute("\n                CREATE TABLE products (\n                    item_upc TEXT PRIMARY KEY CHECK(length(item_upc)=14),\n                    brand_name TEXT NOT NULL DEFAULT '',\n                    item_name TEXT NOT NULL CHECK(length(trim(item_name))>0),\n                    item_weight REAL CHECK(item_weight IS NULL OR item_weight>0),\n                    item_category TEXT NOT NULL DEFAULT 'Unclassified',\n                    updated_at TEXT NOT NULL\n                )\n            ")
            self.local.execute('CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.local.executemany(
                'INSERT INTO app_metadata VALUES (?, ?)',
                [('schema_version', '1'), ('weight_unit', 'g')]
            )

    def find_product(self, barcode: str) -> Product | None:
        code = normalize_barcode(barcode)
        if self.local is None or self.catalog is None:
            raise RuntimeError('ProductDatabase is closed.')
        row = self.local.execute(
            'SELECT item_upc, brand_name, item_name, item_weight, item_category FROM products WHERE item_upc = ?',
            (code,)
        ).fetchone()
        if row is not None:
            return validate_product(Product(**dict(row), source='barcodes.db'))
        candidates = _catalog_barcode_candidates(barcode)
        placeholders = ','.join(('?' for _ in candidates))
        row = self.catalog.execute(f'SELECT item_upc, brand_name, item_name, item_weight, item_category FROM {CATALOG_TABLE} WHERE item_upc IN ({placeholders})', candidates).fetchall()
        rows = [entry for entry in row if (entry['item_name'] or '').strip()]
        if not rows:
            return None
        descriptions = {(r['brand_name'], r['item_name'], r['item_weight'], r['item_category']) for r in rows}
        if len(descriptions) > 1:
            raise ValueError('Conflicting catalogue entries share barcode. Review inventory.')
        row = rows[0]
        return validate_product(Product(item_upc=code, brand_name=row['brand_name'] or '', item_name=row['item_name'], item_weight=_catalog_weight(row['item_weight']), item_category=row['item_category'] or 'Unclassified', source='catalog'))

    def save_product(self, product: Product) -> Product:
        product = validate_product(product)
        if self.local is None:
            raise RuntimeError('ProductDatabase is closed.')
        with self.local:
            self.local.execute(
                '\n                INSERT INTO products\n                    (item_upc, brand_name, item_name, item_weight, item_category, updated_at)\n                VALUES (?, ?, ?, ?, ?, ?)\n                ON CONFLICT(item_upc) DO UPDATE SET\n                    brand_name=excluded.brand_name,\n                    item_name=excluded.item_name,\n                    item_weight=excluded.item_weight,\n                    item_category=excluded.item_category,\n                    updated_at=excluded.updated_at\n            ',
                (product.item_upc, product.brand_name, product.item_name, product.item_weight, product.item_category, utc_now())
            )
        return replace(product, source='barcodes.db')

    def close(self) -> None:
        for attr in ('local', 'catalog'):
            connection = getattr(self, attr, None)
            if connection is not None:
                connection.close()
                setattr(self, attr, None)

    def __enter__(self) -> ProductDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

def inspect_catalog(path: str | Path) -> dict[str, Any]:
    connection = open_readonly(Path(path))
    try:
        tables = sorted(table_names(connection))
        result: dict[str, Any] = {'path': str(Path(path).expanduser().resolve()), 'tables': tables}
        result['items_columns'] = [dict(row) for row in connection.execute(f'PRAGMA table_info({CATALOG_TABLE})')]
        try:
            validate_catalog(connection)
            result['compatible'] = True
            result['sample_items'] = [dict(row) for row in connection.execute(f'SELECT item_upc, brand_name, item_name, item_weight, item_category FROM {CATALOG_TABLE} LIMIT 5')]
        except DatabaseSchemaError as exc:
            result['compatible'] = False
            result['reason'] = str(exc)
        return result
    finally:
        connection.close()

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='Read-only schema and sample check')
    inspect.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
    lookup = sub.add_parser('lookup', help='Look up a GTIN without adding inventory')
    lookup.add_argument('barcode')
    lookup.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
    lookup.add_argument('--products', type=Path, default=DEFAULT_PRODUCTS)
    args = parser.parse_args()
    try:
        if args.command == 'inspect':
            result = inspect_catalog(args.catalog)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result['compatible'] else 2
        with ProductDatabase(args.catalog, args.products) as database:
            product = database.find_product(args.barcode)
            print(json.dumps(asdict(product) if product else {'found': False}, indent=2, ensure_ascii=False))
        return 0
    except (OSError, sqlite3.Error, ValueError, DatabaseSchemaError) as exc:
        parser.exit(2, f'Error: {exc}\n')
if __name__ == '__main__':
    raise SystemExit(main())
