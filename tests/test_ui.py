"""The page must call the same simulation, detection, and CSV code as the CLI."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from flightlog.detect import detect
from flightlog.generate import generate_flight
from flightlog.io import read_flight_csv_text
from flightlog.session import FormError, form_defaults, replay_csv, simulate_form
from flightlog.trajectory import FlightSpec
from flightlog.web import make_server


def test_page_simulation_matches_the_library():
    payload = simulate_form(form_defaults())
    generated = generate_flight(FlightSpec(), seed=42, pressure_noise_pa=18.0, temperature_noise_c=0.25)
    events = detect(generated.log.time_s, generated.log.altitude_m)
    assert payload["simulated"] is True
    assert payload["events"]["liftoff"]["time_s"] == pytest.approx(events.liftoff.time_s)
    assert payload["events"]["apogee"]["time_s"] == pytest.approx(events.apogee.time_s)
    assert payload["events"]["landing"]["time_s"] == pytest.approx(events.landing.time_s)
    assert payload["events"]["apogee"]["altitude_m"] == pytest.approx(events.apogee.altitude_m)
    assert "Educational synthetic telemetry" in payload["csv"]
    assert "simulated" in payload["csv"]

    loaded = read_flight_csv_text(payload["csv"], label="download")
    replayed = detect(loaded.time_s, loaded.altitude_m)
    assert replayed.apogee.time_s == pytest.approx(events.apogee.time_s)
    assert replayed.liftoff.time_s == pytest.approx(events.liftoff.time_s)
    assert replayed.landing.time_s == pytest.approx(events.landing.time_s)


def test_a_stronger_boost_reaches_a_higher_apogee():
    calm = simulate_form(form_defaults())
    harder = dict(form_defaults())
    harder["boost_accel"] = 55
    louder = simulate_form(harder)
    assert louder["events"]["apogee"]["altitude_m"] > calm["events"]["apogee"]["altitude_m"] + 50


def test_bad_input_names_the_field():
    raw = dict(form_defaults())
    raw["boost_s"] = -2
    with pytest.raises(FormError, match="greater than zero") as caught:
        simulate_form(raw)
    assert caught.value.field == "boost_s"
    raw["boost_s"] = 2.8
    raw["seed"] = 1.5
    with pytest.raises(FormError, match="whole number") as caught:
        simulate_form(raw)
    assert caught.value.field == "seed"
    raw["seed"] = 42
    raw["reference_pressure_pa"] = "101,325"
    with pytest.raises(FormError, match="commas") as caught:
        simulate_form(raw)
    assert caught.value.field == "reference_pressure_pa"


def test_replay_uses_the_csv_reader_and_ignores_phase_labels():
    original = simulate_form(form_defaults())
    csv_text = original["csv"].replace(",ascent", ",ground").replace(",coast", ",ground")
    csv_text = csv_text.replace(",descent", ",ground").replace(",landed", ",ground")
    opened = replay_csv(csv_text, form_defaults())
    assert opened["events"]["liftoff"]["time_s"] == pytest.approx(original["events"]["liftoff"]["time_s"])
    assert opened["events"]["apogee"]["time_s"] == pytest.approx(original["events"]["apogee"]["time_s"])
    assert opened["events"]["landing"]["time_s"] == pytest.approx(original["events"]["landing"]["time_s"])
    assert opened["csv"] == csv_text


def test_http_page_runs_replays_and_rejects_bad_input():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        page = urlopen(f"http://127.0.0.1:{port}/", timeout=5)
        html = page.read().decode("utf-8")
        assert page.status == 200
        assert "Run simulation" in html
        assert "Reset" in html
        assert "Download CSV" in html
        assert "Open CSV" in html
        assert "m/s²" in html
        assert "101325" in html
        assert "SIMULATED" not in html or "origin-strip" in html

        script = urlopen(f"http://127.0.0.1:{port}/static/app.js", timeout=5)
        assert script.status == 200
        assert "SIMULATED DATA" in script.read().decode("utf-8")
        missing = urlopen_status(f"http://127.0.0.1:{port}/static/../session.py")
        assert missing == 404

        defaults = json.loads(urlopen(f"http://127.0.0.1:{port}/api/defaults", timeout=5).read())
        body = _post(port, "/api/simulate", defaults)
        assert body["ok"] is True
        assert body["simulated"] is True
        assert body["events"]["apogee"]["time_s"] > body["events"]["liftoff"]["time_s"]
        assert "simulated" in body["csv"]

        bad = dict(defaults)
        bad["ground_s"] = -5
        rejected = _post(port, "/api/simulate", bad)
        assert rejected["ok"] is False
        assert "at least 0" in rejected["error"].lower()
        assert rejected["field"] == "ground_s"

        opened = _post(port, "/api/replay", {**defaults, "csv": body["csv"]})
        assert opened["events"]["landing"]["time_s"] == pytest.approx(body["events"]["landing"]["time_s"])
        assert opened["events"]["apogee"]["time_s"] == pytest.approx(body["events"]["apogee"]["time_s"])
    finally:
        server.shutdown()
        server.server_close()


def _post(port: int, path: str, payload: dict) -> dict:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def urlopen_status(url: str) -> int:
    try:
        with urlopen(url, timeout=5) as response:
            return response.status
    except Exception as exc:
        status = getattr(exc, "code", None)
        if status is None:
            raise
        return int(status)
