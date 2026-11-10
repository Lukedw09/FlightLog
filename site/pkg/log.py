"""In-memory flight log. Detector code should take time and altitude arrays.

``altitude_m``, ``pressure_pa``, and ``temperature_c`` are the sensor
columns. On a simulated log they are noisy. ``*_true`` columns are the
sketch, present only so a plot can show the difference. Real captures
leave the true columns out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class FlightLog:
    time_s: np.ndarray
    altitude_m: np.ndarray
    data_origin: str
    pressure_pa: np.ndarray | None = None
    temperature_c: np.ndarray | None = None
    timestamp_utc: np.ndarray | None = None
    altitude_m_true: np.ndarray | None = None
    pressure_pa_true: np.ndarray | None = None
    temperature_c_true: np.ndarray | None = None
    phase_true: np.ndarray | None = None
    altitude_derived: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.time_s)
        for name in (
            "altitude_m",
            "pressure_pa",
            "temperature_c",
            "timestamp_utc",
            "altitude_m_true",
            "pressure_pa_true",
            "temperature_c_true",
            "phase_true",
        ):
            values = getattr(self, name)
            if values is not None and len(values) != n:
                raise ValueError(f"{name} has {len(values)} rows but time_s has {n}.")

    def __len__(self) -> int:
        return int(len(self.time_s))

    @property
    def simulated(self) -> bool:
        if self.data_origin == "simulated":
            return True
        return self.metadata.get("data_origin") == "simulated"
