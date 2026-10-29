"""
Bridges the barcode/product-catalog subsystem (src/product_id, owned by
Bobby, uploaded/integrated by Sam on the ID-UI-Enviro-Integration branch)
to inventory creation (inventory.weight_logic).

This module only ever *calls into* product_id - it never modifies it.
Scanning and lookup are kept as separate steps, composed by
scan_and_add_item(), so each piece can be tested or swapped independently
(e.g. a fake scanner in tests, or a real AtomicBarcodeReader once the
hardware is wired up).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from inventory.weight_logic import create_item_with_weight
from product_id.product_database import Product, ProductDatabase


class BarcodeScanner(Protocol):
    """What this module needs from a scanner. AtomicBarcodeReader satisfies
    this already; a test double just needs to match the shape."""

    def scan_once(self, timeout: float = 10.0, cancel: object | None = None) -> str | None:
        ...


def scan_barcode(reader: BarcodeScanner, timeout: float = 10.0) -> str | None:
    """
    Thin wrapper around reader.scan_once(). Returns None for "nothing
    scanned in time," same as scan_once itself - callers treat that as
    "no scan happened," not an error. Real scanner/protocol problems
    (ScannerError and friends) are not caught here; let those surface,
    since they mean something is actually wrong with the hardware.
    """
    return reader.scan_once(timeout=timeout)


def lookup_product(database: ProductDatabase, barcode: str) -> Product | None:
    """
    Looks up a scanned barcode in Bobby's product database (local
    barcodes.db first, then the read-only catalog). Returns None if the
    barcode is well-formed but not found anywhere, so the caller can fall
    back to manual entry. A malformed barcode raises BarcodeError (from
    product_id.product_database) - let that propagate, it means the scan
    itself is suspect.
    """
    return database.find_product(barcode)


def create_item_from_product(
    conn,
    sensor,
    product: Product,
    *,
    expiration_date: datetime | None = None,
    location: str = "pantry",
):
    """
    Creates a weight-tracked inventory item from a looked-up Product,
    using the sensor's current settled reading as the initial quantity.
    unit is always "g": product_database.py stores and validates all
    product weights in grams, so there is nothing else it could be here.
    """
    return create_item_with_weight(
        conn,
        sensor,
        name=product.item_name,
        unit="g",
        barcode=product.item_upc,
        brand_name=product.brand_name,
        category=product.item_category,
        expiration_date=expiration_date,
        location=location,
    )


def scan_and_add_item(
    conn,
    sensor,
    reader: BarcodeScanner,
    database: ProductDatabase,
    *,
    on_not_found: Callable[[str], Product | None] | None = None,
    expiration_date: datetime | None = None,
    location: str = "pantry",
    timeout: float = 10.0,
):
    """
    Full scan -> lookup -> create flow.

    on_not_found(barcode) is called when the scanned barcode isn't in the
    database. It should return a Product to save and use (e.g. built from
    manual entry), or None to abandon the scan. If on_not_found is
    omitted, an unmatched barcode just returns None - caller decides how
    to prompt for manual entry, this function doesn't assume a UI.

    Returns the created InventoryItem, or None if nothing was scanned or
    the item was abandoned.
    """
    barcode = scan_barcode(reader, timeout=timeout)
    if barcode is None:
        return None

    product = lookup_product(database, barcode)
    if product is None:
        if on_not_found is None:
            return None
        product = on_not_found(barcode)
        if product is None:
            return None
        product = database.save_product(product)

    return create_item_from_product(
        conn, sensor, product, expiration_date=expiration_date, location=location
    )
