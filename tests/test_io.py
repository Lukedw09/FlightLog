import csv
from dataclasses import replace

import numpy as np
import pytest

from flightlog.constants import DISCLAIMER
from flightlog.detect import detect
from flightlog.generate import generate_flight
from flightlog.io import read_flight_csv, write_flight_csv
from flightlog.report import render_report
from tests.helpers import SHORT


def test_same_seed_rewrites_the_same_csv_bytes(tmp_path):
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    write_flight_csv(first, generate_flight(SHORT, seed=123, pressure_noise_pa=20, temperature_noise_c=0.4).log)
    write_flight_csv(second, generate_flight(SHORT, seed=123, pressure_noise_pa=20, temperature_noise_c=0.4).log)
    assert first.read_bytes() == second.read_bytes()
    again = detect(
        generate_flight(SHORT, seed=123, pressure_noise_pa=20, temperature_noise_c=0.4).log.time_s,
        generate_flight(SHORT, seed=123, pressure_noise_pa=20, temperature_noise_c=0.4).log.altitude_m,
    )
    original = detect(read_flight_csv(first).time_s, read_flight_csv(first).altitude_m)
    assert again.liftoff.time_s == pytest.approx(original.liftoff.time_s)
    assert again.apogee.time_s == pytest.approx(original.apogee.time_s)
    assert again.landing.time_s == pytest.approx(original.landing.time_s)


def test_a_different_seed_changes_noise_and_not_the_true_path():
    one = generate_flight(SHORT, seed=1, pressure_noise_pa=15, temperature_noise_c=0.3)
    two = generate_flight(SHORT, seed=2, pressure_noise_pa=15, temperature_noise_c=0.3)
    assert np.array_equal(one.log.altitude_m_true, two.log.altitude_m_true)
    assert np.array_equal(one.log.pressure_pa_true, two.log.pressure_pa_true)
    assert not np.allclose(one.log.pressure_pa, two.log.pressure_pa)
    assert not np.allclose(one.log.temperature_c, two.log.temperature_c)


def test_csv_roundtrip_keeps_measurements_truth_and_reference_pressure(tmp_path):
    generated = generate_flight(SHORT, seed=9, pressure_noise_pa=12, temperature_noise_c=0.2)
    path = tmp_path / "flight.csv"
    write_flight_csv(path, generated.log)
    text = path.read_text(encoding="utf-8")
    assert DISCLAIMER in text
    assert "data_origin: simulated" in text
    assert "simulated" in text
    loaded = read_flight_csv(path)
    assert loaded.simulated
    assert float(loaded.metadata["reference_pressure_pa"]) == pytest.approx(101325.0)
    assert float(loaded.metadata["site_elevation_m"]) == pytest.approx(0.0)
    assert np.allclose(loaded.time_s, generated.log.time_s, atol=1e-8)
    assert np.allclose(loaded.altitude_m, generated.log.altitude_m, atol=1e-8)
    assert np.allclose(loaded.pressure_pa, generated.log.pressure_pa, atol=1e-6)
    assert np.allclose(loaded.temperature_c, generated.log.temperature_c, atol=1e-8)
    assert np.allclose(loaded.altitude_m_true, generated.log.altitude_m_true, atol=1e-8)
    assert np.allclose(loaded.pressure_pa_true, generated.log.pressure_pa_true, atol=1e-6)
    assert list(loaded.phase_true) == list(generated.log.phase_true)
    assert loaded.timestamp_utc[0].startswith("2026-01-01T00:00:00")


