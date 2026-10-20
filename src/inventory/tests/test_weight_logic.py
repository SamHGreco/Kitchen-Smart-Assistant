from dataclasses import replace

import pytest

from app.shared.models import QuantityType
from inventory.inventory_db import get_connection, init_db, create_item
from inventory.weight_logic import(
    near_empty_quantity, is_near_empty, is_depleted, apply_weight_reading,
)
from scale.interface import SimulatedWeightSensor


@pytest.fixture
def conn():
    """A fresh in-memory db for each test, so tests don't interfere with each other"""
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_near_empty_quantity_rounds_up(conn):
    item = create_item(conn, name="Flour", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    # 15% of 1000 = 150, no rounding check needed
    assert near_empty_quantity(item) == 150

    item2 = create_item(conn, name="Eggs", quantity_type=QuantityType.COUNT, initial_quantity=12, unit="each")
    # 15% of 12 = 1.8, should ceiling to 2
    assert near_empty_quantity(item2) == 2


def test_is_near_empty_true_at_threshold(conn):
    item = create_item(conn, name="Milk", quantity_type=QuantityType.WEIGHT, initial_quantity=2000, unit="g")
    item = replace(item,current_quantity=300) # exactly at 15% threshold
    assert is_near_empty(item) is True


def test_is_near_empty_false_above_threshold(conn):
    item = create_item(conn, name="Flour", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    item = replace(item, current_quantity=151)
    assert is_near_empty(item) is False


def test_apply_weight_reading_rejects_count_items(conn):
    item = create_item(conn, name="Eggs", quantity_type=QuantityType.COUNT, initial_quantity=12, unit="each")
    sensor = SimulatedWeightSensor(base_weight=100.0, noise=0.0)
    sensor.tare()
    with pytest.raises(ValueError):
        apply_weight_reading(conn, item, sensor)


def test_apply_weight_reading_updates_quantity(conn):
    item = create_item(conn, name="Milk", quantity_type=QuantityType.WEIGHT, initial_quantity=2000, unit="g")
    sensor = SimulatedWeightSensor(base_weight=0.0, noise=0.0)
    sensor.tare()
    sensor.set_simulated_load(1800.0)

    result = apply_weight_reading(conn, item, sensor)
    assert result.item.current_quantity == 1800.0
    assert result.became_near_empty is False
    assert result.became_depleted is False


def test_apply_weight_readings_flags_near_empty(conn):
    item = create_item(conn, name="Flour", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    sensor = SimulatedWeightSensor(base_weight=0.0, noise=0.0)
    sensor.tare()
    sensor.set_simulated_load(100.0)  # below the 150g threshold

    result = apply_weight_reading(conn, item, sensor)
    assert result.became_near_empty is True
    assert result.became_depleted is False


def test_apply_weight_reading_flags_depleted(conn):
    item = create_item(conn, name="Flour", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    sensor = SimulatedWeightSensor(base_weight=0.0, noise=0.0)
    sensor.tare()
    sensor.set_simulated_load(0.0)

    result = apply_weight_reading(conn, item, sensor)
    assert result.became_depleted is True
