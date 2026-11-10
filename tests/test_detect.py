import inspect
from dataclasses import replace

import numpy as np
import pytest

from flightlog.atmosphere import Atmosphere, altitude_agl_from_pressure
from flightlog.detect import detect
from flightlog.generate import generate_flight
from tests.helpers import SHORT


def test_detect_signature_is_time_and_altitude_only():
    assert list(inspect.signature(detect).parameters) == ["time_s", "altitude_m", "config"]


def test_clean_profile_orders_events_and_stays_near_the_simulator_clock():
    generated = generate_flight(SHORT, seed=4, pressure_noise_pa=0.0, temperature_noise_c=0.0)
    events = detect(generated.log.time_s, generated.log.altitude_m)
    bounds = generated.bounds
    assert events.liftoff is not None and events.apogee is not None and events.landing is not None
    assert events.liftoff.index < events.apogee.index < events.landing.index
    assert events.liftoff.time_s < events.apogee.time_s < events.landing.time_s
    assert bounds.t_liftoff_s - 0.05 <= events.liftoff.time_s <= bounds.t_liftoff_s + 1.25
    assert bounds.t_apogee_s - 0.25 <= events.apogee.time_s <= bounds.t_apogee_s + 1.0
    assert bounds.t_landing_s - 0.25 <= events.landing.time_s <= bounds.t_landing_s + 2.0
    assert events.liftoff.time_s > 1.0
    assert events.apogee.altitude_m == pytest.approx(bounds.h_apogee_m, abs=25)
    assert events.landing.altitude_m < 8
    assert events.apogee.altitude_m > events.liftoff.altitude_m + 50


def test_noisy_profile_keeps_order_inside_a_wider_tolerance():
    generated = generate_flight(SHORT, seed=11, pressure_noise_pa=30.0, temperature_noise_c=0.4)
    events = detect(generated.log.time_s, generated.log.altitude_m)
    bounds = generated.bounds
    assert events.liftoff is not None and events.apogee is not None and events.landing is not None
    assert events.liftoff.time_s < events.apogee.time_s < events.landing.time_s
    assert bounds.t_liftoff_s - 0.3 <= events.liftoff.time_s <= bounds.t_liftoff_s + 2.0
    assert abs(events.apogee.time_s - bounds.t_apogee_s) <= 1.5
    assert bounds.t_landing_s - 0.5 <= events.landing.time_s <= bounds.t_landing_s + 3.0
    assert events.apogee.altitude_m == pytest.approx(bounds.h_apogee_m, abs=40)
    assert events.liftoff.time_s > bounds.t_liftoff_s - 0.3


def test_pad_noise_does_not_look_like_liftoff():
    rng = np.random.Generator(np.random.PCG64(0))
    time = np.arange(25 * 40) / 25.0
    pressure = 101325.0 + rng.normal(0.0, 40.0, size=len(time))
    altitude = np.asarray(altitude_agl_from_pressure(pressure, Atmosphere(), 0.0), dtype=float)
    events = detect(time, altitude)
    assert events.liftoff is None
    assert events.apogee is None
    assert events.landing is None
    assert events.notes


def test_a_short_spike_does_not_count_as_liftoff():
    time = np.arange(0.0, 20.0, 0.05)
    altitude = np.zeros_like(time)
    altitude[(time >= 5.0) & (time < 5.15)] = 50.0
    events = detect(time, altitude)
    assert events.liftoff is None


def test_a_constant_offset_does_not_move_event_times():
    generated = generate_flight(SHORT, seed=3, pressure_noise_pa=10.0, temperature_noise_c=0.1)
    original = detect(generated.log.time_s, generated.log.altitude_m)
    shifted = detect(generated.log.time_s, generated.log.altitude_m + 1000.0)
    assert shifted.liftoff.time_s == pytest.approx(original.liftoff.time_s)
    assert shifted.apogee.time_s == pytest.approx(original.apogee.time_s)
    assert shifted.landing.time_s == pytest.approx(original.landing.time_s)
    assert shifted.apogee.altitude_m == pytest.approx(original.apogee.altitude_m + 1000.0, abs=0.05)


def test_a_log_that_ends_in_the_air_has_no_landing():
    generated = generate_flight(SHORT, seed=2, pressure_noise_pa=0.0, temperature_noise_c=0.0)
    bounds = generated.bounds
    cut = bounds.t_liftoff_s + 0.55 * (bounds.t_apogee_s - bounds.t_liftoff_s)
    mask = generated.log.time_s <= cut
    events = detect(generated.log.time_s[mask], generated.log.altitude_m_true[mask])
    assert events.liftoff is not None
    assert events.apogee is not None
    assert events.landing is None
    assert events.liftoff.time_s < events.apogee.time_s


def test_time_must_increase_and_noise_settings_must_be_sane():
    with pytest.raises(ValueError, match="strictly increasing"):
        detect(np.array([0, 1, 1, 2, 3, 4, 5, 6, 7, 8], dtype=float), np.zeros(10))
    with pytest.raises(ValueError, match="seed"):
        generate_flight(SHORT, seed=-1, pressure_noise_pa=0, temperature_noise_c=0)
    with pytest.raises(ValueError, match="boost"):
        generate_flight(
            replace(SHORT, boost_accel_mps2=-5),
            seed=1,
            pressure_noise_pa=0,
            temperature_noise_c=0,
        )
