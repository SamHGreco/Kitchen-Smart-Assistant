"""
Expiration status and date calculations for inventory items.

Operates on InventoryItem.expiration_date (see app.shared.models). Items
with no expiration_date are never flagged as expired or expiring soon,
since there is no date to compare against.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from app.shared.models import InventoryItem
from inventory.inventory_db import get_all_items


def days_until_expiration(item: InventoryItem, as_of: datetime | None = None) -> int | None:
    """
    Returns the number of days until the item expires, or None if the item
    has no expiration date. Negative values indicate the item is already
    expired.
    """
    if item.expiration_date is None:
        return None
    if as_of is None:
        as_of = datetime.now()
    delta = item.expiration_date.date() - as_of.date()
    return delta.days


def is_expired(item: InventoryItem, as_of: datetime | None = None) -> bool:
    """Returns True if the item is expired as of the current or given date."""
    days = days_until_expiration(item, as_of)
    return days is not None and days < 0


def is_expiring_soon(item: InventoryItem, within_days: int = 3, as_of: datetime | None = None) -> bool:
    """Returns True if the item is expiring within the given number of days (default 3)."""
    days = days_until_expiration(item, as_of)
    return days is not None and 0 <= days <= within_days


def get_expired_items(conn: sqlite3.Connection, as_of: datetime | None = None) -> list[InventoryItem]:
    """Returns all items whose expiration date has passed."""
    return [item for item in get_all_items(conn) if is_expired(item, as_of)]


def get_items_expiring_soon(
    conn: sqlite3.Connection, within_days: int = 3, as_of: datetime | None = None
) -> list[InventoryItem]:
    """Returns all items expiring within the given number of days."""
    return [item for item in get_all_items(conn) if is_expiring_soon(item, within_days, as_of)]
