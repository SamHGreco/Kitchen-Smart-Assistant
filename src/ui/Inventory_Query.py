#Stand in for now
#inventory queries, supplies the open SQLite connection
from dataclasses import asdict
from Input_Validation import normalize, expiry_state

class InventoryQueries:

    def lookup(self, raw):
        code = normalize(raw)
        count = self.inventory.execute(
            'SELECT COUNT(*) FROM inventory_items WHERE item_upc=? AND removed_at IS NULL',
            (code,)
        ).fetchone()[0]
        if count:
            row = self.inventory.execute(
                'SELECT item_upc,brand_name,item_name,item_weight,item_category FROM inventory_items WHERE item_upc=? AND removed_at IS NULL ORDER BY inventory_id DESC LIMIT 1',
                (code,)
            ).fetchone()
            product = {**dict(row), 'source': 'inventory'}
        else:
            found = self.products.find_product(code)
            product = asdict(found) if found else None
        return {'raw': raw.strip(), 'code': code, 'product': product, 'count': count}

    def count(self):
        return sum((c.execute(f'SELECT COUNT(*) FROM {table} WHERE removed_at IS NULL').fetchone()[0] for c, table in ((self.inventory, 'inventory_items'), (self.manual, 'manual_items'))))

    def list_items(self):
        result = []
        names = 'inventory_id,item_name,brand_name,item_category,item_weight,purchased_on,expires_on,added_at'
        for c, table, kind in (
            (self.inventory, 'inventory_items', 'barcode'),
            (self.manual, 'manual_items', 'manual')
        ):
            barcode = 'item_upc' if kind == 'barcode' else 'NULL AS item_upc'
            rows = c.execute(f'SELECT {barcode},{names} FROM {table} WHERE removed_at IS NULL ORDER BY inventory_id DESC')
            for row in rows:
                entry = dict(row)
                entry['kind'] = kind
                result.append(entry)
        result.sort(key=lambda x: x['added_at'], reverse=True)
        return result

    def matching_items(self, barcode=None):
        rows = self.list_items()
        if barcode is None:
            return rows
        code = normalize(barcode)
        return [row for row in rows if row['item_upc'] == code]

    def get_item(self, kind, record_id):
        if type(record_id) is not int or record_id < 1:
            raise ValueError('Choose a valid inventory item.')
        connection, table = self._target(kind)
        row = connection.execute(
            f'SELECT * FROM {table} WHERE inventory_id=? AND removed_at IS NULL',
            (record_id,)
        ).fetchone()
        if row is None:
            raise ValueError('This inventory item is no longer active.')
        return {**dict(row), 'kind': kind, 'item_upc': row['item_upc'] if kind == 'barcode' else None}


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
            'counts': counts
        }
