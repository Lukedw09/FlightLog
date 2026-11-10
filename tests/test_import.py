"""Synthetic tables for the generic CSV mapping. Not captures from a real controller."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest

from flightlog.detect import detect
from flightlog.generate import generate_flight
from flightlog.import_csv import apply_mapping, inspect_csv
from flightlog.io import read_flight_csv_text
from flightlog.session import FormError, import_mapped_csv, preview_import, replay_csv
from tests.helpers import SHORT


def test_native_flightlog_opens_without_a_mapping_step():
    generated = generate_flight(SHORT, seed=2, pressure_noise_pa=0, temperature_noise_c=0)
    from flightlog.io import flight_csv_text

    text = flight_csv_text(generated.log)
    opened = preview_import(text, {})
    assert opened["native"] is True
    direct = replay_csv(text, {})
    assert opened["flight"]["events"]["apogee"]["time_s"] == pytest.approx(direct["events"]["apogee"]["time_s"])
    assert opened["flight"]["simulated"] is True
    assert opened["flight"]["data_origin"] == "simulated"


def test_synthetic_milliseconds_and_feet_match_the_original_flight():
    generated = generate_flight(SHORT, seed=3, pressure_noise_pa=0.0, temperature_noise_c=0.0)
    log = generated.log
    lines = ["t_ms;alt_ft;temp_f"]
    for index in range(len(log)):
        millis = float(log.time_s[index]) * 1000.0
        feet = float(log.altitude_m[index]) / 0.3048
        fahrenheit = float(log.temperature_c[index]) * 9.0 / 5.0 + 32.0
        lines.append(f"{millis:.6f};{feet:.6f};{fahrenheit:.6f}")
    text = "\n".join(lines) + "\n"
    preview = inspect_csv(text)
    assert preview["native"] is False
    assert preview["delimiter"] == "semicolon"
    by_header = {column["header"]: column for column in preview["columns"]}
    assert by_header["t_ms"]["unit"] == "ms" and by_header["t_ms"]["unit_confident"]
    assert by_header["alt_ft"]["unit"] == "ft" and by_header["alt_ft"]["unit_confident"]
    assert by_header["alt_ft"]["reference_confident"] is False
    assert by_header["temp_f"]["unit"] == "F"
    imported = import_mapped_csv(
        text,
        {
            "delimiter": "semicolon",
            "header": "present",
            "provenance": "imported",
            "time": {"index": 0, "unit": "ms"},
            "altitude": {"index": 1, "unit": "ft", "reference": "agl"},
            "temperature": {"index": 2, "unit": "F"},
            "model_rocket_events": True,
        },
    )
    imported = imported["tracks"][0]
    assert imported["simulated"] is False
    assert imported["data_origin"] == "imported"
    assert "feet" in " ".join(imported["import_summary"])
    loaded = read_flight_csv_text(imported["csv"], label="imported")
    assert np.allclose(loaded.time_s, log.time_s, atol=1e-4)
    assert np.allclose(loaded.altitude_m, log.altitude_m, atol=1e-3)
    assert np.allclose(loaded.temperature_c, log.temperature_c, atol=1e-3)
    events = detect(log.time_s, log.altitude_m)
    assert imported["events"]["liftoff"]["time_s"] == pytest.approx(events.liftoff.time_s, abs=1e-3)
    assert imported["events"]["apogee"]["time_s"] == pytest.approx(events.apogee.time_s, abs=1e-3)
    assert imported["events"]["landing"]["time_s"] == pytest.approx(events.landing.time_s, abs=1e-3)


def test_pressure_only_hpa_uses_the_stated_reference_and_site():
    generated = generate_flight(SHORT, seed=4, pressure_noise_pa=0.0, temperature_noise_c=0.0)
    lines = ["elapsed_s,pressure_hpa"]
    for index in range(len(generated.log)):
        lines.append(
            f"{float(generated.log.time_s[index]):.6f},{float(generated.log.pressure_pa[index]) / 100.0:.6f}"
        )
    imported = import_mapped_csv(
        "\n".join(lines) + "\n",
        {
            "delimiter": "comma",
            "header": "present",
            "provenance": "imported",
            "time": {"index": 0, "unit": "s"},
            "pressure": {"index": 1, "unit": "hPa"},
            "site_elevation_m": 0,
            "reference_pressure_pa": 101325,
        },
    )
    imported = imported["tracks"][0]
    loaded = read_flight_csv_text(imported["csv"], label="pressure")
    assert np.allclose(loaded.altitude_m, generated.log.altitude_m, atol=1e-3)
    assert np.allclose(loaded.pressure_pa, generated.log.pressure_pa, atol=1e-2)
    assert "ISA troposphere" in " ".join(imported["import_summary"])
    assert imported["data_origin"] == "imported"


def test_ambiguous_headers_are_not_given_a_unit():
    text = "time,altitude,temperature\n" + "\n".join(f"{i},{i},{20 + i}" for i in range(12)) + "\n"
    preview = inspect_csv(text)
    columns = {column["header"]: column for column in preview["columns"]}
    assert columns["time"]["role"] == "time" and columns["time"]["unit_confident"] is False
    assert columns["altitude"]["unit_confident"] is False
    assert columns["altitude"]["reference_confident"] is False
    assert columns["temperature"]["unit_confident"] is False
    assert preview["warnings"]
    with pytest.raises(FormError, match="Choose one of"):
        apply_mapping(
            text,
            {
                "delimiter": "comma",
                "header": "present",
                "provenance": "imported",
                "time": {"index": 0, "unit": "s"},
                "altitude": {"index": 1, "unit": "m"},
            },
        )


def test_msl_subtraction_is_explicit_and_required():
    text = "t_s,alt_m_msl\n" + "\n".join(f"{i},{100 + i}" for i in range(12)) + "\n"
    preview = inspect_csv(text)
    altitude = next(column for column in preview["columns"] if column["header"] == "alt_m_msl")
    assert altitude["unit"] == "m" and altitude["reference"] == "msl" and altitude["reference_confident"]
    with pytest.raises(FormError, match="site elevation"):
        apply_mapping(
            text,
            {
                "delimiter": "comma",
                "header": "present",
                "provenance": "imported",
                "time": {"index": 0, "unit": "s"},
                "altitude": {"index": 1, "unit": "m", "reference": "msl"},
            },
        )
    result = apply_mapping(
        text,
        {
            "delimiter": "comma",
            "header": "present",
            "provenance": "measured",
            "time": {"index": 0, "unit": "s"},
            "altitude": {"index": 1, "unit": "m", "reference": "msl"},
            "site_elevation_m": 40,
        },
    )
    assert result.log.altitude_m[0] == pytest.approx(60.0)
    assert result.log.data_origin == "measured"
    assert result.log.simulated is False
    assert any("40" in line and "sea level" in line for line in result.summary)


def test_bad_rows_are_rejected_instead_of_rewritten():
    backwards = "t_s,alt_m\n0,0\n2,10\n1,5\n" + "\n".join(f"{3 + i},{i}" for i in range(10))
    with pytest.raises(FormError, match="backwards") as caught:
        apply_mapping(backwards, _body())
    assert "not reordered" in str(caught.value)
    duplicate = "t_s,alt_m\n" + "\n".join(f"{min(i, 5)},{i}" for i in range(12))
    with pytest.raises(FormError, match="repeats"):
        apply_mapping(duplicate, _body())
    broken = "t_s,alt_m\n" + "\n".join("1,abc" if i == 4 else f"{i},{i}" for i in range(12))
    with pytest.raises(FormError, match="not a finite number") as caught:
        apply_mapping(broken, _body())
    assert "Line" in str(caught.value)
    with pytest.raises(FormError, match="cannot be marked simulated"):
        import_mapped_csv(
            "t_s,alt_m\n" + "\n".join(f"{i},{i}" for i in range(12)),
            {**_body(), "provenance": "simulated"},
        )


def test_pressure_above_11_km_is_not_clamped():
    text = "t_s,pressure_pa\n" + "\n".join(f"{i},1000" for i in range(12)) + "\n"
    body = _body()
    del body["altitude"]
    body["pressure"] = {"index": 1, "unit": "Pa"}
    body["site_elevation_m"] = 0
    body["reference_pressure_pa"] = 101325
    with pytest.raises(FormError, match="11 km"):
        apply_mapping(text, body)


def test_import_http_round_trip(tmp_path):
    from flightlog.web import make_server

    text = "elapsed_ms\talt_m_agl\n" + "\n".join(f"{i * 100}\t{i}" for i in range(20)) + "\n"
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        preview = _post(port, "/api/import/preview", {"csv": text})
        assert preview["native"] is False
        assert preview["preview"]["delimiter"] == "tab"
        altitude = next(column for column in preview["preview"]["columns"] if column["role"] == "altitude")
        assert altitude["unit"] == "m" and altitude["reference"] == "agl"
        imported = _post(
            port,
            "/api/import/apply",
            {
                "csv": text,
                "delimiter": "tab",
                "header": "present",
                "provenance": "imported",
                "time": {"index": 0, "unit": "ms"},
                "altitude": {"index": 1, "unit": "m", "reference": "agl"},
            },
        )
        track = imported["tracks"][0]
        assert track["data_origin"] == "imported"
        assert track["time_s"][0] == 0
        assert track["time_s"][1] == pytest.approx(0.1)
        assert track["altitude_m"][2] == pytest.approx(2)
    finally:
        server.shutdown()
        server.server_close()


def test_recommended_long_format_keeps_mission_time_and_separates_vehicles():
    text = "\n".join(
        [
            "mission_time_s,vehicle,speed_kmh,altitude_km,altitude_reference,speed_reference,data_origin,source,video_time_s",
            "30,Combined stack,100,1.0,unknown,total,webcast_readout,synthetic fixture,10",
            "31,Combined stack,110,,unknown,total,webcast_readout,synthetic fixture,11",
            "32,Combined stack,120,1.2,unknown,total,webcast_readout,synthetic fixture,",
            "30,Booster,80,0.4,unknown,total,webcast_readout,synthetic fixture,10",
            "31,Booster,90,0.5,unknown,total,webcast_readout,synthetic fixture,11",
        ]
    ) + "\n"
    preview = inspect_csv(text)
    roles = {column["header"]: column["role"] for column in preview["columns"]}
    assert roles["mission_time_s"] == "time"
    assert roles["video_time_s"] == "video_time"
    assert roles["vehicle"] == "stage"
    assert roles["altitude_km"] == "altitude"
    assert roles["altitude_reference"] == "altitude_reference"
    assert roles["data_origin"] == "data_origin"
    assert preview["columns"][0]["unit"] == "s"
    imported = import_mapped_csv(text, _long_body())
    names = [track["track_name"] for track in imported["tracks"]]
    assert names == ["Combined stack", "Booster"]
    stack, booster = imported["tracks"]
    assert stack["time_s"][0] == 30
    assert stack["time_s"] != booster["time_s"] or stack["altitude_m"] != booster["altitude_m"]
    assert stack["altitude_m"][1] is None
    assert booster["altitude_m"] == [400.0, 500.0]
    assert stack["data_origin"] == "webcast_readout"
    assert stack["simulated"] is False
    assert stack["analysis"] == "record_only"
    assert stack["events"]["landing"] is None
    assert stack["video_time_s"][2] is None
    assert stack["video_time_s"][0] == 10
    assert "not a raw telemetry downlink" not in " ".join(stack["import_summary"])
    assert any("unknown" in line for line in stack["import_summary"])
    markers = __import__("flightlog.import_csv", fromlist=["parse_event_markers"]).parse_event_markers(
        "mission_time_s,vehicle,event,source,notes\n40,Combined stack,max-q window,synthetic,not detected\n"
    )
    assert markers[0]["kind"] == "source_marker"
    assert markers[0]["event"] == "max-q window"


def _long_body():
    return {
        "delimiter": "comma",
        "header": "present",
        "provenance": "imported",
        "time_basis": "keep",
        "time": {"index": 0, "unit": "s"},
        "stage": {"index": 1},
        "speed": {"index": 2, "unit": "kmh", "frame": "unknown"},
        "altitude": {"index": 3, "unit": "km", "reference": "unknown"},
        "altitude_reference": {"index": 4},
        "speed_reference": {"index": 5},
        "data_origin": {"index": 6},
        "source": {"index": 7},
        "video_time": {"index": 8},
    }


def test_provided_workbook_is_one_partial_track_without_invented_events():
    import base64
    from pathlib import Path

    data = Path("demo/large-rocket-flight-sample.xlsx").read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    sheets = preview_import("", {"xlsx_base64": encoded})
    assert sheets["need_sheet"] is True
    assert sheets["sheets"] == ["Untitled"]
    preview = preview_import("", {"xlsx_base64": encoded, "sheet": "Untitled"})
    headers = [column["header"] for column in preview["preview"]["columns"]]
    assert headers == ["t_s", "speed_kmh", "altitude_km", "V_m_s", "Z_m", "video_time_s"]
    assert preview["preview"]["readout"]["coverage_match"] is True
    assert preview["preview"]["readout"]["rows"] == 81
    opened = import_mapped_csv(
        "",
        {
            "xlsx_base64": encoded,
            "sheet": "Untitled",
            "delimiter": "comma",
            "header": "present",
            "provenance": "imported",
            "time_basis": "keep",
            "time": {"index": 0, "unit": "s"},
            "speed": {"index": 1, "unit": "kmh", "frame": "unknown"},
            "altitude": {"index": 2, "unit": "km", "reference": "unknown"},
            "video_time": {"index": 5},
        },
    )
    assert len(opened["tracks"]) == 1
    track = opened["tracks"][0]
    assert track["time_s"][0] == 30
    assert track["time_s"][-1] == 110
    assert track["extrema"]["altitude_max_m"] == pytest.approx(33100)
    assert track["extrema"]["altitude_max_t_s"] == pytest.approx(110)
    assert track["extrema"]["speed_max_kmh"] == pytest.approx(3799)
    assert track["events"]["liftoff"] is None
    assert track["events"]["apogee"] is None
    assert track["events"]["landing"] is None
    assert track["analysis"] == "record_only"
    assert track["simulated"] is False
    assert track["data_origin"] == "imported"
    assert track["attribution"] is None
    assert track["channels"]["pressure"] == "unavailable"
    assert track["channels"]["temperature"] == "unavailable"
    assert track["video_time_s"][0] == pytest.approx(693.226)
    assert "dynamic pressure" not in " ".join(track["import_summary"]).lower()


def _body():
    return {
        "delimiter": "comma",
        "header": "present",
        "provenance": "imported",
        "time": {"index": 0, "unit": "s"},
        "altitude": {"index": 1, "unit": "m", "reference": "agl"},
    }


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
