"""Plain-text report. Simulator truth is printed only as a comparison.

The comparison is labeled as unused by the detector. Event times come from
``detect``, which sees the altitude estimate and the clock only.
"""

from __future__ import annotations

import textwrap

import numpy as np

from flightlog.constants import DISCLAIMER
from flightlog.detect import DetectionConfig, DetectionResult, FlightEvent
from flightlog.log import FlightLog


def render_report(
    log: FlightLog,
    events: DetectionResult,
    config: DetectionConfig | None = None,
) -> str:
    cfg = config if config is not None else DetectionConfig()
    lines: list[str] = []
    if log.simulated:
        lines.append("flightlog — SIMULATED DATA")
        lines.append(_wrap(DISCLAIMER))
    else:
        lines.append(f"flightlog — data origin: {log.data_origin}")
        lines.append("Events below come from the altitude estimate only.")
    lines.append("")
    duration = float(log.time_s[-1] - log.time_s[0])
    dt = float(np.median(np.diff(log.time_s)))
    rate = 1.0 / dt if dt > 0 else float("nan")
    lines.append(
        f"Samples: {len(log)}    duration: {duration:.2f} s    "
        f"median interval: {dt:.4f} s ({rate:.2f} Hz)"
    )
    sketch = _sketch_lines(log)
    if sketch:
        lines.append("")
        lines.append("Sketch inputs (not measurements)")
        lines.extend(sketch)
    lines.append("")
    lines.append(_wrap(_atmosphere_line(log)))
    if log.altitude_derived:
        lines.append(
            "altitude_m was derived from pressure_pa with the ISA troposphere "
            "inversion. It is not a separate sensor."
        )
    else:
        lines.append(
            "Detection used the altitude_m column as stored. Pressure was not re-inverted."
        )
    if np.any(log.altitude_m > 11000):
        lines.append(
            "Warning: some altitude estimates are above 11 km. "
            "The ISA troposphere formula does not apply there."
        )
    clamped = log.metadata.get("pressure_samples_clamped", "")
    if clamped not in ("", "0"):
        lines.append(
            f"Warning: {clamped} pressure samples were clamped at the 11 km floor."
        )
    lines.append("")
    lines.append(
        f"Pad baseline: {events.baseline_m:.2f} m    "
        f"pad scatter (robust): {events.robust_sigma_m:.2f} m    "
        f"liftoff clearance: {events.altitude_clearance_m:.2f} m"
    )
    lines.append(
        _wrap(
            "Liftoff clearance is the larger of "
            f"{cfg.min_liftoff_altitude_m:.0f} m and {cfg.noise_sigma_factor:.0f} "
            "robust standard deviations of the opening seconds."
        )
    )
    lines.append("")
    lines.append("Detected from the altitude estimate only")
    lines.extend(_event_lines(events))
    truth = _truth(log)
    if truth is not None:
        lines.append("")
        lines.append(f"Simulator truth — not read by the detector ({truth['source']})")
        lines.extend(_truth_lines(truth))
        lines.extend(_comparison_lines(events, truth))
    if events.notes:
        lines.append("")
        for note in events.notes:
            lines.append(_wrap(note))
    lines.append("")
    lines.append(
        _wrap(
            "Limitations: this is a post-flight check, not a flight computer. "
            "Liftoff waits until the climb clears pad noise and holds that climb. "
            "Apogee is the peak of the smoothed estimate, so it can sit a fraction "
            "of a second off the true peak. Landing waits until recent motion has "
            "died away, so it lags touchdown by about a second on the sample flight. "
            "A very low flight, or a very slow descent, can be missed or marked late. "
            "Not for flight safety or flight control."
        )
    )
    lines.append(events_line(events))
    return "\n".join(lines) + "\n"


def events_line(events: DetectionResult) -> str:
    return (
        f"events: liftoff={_stamp(events.liftoff)} "
        f"apogee={_stamp(events.apogee)} landing={_stamp(events.landing)}"
    )


def _stamp(event: FlightEvent | None) -> str:
    if event is None:
        return "none"
    return f"{event.time_s:.6f}"