def test_truth_columns_are_optional_and_detection_matches(tmp_path):
    generated = generate_flight(SHORT, seed=6, pressure_noise_pa=16, temperature_noise_c=0.2)
    path = tmp_path / "measured_schema.csv"
    write_flight_csv(path, generated.log, include_truth=False)
    loaded = read_flight_csv(path)
    assert loaded.altitude_m_true is None
    assert loaded.phase_true is None
    assert "phase_true" not in path.read_text(encoding="utf-8").splitlines()[-1]
    original = detect(generated.log.time_s, generated.log.altitude_m)
    replayed = detect(loaded.time_s, loaded.altitude_m)
    assert replayed.liftoff.time_s == pytest.approx(original.liftoff.time_s)
    assert replayed.apogee.time_s == pytest.approx(original.apogee.time_s)
    assert replayed.landing.time_s == pytest.approx(original.landing.time_s)


def test_rewriting_phase_labels_does_not_change_detection(tmp_path):
    generated = generate_flight(SHORT, seed=8, pressure_noise_pa=8, temperature_noise_c=0.1)
    path = tmp_path / "flight.csv"
    write_flight_csv(path, generated.log)
    rewritten = tmp_path / "mislabeled.csv"
    with path.open(encoding="utf-8", newline="") as incoming, rewritten.open(
        "w", encoding="utf-8", newline=""
    ) as outgoing:
        for line in incoming:
            if line.startswith("#") or line.startswith("time_s"):
                outgoing.write(line)
                continue
            outgoing.write(line.rsplit(",", 1)[0] + ",ground\n")
    loaded = read_flight_csv(rewritten)
    assert set(loaded.phase_true) == {"ground"}
    original = detect(generated.log.time_s, generated.log.altitude_m)
    from_mislabeled = detect(loaded.time_s, loaded.altitude_m)
    assert from_mislabeled.liftoff.time_s == pytest.approx(original.liftoff.time_s)
    assert from_mislabeled.apogee.time_s == pytest.approx(original.apogee.time_s)
    assert from_mislabeled.landing.time_s == pytest.approx(original.landing.time_s)
    assert from_mislabeled.liftoff is not None


def test_pressure_only_csv_derives_altitude_and_stays_on_the_pad(tmp_path):
    rng = np.random.Generator(np.random.PCG64(5))
    path = tmp_path / "pad.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# schema: flightlog.v1\n")
        handle.write("# data_origin: measured\n")
        handle.write("# note: pytest fixture, not a sensor capture\n")
        handle.write("# reference_pressure_pa: 101325\n")
        handle.write("# site_elevation_m: 0\n")
        handle.write("time_s,pressure_pa,temperature_c\n")
        writer = csv.writer(handle, lineterminator="\n")
        pressure = 101325.0 + rng.normal(0.0, 20.0, size=400)
        for i, sample in enumerate(pressure):
            writer.writerow([f"{i / 20:.3f}", f"{sample:.4f}", "15.0"])
    loaded = read_flight_csv(path)
    assert loaded.altitude_derived
    assert loaded.data_origin == "measured"
    assert not loaded.simulated
    assert np.max(np.abs(loaded.altitude_m)) < 5
    events = detect(loaded.time_s, loaded.altitude_m)
    assert events.liftoff is None
    report = render_report(loaded, events)
    assert "SIMULATED DATA" not in report
    assert "derived from pressure_pa" in report


def test_missing_clock_is_a_clear_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("pressure_pa\n101325\n", encoding="utf-8")
    with pytest.raises(ValueError, match="time_s"):
        read_flight_csv(path)


def test_report_marks_simulation_and_says_truth_is_not_used_for_detection():
    generated = generate_flight(SHORT, seed=1, pressure_noise_pa=0, temperature_noise_c=0)
    events = detect(generated.log.time_s, generated.log.altitude_m)
    report = render_report(generated.log, events)
    assert "SIMULATED DATA" in report
    assert "Not a real flight" in report
    assert "not read by the detector" in report
    assert "events: liftoff=" in report
    assert "liftoff=none" not in report
    # The replaced log drops the header clock. Detection was already computed
    # from altitude and must not need that header.
    stripped = replace(generated.log, metadata={})
    assert detect(stripped.time_s, stripped.altitude_m).apogee.time_s == pytest.approx(
        events.apogee.time_s
    )
