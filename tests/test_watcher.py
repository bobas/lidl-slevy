"""Behavioral regression tests; no internet connection required."""

import copy
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lidl_watch.cli import arguments, main, save_run
from lidl_watch.client import download_page, fetch_products, page_url
from lidl_watch.history import prepare_database, update_history
from lidl_watch.models import Alert, Product, WatchError, parse_product
from lidl_watch.report import atomic_write, render_csv, render_html

FIXTURE = Path(__file__).parent / "fixtures" / "search_page.json"


def product(identifier="10001", discount="40", title="Testovací produkt"):
    return Product(
        identifier,
        title,
        f"https://www.lidl.cz/p/test/p{identifier}",
        Decimal(discount),
        Decimal("119.90"),
        Decimal("199"),
        "CZK",
    )


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.execute("BEGIN")
        prepare_database(self.db)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def run_scan(self, products, min_discount="35"):
        self.db.execute("BEGIN")
        result = update_history(
            self.db, products, "2026-11-07T23:00:00+01:00", Decimal(min_discount)
        )
        self.db.commit()
        return result

    def test_initial_scan_suppresses_every_existing_offer(self):
        initial, alerts = self.run_scan([product(discount="80"), product("10002", "35")])
        self.assertTrue(initial)
        self.assertEqual(alerts, [])
        self.assertEqual(self.run_scan([product(discount="80")]), (False, []))

    def test_new_product_requires_strictly_more_than_35(self):
        self.run_scan([product()])
        _, alerts = self.run_scan([product("10002", "35"), product("10003", "35.1")])
        self.assertEqual([a.product.id for a in alerts], ["10003"])

    def test_crossing_threshold_is_a_new_qualifying_offer(self):
        self.run_scan([product(discount="30")])
        self.assertEqual(len(self.run_scan([product(discount="36")])[1]), 1)
        self.assertEqual(self.run_scan([product(discount="36")])[1], [])

    def test_increase_must_be_strictly_more_than_15_points(self):
        self.run_scan([product(discount="40")])
        self.assertEqual(self.run_scan([product(discount="55")])[1], [])
        alerts = self.run_scan([product(discount="55.1")])[1]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].previous_discount, Decimal("40"))

    def test_small_increases_accumulate_against_last_report(self):
        self.run_scan([product(discount="40")])
        self.assertEqual(self.run_scan([product(discount="50")])[1], [])
        self.assertEqual(len(self.run_scan([product(discount="56")])[1]), 1)
        self.assertEqual(self.run_scan([product(discount="60")])[1], [])
        self.assertEqual(len(self.run_scan([product(discount="72")])[1]), 1)

    def test_fall_and_return_does_not_repeat_seen_offer(self):
        self.run_scan([product(discount="60")])
        self.run_scan([product(discount="20")])
        self.assertEqual(self.run_scan([product(discount="60")])[1], [])

    def test_disappearing_product_is_remembered(self):
        self.run_scan([product()])
        self.run_scan([product("10002")])
        self.assertEqual(self.run_scan([product()])[1], [])

    def test_relative_15_percent_is_not_15_percentage_points(self):
        self.run_scan([product(discount="40")])
        self.assertEqual(self.run_scan([product(discount="47")])[1], [])

    def test_alerts_are_sorted_by_discount(self):
        self.run_scan([product()])
        alerts = self.run_scan([product("10002", "36"), product("10003", "80")])[1]
        self.assertEqual([a.product.id for a in alerts], ["10003", "10002"])

    def test_custom_threshold_filters_new_offers_and_reason(self):
        self.run_scan([product(discount="60")], "50")
        alerts = self.run_scan(
            [product("10002", "49"), product("10003", "50"), product("10004", "50.1")],
            "50",
        )[1]
        self.assertEqual([a.product.id for a in alerts], ["10004"])
        self.assertEqual(alerts[0].reason, "Nově nad 50 %")

    def test_raising_threshold_still_recognizes_first_crossing(self):
        self.run_scan([product(discount="40")])
        alerts = self.run_scan([product(discount="51")], "50")[1]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].reason, "Nově nad 50 %")

    def test_lowering_threshold_keeps_previously_seen_offers_acknowledged(self):
        self.run_scan([product(discount="70")], "50")
        self.assertEqual(self.run_scan([product(discount="70")], "20")[1], [])

    def test_increase_rule_is_unchanged_with_custom_threshold(self):
        self.run_scan([product(discount="60")], "50")
        self.assertEqual(self.run_scan([product(discount="75")], "50")[1], [])
        self.assertEqual(len(self.run_scan([product(discount="76")], "50")[1]), 1)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.page = json.loads(FIXTURE.read_text())

    def fetch(self, pages, min_discount="35"):
        offsets = []

        def get_page(offset):
            offsets.append(offset)
            return pages[offset]

        result = fetch_products(
            get_page,
            progress=lambda _: None,
            pause=lambda _: None,
            min_discount=Decimal(min_discount),
        )
        return result, offsets

    def item(self, identifier, discount, daily=False):
        item = copy.deepcopy(self.page["items"][0])
        data = item["gridbox"]["data"]
        item["code"] = str(identifier)
        data["productId"] = identifier
        data["price"]["discount"]["percentageDiscount"] = discount
        data["dealOfDay"] = {"active": daily}
        return item

    def test_real_storefront_fixture(self):
        products, _ = self.fetch({0: self.page})
        self.assertEqual(len(products), 2)
        parkside = next(p for p in products if p.id == "100386322")
        self.assertEqual(parkside.discount, Decimal("46"))
        self.assertEqual(parkside.price, Decimal("239.9"))
        self.assertIn("PARKSIDE", parkside.title)
        self.assertTrue(parkside.daily_deal)

    def test_short_page_uses_server_window_and_does_not_stop_early(self):
        first = copy.deepcopy(self.page)
        first.update(numFound=5, fetchsize=3)
        first["items"][0]["gridbox"]["data"]["price"]["discount"]["percentageDiscount"] = 20
        second = copy.deepcopy(self.page)
        second.update(numFound=5, fetchsize=3, offset=3)
        second["items"] = second["items"][:1]
        second["items"][0]["code"] = "19999"
        second["items"][0]["gridbox"]["data"]["productId"] = 19999
        second["items"][0]["gridbox"]["data"]["price"]["discount"]["percentageDiscount"] = 90
        products, offsets = self.fetch({0: first, 3: second})
        self.assertEqual(offsets, [0, 3])
        self.assertEqual(products[-1].discount, Decimal("90"))
        self.assertEqual(len(products), 3)

    def test_stops_at_equal_or_lower_ordinary_discount_without_prefetch(self):
        for cutoff in [35, 34]:
            with self.subTest(cutoff=cutoff):
                first = dict(
                    self.page,
                    numFound=5,
                    fetchsize=2,
                    items=[
                        self.item(10001, 80),
                        self.item(10002, cutoff),
                    ],
                )
                _, offsets = self.fetch({0: first})
                self.assertEqual(offsets, [0])

    def test_daily_deals_below_threshold_do_not_end_scan_in_any_quantity(self):
        for count in [1, 5, 7]:
            with self.subTest(count=count):
                items = [self.item(10000 + i, 20, daily=True) for i in range(count)]
                items += [self.item(20001, 80), self.item(20002, 35), self.item(20003, 30)]
                pages = {
                    offset: dict(
                        self.page,
                        numFound=len(items),
                        fetchsize=3,
                        offset=offset,
                        items=items[offset : offset + 3],
                    )
                    for offset in range(0, len(items), 3)
                }
                products, offsets = self.fetch(pages)
                self.assertIn("20001", [p.id for p in products])
                self.assertNotIn("20003", [p.id for p in products])
                self.assertEqual(offsets[-1], ((count + 1) // 3) * 3)

    def test_custom_minimum_controls_how_many_pages_are_requested(self):
        first = dict(self.page, numFound=2, fetchsize=1, items=[self.item(10001, 40)])
        second = dict(first, offset=1, items=[self.item(10002, 30)])
        self.assertEqual(self.fetch({0: first}, "50")[1], [0])
        self.assertEqual(self.fetch({0: first, 1: second}, "35")[1], [0, 1])

    def test_eligible_daily_deals_are_included_even_when_ordinary_list_is_below_limit(self):
        first = dict(
            self.page,
            numFound=5,
            fetchsize=3,
            items=[
                self.item(10001, 20, daily=True),
                self.item(10002, 60, daily=True),
                self.item(10003, 40),
            ],
        )
        products, offsets = self.fetch({0: first}, "50")
        self.assertEqual(offsets, [0])
        self.assertIn("10002", [p.id for p in products])

    def test_same_product_id_uses_highest_discount(self):
        duplicate = copy.deepcopy(self.page["items"][0])
        duplicate["gridbox"]["data"]["price"]["discount"]["percentageDiscount"] = 80
        self.page["items"].append(duplicate)
        self.page["numFound"] = 3
        products, _ = self.fetch({0: self.page})
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].discount, Decimal("80"))

    def test_empty_response_is_not_accepted_as_a_baseline(self):
        self.page.update(numFound=0, items=[])
        with self.assertRaises(WatchError):
            self.fetch({0: self.page})

    def test_incomplete_page_aborts(self):
        self.page["numFound"] = 120
        empty = dict(self.page, offset=60, items=[])
        with self.assertRaises(WatchError):
            self.fetch({0: self.page, 60: empty})

    def test_repeated_page_aborts_instead_of_silently_missing_products(self):
        self.page["numFound"] = 120
        repeated = dict(self.page, offset=60)
        with self.assertRaises(WatchError):
            self.fetch({0: self.page, 60: repeated})

    def test_growing_total_is_followed_to_the_new_end(self):
        self.page.update(numFound=2, fetchsize=1, items=self.page["items"][:1])
        second = copy.deepcopy(self.page)
        second.update(offset=1, numFound=3)
        second["items"][0]["gridbox"]["data"]["productId"] = 19998
        third = copy.deepcopy(second)
        third.update(offset=2)
        third["items"][0]["gridbox"]["data"]["productId"] = 19999
        products, offsets = self.fetch({0: self.page, 1: second, 2: third})
        self.assertEqual(offsets, [0, 1, 2])
        self.assertEqual(len(products), 3)

    def test_shrinking_total_accepts_empty_tail_but_not_missing_middle(self):
        self.page.update(numFound=120)
        tail = dict(self.page, offset=60, numFound=60, items=[])
        products, offsets = self.fetch({0: self.page, 60: tail})
        self.assertEqual(offsets, [0, 60])
        self.assertEqual(len(products), 2)

    def test_changing_window_aborts_instead_of_skipping_results(self):
        self.page.update(numFound=120)
        changed = dict(self.page, offset=60, fetchsize=30)
        with self.assertRaises(WatchError):
            self.fetch({0: self.page, 60: changed})

    def test_wrong_offset_aborts(self):
        self.page["offset"] = 60
        with self.assertRaises(WatchError):
            self.fetch({0: self.page})

    def test_missing_or_invalid_product_data_aborts(self):
        for field, value in [("price", {}), ("canonicalUrl", "https://example.com/p/x")]:
            with self.subTest(field=field):
                item = copy.deepcopy(self.page["items"][0])
                item["gridbox"]["data"][field] = value
                with self.assertRaises(WatchError):
                    parse_product(item)

    def test_both_availability_filters_are_preserved(self):
        query = parse_qs(urlsplit(page_url(60)).query)
        self.assertEqual(query["availabilityIndicator"], ["2", "3"])
        self.assertEqual(query["offset"], ["60"])
        self.assertEqual(query["version"], ["2.1.0"])

    def test_transient_http_error_is_retried(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.StringIO(json.dumps(self.page))
        error = HTTPError("https://www.lidl.cz", 503, "Unavailable", {}, None)
        with patch("lidl_watch.client.urlopen", side_effect=[error, response]) as request:
            with patch("lidl_watch.client.time.sleep"):
                result = download_page(0)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["numFound"], 2)

    def test_access_error_is_reported_without_retries(self):
        error = HTTPError("https://www.lidl.cz", 403, "Forbidden", {}, None)
        with patch("lidl_watch.client.urlopen", side_effect=error) as request:
            with self.assertRaises(WatchError):
                download_page(0)
        self.assertEqual(request.call_count, 1)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "history.sqlite3"
        self.output_base = self.root / "slevy.html"
        self.output = self.output_base

    def scan(self, products, dry_run=False, min_discount=None, open_report=False):
        args = ["--state", str(self.state), "--output", str(self.output_base)]
        if dry_run:
            args.append("--dry-run")
        if min_discount is not None:
            args.extend(["--min-discount", min_discount])
        if open_report:
            args.append("--open")
        with patch("lidl_watch.cli.fetch_products", return_value=products):
            with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
                result = main(args)
        if result == 0:
            report_line = next(
                line for line in stdout.getvalue().splitlines() if line.startswith("Přehled: ")
            )
            self.output = Path(report_line.removeprefix("Přehled: "))
        return result

    def test_initial_and_subsequent_processes_persist_seen_offers(self):
        self.assertEqual(self.scan([product()]), 0)
        self.assertIn("Výchozí stav je uložený", self.output.read_text())
        self.assertEqual(self.scan([product(), product("10002", "70")]), 0)
        self.assertIn("−70 %", self.output.read_text())
        self.assertEqual(self.scan([product(), product("10002", "70")]), 0)
        self.assertIn("Žádné nové produkty", self.output.read_text())

    def test_dry_run_does_not_acknowledge_new_offers(self):
        self.scan([product()])
        before = self.state.read_bytes()
        self.assertEqual(self.scan([product("10002", "70")], dry_run=True), 0)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertIn("−70 %", self.output.read_text())
        self.scan([product("10002", "70")])
        self.assertIn("−70 %", self.output.read_text())

    def test_first_dry_run_does_not_create_state(self):
        self.assertEqual(self.scan([product()], dry_run=True), 0)
        self.assertFalse(self.state.exists())

    def test_same_second_reports_keep_older_files_and_open_newest(self):
        legacy_report = self.root / "latest.html"
        legacy_report.write_text("Starší přehled")
        with (
            patch("lidl_watch.cli.datetime") as clock,
            patch("lidl_watch.cli.webbrowser.open", return_value=True) as browser,
        ):
            clock.now.return_value = datetime(2026, 11, 9, 18, 42, 7)
            self.assertEqual(self.scan([product()]), 0)
            first = self.output
            first_html = first.read_bytes()
            first_csv = first.with_suffix(".csv").read_bytes()
            self.assertEqual(self.scan([product("10002", "70")], open_report=True), 0)

        self.assertEqual(first.name, "slevy-2026-11-09_18-42-07.html")
        self.assertEqual(self.output.name, "slevy-2026-11-09_18-42-07-2.html")
        self.assertIn("−70 %", self.output.read_text())
        self.assertIn(";70;", self.output.with_suffix(".csv").read_text(encoding="utf-8-sig"))
        self.assertEqual(first.read_bytes(), first_html)
        self.assertEqual(first.with_suffix(".csv").read_bytes(), first_csv)
        self.assertEqual(legacy_report.read_text(), "Starší přehled")
        browser.assert_called_once_with(self.output.as_uri())

    def test_report_write_failure_rolls_back_history(self):
        self.scan([product()])
        db = sqlite3.connect(self.state, isolation_level=None)
        self.addCleanup(db.close)
        failed_report = self.root / "failed.html"

        def fail_on_html(path, content):
            if path.suffix == ".html":
                raise OSError("Disk full")
            atomic_write(path, content)

        with patch("lidl_watch.report.atomic_write", side_effect=fail_on_html):
            with self.assertRaises(OSError):
                save_run(db, [product("10002", "70")], failed_report, "later", False)
        self.assertEqual(db.execute("SELECT count(*) FROM products").fetchone()[0], 1)
        self.assertFalse(failed_report.with_suffix(".csv").exists())
        self.scan([product("10002", "70")])
        self.assertIn("−70 %", self.output.read_text())

    def test_download_failure_preserves_state_and_previous_report(self):
        self.scan([product()])
        before_state = self.state.read_bytes()
        before_report = self.output.read_bytes()
        with patch("lidl_watch.cli.fetch_products", side_effect=WatchError("Network failed")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = main(["--state", str(self.state), "--output", str(self.output_base)])
        self.assertEqual(result, 1)
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.output.read_bytes(), before_report)

    def test_corrupted_database_is_not_replaced(self):
        self.state.write_text("not a database")
        self.assertEqual(self.scan([product()]), 1)
        self.assertEqual(self.state.read_text(), "not a database")

    def test_reports_escape_product_text_and_csv_formulas(self):
        p = product(title='=SUM(1) <script>alert("x")</script>')
        alerts = [Alert(p, "Nově nad 35 %")]
        html = render_html(alerts, False, 1, "now")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        csv = render_csv(alerts)
        self.assertIn("'=SUM", csv)

    def test_report_shows_server_image_beside_product_link_when_available(self):
        items = json.loads(FIXTURE.read_text())["items"]
        products = [parse_product(item) for item in items]
        self.assertEqual(self.scan([product()]), 0)
        self.assertEqual(self.scan(products), 0)
        report = self.output.read_text()
        image_url = items[0]["gridbox"]["data"]["image"]
        self.assertIn(f'src="{image_url}"', report)
        self.assertIn("img-src https://www.lidl.cz/assets/", report)
        self.assertEqual(report.count('<img class="product-image"'), 1)
        for offer in products:
            self.assertIn(f'href="{offer.url}"', report)

    def test_custom_threshold_flows_to_history_and_report(self):
        self.scan([product(discount="60")], min_discount="50")
        self.scan([product("10002", "45"), product("10003", "51")], min_discount="50")
        report = self.output.read_text()
        self.assertIn("nad 50 %", report)
        self.assertIn("−51 %", report)
        self.assertNotIn("−45 %", report)
        self.assertNotIn("nad 35 %", report)

    def test_default_and_decimal_threshold_arguments(self):
        self.assertEqual(arguments([]).min_discount, Decimal("35"))
        self.assertEqual(arguments(["--min-discount", "42,5"]).min_discount, Decimal("42.5"))
        self.assertEqual(arguments(["--min-discount", "0"]).min_discount, Decimal("0"))

    def test_invalid_thresholds_fail_before_downloading(self):
        for value in ["-1", "100", "101", "NaN", "Infinity", "abc"]:
            with self.subTest(value=value), redirect_stderr(io.StringIO()):
                with patch("lidl_watch.cli.fetch_products") as fetch:
                    with self.assertRaises(SystemExit) as exc:
                        main(["--min-discount", value])
                    self.assertEqual(exc.exception.code, 2)
                    fetch.assert_not_called()

    def test_custom_threshold_is_passed_to_downloader(self):
        with patch("lidl_watch.cli.fetch_products", return_value=[product()]) as fetch:
            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "--min-discount",
                        "42.5",
                        "--dry-run",
                        "--state",
                        str(self.state),
                        "--output",
                        str(self.output_base),
                    ]
                )
        self.assertEqual(result, 0)
        self.assertEqual(fetch.call_args.kwargs["min_discount"], Decimal("42.5"))


if __name__ == "__main__":
    unittest.main()
