import subprocess
import sys

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.image as mpimg

from flightlog.trajectory import FlightSpec


def test_cli_simulate_then_replay(tmp_path):
    csv_path = tmp_path / "flight.csv"
    png_path = tmp_path / "flight.png"
    replay_png = tmp_path / "replay.png"
    spec = FlightSpec()
    simulate = subprocess.run(
        [
            sys.executable,
            "-m",
            "flightlog",
            "simulate",
            "--output",
            str(csv_path),
            "--plot",
            str(png_path),
            "--seed",
            "42",
            "--ground-s",
            str(spec.ground_s),
            "--boost-s",
            str(spec.boost_s),
            "--boost-accel",
            str(spec.boost_accel_mps2),
            "--descent-rate",
            str(spec.descent_rate_mps),
            "--landed-s",
            str(spec.landed_s),
            "--sample-hz",
            str(spec.sample_hz),
            "--site-elevation-m",
            str(spec.site_elevation_m),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "SIMULATED DATA" in simulate.stdout
    assert "not read by the detector" in simulate.stdout
    assert "Wrote" in simulate.stdout
    assert b"simulated" in csv_path.read_bytes()
    assert "Educational synthetic telemetry" in csv_path.read_text(encoding="utf-8")
    _assert_png(png_path)

    replay = subprocess.run(
        [sys.executable, "-m", "flightlog", "replay", str(csv_path), "--plot", str(replay_png)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "SIMULATED DATA" in replay.stdout
    assert "not read by the detector" in replay.stdout
    sim_events = _events_line(simulate.stdout)
    replay_events = _events_line(replay.stdout)
    assert sim_events == replay_events
    assert "liftoff=none" not in sim_events
    assert "apogee=none" not in sim_events
    assert "landing=none" not in sim_events
    _assert_png(replay_png)

    detect = subprocess.run(
        [sys.executable, "-m", "flightlog", "detect", str(csv_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert _events_line(detect.stdout) == sim_events


def test_plot_accepts_an_altitude_column_without_pressure_or_temperature(tmp_path):
    from flightlog.detect import detect
    from flightlog.generate import generate_flight
    from flightlog.log import FlightLog
    from flightlog.plot import plot_flight
    from tests.helpers import SHORT

    generated = generate_flight(SHORT, seed=1, pressure_noise_pa=5, temperature_noise_c=0.1)
    log = FlightLog(
        time_s=generated.log.time_s,
        altitude_m=generated.log.altitude_m,
        data_origin="measured",
        metadata={"data_origin": "measured"},
    )
    png_path = tmp_path / "altitude_only.png"
    events = plot_flight(log, png_path)
    assert events.liftoff is not None
    assert detect(log.time_s, log.altitude_m).liftoff.time_s == events.liftoff.time_s
    _assert_png(png_path)


def _events_line(stdout: str) -> str:
    matches = [line for line in stdout.splitlines() if line.startswith("events: ")]
    assert matches, stdout
    assert matches[-1].startswith("events: liftoff=")
    return matches[-1]


def _assert_png(path):
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 20_000
    image = mpimg.imread(path)
    assert image.shape[0] > 500
    assert image.shape[1] > 700
    assert float(image.std()) > 0.02
