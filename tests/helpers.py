"""Shared flight sketch for tests. The formula here is intentionally separate."""

from __future__ import annotations

from flightlog.trajectory import FlightSpec

SHORT = FlightSpec(
    ground_s=5.0,
    boost_s=2.0,
    boost_accel_mps2=45.0,
    descent_rate_mps=12.0,
    landed_s=6.0,
    sample_hz=25.0,
    site_elevation_m=0.0,
)


def independent_clock(spec: FlightSpec) -> tuple[float, float, float, float]:
    """Apogee altitude, apogee time, landing time, liftoff time.

    Constant net acceleration, then a drag-free coast, then a constant sink.
    Kept here so a copy-paste bug in flight_bounds does not hide itself.
    """
    speed = spec.boost_accel_mps2 * spec.boost_s
    burnout = 0.5 * spec.boost_accel_mps2 * spec.boost_s * spec.boost_s
    apogee_m = burnout + speed * speed / (2.0 * spec.gravity_mps2)
    apogee_s = spec.ground_s + spec.boost_s + speed / spec.gravity_mps2
    landing_s = apogee_s + apogee_m / spec.descent_rate_mps
    return apogee_m, apogee_s, landing_s, spec.ground_s
