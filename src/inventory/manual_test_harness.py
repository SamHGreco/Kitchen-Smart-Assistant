"""
Manual test harness for the inventory + scale + expiration subsystems.

Stands in for the real touchscreen UI (not built yet) and real scale
hardware (not on hand). Every weight is typed in by hand and fed through
SimulatedWeightSensor, so no physical scale is needed to run this.
"""

from __future__ import annotations

from datetime import datetime

from app.shared.models import QuantityType
from inventory.inventory_db import get_connection, init_db, get_all_items, get_items_by_name, delete_item as delete_item_db
from inventory.expiration import is_expired, is_expiring_soon
from inventory.weight_logic import create_item_with_weight, apply_weight_reading, is_near_empty, is_depleted
from scale.interface import SimulatedWeightSensor


def simulated_reading(grams: float) -> SimulatedWeightSensor:
    """A SimulatedWeightSensor pre-set to report exactly `grams`, no noise."""
    sensor = SimulatedWeightSensor(base_weight=0.0, noise=0.0)
    sensor.tare()
    sensor.set_simulated_load(grams)
    return sensor


def prompt_float(label: str) -> float:
    while True:
        raw = input(label)
        try:
            return float(raw)
        except ValueError:
            print("Enter a number.")


def add_item(conn):
    name = input("Item name: ").strip()
    unit = input("Unit (e.g. g): ").strip() or "g"
    weight = prompt_float("Simulated scale reading (grams): ")
    exp_raw = input("Expiration date (YYYY-MM-DD, blank for none): ").strip()
    expiration_date = datetime.fromisoformat(exp_raw) if exp_raw else None

    sensor = simulated_reading(weight)
    item = create_item_with_weight(conn, sensor, name=name, unit=unit, expiration_date=expiration_date)
    print(f"Created {item.name} (id={item.item_id}, index={item.multiple_index}): "
          f"{item.current_quantity}{item.unit}")


def update_item(conn):
    name = input("Item name to update: ").strip()
    matches = get_items_by_name(conn, name)
    if not matches:
        print("No items with that name.")
        return
    for m in matches:
        print(f"  id={m.item_id} index={m.multiple_index} current={m.current_quantity}{m.unit}")
    item_id = int(input("item_id to update: "))
    item = next((i for i in matches if i.item_id == item_id), None)
    if item is None:
        print("Not a valid id from the list above.")
        return

    weight = prompt_float("Simulated scale reading (grams): ")
    sensor = simulated_reading(weight)
    result = apply_weight_reading(conn, item, sensor)
    print(f"{result.item.name} now at {result.item.current_quantity}{result.item.unit}")
    if result.is_near_empty:
        print("  -> near empty")
    if result.is_depleted:
        print("  -> depleted")


def delete_item(conn):
    name = input("Item name to delete: ").strip()
    matches = get_items_by_name(conn, name)
    if not matches:
        print("No items with that name.")
        return
    for m in matches:
        print(f"  id={m.item_id} index={m.multiple_index} current={m.current_quantity}{m.unit}")
    item_id = int(input("item_id to delete: "))
    item = next((i for i in matches if i.item_id == item_id), None)
    if item is None:
        print("Not a valid id from the list above.")
        return

    confirm = input(f"Delete {item.name} (id={item_id})? y/n: ").strip().lower()
    if confirm == "y":
        delete_item_db(conn, item_id)
        print("Deleted.")
    else:
        print("Cancelled.")


def view_inventory(conn):
    items = get_all_items(conn)
    if not items:
        print("Inventory is empty.")
        return
    now = datetime.now()
    for item in items:
        flags = []
        if item.quantity_type == QuantityType.WEIGHT:
            if is_depleted(item):
                flags.append("depleted")
            elif is_near_empty(item):
                flags.append("near empty")
        if is_expired(item, as_of=now):
            flags.append("expired")
        elif is_expiring_soon(item, as_of=now):
            flags.append("expiring soon")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  id={item.item_id} {item.name} {item.multiple_index or ''} "
              f"{item.current_quantity}/{item.initial_quantity}{item.unit}{flag_str}")


def main():
    conn = get_connection()
    init_db(conn)
    actions = {"1": add_item, "2": update_item, "3": view_inventory, "4": delete_item}
    while True:
        print("\n1) Add item  2) Update item  3) View inventory  4) Delete item  q) Quit")
        choice = input("> ").strip().lower()
        if choice == "q":
            break
        action = actions.get(choice)
        if action:
            action(conn)
        else:
            print("Not a valid option.")
    conn.close()


if __name__ == "__main__":
    main()
