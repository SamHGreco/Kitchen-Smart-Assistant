from datetime import datetime, timedelta

import pytest

from app.shared.models import QuantityType
from inventory.inventory_db import (
    get_connection, init_db, create_item, update_expiration_date
    )
from inventory.expiration import (
    days_until_expiration, is_expired, is_expiring_soon,
    get_expired_items, get_items_expiring_soon
)


@pytest.fixture
def conn():
    """A fresh in-memory database for each test, so tests don't interfere with each other."""
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


NOW = datetime(2026, 10, 4)


def test_no_expiration_date_is_never_flagged(conn):
    item = create_item(
        conn, name="Rice", quantity_type=QuantityType.WEIGHT, 
        initial_quantity=2000, unit="g"
    )
    assert days_until_expiration(item, as_of=NOW) is None
    assert is_expired(item, as_of=NOW) is False
    assert is_expiring_soon(item, as_of=NOW) is False


def test_future_expiration_not_yet_expiring_soon(conn):
    item = create_item(
        conn, name="Milk", quantity_type=QuantityType.WEIGHT, 
        initial_quantity=1000, unit="g", 
        expiration_date=NOW + timedelta(days=10),
    )
    assert days_until_expiration(item, as_of=NOW) == 10
    assert is_expired(item, as_of=NOW) is False
    assert is_expiring_soon(item, as_of=NOW) is False



def test_expiration_within_window_is_expiring_soon(conn):
    item = create_item(
        conn, name="Eggs", quantity_type=QuantityType.COUNT,
        initial_quantity=12, unit="each",
        expiration_date=NOW + timedelta(days=2),
    )
    assert is_expiring_soon(item, within_days=3, as_of=NOW) is True
    assert is_expired(item, as_of=NOW) is False


def test_past_expiration_is_expired_not_expiring_soon(conn):
    item = create_item(
        conn, name="Leftovers", quantity_type=QuantityType.COUNT,
        initial_quantity=1, unit="container",
        expiration_date=NOW - timedelta(days=1),
    )
    assert is_expired(item, as_of=NOW) is True
    assert is_expiring_soon(item, as_of=NOW) is False


def test_get_expired_items_filters_correctly(conn):
    create_item(
        conn, name="Old Bread", quantity_type=QuantityType.WEIGHT,
        initial_quantity=1000, unit="g",
        expiration_date=NOW - timedelta(days=3),
    )
    create_item(
        conn, name="Fresh Bread", quantity_type=QuantityType.WEIGHT,
        initial_quantity=1000, unit="g",
        expiration_date=NOW + timedelta(days=5),
    )
    expired = get_expired_items(conn, as_of=NOW)
    assert [item.name for item in expired] == ["Old Bread"]
    

def test_get_items_expiring_soon_excludes_already_expired(conn):
    create_item(
        conn, name="Expired Cheese", quantity_type=QuantityType.WEIGHT, 
        initial_quantity=300, unit="g", 
        expiration_date=NOW - timedelta(days=1),
    )
    create_item(
        conn, name="Soon Cheese", quantity_type=QuantityType.WEIGHT, 
        initial_quantity=100, unit="g",
        expiration_date=NOW + timedelta(days=1),
    )
    expiring = get_items_expiring_soon(conn, within_days=3, as_of=NOW)
    assert [item.name for item in expiring] == ["Soon Cheese"]


def test_update_expiration_date_changes_the_stored_value(conn):
    item = create_item(
        conn, name="Sauce", quantity_type=QuantityType.COUNT, 
        initial_quantity=1, unit="jar"
        )
    updated = update_expiration_date(conn, item.item_id, NOW + timedelta(days=60))
    assert updated.expiration_date == NOW + timedelta(days=60)