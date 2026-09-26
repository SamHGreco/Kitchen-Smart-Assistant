import pytest

from app.shared.models import QuantityType, ItemStatus
from inventory.inventory_db import get_connection, init_db, create_item, get_item, update_quantity, delete_item


@pytest.fixture
def conn():
    """A fresh in-memory database for each test, so tests don't interfere with each other."""
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


def test_create_item_sets_defaults(conn):
    item = create_item(conn, name="Milk", quantity_type=QuantityType.WEIGHT, initial_quantity=1000, unit="g")
    assert item.current_quantity == 1000
    assert item.initial_quantity == 1000
    assert item.status == ItemStatus.ACTIVE


def test_update_quantity_marks_depleted_at_zero(conn):
    item = create_item(conn, name="Eggs", quantity_type=QuantityType.COUNT, initial_quantity=12, unit="each")
    updated = update_quantity(conn, item.item_id, 0)
    assert updated.status == ItemStatus.DEPLETED


def test_delete_item_removes_it(conn):
    item = create_item(conn, name="Bread", quantity_type=QuantityType.COUNT, initial_quantity=1, unit="each")
    delete_item(conn, item.item_id)
    assert get_item(conn, item.item_id) is None