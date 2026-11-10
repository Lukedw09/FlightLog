"""Find liftoff, apogee, and landing from the altitude estimate alone.

The function takes time and altitude. It does not take phase labels, true
altitude, or the simulator clock. Run it on a finished log. The smoother
uses each sample and a short stretch of samples before it, never samples
from later in the log. That still does not make it a flight computer: it
does not command anything, and the confirmation window means the reported
liftoff and landing times are recognized slightly after the fact.

Pad noise is handled in three ways:

* the baseline and its scatter come from the opening seconds
* liftoff has to clear several standard deviations, and at least a few meters
* the climb has to stay above that bar for a short run of samples

A single spike does not last long enough. A flight that never clears the
bar is reported as no liftoff. That miss is intentional.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DetectionConfig:
    """Knobs for the post-flight detector. Distances are meters."""

    smooth_window_s: float = 0.6
    # Short on purpose. A spike that the smoother stretches into a flat bump
    # then has almost no climb rate, so it cannot hold this test. The landing
    # check uses a longer window so a recent descent still counts as motion.
    liftoff_velocity_window_s: float = 0.3
    landing_velocity_window_s: float = 1.0
    baseline_window_s: float = 2.0
    min_liftoff_altitude_m: float = 5.0
    noise_sigma_factor: float = 8.0
    min_climb_mps: float = 3.0
    liftoff_sustain_s: float = 0.5
    landing_band_m: float = 4.0
    max_landing_speed_mps: float = 2.5
    landing_sustain_s: float = 0.8
    min_apogee_clearance_m: float = 12.0

    def validate(self) -> None:
        for name, value in (
            ("smooth_window_s", self.smooth_window_s),
            ("liftoff_velocity_window_s", self.liftoff_velocity_window_s),
            ("landing_velocity_window_s", self.landing_velocity_window_s),
            ("baseline_window_s", self.baseline_window_s),
            ("min_liftoff_altitude_m", self.min_liftoff_altitude_m),
            ("noise_sigma_factor", self.noise_sigma_factor),
            ("min_climb_mps", self.min_climb_mps),
            ("liftoff_sustain_s", self.liftoff_sustain_s),
            ("landing_band_m", self.landing_band_m),
            ("max_landing_speed_mps", self.max_landing_speed_mps),
            ("landing_sustain_s", self.landing_sustain_s),
            ("min_apogee_clearance_m", self.min_apogee_clearance_m),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive number.")


@dataclass(frozen=True)
class FlightEvent:
    """One detected event. ``altitude_m`` is the smoothed estimate."""

    name: str
    time_s: float
    altitude_m: float
    index: int


@dataclass(frozen=True)
class DetectionResult:
    liftoff: FlightEvent | None
    apogee: FlightEvent | None
    landing: FlightEvent | None
    baseline_m: float
    robust_sigma_m: float
    altitude_clearance_m: float
    smoothed_altitude_m: np.ndarray
    notes: tuple[str, ...]


def detect(
    time_s: np.ndarray,
    altitude_m: np.ndarray,
    config: DetectionConfig | None = None,
) -> DetectionResult:
    """Detect liftoff, apogee, and landing from a measured altitude series."""
    cfg = config if config is not None else DetectionConfig()
    cfg.validate()
    time = np.asarray(time_s, dtype=float)
    altitude = np.asarray(altitude_m, dtype=float)
    _validate_series(time, altitude)
    dt = float(np.median(np.diff(time)))
    smooth_n = _span_samples(cfg.smooth_window_s, dt, minimum=1)
    smoothed = trailing_average(altitude, smooth_n)
    climb = trailing_velocity(smoothed, time, cfg.liftoff_velocity_window_s)
    settling = trailing_velocity(smoothed, time, cfg.landing_velocity_window_s)

    base_n = _span_samples(cfg.baseline_window_s, dt, minimum=5)
    base_n = min(base_n, max(5, len(time) // 5))
    baseline, sigma = _robust_sigma(altitude[:base_n])
    clearance = max(cfg.min_liftoff_altitude_m, cfg.noise_sigma_factor * sigma)
    liftoff_n = _span_samples(cfg.liftoff_sustain_s, dt, minimum=3)
    landing_n = _span_samples(cfg.landing_sustain_s, dt, minimum=3)

    liftoff_mask = (smoothed > baseline + clearance) & (climb > cfg.min_climb_mps)
    liftoff_idx = _first_run(liftoff_mask, liftoff_n)
    notes: list[str] = []
    if liftoff_idx is None:
        notes.append(
            "No liftoff detected. The smoothed altitude never stayed above the "
            "pad-noise clearance while the recent climb was fast enough."
        )
        return _result(None, None, None, baseline, sigma, clearance, smoothed, notes)

    liftoff = _event("liftoff", liftoff_idx, time, smoothed)
    apogee_idx = liftoff_idx + int(np.argmax(smoothed[liftoff_idx:]))
    apogee_bar = max(cfg.min_apogee_clearance_m, clearance)
    if apogee_idx <= liftoff_idx or smoothed[apogee_idx] < baseline + apogee_bar:
        notes.append(
            "Liftoff was found, but the altitude estimate never rose far enough "
            "above the pad to call an apogee."
        )
        return _result(liftoff, None, None, baseline, sigma, clearance, smoothed, notes)

    apogee = _event("apogee", apogee_idx, time, smoothed)
    if apogee_idx >= len(time) - 2:
        notes.append(
            "The maximum is at the end of the log. The vehicle may still be climbing, "
            "so this apogee is only the highest sample in the file."
        )

    band = max(cfg.landing_band_m, 2.0 * sigma)
    on_pad = np.abs(smoothed - baseline) <= band
    settled = np.abs(settling) <= cfg.max_landing_speed_mps
    landing_idx = _first_run(on_pad & settled, landing_n, start=apogee_idx + 1)
    if landing_idx is None:
        notes.append(
            "No landing detected after apogee. The log may end in the air, or the "
            "estimate never settled near the pad altitude."
        )
        landing = None
    else:
        landing = _event("landing", landing_idx, time, smoothed)
    return _result(liftoff, apogee, landing, baseline, sigma, clearance, smoothed, notes)


def trailing_average(values: np.ndarray, window: int) -> np.ndarray:
    """Average of the current sample and up to ``window - 1`` samples before it."""
    data = np.asarray(values, dtype=float)
    if window <= 1:
        return data.copy()
    cumulative = np.cumsum(data)
    index = np.arange(len(data))
    start = index - window + 1
    out = np.empty(len(data), dtype=float)
    short = start <= 0
    out[short] = cumulative[short] / (index[short] + 1)
    long = ~short
    out[long] = (cumulative[index[long]] - cumulative[start[long] - 1]) / window
    return out


def trailing_velocity(altitude_m: np.ndarray, time_s: np.ndarray, window_s: float) -> np.ndarray:
    """Climb rate from the change over the recent ``window_s`` seconds."""
    altitude = np.asarray(altitude_m, dtype=float)
    time = np.asarray(time_s, dtype=float)
    dt = float(np.median(np.diff(time)))
    back = _span_samples(window_s, dt, minimum=1)
    index = np.arange(len(altitude))
    earlier = np.clip(index - back, 0, len(altitude) - 1)
    elapsed = time[index] - time[earlier]
    speed = np.zeros(len(altitude), dtype=float)
    ok = elapsed > 0
    speed[ok] = (altitude[index[ok]] - altitude[earlier[ok]]) / elapsed[ok]
    return speed


def _robust_sigma(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    # 1.4826 scales the median absolute deviation to a standard deviation
    # when the scatter is roughly bell-shaped. On a perfectly flat pad it is 0.
    return median, 1.4826 * mad


def _span_samples(seconds: float, dt: float, minimum: int) -> int:
    if dt <= 0:
        raise ValueError("sample interval must be positive.")
    return max(minimum, int(math.floor(seconds / dt + 0.5)))


def _first_run(mask: np.ndarray, length: int, start: int = 0) -> int | None:
    """Index where a run of ``length`` true samples begins, or None."""
    if length < 1:
        raise ValueError("run length must be at least 1.")
    run = 0
    for i in range(max(0, start), len(mask)):
        if mask[i]:
            run += 1
            if run >= length:
                return i - length + 1
        else:
            run = 0
    return None


def _event(name: str, index: int, time_s: np.ndarray, smoothed: np.ndarray) -> FlightEvent:
    return FlightEvent(
        name=name,
        time_s=float(time_s[index]),
        altitude_m=float(smoothed[index]),
        index=int(index),
    )


def _result(
    liftoff: FlightEvent | None,
    apogee: FlightEvent | None,
    landing: FlightEvent | None,
    baseline: float,
    sigma: float,
    clearance: float,
    smoothed: np.ndarray,
    notes: list[str],
) -> DetectionResult:
    return DetectionResult(
        liftoff=liftoff,
        apogee=apogee,
        landing=landing,
        baseline_m=baseline,
        robust_sigma_m=sigma,
        altitude_clearance_m=clearance,
        smoothed_altitude_m=smoothed,
        notes=tuple(notes),
    )


def _validate_series(time_s: np.ndarray, altitude_m: np.ndarray) -> None:
    if time_s.ndim != 1 or altitude_m.ndim != 1:
        raise ValueError("time_s and altitude_m must be one-dimensional.")
    if len(time_s) != len(altitude_m):
        raise ValueError("time_s and altitude_m must be the same length.")
    if len(time_s) < 10:
        raise ValueError("Need at least 10 samples to look for flight events.")
    if not np.all(np.isfinite(time_s)):
        raise ValueError("time_s has a non-numeric value.")
    if np.any(np.diff(time_s) <= 0):
        raise ValueError("time_s must be strictly increasing.")
    if not np.all(np.isfinite(altitude_m)):
        raise ValueError("altitude_m has an empty or non-numeric value.")
