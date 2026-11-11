"""Read discounted products in server order, stopping below the selected threshold."""

import json
import time
from collections.abc import Callable
from decimal import Decimal
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import BASE_URL, MIN_DISCOUNT, Product, WatchError, parse_product

API_URL = BASE_URL + "/q/api/query/slevy"
PAGE_SIZE = 60


def page_url(offset: int) -> str:
    params = [
        ("assortment", "CZ"),
        ("locale", "cs_CZ"),
        ("version", "2.1.0"),
        ("sort", "percentageDiscount-desc"),
        ("availabilityIndicator", "2"),
        ("availabilityIndicator", "3"),
        ("online", "1"),
        ("discountFlag", "1"),
        ("offset", str(offset)),
        ("fetchsize", str(PAGE_SIZE)),
        ("idsOnly", "false"),
        ("productsOnly", "false"),
    ]
    return API_URL + "?" + urlencode(params)


def download_page(offset: int) -> dict:
    request = Request(
        page_url(offset),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; LidlDiscountWatcher/1.0)",
            "Accept": "application/mindshift.search+json;version=2",
            "Accept-Language": "cs-CZ,cs;q=0.9",
        },
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=45) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise WatchError("Lidl nevrátil očekávaný JSON objekt.")
            return payload
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise WatchError(
                    f"Lidl vrátil HTTP {exc.code}. Historie nebyla změněna; zkuste to později."
                ) from exc
            retry_after = exc.headers.get("Retry-After", "")
            delay = min(60, int(retry_after)) if retry_after.isdigit() else 2 ** (attempt + 1)
            time.sleep(delay)
        except (URLError, TimeoutError, ConnectionError, OSError, HTTPException) as exc:
            if attempt == 2:
                raise WatchError(f"Nepodařilo se spojit s Lidl.cz: {exc}") from exc
            time.sleep(2 ** (attempt + 1))
        except (ValueError, UnicodeError) as exc:
            raise WatchError("Lidl nevrátil platný JSON. Historie nebyla změněna.") from exc
    raise WatchError("Načítání se nepodařilo dokončit.")


def fetch_products(
    fetch_page: Callable[[int], dict] = download_page,
    progress: Callable[[str], None] = print,
    pause: Callable[[float], None] = time.sleep,
    *,
    min_discount: Decimal = MIN_DISCOUNT,
) -> list[Product]:
    products: dict[str, Product] = {}
    page_fingerprints: set[tuple[str, ...]] = set()
    offset = 0
    total = None
    window = None
    while True:
        page = fetch_page(offset)
        count = page.get("numFound")
        step = page.get("fetchsize")
        returned_offset = page.get("offset")
        items = page.get("items")
        if (
            type(count) is not int
            or not 0 < count <= 100_000
            or type(step) is not int
            or not 0 < step <= 1000
            or (window is not None and step != window)
            or type(returned_offset) is not int
            or returned_offset != offset
            or not isinstance(items, list)
            or len(items) > step
        ):
            raise WatchError(
                f"Neúplná nebo změněná odpověď Lidl.cz (offset {offset}). Historie nebyla změněna."
            )
        if total is not None and count != total:
            progress(f"Počet nabídek se změnil ({total} → {count}); pokračuji.")
        total, window = count, step
        if not items:
            if offset >= count and products:
                break
            raise WatchError("Chybí stránka produktů. Historie nebyla změněna.")
        page_ids = []
        reached_minimum = False
        for item in items:
            if not isinstance(item, dict) or item.get("type") != "product":
                raise WatchError("Neočekávaná položka ve výpisu Lidl.cz.")
            product = parse_product(item)
            page_ids.append(product.id)
            previous = products.get(product.id)
            if previous is None or product.discount > previous.discount:
                products[product.id] = product
            # Promoted daily deals precede the ordinary descending list, in any quantity.
            if not product.daily_deal and product.discount <= min_discount:
                reached_minimum = True
                break
        fingerprint = tuple(page_ids)
        if fingerprint in page_fingerprints:
            raise WatchError("Lidl opakuje stejnou stránku. Historie nebyla změněna.")
        page_fingerprints.add(fingerprint)
        # Collapsed variants can shorten items; advance by the server's window.
        offset += step
        progress(f"Načteno {min(offset, total)}/{total} pozic, {len(products)} produktů.")
        if reached_minimum:
            progress(f"Dosažena hranice {min_discount} %; další stránky nenačítám.")
            break
        if offset >= total:
            break
        pause(0.5)
    return list(products.values())
