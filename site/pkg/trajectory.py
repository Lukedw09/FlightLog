"""One-dimensional flight sketch used only to build synthetic telemetry.

The vehicle moves straight up and straight down. There is no wind, no
thrust curve, and no drag. Phases, in order:

* ground — sitting on the pad at 0 m above ground level
* ascent — constant net upward acceleration until burnout
* coast — ballistic, acceleration is -g, until vertical speed is zero
* descent — parachute opens at apogee and the vehicle sinks at a constant rate
* landed — back on the pad at 0 m

Altitude is continuous. Vertical speed jumps at apogee, from about zero to
the sink rate. That jump is the "parachute opens instantly" assumption.
It is not how a recovery system works.

Net ascent acceleration already includes gravity. It is whatever upward
acceleration you type in, not a motor designation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from flightlog.constants import GRAVITY_MPS2, TROPOPAUSE_M


@dataclass(frozen=True)
class FlightSpec:
    """Knobs for the sketch. Times are seconds. Distances are meters."""

    ground_s: float = 8.0
    boost_s: float = 2.8
    boost_accel_mps2: float = 35.0
    descent_rate_mps: float = 7.5
    landed_s: float = 10.0
    sample_hz: float = 25.0
    site_elevation_m: float = 150.0
    gravity_mps2: float = GRAVITY_MPS2

    def validate(self) -> None:
        _require_positive("sample rate (Hz)", self.sample_hz)
        _require_positive("boost time (s)", self.boost_s)
        _require_positive("boost acceleration (m/s^2)", self.boost_accel_mps2)
        _require_positive("descent rate (m/s)", self.descent_rate_mps)
        _require_positive("gravity (m/s^2)", self.gravity_mps2)
        if self.ground_s < 0 or not math.isfinite(self.ground_s):
            raise ValueError("ground time cannot be negative.")
        if self.landed_s < 0 or not math.isfinite(self.landed_s):
            raise ValueError("landed time cannot be negative.")
        if not math.isfinite(self.site_elevation_m):
            raise ValueError("site elevation must be a finite number of meters.")
        if self.site_elevation_m < -500 or self.site_elevation_m > 5000:
            raise ValueError(
                "site elevation must be between -500 m and 5000 m for this sketch."
            )


@dataclass(frozen=True)
class FlightBounds:
    """Clock times of the sketch. These are simulator truth, not detections."""

    t_liftoff_s: float
    t_burnout_s: float
    t_apogee_s: float
    t_landing_s: float
    t_end_s: float
    h_burnout_m: float
    v_burnout_mps: float
    h_apogee_m: float


def flight_bounds(spec: FlightSpec) -> FlightBounds:
    spec.validate()
    t_liftoff = spec.ground_s
    t_burnout = t_liftoff + spec.boost_s
    v_burnout = spec.boost_accel_mps2 * spec.boost_s
    h_burnout = 0.5 * spec.boost_accel_mps2 * spec.boost_s * spec.boost_s
    t_coast = v_burnout / spec.gravity_mps2
    t_apogee = t_burnout + t_coast
    h_apogee = h_burnout + (v_burnout * v_burnout) / (2.0 * spec.gravity_mps2)
    t_landing = t_apogee + h_apogee / spec.descent_rate_mps
    t_end = t_landing + spec.landed_s
    amsl_apogee = spec.site_elevation_m + h_apogee
    if amsl_apogee > TROPOPAUSE_M:
        raise ValueError(
            "The simulated apogee would be above 11 km above mean sea level "
            f"({amsl_apogee:.0f} m). The pressure model is the ISA troposphere only. "
            "Reduce boost acceleration, burn time, or site elevation."
        )
    return FlightBounds(
        t_liftoff_s=t_liftoff,
        t_burnout_s=t_burnout,
        t_apogee_s=t_apogee,
        t_landing_s=t_landing,
        t_end_s=t_end,
        h_burnout_m=h_burnout,
        v_burnout_mps=v_burnout,
        h_apogee_m=h_apogee,
    )


def state_at(time_s: float, spec: FlightSpec, bounds: FlightBounds) -> tuple[float, float, str]:
    """Return altitude AGL (m), vertical speed (m/s, up positive), and phase name."""
    t = float(time_s)
    if t < bounds.t_liftoff_s:
        return 0.0, 0.0, "ground"
    if t < bounds.t_burnout_s:
        tau = t - bounds.t_liftoff_s
        accel = spec.boost_accel_mps2
        return 0.5 * accel * tau * tau, accel * tau, "ascent"
    if t < bounds.t_apogee_s:
        tau = t - bounds.t_burnout_s
        speed = bounds.v_burnout_mps - spec.gravity_mps2 * tau
        altitude = (
            bounds.h_burnout_m
            + bounds.v_burnout_mps * tau
            - 0.5 * spec.gravity_mps2 * tau * tau
        )
        return altitude, speed, "coast"
    if t < bounds.t_landing_s:
        tau = t - bounds.t_apogee_s
        altitude = bounds.h_apogee_m - spec.descent_rate_mps * tau
        if altitude < 0.0:
            altitude = 0.0
        return altitude, -spec.descent_rate_mps, "descent"
    return 0.0, 0.0, "landed"


def sample_times(spec: FlightSpec, bounds: FlightBounds) -> np.ndarray:
    """Inclusive sample clock from 0 to the end of the landed phase."""
    intervals = int(round(bounds.t_end_s * spec.sample_hz))
    if intervals < 2:
        raise ValueError(
            "The flight is too short for this sample rate. Raise the sample rate "
            "or lengthen a phase."
        )
    if intervals + 1 > 500_000:
        raise ValueError(
            f"This would generate {intervals + 1} samples, above the 500000 limit. "
            "Lower the sample rate or shorten the flight."
        )
    return np.linspace(0.0, bounds.t_end_s, intervals + 1)


def sample_states(
    spec: FlightSpec, bounds: FlightBounds, times: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    altitude = np.empty(len(times), dtype=float)
    velocity = np.empty(len(times), dtype=float)
    phase = np.empty(len(times), dtype=object)
    for i, time in enumerate(times):
        altitude[i], velocity[i], phase[i] = state_at(float(time), spec, bounds)
    return altitude, velocity, phase.astype(str)


def _require_positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number.")
