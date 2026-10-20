"""
Quantity and depletion logic for inventory items.

Bridges weight sensor readings (see scale.interface.WeightSensor)
to inventory records (see inventory.inventory_db), and determines
near-empty status so the UI can prompt the user before an item runs out.
"""

from __future__ import annotations

import math
import sqlite3

from app.shared.models import InventoryItem, ItemStatus, QuantityType
from inventory.inventory_db import create_item, get_items_by_name, update_quantity
from scale.interface import WeightSensor

# Fraction of initial_quantity at or below which an item counts as
# "near empty." Rounded up (not down) when applied, so alert fires
# with at least this much margin rather than less.
NEAR_EMPTY_FRACTION = 0.15


def near_empty_quantity(item: InventoryItem) -> float:
    """
    The quantity (in the item's own unit) at or below which the item is
    considered "near empty." Ceiling-rounded so threshold errs toward
    firing earlier, giving user more time to restock.
    """
    return math.ceil(item.initial_quantity * NEAR_EMPTY_FRACTION)


def is_near_empty(item: InventoryItem) -> bool:
    """True if the item's current_quantity is at or below its near-empty threshold."""
    return item.current_quantity <= near_empty_quantity(item)


def is_depleted(item: InventoryItem) -> bool:
    """True if the item is already flagged depleted (current_quantity reached 0)"""
    return item.status == ItemStatus.DEPLETED


class WeightUpdateResult:
    """
    Outcome of applying a new weight reading to an inventory item.
    """
    def __init__(self, item, is_near_empty, is_depleted):
        self.item = item
        self.is_near_empty = is_near_empty
        self.is_depleted = is_depleted

def apply_weight_reading(conn, item, sensor):
    if item.quantity_type != QuantityType.WEIGHT:
        raise ValueError(
            f"Cannot apply a weight reading to {item.name!r}: "
            f"tracked by {item.quantity_type.value}, not weight"
        )

    new_weight = sensor.read_settled_weight()
    new_weight = max(new_weight, 0.0)
    updated_item = update_quantity(conn, item.item_id, new_weight)

    return WeightUpdateResult(
        item=updated_item,
        is_near_empty=is_near_empty(updated_item),
        is_depleted=is_depleted(updated_item),
    )


def create_item_with_weight(conn, sensor, name, unit, barcode=None, category=None,
                            expiration_date=None, location="pantry") -> InventoryItem:
    """
    Captures settled weight reading and creates a new weight-tracked
    inventory item from it. Every item gets a multiple_index, starting at 1,
    based on how many items with this name already exist. A lone milk entry is
    entered as "Milk 1" rather than being unnumbered.
    """
    weight = sensor.read_settled_weight()
    weight = max(weight, 0.0)

    existing = get_items_by_name(conn, name)
    next_index = len(existing) + 1

    return create_item(
        conn, name=name, quantity_type=QuantityType.WEIGHT, initial_quantity=weight,
        unit=unit, barcode=barcode, category=category, expiration_date=expiration_date,
        location=location, multiple_group=name, multiple_index=next_index,
    )

