import pytest

from app.shared.models import OperationType, QuantityType
from inventory.inventory_db import (
    get_connection, init_db, create_item, update_quantity, update_location,
    delete_item, get_item_history, get_all_history,
)


@pytest.fixture
def conn():
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_create_item_logs_added(conn):
    item = create_item(conn, name="Milk", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    history = get_item_history(conn, item.item_id)
    assert len(history) == 1
    assert history[0].operation_type == OperationType.ADDED
    assert history[0].quantity_after == 1000
    assert history[0].location_after == "pantry"


def test_update_quantity_logs_before_and_after(conn):
    item = create_item(conn, name="Milk", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    update_quantity(conn, item.item_id, 400)
    history = get_item_history(conn, item.item_id)
    assert history[0].operation_type == OperationType.QUANTITY_UPDATED
    assert history[0].quantity_before == 1000
    assert history[0].quantity_after == 400


def test_update_location_logs_before_and_after(conn):
    item = create_item(
        conn, name="Milk", quantity_type=QuantityType.WEIGHT, initial_quantity=1000,
        unit="g", location="pantry",
    )
    update_location(conn, item.item_id, "fridge")
    history = get_item_history(conn, item.item_id)
    assert history[0].operation_type == OperationType.LOCATION_CHANGED
    assert history[0].location_before == "pantry"
    assert history[0].location_after == "fridge"


def test_delete_item_logs_removed_and_survives_deletion(conn):
    item = create_item(conn, name="Eggs", quantity_type=QuantityType.COUNT, initial_quantity=12, unit="each")
    delete_item(conn, item.item_id)

    history = get_item_history(conn, item.item_id)
    assert history[0].operation_type == OperationType.REMOVED
    assert history[0].item_name == "Eggs"
    assert history[0].quantity_before == 12


def test_get_all_history_spans_items_and_respects_limit(conn):
    create_item(conn, name="Milk", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    create_item(conn, name="Eggs", quantity_type=QuantityType.COUNT, initial_quantity=12, unit="each")

    full = get_all_history(conn)
    assert len(full) == 2

    limited = get_all_history(conn, limit=1)
    assert len(limited) == 1
    assert limited[0].item_name == "Eggs"  # newest first