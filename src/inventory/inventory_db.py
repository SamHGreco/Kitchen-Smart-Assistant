"""SQLite inventory database: schema creation and CRUD operations.

Owns storage for InventoryItem records (see app.shared.models).
Other subsystems should go through these functions rather than
opening the database file directly.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from app.shared.models import InventoryItem, InventoryLogEntry, ItemStatus, OperationType, QuantityType

DB_PATH = Path(__file__).resolve().parent.parent.parent / "inventory.db"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open a connection to the inventory database, creating the file if needed."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
    """Adds `column` to `table` if missing, so an existing local .db file
    picks up new fields without being deleted and recreated."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def init_db(conn: sqlite3.Connection) -> None:
    """Create the inventory schema if it does not already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT,
            brand_name TEXT,
            name TEXT NOT NULL,
            category TEXT,
            quantity_type TEXT NOT NULL,
            current_quantity REAL NOT NULL,
            initial_quantity REAL NOT NULL,
            unit TEXT,
            expiration_date TEXT,
            date_added TEXT NOT NULL,
            multiple_group TEXT,
            multiple_index INTEGER,
            location TEXT,
            status TEXT NOT NULL,
            last_updated TEXT NOT NULL
        )
        """
    )
    _ensure_column(conn, "inventory_items", "brand_name", "brand_name TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            item_name TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            quantity_before REAL,
            quantity_after REAL,
            location_before TEXT,
            location_after TEXT,
            note TEXT,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _row_to_item(row: sqlite3.Row) -> InventoryItem:
    """Convert a raw SQLite row to an InventoryItem dataclass."""
    return InventoryItem(
        item_id=row["item_id"],
        barcode=row["barcode"],
        brand_name=row["brand_name"],
        name=row["name"],
        category=row["category"],
        quantity_type=QuantityType(row["quantity_type"]),
        current_quantity=row["current_quantity"],
        initial_quantity=row["initial_quantity"],
        unit=row["unit"],
        expiration_date=datetime.fromisoformat(row["expiration_date"])
        if row["expiration_date"] else None,
        date_added=datetime.fromisoformat(row["date_added"]),
        multiple_group=row["multiple_group"],
        multiple_index=row["multiple_index"],
        location=row["location"],
        status=ItemStatus(row["status"]),
        last_updated=datetime.fromisoformat(row["last_updated"]),
    )


def _row_to_log_entry(row: sqlite3.Row) -> InventoryLogEntry:
    """Convert a raw SQLite row from inventory_log to an InventoryLogEntry dataclass."""
    return InventoryLogEntry(
        log_id=row["log_id"],
        item_id=row["item_id"],
        item_name=row["item_name"],
        operation_type=OperationType(row["operation_type"]),
        quantity_before=row["quantity_before"],
        quantity_after=row["quantity_after"],
        location_before=row["location_before"],
        location_after=row["location_after"],
        note=row["note"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
    )


def _log_operation(
    conn: sqlite3.Connection,
    item_id: int | None,
    item_name: str,
    operation_type: OperationType,
    *,
    quantity_before: float | None = None,
    quantity_after: float | None = None,
    location_before: str | None = None,
    location_after: str | None = None,
    note: str | None = None,
) -> None:
    """Records one MR20 history row. Called automatically by the functions
    below - nothing outside this module needs to call it directly."""
    conn.execute(
        """
        INSERT INTO inventory_log
        (item_id, item_name, operation_type, quantity_before, quantity_after,
         location_before, location_after, note, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id, item_name, operation_type.value, quantity_before, quantity_after,
            location_before, location_after, note, datetime.now().isoformat(),
        ),
    )
    conn.commit()


def create_item(
        conn: sqlite3.Connection,
        name: str,
        quantity_type: QuantityType,
        initial_quantity: float,
        unit: str,
        barcode: str | None = None,
        brand_name: str | None = None,
        category: str | None = None,
        expiration_date: datetime | None = None,
        location: str = "pantry",
        multiple_group: str | None = None,
        multiple_index: int | None = None,
) -> InventoryItem:
    """Add a new item. current_quantity is initialized to initial_quantity, and status is set to ACTIVE."""
    now = datetime.now()
    cursor = conn.execute(
        """
        INSERT INTO inventory_items 
        (barcode, brand_name, name, category, quantity_type, current_quantity, initial_quantity,
         unit, expiration_date, date_added, multiple_group, multiple_index, location,
         status, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            barcode,
            brand_name,
            name,
            category,
            quantity_type.value,
            initial_quantity,
            initial_quantity,
            unit,
            expiration_date.isoformat() if expiration_date else None,
            now.isoformat(),
            multiple_group,
            multiple_index,
            location,
            ItemStatus.ACTIVE.value,
            now.isoformat(),
        ),
    )
    conn.commit()
    item = get_item(conn, cursor.lastrowid)
    _log_operation(
        conn, item.item_id, item.name, OperationType.ADDED,
        quantity_after=initial_quantity, location_after=location,
    )
    return item


def get_item(conn: sqlite3.Connection, item_id: int) -> InventoryItem | None:
    """Retrieve a single item by its ID."""
    row = conn.execute(
        "SELECT * FROM inventory_items WHERE item_id = ?", (item_id,)
    ).fetchone()
    return _row_to_item(row) if row else None


def get_items_by_name(conn: sqlite3.Connection, name: str) -> list[InventoryItem]:
    """Fetch all items matching a given name, ordered by multiple_index (for milk 1, milk 2,...etc.)"""
    rows = conn.execute(
        "SELECT * FROM inventory_items WHERE name = ? ORDER BY multiple_index", (name,)
    ).fetchall()
    return [_row_to_item(row) for row in rows]


def update_quantity(conn: sqlite3.Connection, item_id: int, new_quantity: float) -> InventoryItem | None:
    """Update current_quantity after a scale reading, auto-flagging depleted items."""
    existing = get_item(conn, item_id)
    if existing is None:
        return None
    status = ItemStatus.DEPLETED if new_quantity <= 0 else ItemStatus.ACTIVE
    conn.execute(
        """
        UPDATE inventory_items
        SET current_quantity = ?, status = ?, last_updated = ?
        WHERE item_id = ?
        """,
        (new_quantity, status.value, datetime.now().isoformat(), item_id),
    )
    conn.commit()
    _log_operation(
        conn, item_id, existing.name, OperationType.QUANTITY_UPDATED,
        quantity_before=existing.current_quantity, quantity_after=new_quantity,
    )
    return get_item(conn, item_id)


def update_location(conn: sqlite3.Connection, item_id: int, new_location: str) -> InventoryItem | None:
    """Move an item (e.g. pantry -> fridge). New function - nothing changed
    an item's location after creation before this. Logs the change for MR20."""
    existing = get_item(conn, item_id)
    if existing is None:
        return None
    conn.execute(
        """
        UPDATE inventory_items
        SET location = ?, last_updated = ?
        WHERE item_id = ?
        """,
        (new_location, datetime.now().isoformat(), item_id),
    )
    conn.commit()
    _log_operation(
        conn, item_id, existing.name, OperationType.LOCATION_CHANGED,
        location_before=existing.location, location_after=new_location,
    )
    return get_item(conn, item_id)


def delete_item(conn: sqlite3.Connection, item_id: int) -> None:
    """Remove an item from the inventory."""
    existing = get_item(conn, item_id)
    conn.execute("DELETE FROM inventory_items WHERE item_id = ?", (item_id,))
    conn.commit()
    if existing is not None:
        _log_operation(
            conn, item_id, existing.name, OperationType.REMOVED,
            quantity_before=existing.current_quantity, location_before=existing.location,
        )


def get_all_items(conn: sqlite3.Connection) -> list[InventoryItem]:
    """Fetch all items in the inventory."""
    rows = conn.execute("SELECT * FROM inventory_items").fetchall()
    return [_row_to_item(row) for row in rows]


def update_expiration_date(
    conn: sqlite3.Connection, item_id: int, new_expiration_date: datetime | None
) -> InventoryItem | None:
    """Update an item's expiration date, for manual entry or correcting it after creation."""
    conn.execute(
        """
        UPDATE inventory_items
        SET expiration_date = ?, last_updated = ?
        WHERE item_id = ?
        """,
        (
            new_expiration_date.isoformat() if new_expiration_date else None,
            datetime.now().isoformat(),
            item_id,
        ),
    )
    conn.commit()
    return get_item(conn, item_id)


def get_item_history(conn: sqlite3.Connection, item_id: int) -> list[InventoryLogEntry]:
    """MR20: full history for one item, newest first."""
    rows = conn.execute(
        "SELECT * FROM inventory_log WHERE item_id = ? ORDER BY log_id DESC", (item_id,)
    ).fetchall()
    return [_row_to_log_entry(row) for row in rows]


def get_all_history(conn: sqlite3.Connection, limit: int | None = None) -> list[InventoryLogEntry]:
    """MR20: full history across every item, newest first. Pass `limit` for just the most recent N."""
    query = "SELECT * FROM inventory_log ORDER BY log_id DESC"
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    rows = conn.execute(query, params).fetchall()
    return [_row_to_log_entry(row) for row in rows]