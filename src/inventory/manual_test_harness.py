"""
Manual test harness for the inventory + scale + expiration subsystems.

Stands in for the real touchscreen UI. Supports both simulated scale mode
(weight is typed in), and real hardware (same calibration flow as 
manual_calibration_test.py, then reads actual HX711).
"""

from __future__ import annotations

import time
from datetime import datetime

from app.shared.models import QuantityType
from inventory.inventory_db import get_connection, init_db, get_all_items, get_items_by_name, delete_item as delete_item_db
from inventory.expiration import is_expired, is_expiring_soon
from inventory.weight_logic import create_item_with_weight, apply_weight_reading, is_near_empty, is_depleted
from scale.interface import SimulatedWeightSensor, HX711WeightSensor
from scale.hx711_driver import HX711Driver
from scale.calibration import calibrate_from_known_weight

DOUT_PIN = 5
SCK_PIN = 6


def average_reading(driver: HX711Driver, samples: int = 20, trim: int = 4) -> float:
    readings = []
    for _ in range(samples):
        readings.append(driver.raw_read())
        time.sleep(0.1)
    readings.sort()
    trimmed = readings[trim: samples - trim]
    return sum(trimmed) / len(trimmed)


def setup_sensor():
    """Returns (sensor, hardware_mode). Asks once at startup which to use."""
    choice = input("Use real hardware scale? y/n: ").strip().lower()
    if choice == "y":
        driver = HX711Driver(dout_pin=DOUT_PIN, sck_pin=SCK_PIN)
        input("Ensure scale has nothing on it, then press Enter...")
        raw_zero = average_reading(driver)
        known_weight = prompt_float("Known reference weight to be placed (grams): ")
        input(f"Place the {known_weight}g reference weight, let it settle, then press Enter...")
        raw_loaded = average_reading(driver)
        params = calibrate_from_known_weight(round(raw_zero), round(raw_loaded), known_weight)
        print(f"Calibration: zero_offset={params.zero_offset}, scale_factor={params.scale_factor:.4f}")
        sensor = HX711WeightSensor(dout_pin=DOUT_PIN, sck_pin=SCK_PIN, calibration=params)
        return sensor, True
    else:
        sensor = SimulatedWeightSensor(base_weight=0.0, noise=0.0)
        sensor.tare()  # permanent zero offset; never re-tare after this
        return sensor, False


def prepare_reading(sensor, hardware_mode):
    """Gets the sensor ready for one reading: place-and-wait for real
    hardware, or a typed-in number for the simulated sensor."""
    if hardware_mode:
        input("Place the item on the scale, let it settle, then press Enter...")
    else:
        weight = prompt_float("Simulated scale reading (grams): ")
        sensor.set_simulated_load(weight)


def prompt_float(label: str) -> float:
    while True:
        raw = input(label)
        try:
            return float(raw)
        except ValueError:
            print("Enter a number.")


def add_item(conn, sensor, hardware_mode):
    name = input("Item name: ").strip()
    unit = input("Unit (e.g. g): ").strip() or "g"
    exp_raw = input("Expiration date (YYYY-MM-DD, blank for none): ").strip()
    expiration_date = datetime.fromisoformat(exp_raw) if exp_raw else None

    prepare_reading(sensor, hardware_mode)
    item = create_item_with_weight(conn, sensor, name=name, unit=unit, expiration_date=expiration_date)
    print(f"Created {item.name} (id={item.item_id}, index={item.multiple_index}): "
          f"{item.current_quantity}{item.unit}")


def update_item(conn, sensor, hardware_mode):
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

    prepare_reading(sensor, hardware_mode)
    result = apply_weight_reading(conn, item, sensor)
    print(f"{result.item.name} now at {result.item.current_quantity}{result.item.unit}")
    if result.is_near_empty:
        print("  -> near empty")
    if result.is_depleted:
        print("  -> depleted")


def delete_item(conn, sensor, hardware_mode):
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


def view_inventory(conn, sensor, hardware_mode):
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
    sensor, hardware_mode = setup_sensor()

    actions = {"1": add_item, "2": update_item, "3": view_inventory, "4": delete_item}
    while True:
        print("\n1) Add item  2) Update item  3) View inventory  4) Delete item  q) Quit")
        choice = input("> ").strip().lower()
        if choice == "q":
            break
        action = actions.get(choice)
        if action:
            action(conn, sensor, hardware_mode)
        else:
            print("Not a valid option.")
    conn.close()


if __name__ == "__main__":
    main()


