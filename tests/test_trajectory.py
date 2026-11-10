import numpy as np
import pytest

from flightlog.generate import generate_flight
from flightlog.trajectory import flight_bounds, state_at
from tests.helpers import SHORT, independent_clock


def test_analytic_clock_matches_an_independent_formula():
    bounds = flight_bounds(SHORT)
    apogee_m, apogee_s, landing_s, liftoff_s = independent_clock(SHORT)
    assert bounds.t_liftoff_s == pytest.approx(liftoff_s)
    assert bounds.h_apogee_m == pytest.approx(apogee_m)
    assert bounds.t_apogee_s == pytest.approx(apogee_s)
    assert bounds.t_landing_s == pytest.approx(landing_s)
    assert bounds.h_apogee_m > 400


def test_phases_follow_ground_ascent_coast_descent_landed():
    generated = generate_flight(SHORT, seed=1, pressure_noise_pa=0, temperature_noise_c=0)
    order = []
    counts = {}
    for phase in generated.log.phase_true:
        counts[phase] = counts.get(phase, 0) + 1
        if not order or order[-1] != phase:
            order.append(phase)
    assert order == ["ground", "ascent", "coast", "descent", "landed"]
    assert all(counts[name] > 5 for name in order)


def test_altitude_is_continuous_and_velocity_jumps_only_at_apogee():
    bounds = flight_bounds(SHORT)
    for boundary in (
        bounds.t_liftoff_s,
        bounds.t_burnout_s,
        bounds.t_apogee_s,
        bounds.t_landing_s,
    ):
        before, _, _ = state_at(boundary - 1e-6, SHORT, bounds)
        at, _, _ = state_at(boundary, SHORT, bounds)
        assert at == pytest.approx(before, abs=1e-3)

    _, speed_before, phase_before = state_at(bounds.t_burnout_s - 1e-6, SHORT, bounds)
    _, speed_at, phase_at = state_at(bounds.t_burnout_s, SHORT, bounds)
    assert phase_before == "ascent"
    assert phase_at == "coast"
    assert speed_at == pytest.approx(speed_before, rel=1e-5)

    _, speed_before, phase_before = state_at(bounds.t_apogee_s - 1e-6, SHORT, bounds)
    _, speed_at, phase_at = state_at(bounds.t_apogee_s, SHORT, bounds)
    assert phase_before == "coast"
    assert phase_at == "descent"
    assert speed_before == pytest.approx(0.0, abs=1e-2)
    assert speed_at == pytest.approx(-SHORT.descent_rate_mps)


def test_ground_and_landed_are_still_and_the_middle_moves_the_right_way():
    generated = generate_flight(SHORT, seed=1, pressure_noise_pa=0, temperature_noise_c=0)
    altitude = generated.log.altitude_m_true
    phase = generated.log.phase_true
    assert np.all(altitude[phase == "ground"] == 0.0)
    assert np.all(altitude[phase == "landed"] == 0.0)
    assert np.all(np.diff(altitude[phase == "ascent"]) > 0)
    assert np.all(np.diff(altitude[phase == "descent"]) < 0)
    assert altitude.min() >= -1e-9
    apogee_index = int(np.argmin(np.abs(generated.log.time_s - generated.bounds.t_apogee_s)))
    assert generated.log.pressure_pa_true[apogee_index] < generated.log.pressure_pa_true[0] - 1000
    assert generated.log.temperature_c_true[apogee_index] < generated.log.temperature_c_true[0] - 1


def test_zero_noise_estimate_matches_the_true_path_including_site_elevation():
    from dataclasses import replace

    spec = replace(SHORT, site_elevation_m=250.0)
    generated = generate_flight(spec, seed=5, pressure_noise_pa=0.0, temperature_noise_c=0.0)
    log = generated.log
    assert log.altitude_m[0] == pytest.approx(0.0, abs=1e-6)
    assert np.allclose(log.altitude_m, log.altitude_m_true, atol=1e-6)
    assert np.allclose(log.pressure_pa, log.pressure_pa_true, atol=1e-6)
    assert np.allclose(log.temperature_c, log.temperature_c_true, atol=1e-6)
    assert log.pressure_pa_true[0] < 101325.0
    assert log.temperature_c_true[0] == pytest.approx(15.0 - 0.0065 * 250.0, abs=1e-6)
    assert log.data_origin == "simulated"
    assert "simulated" == log.metadata["data_origin"]
