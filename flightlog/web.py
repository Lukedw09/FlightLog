"""Local page for the flight log. It listens on this computer only.

The page calls ``flightlog.session``, which calls the same simulation,
detection, and CSV code as the command line. Closing the window that
started this module stops the page.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from flightlog.session import (
    FormError,
    form_defaults,
    import_event_file,
    import_mapped_csv,
    preview_import,
    replay_csv,
    simulate_form,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 47231
INDEX = STATIC_DIR / "index.html"


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    if not INDEX.is_file():
        raise ValueError(
            "The page files are missing next to the flightlog package. "
            "Reinstall with: python -m pip install -e ."
        )
    httpd, chosen = _bind(host, port)
    url = f"http://{host}:{chosen}/"
    print(f"Flight log is open at {url}")
    print("Leave this window open. Closing it stops the page.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


def make_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), FlightLogHandler)


class FlightLogHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, _index_bytes(), "text/html; charset=utf-8")
            return
        if path == "/browser":
            self._send(200, _index_bytes(engine=True), "text/html; charset=utf-8")
            return
        if path == "/pkg/manifest.json":
            body = json.dumps({"files": _package_files()}).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if path.startswith("/pkg/"):
            self._package(path[len("/pkg/") :])
            return
        if path == "/api/defaults":
            body = json.dumps(form_defaults()).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if path.startswith("/static/"):
            self._static(path[len("/static/") :])
            return
        self._send(404, b"Not found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            raw = self._json_body()
        except FormError as exc:
            self._error(exc)
            return
        try:
            if path == "/api/simulate":
                payload = simulate_form(raw)
            elif path == "/api/replay":
                csv_text = raw.get("csv")
                if not isinstance(csv_text, str):
                    raise FormError("Choose a CSV file to open.", "csv")
                payload = replay_csv(csv_text, raw)
            elif path == "/api/import/preview":
                csv_text = raw.get("csv") if isinstance(raw.get("csv"), str) else ""
                if not csv_text and not raw.get("xlsx_base64"):
                    raise FormError("Choose a CSV file or a workbook to open.", "csv")
                payload = preview_import(csv_text, raw)
            elif path == "/api/import/apply":
                csv_text = raw.get("csv") if isinstance(raw.get("csv"), str) else ""
                if not csv_text and not raw.get("xlsx_base64"):
                    raise FormError("Choose a CSV file or a workbook to open.", "csv")
                payload = import_mapped_csv(csv_text, raw)
            elif path == "/api/import/events":
                csv_text = raw.get("csv")
                if not isinstance(csv_text, str):
                    raise FormError("Choose an event list to open.", "events")
                payload = import_event_file(csv_text)
            else:
                self._send(404, b"Not found\n", "text/plain; charset=utf-8")
                return
        except FormError as exc:
            self._error(exc)
            return
        except ValueError as exc:
            self._error(FormError(str(exc)))
            return
        body = json.dumps(payload).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        # Keep the launcher window quiet. Errors are shown in the page.
        return

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 25_000_000:
            raise FormError("That upload is too large for this page.", "csv")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FormError("The page sent data this program could not read.") from exc
        if not isinstance(parsed, dict):
            raise FormError("The page sent data this program could not read.")
        return parsed

    def _package(self, name: str) -> None:
        body = _package_bytes(unquote(name))
        if body is None:
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        self._send(200, body, "text/plain; charset=utf-8")

    def _static(self, name: str) -> None:
        relative = unquote(name)
        if relative.startswith("/") or ".." in Path(relative).parts:
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        root = STATIC_DIR.resolve()
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        if not target.is_file():
            self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        kind = "text/plain; charset=utf-8"
        if target.suffix == ".js":
            kind = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            kind = "text/css; charset=utf-8"
        self._send(200, target.read_bytes(), kind)

    def _error(self, exc: FormError) -> None:
        body = json.dumps(
            {"ok": False, "error": str(exc), "field": exc.field}
        ).encode("utf-8")
        self._send(400, body, "application/json; charset=utf-8")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _index_bytes(engine: bool = False) -> bytes:
    html = INDEX.read_text(encoding="utf-8")
    defaults = json.dumps(form_defaults()).replace("<", "\\u003c")
    html = html.replace("__DEFAULTS_JSON__", defaults)
    engine_html = ""
    if engine:
        engine_html = (
            '<script src="https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.js"></script>\n'
            '<script src="/static/pyodide-boot.js"></script>'
        )
    return html.replace("<!-- __ENGINE__ -->", engine_html).encode("utf-8")


def _package_files() -> list[str]:
    root = Path(__file__).resolve().parent
    names = []
    for path in sorted(root.glob("*.py")):
        if path.name == "web.py":
            continue
        names.append(path.name)
    return names


def _package_bytes(name: str) -> bytes | None:
    if "/" in name or ".." in name or not name.endswith(".py"):
        return None
    path = (Path(__file__).resolve().parent / name).resolve()
    try:
        path.relative_to(Path(__file__).resolve().parent)
    except ValueError:
        return None
    if path.name == "web.py" or not path.is_file():
        return None
    return path.read_bytes()


def _bind(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    last_error: OSError | None = None
    for candidate in range(port, port + 10):
        try:
            return ThreadingHTTPServer((host, candidate), FlightLogHandler), candidate
        except OSError as exc:
            last_error = exc
    raise ValueError(
        f"Could not open a local page on {host} ports {port}–{port + 9}. "
        f"Close the other flight log window and try again. ({last_error})"
    )
