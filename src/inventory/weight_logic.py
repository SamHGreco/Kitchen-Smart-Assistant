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
from inventory.inventory_db import update_quantity
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
    Carries the updated item plus whether this specific update is what crossed
    item into near-empty or depleted, so UI knows when to prompt rather
    than re-prompting on every read.
    """

    def __init__(self, item: InventoryItem, became_near_empty: bool, became_depleted: bool):
        self.item = item
        self.became_near_empty = became_near_empty
        self.became_depleted = became_depleted

def apply_weight_reading(
    conn: sqlite3.Connection, item: InventoryItem, sensor: WeightSensor
) -> WeightUpdateResult:
    """
    Takes a settled reading from sensor and applies it to item's inventory
    record. Only valid for QuantityType.WEIGHT items, since count items
    (eggs, etc) aren't measured on the scale.
    """
    if item.quantity_type != QuantityType.WEIGHT:
        raise ValueError(
            f"Cannot apply a weight reading to {item.name!r}: "
            f"tracked by {item.quantity_type.value}, not weight"
        )

    new_weight = sensor.read_settled_weight()
    # Scale noise can report a hair below zero on empty tray; 
    # clamp so a negative quantity is never stored
    new_weight = max(new_weight, 0.0)

    was_near_empty = is_near_empty(item)
    was_depleted = is_depleted(item)

    updated_item = update_quantity(conn, item.item_id, new_weight)

    return WeightUpdateResult(
        item=updated_item,
        became_near_empty=is_near_empty(updated_item) and not was_near_empty,
        became_depleted=is_depleted(updated_item) and not was_depleted,
    )
