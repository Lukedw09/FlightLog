"""Pack the browser page into a folder whose root is index.html.

The folder is what a static host serves. It does not include the Python
web server, git metadata, or the test suite.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from flightlog.session import form_defaults

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "site"
MODULES = (
    "__init__.py",
    "atmosphere.py",
    "constants.py",
    "detect.py",
    "generate.py",
    "import_csv.py",
    "io.py",
    "log.py",
    "session.py",
    "trajectory.py",
    "xlsx_io.py",
)
DEMOS = (
    "demo/starlink-15-18/telemetry.csv",
    "demo/starlink-15-18/events.csv",
    "demo/starlink-15-18/README.md",
    "demo/starlink-2026-10-27/telemetry.csv",
    "demo/starlink-2026-10-27/events.csv",
    "demo/starlink-2026-10-27/README.md",
    "demo/starlink-2026-10-23/telemetry.csv",
    "demo/starlink-2026-10-23/events.csv",
    "demo/starlink-2026-10-23/README.md",
    "demo/large-rocket-flight-sample.xlsx",
)

PRACTICE = """
        <div class="practice-files" aria-label="Practice files included with this page">
          <button type="button" data-demo="demos/starlink-15-18/telemetry.csv" data-events="demos/starlink-15-18/events.csv">Starlink 15-18</button>
          <button type="button" data-demo="demos/starlink-2026-10-27/telemetry.csv" data-events="demos/starlink-2026-10-27/events.csv">Starlink Mission 2026-10-27</button>
          <button type="button" data-demo="demos/starlink-2026-10-23/telemetry.csv" data-events="demos/starlink-2026-10-23/events.csv">Starlink Mission 2026-10-23</button>
          <button type="button" data-demo="demos/large-rocket-flight-sample.xlsx">Partial workbook</button>
        </div>
"""

HEADERS = """# Cloudflare Pages headers. Later rules override earlier ones.
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: DENY
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Content-Security-Policy: default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-eval' 'wasm-unsafe-eval' blob:; style-src 'self'; connect-src 'self' https://cdn.jsdelivr.net https://pypi.org https://files.pythonhosted.org; img-src 'self' data:; worker-src 'self' blob:; frame-ancestors 'none'

/
  Cache-Control: no-cache

/index.html
  Cache-Control: no-cache

/static/*
  Cache-Control: public, max-age=3600

/pkg/*
  Cache-Control: public, max-age=3600
  Content-Type: text/plain; charset=utf-8

/pkg/manifest.json
  Cache-Control: public, max-age=300
  Content-Type: application/json; charset=utf-8

/demos/*
  Cache-Control: public, max-age=86400

/demos/large-rocket-flight-sample.xlsx
  Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
"""

def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "static").mkdir(parents=True)
    (DIST / "pkg").mkdir()
    (DIST / "demos").mkdir()
    html = (ROOT / "flightlog" / "static" / "index.html").read_text(encoding="utf-8")
    defaults = json.dumps(form_defaults()).replace("<", "\\u003c")
    engine = (
        '<script src="https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.js"></script>\n'
        '  <script src="static/pyodide-boot.js"></script>'
    )
    html = html.replace("__DEFAULTS_JSON__", defaults)
    html = html.replace("<!-- __ENGINE__ -->", engine)
    html = html.replace('<div id="practice-files"></div>', PRACTICE.strip())
    (DIST / "index.html").write_text(html, encoding="utf-8")
    for name in ("app.js", "style.css", "pyodide-boot.js"):
        shutil.copy2(ROOT / "flightlog" / "static" / name, DIST / "static" / name)
    for name in MODULES:
        shutil.copy2(ROOT / "flightlog" / name, DIST / "pkg" / name)
    (DIST / "pkg" / "manifest.json").write_text(
        json.dumps({"files": list(MODULES)}, indent=2) + "\n",
        encoding="utf-8",
    )
    for relative in DEMOS:
        source = ROOT / relative
        target = DIST / "demos" / Path(relative).relative_to("demo")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (DIST / "_headers").write_text(HEADERS, encoding="utf-8")
    archive = Path("/opt/cursor/artifacts/flightlog-pages.zip")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(DIST).as_posix())
    names = zipfile.ZipFile(archive).namelist()
    if "index.html" not in names:
        raise SystemExit("index.html is not at the zip root")
    if any(name.startswith(".git") or ".env" in name or name.endswith("web.py") for name in names):
        raise SystemExit("unexpected private or server file in the zip")
    print(f"{archive} {archive.stat().st_size} bytes {len(names)} files")


if __name__ == "__main__":
    main()
