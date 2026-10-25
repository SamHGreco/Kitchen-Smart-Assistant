"""
Tests the inventory <-> product_id integration without needing: a real
scanner (FakeScanner stands in), a real scale (SimulatedWeightSensor, the
existing scale stub from scale.interface), or Bobby's real catalog.sqlite
(the `database` fixture builds a throwaway one - the real file lives
outside git per .gitignore and isn't on this machine).
"""

import sqlite3

import pytest

from inventory.barcode_integration import scan_and_add_item
from inventory.inventory_db import get_connection, init_db
from product_id.product_database import Product, ProductDatabase
from scale.interface import SimulatedWeightSensor

# Valid EAN/UPC-style codes (correct check digit) used as test barcodes.
KNOWN_BARCODE = "00000000000017"      # seeded into the fake catalog below
UNKNOWN_BARCODE = "00000000000024"    # well-formed, not in the catalog
FALLBACK_BARCODE = "00000000000031"   # well-formed, not in the catalog


class FakeScanner:
    """Stands in for product_id.barcode_reader.AtomicBarcodeReader until
    the real scanner hardware is wired up. `queue` holds one return value
    per expected scan_once() call, in order (use None for "nothing
    scanned / timed out")."""

    def __init__(self, queue):
        self._queue = list(queue)

    def scan_once(self, timeout: float = 10.0, cancel=None):
        return self._queue.pop(0)


@pytest.fixture
def conn():
    """Fresh in-memory inventory database for each test."""
    connection = get_connection(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def sensor():
    """The scale stub: reports a fixed weight with no noise, no hardware
    required. Same class the manual_test_harness already uses for
    simulated-mode runs."""
    sim = SimulatedWeightSensor(base_weight=0.0, noise=0.0)
    sim.tare()
    sim.set_simulated_load(368.0)
    return sim


@pytest.fixture
def database(tmp_path):
    """A throwaway catalog + local products DB standing in for Bobby's
    real catalog.sqlite. Schema matches what
    product_database.validate_catalog expects: an `items` table with
    TEXT columns (including item_weight, stored as text and parsed back
    to float by product_database._catalog_weight)."""
    catalog_path = tmp_path / "catalog.sqlite"
    catalog_conn = sqlite3.connect(catalog_path)
    catalog_conn.execute(
        "CREATE TABLE items ("
        "item_upc TEXT, brand_name TEXT, item_name TEXT, "
        "item_weight TEXT, item_category TEXT)"
    )
    catalog_conn.execute(
        "INSERT INTO items VALUES (?, ?, ?, ?, ?)",
        (KNOWN_BARCODE, "Store Brand", "Whole Milk", "946", "Dairy"),
    )
    catalog_conn.commit()
    catalog_conn.close()

    products_path = tmp_path / "barcodes.db"
    with ProductDatabase(catalog_path, products_path) as db:
        yield db


def test_scan_known_barcode_creates_item(conn, sensor, database):
    scanner = FakeScanner([KNOWN_BARCODE])

    item = scan_and_add_item(conn, sensor, scanner, database)

    assert item is not None
    assert item.name == "Whole Milk"
    assert item.category == "Dairy"
    assert item.barcode == KNOWN_BARCODE
    assert item.current_quantity == 368.0


def test_unknown_barcode_without_fallback_returns_none(conn, sensor, database):
    scanner = FakeScanner([UNKNOWN_BARCODE])

    item = scan_and_add_item(conn, sensor, scanner, database)

    assert item is None


def test_unknown_barcode_with_fallback_saves_and_creates(conn, sensor, database):
    scanner = FakeScanner([FALLBACK_BARCODE])

    def manual_entry(barcode):
        return Product(
            item_upc=barcode,
            brand_name="Generic",
            item_name="Rice",
            item_weight=None,
            item_category="Pantry",
        )

    item = scan_and_add_item(
        conn, sensor, scanner, database, on_not_found=manual_entry
    )

    assert item is not None
    assert item.name == "Rice"
    # Manual entry gets saved to the local products DB, so next scan of
    # this barcode will be a known-product hit instead of another fallback.
    assert database.find_product(FALLBACK_BARCODE) is not None


def test_scan_timeout_returns_none(conn, sensor, database):
    scanner = FakeScanner([None])

    assert scan_and_add_item(conn, sensor, scanner, database) is None
