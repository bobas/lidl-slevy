"""A small local-network interface for running and reading Lidl discount reports."""

import argparse
import html
import mimetypes
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .models import MIN_DISCOUNT, WatchError, number
from .report import percent

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REPORT_PATH = re.compile(r"^Přehled: (.+)$", re.MULTILINE)


def parse_discount(value: str) -> Decimal:
    try:
        discount = number(value.replace(",", "."), "hranice slevy")
    except WatchError as exc:
        raise ValueError(str(exc)) from exc
    if not 0 <= discount < 100:
        raise ValueError("Hranice slevy musí být od 0 do méně než 100 %.")
    return discount


@dataclass
class ScanState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    min_discount: Decimal = MIN_DISCOUNT
    started_at: str | None = None
    finished_at: str | None = None
    succeeded: bool | None = None
    message: str = "Zatím nebyla spuštěna žádná kontrola."
    output: str = ""

    def start(self, min_discount: Decimal) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.min_discount = min_discount
            self.started_at = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S")
            self.finished_at = None
            self.succeeded = None
            self.message = "Kontrola běží. Stránka se obnoví za pět sekund."
            self.output = ""
        threading.Thread(target=self._scan, daemon=True).start()
        return True

    def _scan(self) -> None:
        command = [
            sys.executable,
            str(ROOT / "lidl_slevy.py"),
            "--min-discount",
            str(self.min_discount),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        with self.lock:
            self.running = False
            self.finished_at = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S")
            self.output = result.stdout.strip()
            self.succeeded = result.returncode == 0
            if result.returncode == 0:
                self.message = "Kontrola je hotová. Nejnovější přehled je nahoře v archivu."
            else:
                self.message = "Kontrola skončila chybou. Podrobnosti jsou níže."


def reports() -> list[Path]:
    if not REPORTS.is_dir():
        return []
    return sorted(REPORTS.glob("*.html"), key=lambda path: path.stat().st_mtime, reverse=True)


def report_path(name: str) -> Path | None:
    if name != Path(name).name or not name.endswith((".html", ".csv")):
        return None
    path = REPORTS / name
    return path if path.is_file() else None


def favicon_svg(running: bool, succeeded: bool | None) -> str:
    """Return a compact tab icon that represents the latest scan state."""
    if running:
        color, symbol, label = "#ef8b00", "…", "Kontrola běží"
    elif succeeded is True:
        color, symbol, label = "#16803c", "✓", "Kontrola hotová"
    elif succeeded is False:
        color, symbol, label = "#c42b1c", "×", "Kontrola skončila chybou"
    else:
        color, symbol, label = "#516478", "•", "Kontrola zatím nebyla spuštěna"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<title>{label}</title><circle cx="32" cy="32" r="29" fill="{color}"/>
<text x="32" y="43" fill="white" font-family="Arial, sans-serif" font-size="42"
text-anchor="middle">{symbol}</text></svg>'''


def dashboard(state: ScanState) -> str:
    escape = html.escape
    with state.lock:
        running = state.running
        current_discount = percent(state.min_discount)
        message = state.message
        started_at = state.started_at
        finished_at = state.finished_at
        succeeded = state.succeeded
        output = state.output
    report_rows = "".join(
        '<li><a href="/reports/'
        + escape(report.name, quote=True)
        + '">'
        + escape(report.name)
        + "</a>"
        + (
            ' · <a class="csv" href="/reports/'
            + escape(report.with_suffix(".csv").name, quote=True)
            + '">CSV</a>'
            if report.with_suffix(".csv").is_file()
            else ""
        )
        + "</li>"
        for report in reports()
    ) or "<li>Zatím nejsou uložené žádné přehledy.</li>"
    refresh = '<meta http-equiv="refresh" content="5">' if running else ""
    details = ""
    if started_at:
        details += "<p><strong>Začátek</strong> " + escape(started_at) + "</p>"
    if finished_at:
        details += "<p><strong>Konec</strong> " + escape(finished_at) + "</p>"
    if output:
        details += "<pre>" + escape(output) + "</pre>"
    disabled = " disabled" if running else ""
    if running:
        favicon_state = "running"
    elif succeeded is True:
        favicon_state = "success"
    elif succeeded is False:
        favicon_state = "error"
    else:
        favicon_state = "idle"
    page_title = "Lidl · Kontrola běží" if running else "Lidl · Slevy"
    return f"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}
<link rel="icon" type="image/svg+xml" href="/favicon.svg?state={favicon_state}">
<title>{page_title}</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #172c40; background: #f2f5f8; }}
body {{ max-width: 860px; margin: 0 auto; padding: 42px 22px; }}
header {{ border-top: 5px solid #0754a6; padding-top: 24px; }}
h1 {{ margin: 0 0 8px; font-size: 38px; }}
p {{ line-height: 1.55; }}
section {{ background: white; border: 1px solid #dce4ec; border-radius: 12px; padding: 24px; margin-top: 22px; }}
form {{ display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }}
label {{ display: grid; gap: 6px; font-weight: 650; }}
input {{ font: inherit; width: 110px; padding: 9px; border: 1px solid #8fa1b3; border-radius: 6px; }}
button {{ background: #0754a6; border: 0; border-radius: 6px; color: white; cursor: pointer; font: inherit; font-weight: 650; padding: 11px 17px; }}
button:disabled {{ cursor: wait; opacity: .6; }}
.status {{ border-left: 4px solid #0754a6; padding-left: 14px; }}
a {{ color: #0754a6; text-underline-offset: 3px; }}
li {{ margin: 11px 0; }}
.csv {{ color: #516478; font-size: 14px; }}
pre {{ background: #172c40; border-radius: 7px; color: #f5f8fa; overflow-x: auto; padding: 15px; white-space: pre-wrap; }}
</style></head><body>
<header><h1>Lidl · Slevy</h1><p>Kontrola nabídky a archiv uložených přehledů.</p></header>
<section><form method="post" action="/run"><label>Hranice slevy (%)
<input name="min_discount" type="number" min="0" max="99.99" step="0.1" value="{current_discount}"{disabled}></label>
<button type="submit"{disabled}>{"Kontrola běží…" if running else "Spustit kontrolu"}</button></form></section>
<section class="status"><p>{escape(message)}</p>{details}</section>
<section><h2>Archiv přehledů</h2><ol>{report_rows}</ol></section>
</body></html>"""


class LidlHandler(BaseHTTPRequestHandler):
    state: ScanState

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._html(dashboard(self.state))
            return
        if path == "/favicon.svg":
            self._favicon()
            return
        if path.startswith("/reports/"):
            self._report(path.removeprefix("/reports/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 1024:
            self.send_error(HTTPStatus.BAD_REQUEST, "Neplatný formulář.")
            return
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        try:
            discount = parse_discount(fields.get("min_discount", [""])[0])
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self.state.start(discount)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()

    def _html(self, content: str) -> None:
        payload = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _favicon(self) -> None:
        with self.state.lock:
            content = favicon_svg(self.state.running, self.state.succeeded)
        payload = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _report(self, name: str) -> None:
        path = report_path(name)
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lokální webové rozhraní hlídače slev Lidl.cz.")
    parser.add_argument("--host", default="127.0.0.1", help="Adresa rozhraní serveru.")
    parser.add_argument("--port", default=8088, type=int, help="TCP port serveru.")
    options = parser.parse_args(argv)
    if not 1 <= options.port <= 65535:
        parser.error("Port musí být číslo od 1 do 65535.")
    LidlHandler.state = ScanState()
    server = ThreadingHTTPServer((options.host, options.port), LidlHandler)
    print(f"Web běží na http://{options.host}:{options.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0
