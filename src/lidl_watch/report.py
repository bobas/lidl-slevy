"""Readable HTML and CSV reports with optional product images from Lidl."""

import csv
import html
import io
import os
import tempfile
from decimal import Decimal
from itertools import count
from pathlib import Path

from .models import LISTING_URL, MIN_DISCOUNT, Alert


def percent(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


def money(value: Decimal | None, currency: str) -> str:
    if value is None:
        return "—"
    return (
        f"{value:,.2f}".replace(",", " ").replace(".", ",")
        + " "
        + ("Kč" if currency == "CZK" else currency)
    )


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        path.touch(exist_ok=False)
        try:
            os.replace(temporary, path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_reports(output: Path, html_report: str, csv_report: str) -> Path:
    """Save a new pair and return its HTML path, even if the timestamp is taken."""
    for sequence in count(1):
        path = output if sequence == 1 else output.with_stem(f"{output.stem}-{sequence}")
        csv_path = path.with_suffix(".csv")
        try:
            atomic_write(csv_path, csv_report)
        except FileExistsError:
            continue
        try:
            atomic_write(path, html_report)
        except FileExistsError:
            csv_path.unlink()
            continue
        except BaseException:
            csv_path.unlink()
            raise
        return path


def render_html(
    alerts: list[Alert],
    initial: bool,
    total: int,
    checked_at: str,
    min_discount: Decimal = MIN_DISCOUNT,
) -> str:
    escape = html.escape
    minimum = percent(min_discount)
    rows = []
    for alert in alerts:
        product = alert.product
        thumbnail = ""
        if product.image_url:
            thumbnail = (
                f'<img class="product-image" src="{escape(product.image_url, quote=True)}" '
                'alt="" width="96" height="72" loading="lazy" decoding="async" '
                'referrerpolicy="no-referrer">'
            )
        difference = (
            f"{percent(alert.previous_discount)} → {percent(product.discount)} % "
            f"(+{percent(product.discount - alert.previous_discount)} p. b.)"
            if alert.previous_discount is not None
            else f"První zaznamenaná nabídka nad {minimum} %"
        )
        rows.append(
            '<tr><td><div class="product-cell">'
            + thumbnail
            + '<div><a target="_blank" rel="noopener noreferrer" href="'
            + escape(product.url, quote=True)
            + '">'
            + escape(product.title)
            + "</a><small>Produkt "
            + escape(product.id)
            + '</small></div></div></td><td class="discount">−'
            + percent(product.discount)
            + ' %</td><td class="price">'
            + escape(money(product.price, product.currency))
            + "<small>Srovnávací cena "
            + escape(money(product.old_price, product.currency))
            + '</small></td><td><span class="tag">'
            + escape(alert.reason)
            + "</span><small>"
            + escape(difference)
            + "</small></td></tr>"
        )
    empty = (
        "Výchozí stav je uložený. Aktuální nabídky jsou označené jako již viděné. "
        "Při dalším spuštění se zde objeví pouze změny."
        if initial
        else "Žádné nové produkty ani dostatečně zvýšené slevy."
    )
    body = (
        '<div class="table-wrap"><table><thead><tr><th>Produkt</th><th>Sleva</th>'
        "<th>Aktuální cena</th><th>Důvod zobrazení</th></tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table></div>"
        if rows
        else '<div class="empty">' + empty + "</div>"
    )
    return f'''<!doctype html>
<html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https://www.lidl.cz/assets/; style-src 'unsafe-inline'; base-uri 'none'">
<title>Lidl · Nové slevy</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #172c40; background: #f2f5f8; }}
body {{ max-width: 1180px; margin: 0 auto; padding: 42px 22px; }}
header {{ border-top: 5px solid #0754a6; padding-top: 24px; }}
h1 {{ font-size: clamp(28px, 5vw, 42px); margin: 0 0 10px; letter-spacing: -1px; }}
.intro, footer {{ color: #516478; line-height: 1.7; }}
.stats {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 28px 0; }}
.stat {{ background: #fff; border: 1px solid #dce4ec; border-radius: 12px; padding: 18px 24px; }}
.stat strong {{ font-size: 27px; margin-right: 8px; color: #0754a6; }}
.table-wrap {{ overflow-x: auto; border: 1px solid #dce4ec; border-radius: 12px; background: #fff; }}
table {{ width: 100%; border-collapse: collapse; text-align: left; }}
th {{ background: #e7eef5; font-size: 13px; padding: 16px; white-space: nowrap; }}
td {{ padding: 20px 16px; border-top: 1px solid #e4eaf0; vertical-align: top; }}
td:first-child {{ min-width: 240px; }}
.product-cell {{ display: flex; align-items: center; gap: 14px; }}
.product-image {{ flex-shrink: 0; object-fit: contain; border-radius: 6px; }}
a {{ color: #0754a6; text-underline-offset: 3px; font-weight: 600; }}
a:hover {{ color: #00366e; }}
small {{ display: block; color: #607287; font-size: 12px; font-weight: 400; margin-top: 9px; }}
.discount {{ font-size: 22px; font-weight: 750; color: #b51e25; white-space: nowrap; }}
.price {{ font-weight: 700; white-space: nowrap; }}
.tag {{ display: inline-block; border-radius: 5px; background: #e8f3e9; color: #245d33; padding: 4px 8px; font-size: 12px; white-space: nowrap; }}
.empty {{ border: 1px solid #dce4ec; border-radius: 12px; padding: 32px; background: white; line-height: 1.8; }}
footer {{ margin-top: 25px; font-size: 13px; }}
@media (max-width: 600px) {{ body {{ padding: 24px 12px; }} td, th {{ padding: 14px 10px; }} .stat {{ padding: 12px 16px; }} }}
</style></head><body><header><h1>Lidl · Nové slevy</h1>
<p class="intro">Jen nové nabídky se slevou nad {minimum} % a zvýšení o více než 15 procentních bodů.</p>
</header><div class="stats"><div class="stat"><strong>{len(alerts)}</strong>novinek</div>
<div class="stat"><strong>{total}</strong>zkontrolovaných produktů</div></div>
{body}
<footer>Kontrola: {escape(checked_at)} · <a href="{escape(LISTING_URL, quote=True)}">Otevřít nabídku Lidl.cz</a>
<br>Zvýšení se porovnává s poslední zobrazenou slevou nebo s výchozím stavem.
Přesně {minimum} % ani zvýšení přesně o 15 p. b. se nezobrazí. Historie zůstává v tomto počítači.
<br>Ceny a dostupnost odpovídají okamžiku kontroly. Neoficiální osobní přehled.</footer>
</body></html>'''


def csv_cell(text: str) -> str:
    """Avoid interpreting product names as formulas when opened in a spreadsheet."""
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def render_csv(alerts: list[Alert]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(
        ["Produkt", "Sleva (%)", "Cena", "Měna", "Předchozí sleva (%)", "Důvod", "Odkaz"]
    )
    for alert in alerts:
        p = alert.product
        writer.writerow(
            [
                csv_cell(p.title),
                percent(p.discount),
                format(p.price, "f").replace(".", ","),
                p.currency,
                percent(alert.previous_discount) if alert.previous_discount is not None else "",
                alert.reason,
                p.url,
            ]
        )
    return "\ufeff" + stream.getvalue()
