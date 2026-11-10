"""Shared constants for the educational flight-data logger.

These are the International Standard Atmosphere (ISA) sea-level values used
by the troposphere pressure model. They are not a weather report and not a
claim about any particular barometer.
"""

VERSION = "0.1.0"
SCHEMA = "flightlog.v1"

DISCLAIMER = (
    "Educational synthetic telemetry. Not a real flight. "
    "Not validated flight physics or flight-control data."
)

# ISA / ICAO standard-day constants, troposphere.
GRAVITY_MPS2 = 9.80665
GAS_CONSTANT_J_PER_KG_K = 287.05287  # dry air
SEA_LEVEL_TEMPERATURE_K = 288.15  # 15 °C
SEA_LEVEL_PRESSURE_PA = 101325.0
LAPSE_RATE_K_PER_M = 0.0065
TROPOPAUSE_M = 11000.0

# Pressures below the tropopause value are outside this formula.
# The sensor path clamps to this floor so a wild noise draw cannot
# produce a nonsense altitude. It is not a hardware limit.
MIN_VALID_ALTITUDE_AMSL_M = -1000.0