def _event_lines(events: DetectionResult) -> list[str]:
    rows = []
    labels = (
        (events.liftoff, "liftoff"),
        (events.apogee, "apogee"),
        (events.landing, "landing"),
    )
    for event, name in labels:
        if event is None:
            rows.append(f"  {name:<8} not detected")
        else:
            rows.append(
                f"  {name:<8} {event.time_s:8.3f} s    "
                f"smoothed estimate {event.altitude_m:8.1f} m AGL"
            )
    return rows


def _sketch_lines(log: FlightLog) -> list[str]:
    meta = log.metadata
    needed = ("ground_s", "boost_s", "boost_accel_mps2", "descent_rate_mps", "landed_s")
    if not all(key in meta for key in needed):
        return []
    lines = [
        (
            f"  ground {meta['ground_s']} s, boost {meta['boost_s']} s at "
            f"{meta['boost_accel_mps2']} m/s^2 net, "
            f"parachute sink {meta['descent_rate_mps']} m/s, "
            f"landed {meta['landed_s']} s"
        )
    ]
    if "seed" in meta:
        noise = ""
        if "pressure_noise_pa" in meta and "temperature_noise_c" in meta:
            noise = (
                f", noise {meta['pressure_noise_pa']} Pa and "
                f"{meta['temperature_noise_c']} °C"
            )
        lines.append(f"  seed {meta['seed']}{noise}")
    return lines


def _atmosphere_line(log: FlightLog) -> str:
    pressure = log.metadata.get("reference_pressure_pa", "101325")
    site = log.metadata.get("site_elevation_m", "0")
    return (
        f"Atmosphere: ISA troposphere. Reference pressure {pressure} Pa. "
        f"Site elevation {site} m. "
        "altitude_m is meters above the launch site, not above sea level."
    )


def _truth(log: FlightLog) -> dict | None:
    found: dict[str, float | str] = {}
    for name, key in (
        ("liftoff_s", "truth_liftoff_s"),
        ("burnout_s", "truth_burnout_s"),
        ("apogee_s", "truth_apogee_s"),
        ("apogee_m", "truth_apogee_m"),
        ("landing_s", "truth_landing_s"),
    ):
        raw = log.metadata.get(key, "")
        if raw:
            found[name] = float(raw)
    if found:
        found["source"] = "simulator clock stored in the CSV header"
        return found
    if log.altitude_m_true is not None:
        index = int(np.argmax(log.altitude_m_true))
        return {
            "apogee_s": float(log.time_s[index]),
            "apogee_m": float(log.altitude_m_true[index]),
            "source": "highest altitude_m_true sample in the file",
        }
    return None


def _truth_lines(truth: dict) -> list[str]:
    lines = []
    if "liftoff_s" in truth:
        lines.append(f"  liftoff  {truth['liftoff_s']:8.3f} s")
    if "burnout_s" in truth:
        lines.append(f"  burnout  {truth['burnout_s']:8.3f} s")
    if "apogee_s" in truth and "apogee_m" in truth:
        lines.append(
            f"  apogee   {truth['apogee_s']:8.3f} s    {truth['apogee_m']:8.1f} m AGL"
        )
    elif "apogee_s" in truth:
        lines.append(f"  apogee   {truth['apogee_s']:8.3f} s")
    if "landing_s" in truth:
        lines.append(f"  landing  {truth['landing_s']:8.3f} s")
    return lines


def _comparison_lines(events: DetectionResult, truth: dict) -> list[str]:
    lines = []
    pairs = (
        (events.liftoff, "liftoff_s", None, "liftoff"),
        (events.apogee, "apogee_s", "apogee_m", "apogee"),
        (events.landing, "landing_s", None, "landing"),
    )
    for event, time_key, alt_key, name in pairs:
        if event is None or time_key not in truth:
            continue
        delta_t = event.time_s - float(truth[time_key])
        extra = ""
        if alt_key is not None and alt_key in truth:
            delta_h = event.altitude_m - float(truth[alt_key])
            extra = f", {delta_h:+.1f} m"
        lines.append(f"  {name} detection minus truth: {delta_t:+.2f} s{extra}")
    return lines


def _wrap(text: str) -> str:
    return textwrap.fill(text, width=78)
