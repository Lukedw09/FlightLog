"""Acceptance checks for the supplied Starlink 15-18 bundle.

The files are used as given. Nothing here authenticates the webcast readout.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from flightlog.import_csv import inspect_csv, parse_event_markers, readout_profile
from flightlog.session import import_mapped_csv

BUNDLE = Path("demo/starlink-15-18")


def _body():
    return {
        "delimiter": "comma",
        "header": "present",
        "provenance": "imported",
        "time_basis": "keep",
        "model_rocket_events": False,
        "confirm_attribution": False,
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


def _rows():
    with (BUNDLE / "telemetry.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_starlink_bundle_imports_three_tracks_without_filling_gaps():
    text = (BUNDLE / "telemetry.csv").read_text(encoding="utf-8")
    preview = inspect_csv(text)
    assert preview["native"] is False
    assert preview["data_rows"] == 1420
    roles = {column["header"]: column["role"] for column in preview["columns"]}
    assert roles["mission_time_s"] == "time"
    assert roles["vehicle"] == "stage"
    assert roles["video_time_s"] == "video_time"
    assert roles["g_force_g"] is None
    assert roles["engines_lit"] is None
    assert any("not throttle" in warning for warning in preview["warnings"])
    assert readout_profile(text) is None

    opened = import_mapped_csv(text, _body())
    encoded = json.dumps(opened)
    assert "NaN" not in encoded
    tracks = {track["track_name"]: track for track in opened["tracks"]}
    assert list(tracks) == ["combined_stack", "booster", "upper_stage"]
    source_rows = {}
    for row in _rows():
        source_rows.setdefault(row["vehicle"], []).append(row)
    assert {name: len(rows) for name, rows in source_rows.items()} == {
        "combined_stack": 659,
        "booster": 357,
        "upper_stage": 404,
    }

    for name, track in tracks.items():
        rows = source_rows[name]
        assert track["samples"] == len(rows)
        assert track["simulated"] is False
        assert track["data_origin"] == "webcast_readout"
        assert track["attribution"] is None
        assert track["analysis"] == "record_only"
        assert track["events"]["liftoff"] is None
        assert track["events"]["apogee"] is None
        assert track["events"]["landing"] is None
        assert track["altitude_reference"] == "unknown"
        assert track["speed_frame"] == "unknown"
        assert track["channels"]["pressure"] == "unavailable"
        assert track["channels"]["temperature"] == "unavailable"
        assert "2116378109218009267" in track["source_note"]
        summary = " ".join(track["import_summary"]).lower()
        assert "not a raw telemetry downlink" not in summary
        assert "dynamic pressure" not in summary
        assert "not filled" in summary
        assert "not interpolated" in (track["chart_note"] or "").lower()
        times = [float(row["mission_time_s"]) for row in rows]
        assert track["time_s"][0] == pytest.approx(times[0])
        assert track["time_s"][-1] == pytest.approx(times[-1])
        assert track["time_s"] == pytest.approx(times)
        for got, row in zip(track["altitude_m"], rows):
            raw = row["altitude_km"].strip()
            if raw == "":
                assert got is None
            else:
                assert got == pytest.approx(float(raw) * 1000.0)
        for got, row in zip(track["speed_kmh"], rows):
            raw = row["speed_kmh"].strip()
            if raw == "":
                assert got is None
            else:
                assert got == pytest.approx(float(raw))
        finite_alt = [float(row["altitude_km"]) * 1000.0 for row in rows if row["altitude_km"].strip()]
        finite_speed = [float(row["speed_kmh"]) for row in rows if row["speed_kmh"].strip()]
        assert track["extrema"]["altitude_max_m"] == pytest.approx(max(finite_alt))
        assert track["extrema"]["altitude_min_m"] == pytest.approx(min(finite_alt))
        assert track["extrema"]["speed_max_kmh"] == pytest.approx(max(finite_speed))
        assert track["extrema"]["speed_min_kmh"] == pytest.approx(min(finite_speed))
        video = [float(row["video_time_s"]) for row in rows]
        assert track["video_time_s"] == pytest.approx(video)
        assert track["video_time_s"][0] != pytest.approx(track["time_s"][0])

    stack = tracks["combined_stack"]
    assert stack["time_s"][0] < 0
    assert stack["altitude_m"][0] is None
    assert stack["speed_kmh"][0] is None
    assert sum(value is None for value in stack["altitude_m"]) == 500
    assert any(value == 0 for value in tracks["booster"]["altitude_m"])
    assert sum(value is None for value in tracks["booster"]["speed_kmh"]) == 66
    assert sum(value is None for value in tracks["upper_stage"]["altitude_m"]) == 13

    all_times = np.concatenate([np.asarray(track["time_s"], dtype=float) for track in tracks.values()])
    assert not np.any((all_times > 18.519) & (all_times < 21.221))
    assert not np.any((all_times > 388.522) & (all_times < 390.59))
    stack_end = stack["time_s"][-1]
    assert tracks["booster"]["time_s"][0] > stack_end
    assert tracks["upper_stage"]["time_s"][0] > stack_end


def test_starlink_event_list_keeps_graphic_and_provisional_audio():
    text = (BUNDLE / "events.csv").read_text(encoding="utf-8")
    with (BUNDLE / "events.csv").open(newline="") as handle:
        source = list(csv.DictReader(handle))
    markers = parse_event_markers(text)
    assert len(markers) == len(source) == 18
    graphic = 0
    audio = 0
    for marker, row in zip(markers, source):
        assert marker["kind"] == "source_marker"
        assert marker["event"] == row["event"]
        assert marker["vehicle"] == row["vehicle"]
        assert marker["source"] == row["source"]
        assert marker["notes"] == row["notes"]
        assert marker["mission_time_s"] == pytest.approx(float(row["mission_time_s"]))
        assert "detected" not in marker["kind"]
        if marker["source"].startswith("graphic"):
            graphic += 1
        elif marker["source"].startswith("audio"):
            audio += 1
            assert "provisional" in marker["notes"].lower() or "asr" in marker["notes"].lower()
        else:
            raise AssertionError(marker["source"])
    assert graphic == 3
    assert audio == 15
    names = " ".join(marker["event"].lower() for marker in markers)
    assert "boostback" not in names
    assert any(marker["event"] == "Landing confirmed" and marker["source"].startswith("audio") for marker in markers)
