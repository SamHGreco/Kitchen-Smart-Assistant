#Checks input
from __future__ import annotations
import json
import re
from datetime import date
from pathlib import Path
from product_Database import normalize_barcode as normalize, validate_weight, utc_now
FIELDS = {'item_upc', 'brand_name', 'item_name', 'item_weight', 'item_category'}
INVENTORY_FIELDS = FIELDS | {'inventory_id', 'added_at', 'removed_at', 'operation_id'}
DATE_FIELDS = {'purchased_on', 'expires_on'}
CATEGORIES = (
    'Pasta - Spaghetti',
    'Pasta - Lasagna sheets',
    'Tomato sauce',
    'Fruit',
    'Vegetables',
    'Dairy',
    'Meat',
    'Beverages',
    'Other',
    'Unclassified'
)

def text_value(value, label, *, required=False, maximum=1000):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be text.')
    result = value.strip()
    if required and (not result):
        raise ValueError(f'{label} is required.')
    if len(result) > maximum or any((ord(c) < 32 for c in result)):
        raise ValueError(f'{label} is too long or wrong characters.')
    if result.lower() in ('/cancel', '\\cancel'):
        raise ValueError('Use  Cancel button.')
    return result

def iso_date(value, label):
    if value in (None, ''):
        return None
    if not isinstance(value, str) or not re.fullmatch('\\d{4}-\\d{2}-\\d{2}', value):
        raise ValueError(f'{label}: use YYYY-MM-DD or leave blank.')
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f'{label} is not a valid date.') from exc

def entry_values(data):
    result = {}
    for key, label in [('item_name', 'Item name'), ('brand_name', 'Brand'), ('item_category', 'Food type')]:
        result[key] = text_value(data.get(key, ''), label, required=key == 'item_name')
    result['item_category'] = result['item_category'] or 'Unclassified'
    quantity = str(data.get('quantity', '1')).strip()
    if not re.fullmatch('[0-9]{1,2}', quantity) or not 1 <= int(quantity) <= 99:
        raise ValueError('Quantity must be a whole number from 1 to 99.')
    result['quantity'] = int(quantity)
    result['item_weight'] = validate_weight(data.get('item_weight'))
    result['purchased_on'] = iso_date(data.get('purchased_on'), 'Purchase date')
    result['expires_on'] = iso_date(data.get('expires_on'), 'Expiration date')
    if result['purchased_on'] and result['expires_on'] and (result['expires_on'] < result['purchased_on']):
        raise ValueError('Expiration is before purchase date. Check dates.')
    return result

def load_config(filename):
    path = Path(filename).expanduser().resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    for key in ('catalog', 'products', 'inventory'):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{path.name} needs a {key} path.')
        p = Path(value).expanduser()
        data[key] = (path.parent / p).resolve() if not p.is_absolute() else p.resolve()
    paths = [data[k] for k in ('catalog', 'products', 'inventory')]
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if a == b or (a.exists() and b.exists() and a.samefile(b)):
                raise ValueError('Catalogue, manually input products and inventory must be different.')
    data['manual'] = data['inventory'].parent / 'touch_manual.sqlite'
    for existing in paths:
        manual = data['manual']
        if manual == existing or (manual.exists() and existing.exists() and manual.samefile(existing)):
            raise ValueError('touch_manual.sqlite must be different.')
    data['_config_file'] = path
    return data
DEFAULT_PREFERENCES = {'temperature_unit': 'C', 'clock_format': '24h', 'idle_seconds': 60, 'expiry_warning_days': 3}

def read_preferences(path):
    result = DEFAULT_PREFERENCES.copy()
    if Path(path).exists():
        result.update(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    if result['temperature_unit'] not in ('C', 'F') or result['clock_format'] not in ('12h', '24h'):
        raise ValueError('Invalid temperature unit or clock format.')
    if type(result['idle_seconds']) is not int or not 0 <= result['idle_seconds'] <= 3600:
        raise ValueError('idle_seconds must be from 0 to 3600.')
    if type(result['expiry_warning_days']) is not int or not 0 <= result['expiry_warning_days'] <= 365:
        raise ValueError('Expiration warning days must be between 0 and 365.')
    return result

def save_preferences(path, value):
    path = Path(path)
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)

def expiry_state(value, today, warning_days):
    if not value:
        return {'state': 'unknown', 'label': 'No date', 'days': None}
    try:
        due = date.fromisoformat(iso_date(value, 'Expiration date'))
    except (ValueError, TypeError):
        return {'state': 'invalid', 'label': 'Check date', 'days': None}
    days = (due - today).days
    if days < 0:
        state, label = ('past', f'Past date by {-days} day(s)')
    elif days == 0:
        state, label = ('today', 'Due today')
    elif days <= warning_days:
        state, label = ('soon', f'Due in {days} day(s)')
    else:
        state, label = ('later', f'{days} days remaining')
    return {'state': state, 'label': label, 'days': days}
