"""Validated product data shared by the downloader, history, and reports."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

MIN_DISCOUNT = Decimal("35")
MIN_INCREASE = Decimal("15")
BASE_URL = "https://www.lidl.cz"
LISTING_URL = (
    BASE_URL + "/q/query/slevy?sort=percentageDiscount-desc"
    "&availabilityIndicator=2&availabilityIndicator=3&online=1&discountFlag=1"
)


class WatchError(Exception):
    """An incomplete or unsafe run that must not update history."""


def number(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise WatchError(f"Neplatné číslo {label}: {value!r}") from exc
    if not result.is_finite():
        raise WatchError(f"Neplatné číslo {label}: {value!r}")
    return result


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    url: str
    discount: Decimal
    price: Decimal
    old_price: Decimal | None
    currency: str
    daily_deal: bool = False
    image_url: str | None = None


@dataclass(frozen=True)
class Alert:
    product: Product
    reason: str
    previous_discount: Decimal | None = None


def parse_product(item: dict) -> Product:
    """Read the same gridbox data that Lidl renders on its product cards."""
    try:
        gridbox = item["gridbox"]
        data = gridbox.get("data", gridbox)
        identifier = str(data.get("productId") or item["code"])
        title = data.get("fullTitle") or data["title"]
        path = data.get("canonicalUrl") or data["canonicalPath"]
        url = urljoin(BASE_URL, path)
        price_data = data["price"]
        discount_data = price_data.get("discount") or {}
        percentage = discount_data.get("percentageDiscount", 0)
        discount = number(percentage, "sleva")
        price = number(price_data["price"], "cena")
        old = discount_data.get("deletedPrice") or price_data.get("oldPrice")
        old_price = number(old, "původní cena") if old is not None else None
        currency = price_data["currencyCode"]
        daily_deal = (data.get("dealOfDay") or {}).get("active") is True
    except (KeyError, TypeError, AttributeError) as exc:
        raise WatchError("Změnil se formát produktových dat Lidl.cz.") from exc
    if (
        not identifier.isdigit()
        or not isinstance(title, str)
        or not title.strip()
        or urlsplit(url).scheme != "https"
        or urlsplit(url).netloc != "www.lidl.cz"
        or not urlsplit(url).path.startswith("/p/")
        or not 0 <= discount <= 100
        or price < 0
        or not isinstance(currency, str)
    ):
        raise WatchError(f"Neplatný produkt: {identifier!r}.")
    image = data.get("image")
    image_url = None
    if isinstance(image, str) and image.startswith(("/assets/", f"{BASE_URL}/assets/")):
        image_url = urljoin(BASE_URL, image)
    return Product(
        identifier, title.strip(), url, discount, price, old_price, currency, daily_deal, image_url
    )
