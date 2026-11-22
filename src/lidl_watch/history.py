"""Transactional local history, compared to the last reported discount."""

import sqlite3
from decimal import Decimal

from .models import MIN_DISCOUNT, MIN_INCREASE, Alert, Product, WatchError

SCHEMA_VERSION = "1"


def prepare_database(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS products ("
        "id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL, "
        "last_discount TEXT NOT NULL, reference_discount TEXT, "
        "first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)"
    )
    version = db.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
    if version is not None and version[0] != SCHEMA_VERSION:
        raise WatchError(
            "Neznámá verze historie. Soubor historie nemažte; zkontrolujte verzi skriptu."
        )
    db.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version', ?)", (SCHEMA_VERSION,))


def update_history(
    db: sqlite3.Connection,
    products: list[Product],
    checked_at: str,
    min_discount: Decimal = MIN_DISCOUNT,
) -> tuple[bool, list[Alert]]:
    """Stage changes; the caller commits only after successfully writing reports."""
    initial = (
        db.execute("SELECT value FROM metadata WHERE key = 'initialized_at'").fetchone() is None
    )
    alerts = []
    for product in products:
        row = db.execute(
            "SELECT reference_discount FROM products WHERE id = ?", (product.id,)
        ).fetchone()
        reference = Decimal(row[0]) if row and row[0] is not None else None
        qualifies = product.discount > min_discount
        if initial:
            reference = product.discount if qualifies else None
        elif qualifies and (reference is None or reference <= min_discount):
            minimum = format(min_discount.normalize(), "f").replace(".", ",")
            alerts.append(Alert(product, f"Nově nad {minimum} %"))
            reference = product.discount
        elif qualifies and product.discount - reference > MIN_INCREASE:
            alerts.append(Alert(product, "Vyšší sleva", reference))
            reference = product.discount
        db.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, url=excluded.url, "
            "last_discount=excluded.last_discount, reference_discount=excluded.reference_discount, "
            "last_seen=excluded.last_seen",
            (
                product.id,
                product.title,
                product.url,
                str(product.discount),
                str(reference) if reference is not None else None,
                checked_at,
                checked_at,
            ),
        )
    db.execute("INSERT OR IGNORE INTO metadata VALUES ('initialized_at', ?)", (checked_at,))
    db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_check', ?)", (checked_at,))
    alerts.sort(key=lambda a: (-a.product.discount, a.product.title.casefold(), a.product.id))
    return initial, alerts
