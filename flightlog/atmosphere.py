"""ISA troposphere pressure, temperature, and altitude.

The model is hydrostatic dry air with a constant temperature lapse rate.
It is the standard-day troposphere only (from a bit below sea level up to
11 km). It is not a forecast, and it is not valid in the stratosphere.

Forward model, geometric altitude h in meters above mean sea level:

    T(h) = T0 - L * h
    p(h) = p0 * (T(h) / T0) ** (g / (R * L))

Inverse, used to turn a pressure reading into an altitude estimate:

    h(p) = (T0 / L) * (1 - (p / p0) ** (R * L / g))

Altitude above the launch site is that result minus the site elevation.
With zero sensor noise the estimate matches the simulated altitude above
the site, because both sides use this same formula. That match is by
construction. It is not evidence that the formula is the real atmosphere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from flightlog.constants import (
    GAS_CONSTANT_J_PER_KG_K,
    GRAVITY_MPS2,
    LAPSE_RATE_K_PER_M,
    MIN_VALID_ALTITUDE_AMSL_M,
    SEA_LEVEL_PRESSURE_PA,
    SEA_LEVEL_TEMPERATURE_K,
    TROPOPAUSE_M,
)


@dataclass(frozen=True)
class Atmosphere:
    """Standard-day troposphere constants. Override reference pressure for a what-if."""

    reference_pressure_pa: float = SEA_LEVEL_PRESSURE_PA
    reference_temperature_k: float = SEA_LEVEL_TEMPERATURE_K
    lapse_rate_k_per_m: float = LAPSE_RATE_K_PER_M
    gravity_mps2: float = GRAVITY_MPS2
    gas_constant_j_per_kg_k: float = GAS_CONSTANT_J_PER_KG_K
    tropopause_m: float = TROPOPAUSE_M

    def validate(self) -> None:
        if not math.isfinite(self.reference_pressure_pa) or self.reference_pressure_pa <= 0:
            raise ValueError("reference pressure must be a positive number of pascals.")
        if not math.isfinite(self.reference_temperature_k) or self.reference_temperature_k <= 0:
            raise ValueError("reference temperature must be a positive temperature in kelvin.")
        if not math.isfinite(self.lapse_rate_k_per_m) or self.lapse_rate_k_per_m <= 0:
            raise ValueError("lapse rate must be a positive number of kelvin per meter.")
        if not math.isfinite(self.gravity_mps2) or self.gravity_mps2 <= 0:
            raise ValueError("gravity must be a positive number of meters per second squared.")
        if not math.isfinite(self.gas_constant_j_per_kg_k) or self.gas_constant_j_per_kg_k <= 0:
            raise ValueError("the specific gas constant must be positive.")
        if self.tropopause_m <= 0:
            raise ValueError("tropopause altitude must be positive.")

    def _exponent(self) -> float:
        return self.gravity_mps2 / (self.gas_constant_j_per_kg_k * self.lapse_rate_k_per_m)

    def temperature_k(self, altitude_amsl_m: float | np.ndarray) -> float | np.ndarray:
        self._check_altitude(altitude_amsl_m)
        temperature = self.reference_temperature_k - self.lapse_rate_k_per_m * np.asarray(
            altitude_amsl_m, dtype=float
        )
        return _as_input_type(altitude_amsl_m, temperature)

    def temperature_c(self, altitude_amsl_m: float | np.ndarray) -> float | np.ndarray:
        return _as_input_type(
            altitude_amsl_m,
            np.asarray(self.temperature_k(altitude_amsl_m), dtype=float) - 273.15,
        )

    def pressure_pa(self, altitude_amsl_m: float | np.ndarray) -> float | np.ndarray:
        self._check_altitude(altitude_amsl_m)
        height = np.asarray(altitude_amsl_m, dtype=float)
        temperature = self.reference_temperature_k - self.lapse_rate_k_per_m * height
        ratio = temperature / self.reference_temperature_k
        pressure = self.reference_pressure_pa * ratio ** self._exponent()
        return _as_input_type(altitude_amsl_m, pressure)

    def altitude_amsl_m(self, pressure_pa: float | np.ndarray) -> float | np.ndarray:
        pressure = np.asarray(pressure_pa, dtype=float)
        if np.any(~np.isfinite(pressure)) or np.any(pressure <= 0):
            raise ValueError("pressure must be a positive finite number of pascals to invert.")
        power = (self.gas_constant_j_per_kg_k * self.lapse_rate_k_per_m) / self.gravity_mps2
        ratio = (pressure / self.reference_pressure_pa) ** power
        altitude = (self.reference_temperature_k / self.lapse_rate_k_per_m) * (1.0 - ratio)
        return _as_input_type(pressure_pa, altitude)

    def tropopause_pressure_pa(self) -> float:
        return float(self.pressure_pa(self.tropopause_m))

    def _check_altitude(self, altitude_amsl_m: float | np.ndarray) -> None:
        height = np.asarray(altitude_amsl_m, dtype=float)
        if np.any(~np.isfinite(height)):
            raise ValueError("altitude must be a finite number of meters.")
        if np.any(height > self.tropopause_m + 1e-6):
            raise ValueError(
                "Altitude is above 11 km. This sketch uses the ISA troposphere "
                "formula only, which stops at the tropopause and is not a stratosphere model."
            )
        if np.any(height < MIN_VALID_ALTITUDE_AMSL_M):
            raise ValueError(
                f"Altitude below {MIN_VALID_ALTITUDE_AMSL_M:.0f} m is outside this sketch."
            )


def altitude_agl_from_pressure(
    pressure_pa: float | np.ndarray,
    atmosphere: Atmosphere | None = None,
    site_elevation_m: float = 0.0,
) -> float | np.ndarray:
    """Meters above the launch site from a pressure reading.

    ``site_elevation_m`` is the launch site above mean sea level. The same
    number is subtracted from the ISA pressure altitude, so a reading taken
    on the pad comes back near 0 m above ground level when the reference
    pressure matches the forward model.
    """
    atm = atmosphere if atmosphere is not None else Atmosphere()
    atm.validate()
    if not math.isfinite(site_elevation_m):
        raise ValueError("site elevation must be a finite number of meters.")
    return _as_input_type(
        pressure_pa,
        np.asarray(atm.altitude_amsl_m(pressure_pa), dtype=float) - site_elevation_m,
    )


def clamp_pressure_to_troposphere(
    pressure_pa: float | np.ndarray,
    atmosphere: Atmosphere | None = None,
) -> tuple[float | np.ndarray, int]:
    """Raise pressures that would invert to above the tropopause.

    Returns the clamped pressure and how many samples were raised.
    A clamped sample is saturated at 11 km. It is not a real altitude.
    """
    atm = atmosphere if atmosphere is not None else Atmosphere()
    pressure = np.asarray(pressure_pa, dtype=float)
    floor = float(atm.tropopause_pressure_pa())
    too_low = pressure < floor
    clamped = np.maximum(pressure, floor)
    count = int(np.count_nonzero(too_low))
    return _as_input_type(pressure_pa, clamped), count


def _as_input_type(original: float | np.ndarray, values: np.ndarray) -> float | np.ndarray:
    array = np.asarray(values, dtype=float)
    if np.isscalar(original):
        return float(array)
    return array
