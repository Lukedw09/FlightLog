import numpy as np
import pytest

from flightlog.atmosphere import (
    Atmosphere,
    altitude_agl_from_pressure,
    clamp_pressure_to_troposphere,
)
from flightlog.generate import generate_flight
from flightlog.trajectory import FlightSpec


def test_isa_sea_level_lapse_and_inverse():
    atmosphere = Atmosphere()
    assert atmosphere.pressure_pa(0) == pytest.approx(101325.0)
    assert atmosphere.temperature_c(0) == pytest.approx(15.0)
    assert atmosphere.temperature_c(1000) == pytest.approx(8.5)
    assert atmosphere.pressure_pa(1000) < atmosphere.pressure_pa(0)
    heights = np.array([0.0, 100.0, 800.0, 2500.0, 10000.0])
    recovered = atmosphere.altitude_amsl_m(atmosphere.pressure_pa(heights))
    assert np.allclose(recovered, heights, atol=1e-6)


def test_agl_subtracts_site_elevation():
    atmosphere = Atmosphere()
    on_the_pad = atmosphere.pressure_pa(150.0)
    assert altitude_agl_from_pressure(on_the_pad, atmosphere, 150.0) == pytest.approx(0.0, abs=1e-6)
    aloft = atmosphere.pressure_pa(190.0)
    assert altitude_agl_from_pressure(aloft, atmosphere, 150.0) == pytest.approx(40.0, abs=1e-6)


def test_reference_pressure_is_the_zero_altitude_pressure():
    atmosphere = Atmosphere(reference_pressure_pa=100000.0)
    assert atmosphere.pressure_pa(0) == pytest.approx(100000.0)


def test_troposphere_formula_rejects_the_stratosphere():
    with pytest.raises(ValueError, match="11 km"):
        Atmosphere().pressure_pa(12000)


def test_pressure_below_the_tropopause_is_clamped():
    atmosphere = Atmosphere()
    clamped, count = clamp_pressure_to_troposphere(
        np.array([101325.0, 1000.0, 50000.0]),
        atmosphere,
    )
    assert count == 1
    assert clamped[1] == pytest.approx(atmosphere.tropopause_pressure_pa())
    altitude = np.asarray(altitude_agl_from_pressure(clamped, atmosphere, 0.0))
    assert altitude[1] <= 11000.0 + 1e-4


def test_sketch_that_leaves_the_troposphere_is_refused():
    spec = FlightSpec(
        ground_s=1.0,
        boost_s=8.0,
        boost_accel_mps2=500.0,
        descent_rate_mps=50.0,
        landed_s=1.0,
        sample_hz=5.0,
        site_elevation_m=0.0,
    )
    with pytest.raises(ValueError, match="troposphere"):
        generate_flight(spec, seed=1, pressure_noise_pa=0, temperature_noise_c=0)
