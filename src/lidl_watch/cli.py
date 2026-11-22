"""Command-line entrypoint with durable history and complete-run semantics."""

import argparse
import sqlite3
import sys
import webbrowser
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .client import fetch_products
from .history import prepare_database, update_history
from .models import MIN_DISCOUNT, WatchError, number
from .report import money, percent, render_csv, render_html, write_reports

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIRECTORY = ROOT if (ROOT / "lidl_slevy.py").is_file() else Path.cwd()


def discount_argument(value: str) -> Decimal:
    try:
        result = number(value.replace(",", "."), "hranice slevy")
    except WatchError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not 0 <= result < 100:
        raise argparse.ArgumentTypeError("Hranice slevy musí být od 0 do méně než 100 %.")
    return result


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nové slevy Lidl.cz; opakovaně pouze při zvýšení o více než 15 p. b."
    )
    parser.add_argument(
        "--min-discount",
        type=discount_argument,
        default=MIN_DISCOUNT,
        metavar="PROCENT",
        help="Minimální sleva v procentech (výchozí: 35); zobrazí se jen vyšší slevy.",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_DIRECTORY / "data" / "history.sqlite3",
        help="Soubor historie SQLite.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_DIRECTORY / "reports" / "slevy.html",
        help="Složka a základ názvu pro HTML a CSV. K názvu se přidá datum a čas.",
    )
    parser.add_argument(
        "--open", action="store_true", help="Po kontrole otevřít přehled v prohlížeči."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Vytvořit přehled bez změny historie."
    )
    options = parser.parse_args(argv)
    options.state = options.state.expanduser().resolve()
    options.output = options.output.expanduser().resolve()
    if options.output.suffix.lower() != ".html":
        parser.error("--output musí končit příponou .html")
    if options.state in (options.output, options.output.with_suffix(".csv")):
        parser.error("Historie a přehled musí používat rozdílné soubory.")
    return options


def save_run(
    db: sqlite3.Connection,
    products: list,
    output: Path,
    checked_at: str,
    dry_run: bool,
    min_discount: Decimal = MIN_DISCOUNT,
):
    # Serialize comparison and reporting, even when two scans finish concurrently.
    db.execute("BEGIN IMMEDIATE")
    try:
        prepare_database(db)
        initial, alerts = update_history(db, products, checked_at, min_discount)
        output = write_reports(
            output,
            render_html(alerts, initial, len(products), checked_at, min_discount),
            render_csv(alerts),
        )
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return initial, alerts, output
    except BaseException:
        db.rollback()
        raise


def main(argv: list[str] | None = None) -> int:
    options = arguments(argv)
    try:
        print(
            f"Načítám nabídky Lidl.cz se slevou nad {percent(options.min_discount)} %…", flush=True
        )
        products = fetch_products(
            min_discount=options.min_discount,
            progress=lambda message: print(message, flush=True),
        )
        finished_at = datetime.now().astimezone()
        checked_at = finished_at.isoformat(timespec="seconds")
        timestamp = finished_at.strftime("%Y-%m-%d_%H-%M-%S")
        output = options.output.with_stem(f"{options.output.stem}-{timestamp}")
        # A dry run uses an in-memory copy, leaving even a missing state path untouched.
        if options.dry_run:
            db = sqlite3.connect(":memory:", isolation_level=None)
            if options.state.exists():
                with sqlite3.connect(options.state.as_uri() + "?mode=ro", uri=True) as source:
                    source.backup(db)
        else:
            options.state.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(options.state, timeout=30, isolation_level=None)
        try:
            initial, alerts, output = save_run(
                db, products, output, checked_at, options.dry_run, options.min_discount
            )
        finally:
            db.close()
        if options.dry_run:
            print("Zkušební běh: historie nebyla změněna.")
        if initial:
            if options.dry_run:
                print(f"Náhled prvního běhu: {len(products)} produktů, žádné novinky.")
            else:
                print(
                    f"Výchozí stav: {len(products)} produktů označeno jako již viděné. Novinky: 0."
                )
        else:
            print(f"\nNové nebo výrazně zlevněné produkty: {len(alerts)}")
            for alert in alerts:
                product = alert.product
                print(
                    f"\n−{percent(product.discount)} % | {money(product.price, product.currency)} | {product.title}"
                )
                if alert.previous_discount is not None:
                    print(
                        f"  Dříve {percent(alert.previous_discount)} %, nyní +{percent(product.discount - alert.previous_discount)} p. b."
                    )
                print(f"  {product.url}")
        print(f"\nPřehled: {output}")
        print(f"CSV:     {output.with_suffix('.csv')}")
        if not options.dry_run:
            print(f"Historie: {options.state}")
        if options.open:
            try:
                if not webbrowser.open(output.as_uri()):
                    print(
                        "Prohlížeč se nepodařilo otevřít; přehled otevřete ručně.", file=sys.stderr
                    )
            except webbrowser.Error as exc:
                print(f"Přehled otevřete ručně: {exc}", file=sys.stderr)
        return 0
    except (WatchError, OSError, sqlite3.Error) as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nKontrola přerušena. Historie nebyla změněna.", file=sys.stderr)
        return 130
