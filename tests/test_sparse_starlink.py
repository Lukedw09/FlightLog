"""Acceptance checks for the two later Starlink Mission webcast bundles.

The posts are titled only Starlink Mission. Group numbers and liftoff
wall-clock times are not verified here. Coverage is representative.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from flightlog.import_csv import inspect_csv, parse_event_markers, readout_profile
from flightlog.session import import_mapped_csv

CASES = (
    pytest.param(
        Path("demo/starlink-2026-10-27"),
        {
            "rows": 475,
            "events": 19,
            "graphic": 3,
            "audio": 16,
            "status": "2114979142638960965",
            "tracks": {
                "combined_stack": (159, -5.472, 152.519, 0, 0),
                "booster": (142, 153.520, 510.510, 67, 0),
                "upper_stage": (174, 153.520, 558.525, 2, 13),
            },
        },
        id="2026-10-27",
    ),
    pytest.param(
        Path("demo/starlink-2026-10-23"),
        {
            "rows": 476,
            "events": 20,
            "graphic": 3,
            "audio": 17,
            "status": "2113761872264712327",
            "tracks": {
                "combined_stack": (158, -5.472, 151.518, 0, 0),
                "booster": (143, 152.519, 510.510, 67, 0),
                "upper_stage": (175, 152.519, 558.525, 2, 13),
            },
        },
        id="2026-10-23",
    ),
)


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


def _rows(path: Path):
    with (path / "telemetry.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("bundle,expect", CASES)
def test_sparse_starlink_bundle_keeps_samples_and_blanks(bundle: Path, expect: dict):
    text = (bundle / "telemetry.csv").read_text(encoding="utf-8")
    preview = inspect_csv(text)
    assert preview["data_rows"] == expect["rows"]
    assert preview["native"] is False
    assert readout_profile(text) is None
    assert any("not throttle" in warning for warning in preview["warnings"])
    opened = import_mapped_csv(text, _body())
    assert "NaN" not in json.dumps(opened)
    tracks = {track["track_name"]: track for track in opened["tracks"]}
    assert list(tracks) == ["combined_stack", "booster", "upper_stage"]
    grouped: dict[str, list] = {}
    for row in _rows(bundle):
        grouped.setdefault(row["vehicle"], []).append(row)
    wide_steps = 0
    close_steps = 0
    for name, (count, first, last, blank_speed, blank_alt) in expect["tracks"].items():
        rows = grouped[name]
        track = tracks[name]
        assert len(rows) == count == track["samples"]
        times = [float(row["mission_time_s"]) for row in rows]
        assert track["time_s"] == pytest.approx(times)
        assert times[0] == pytest.approx(first)
        assert times[-1] == pytest.approx(last)
        assert all(times[i] < times[i + 1] for i in range(len(times) - 1))
        for left, right in zip(times, times[1:]):
            step = right - left
            if step > 8:
                wide_steps += 1
            if step < 1.5:
                close_steps += 1
        assert sum(value is None for value in track["speed_kmh"]) == blank_speed
        assert sum(value is None for value in track["altitude_m"]) == blank_alt
        for got, row in zip(track["speed_kmh"], rows):
            raw = row["speed_kmh"].strip()
            if raw == "":
                assert got is None
            else:
                assert got == pytest.approx(float(raw))
        assert track["data_origin"] == "webcast_readout"
        assert track["simulated"] is False
        assert track["attribution"] is None
        assert track["analysis"] == "record_only"
        assert track["events"]["liftoff"] is None
        assert track["events"]["landing"] is None
        assert track["altitude_reference"] == "unknown"
        assert expect["status"] in track["source_note"]
        assert "unverified" in track["source_note"]
        assert "not a raw telemetry downlink" not in " ".join(track["import_summary"]).lower()
    assert wide_steps > 0
    assert close_steps > 100
    assert any(value == 0 for value in tracks["combined_stack"]["speed_kmh"])
    assert any(value == 0 for value in tracks["booster"]["altitude_m"])


@pytest.mark.parametrize("bundle,expect", CASES)
def test_sparse_starlink_events_stay_graphic_or_provisional_audio(bundle: Path, expect: dict):
    text = (bundle / "events.csv").read_text(encoding="utf-8")
    with (bundle / "events.csv").open(newline="") as handle:
        source = list(csv.DictReader(handle))
    markers = parse_event_markers(text)
    assert len(markers) == len(source) == expect["events"]
    graphic = audio = 0
    for marker, row in zip(markers, source):
        assert marker["kind"] == "source_marker"
        assert marker["event"] == row["event"]
        assert marker["source"] == row["source"]
        assert marker["notes"] == row["notes"]
        assert marker["mission_time_s"] == pytest.approx(float(row["mission_time_s"]))
        if marker["source"].startswith("graphic"):
            graphic += 1
        elif marker["source"].startswith("audio"):
            audio += 1
            assert "provisional" in marker["notes"].lower()
        else:
            raise AssertionError(marker["source"])
    assert graphic == expect["graphic"]
    assert audio == expect["audio"]
    names = " ".join(marker["event"].lower() for marker in markers)
    assert "boostback" not in names
    assert any(marker["event"] == "Landing confirmed" and marker["source"].startswith("audio") for marker in markers)
