"""Build a simulated log: true sketch, then independent Gaussian noise.

Noise is applied to pressure and temperature. Altitude in ``altitude_m``
is not a third sensor. It is the ISA inversion of the noisy pressure,
minus site elevation. The seed fixes both noise draws, pressure first,
then temperature, so the same seed repeats the same file.

Nothing here is a barometer model. The standard deviations are plain
numbers in pascals and degrees Celsius.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from flightlog.atmosphere import (
    Atmosphere,
    altitude_agl_from_pressure,
    clamp_pressure_to_troposphere,
)
from flightlog.constants import DISCLAIMER, SCHEMA, VERSION
from flightlog.log import FlightLog
from flightlog.trajectory import FlightBounds, FlightSpec, flight_bounds, sample_states, sample_times


SYNTHETIC_CLOCK = "2026-01-01T00:00:00Z"


@dataclass(frozen=True)
class GeneratedFlight:
    log: FlightLog
    spec: FlightSpec
    bounds: FlightBounds
    atmosphere: Atmosphere
    seed: int
    pressure_noise_pa: float
    temperature_noise_c: float


def generate_flight(
    spec: FlightSpec | None = None,
    *,
    seed: int = 42,
    pressure_noise_pa: float = 18.0,
    temperature_noise_c: float = 0.25,
    atmosphere: Atmosphere | None = None,
    start_utc: str = SYNTHETIC_CLOCK,
) -> GeneratedFlight:
    spec = spec if spec is not None else FlightSpec()
    atmosphere = atmosphere if atmosphere is not None else Atmosphere()
    spec.validate()
    atmosphere.validate()
    _validate_noise(seed, pressure_noise_pa, temperature_noise_c)
    bounds = flight_bounds(spec)
    times = sample_times(spec, bounds)
    altitude_true, _velocity, phase = sample_states(spec, bounds, times)
    amsl = altitude_true + spec.site_elevation_m
    pressure_true = np.asarray(atmosphere.pressure_pa(amsl), dtype=float)
    temperature_true = np.asarray(atmosphere.temperature_c(amsl), dtype=float)

    rng = np.random.Generator(np.random.PCG64(seed))
    pressure_noise = rng.normal(0.0, pressure_noise_pa, size=len(times))
    temperature_noise = rng.normal(0.0, temperature_noise_c, size=len(times))
    measured_pressure, n_clamped = clamp_pressure_to_troposphere(
        pressure_true + pressure_noise, atmosphere
    )
    measured_pressure = np.asarray(measured_pressure, dtype=float)
    measured_temperature = temperature_true + temperature_noise
    altitude_est = np.asarray(
        altitude_agl_from_pressure(measured_pressure, atmosphere, spec.site_elevation_m),
        dtype=float,
    )
    start = _parse_utc(start_utc)
    timestamps = _timestamps(start, times)
    metadata = _metadata(
        spec=spec,
        bounds=bounds,
        atmosphere=atmosphere,
        seed=seed,
        pressure_noise_pa=pressure_noise_pa,
        temperature_noise_c=temperature_noise_c,
        start_utc=_format_utc(start),
        n_clamped=n_clamped,
    )
    log = FlightLog(
        time_s=times,
        altitude_m=altitude_est,
        pressure_pa=measured_pressure,
        temperature_c=measured_temperature,
        timestamp_utc=timestamps,
        data_origin="simulated",
        altitude_m_true=altitude_true,
        pressure_pa_true=pressure_true,
        temperature_c_true=temperature_true,
        phase_true=phase,
        altitude_derived=False,
        metadata=metadata,
    )
    return GeneratedFlight(
        log=log,
        spec=spec,
        bounds=bounds,
        atmosphere=atmosphere,
        seed=seed,
        pressure_noise_pa=pressure_noise_pa,
        temperature_noise_c=temperature_noise_c,
    )


def _validate_noise(seed: int, pressure_noise_pa: float, temperature_noise_c: float) -> None:
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be zero or a positive integer.")
    if pressure_noise_pa < 0 or not np.isfinite(pressure_noise_pa):
        raise ValueError("pressure noise must be zero or a positive standard deviation in pascals.")
    if temperature_noise_c < 0 or not np.isfinite(temperature_noise_c):
        raise ValueError(
            "temperature noise must be zero or a positive standard deviation in degrees Celsius."
        )


def _parse_utc(text: str) -> datetime:
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            "start time must look like 2026-01-01T00:00:00Z."
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError("start time must include a timezone, for example 2026-01-01T00:00:00Z.")
    return parsed.astimezone(timezone.utc)


def _format_utc(moment: datetime) -> str:
    moment = moment.astimezone(timezone.utc)
    millis = moment.microsecond // 1000
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def _timestamps(start: datetime, time_s: np.ndarray) -> np.ndarray:
    start_us = int(round(start.timestamp() * 1_000_000))
    labels = []
    for t in time_s:
        us = start_us + int(round(float(t) * 1_000_000))
        moment = datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc)
        labels.append(_format_utc(moment))
    return np.asarray(labels, dtype=object)


def _fmt(value: float | int) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.10g}"


def _metadata(
    *,
    spec: FlightSpec,
    bounds: FlightBounds,
    atmosphere: Atmosphere,
    seed: int,
    pressure_noise_pa: float,
    temperature_noise_c: float,
    start_utc: str,
    n_clamped: int,
) -> dict[str, str]:
    return {
        "schema": SCHEMA,
        "data_origin": "simulated",
        "disclaimer": DISCLAIMER,
        "generator": f"flightlog {VERSION}",
        "clock": "synthetic_utc",
        "start_utc": start_utc,
        "units": (
            "time_s seconds from log start; timestamp_utc synthetic; "
            "altitude_m meters above the launch site; pressure_pa pascals; "
            "temperature_c degrees Celsius"
        ),
        "atmosphere": "ISA troposphere hydrostatic dry air, constant lapse rate, standard day",
        "reference_pressure_pa": _fmt(atmosphere.reference_pressure_pa),
        "reference_temperature_k": _fmt(atmosphere.reference_temperature_k),
        "lapse_rate_k_per_m": _fmt(atmosphere.lapse_rate_k_per_m),
        "gravity_mps2": _fmt(atmosphere.gravity_mps2),
        "gas_constant_j_per_kg_k": _fmt(atmosphere.gas_constant_j_per_kg_k),
        "tropopause_m": _fmt(atmosphere.tropopause_m),
        "site_elevation_m": _fmt(spec.site_elevation_m),
        "altitude_m_meaning": (
            "ISA troposphere inversion of pressure_pa, minus site_elevation_m. "
            "Not an independent altitude sensor"
        ),
        "phase_true_note": (
            "Simulator bookkeeping only. Event detection does not read this column"
        ),
        "sample_hz": _fmt(spec.sample_hz),
        "seed": _fmt(seed),
        "pressure_noise_pa": _fmt(pressure_noise_pa),
        "temperature_noise_c": _fmt(temperature_noise_c),
        "pressure_samples_clamped": _fmt(n_clamped),
        "ground_s": _fmt(spec.ground_s),
        "boost_s": _fmt(spec.boost_s),
        "boost_accel_mps2": _fmt(spec.boost_accel_mps2),
        "descent_rate_mps": _fmt(spec.descent_rate_mps),
        "landed_s": _fmt(spec.landed_s),
        "truth_liftoff_s": _fmt(bounds.t_liftoff_s),
        "truth_burnout_s": _fmt(bounds.t_burnout_s),
        "truth_apogee_s": _fmt(bounds.t_apogee_s),
        "truth_apogee_m": _fmt(bounds.h_apogee_m),
        "truth_landing_s": _fmt(bounds.t_landing_s),
        "truth_end_s": _fmt(bounds.t_end_s),
        "assumptions": (
            "1D vertical sketch; constant net ascent acceleration; coast is drag-free "
            "under constant g; parachute opens at apogee and sinks at a constant rate; "
            "sensor noise is independent Gaussian white noise, not a hardware model"
        ),
    }
