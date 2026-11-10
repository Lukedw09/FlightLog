"""Educational simulated flight-data logger.

Synthetic barometric telemetry for learning the shape of a flight log.
Not validated flight physics and not flight-control software.
"""

import os

os.environ.setdefault("MPLBACKEND", "Agg")

from flightlog.atmosphere import Atmosphere, altitude_agl_from_pressure
from flightlog.constants import VERSION
from flightlog.detect import DetectionConfig, detect
from flightlog.generate import generate_flight
from flightlog.io import read_flight_csv, write_flight_csv

__version__ = VERSION

__all__ = [
    "Atmosphere",
    "DetectionConfig",
    "altitude_agl_from_pressure",
    "detect",
    "generate_flight",
    "read_flight_csv",
    "write_flight_csv",
    "__version__",
]
