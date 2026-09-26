"""SQLite inventory database: schema creation and CRUD operations.

Owns storage for InventoryItem records (see app.shared.models).
Other subsystems should go through these functions rather than
opening the database file directly.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from app.shared.models import InventoryItem, ItemStatus, QuantityType

DB_PATH = Path(__file__).resolve().parent.parent.parent / "inventory.db"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open a connection to the inventory database, creating the file if needed."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the inventory schema if it does not already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT,
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
    conn.commit() 


def _row_to_item(row: sqlite3.Row) -> InventoryItem:
    """Convert a raw SQLite row to an InventoryItem dataclass."""
    return InventoryItem(
        item_id=row["item_id"],
        barcode=row["barcode"],
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


def create_item(
        conn: sqlite3.Connection,
        name: str,
        quantity_type: QuantityType,
        initial_quantity: float,
        unit: str,
        barcode: str | None = None,
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
        (barcode, name, category, quantity_type, current_quantity, initial_quantity,
         unit, expiration_date, date_added, multiple_group, multiple_index, location,
         status, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            barcode,
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
    return get_item(conn, cursor.lastrowid)


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
    return get_item(conn, item_id)


def delete_item(conn: sqlite3.Connection, item_id: int) -> None:
    """Remove an item from the inventory."""
    conn.execute("DELETE FROM inventory_items WHERE item_id = ?", (item_id,))
    conn.commit()
