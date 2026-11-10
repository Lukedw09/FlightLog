"""CSV schema shared by the simulator and a future measured log.

Header lines start with ``#`` and are ``key: value`` pairs. The detector
does not need the header. It needs ``time_s`` and ``altitude_m``. If
``altitude_m`` is missing and ``pressure_pa`` is present, altitude is
derived with the ISA inversion and the header's reference pressure and
site elevation (defaults: 101325 Pa and 0 m).

Measured columns:

    time_s, timestamp_utc, data_origin, pressure_pa, temperature_c, altitude_m

Optional simulator columns, safe to omit:

    pressure_pa_true, temperature_c_true, altitude_m_true, phase_true
"""

from __future__ import annotations

import csv
import math
from dataclasses import replace
from io import StringIO
from pathlib import Path

import numpy as np

from flightlog.atmosphere import Atmosphere, altitude_agl_from_pressure
from flightlog.constants import (
    GAS_CONSTANT_J_PER_KG_K,
    GRAVITY_MPS2,
    LAPSE_RATE_K_PER_M,
    SEA_LEVEL_PRESSURE_PA,
    SEA_LEVEL_TEMPERATURE_K,
    TROPOPAUSE_M,
)
from flightlog.log import FlightLog

MEASURED_COLUMNS = (
    "time_s",
    "timestamp_utc",
    "data_origin",
    "pressure_pa",
    "temperature_c",
    "altitude_m",
)
TRUTH_COLUMNS = (
    "pressure_pa_true",
    "temperature_c_true",
    "altitude_m_true",
    "phase_true",
)


def write_flight_csv(path: str | Path, log: FlightLog, *, include_truth: bool = True) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        _write_flight_csv(handle, log, include_truth=include_truth)


def flight_csv_text(log: FlightLog, *, include_truth: bool = True) -> str:
    """Same bytes ``write_flight_csv`` would put in a file, as text."""
    buffer = StringIO()
    _write_flight_csv(buffer, log, include_truth=include_truth)
    return buffer.getvalue()


def _write_flight_csv(handle, log: FlightLog, *, include_truth: bool) -> None:
    fields = list(MEASURED_COLUMNS)
    truth = include_truth and _has_truth(log)
    if truth:
        fields.extend(TRUTH_COLUMNS)
    for key, value in log.metadata.items():
        if "\n" in key or "\n" in value or ":" in key:
            raise ValueError(f"metadata {key!r} cannot be stored on one header line.")
        handle.write(f"# {key}: {value}\n")
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for i in range(len(log)):
        row = {
            "time_s": _format_float(float(log.time_s[i])),
            "timestamp_utc": "" if log.timestamp_utc is None else str(log.timestamp_utc[i]),
            "data_origin": log.data_origin,
            "pressure_pa": _format_optional(log.pressure_pa, i),
            "temperature_c": _format_optional(log.temperature_c, i),
            "altitude_m": _format_float(float(log.altitude_m[i])),
        }
        if truth:
            row["pressure_pa_true"] = _format_optional(log.pressure_pa_true, i)
            row["temperature_c_true"] = _format_optional(log.temperature_c_true, i)
            row["altitude_m_true"] = _format_optional(log.altitude_m_true, i)
            row["phase_true"] = "" if log.phase_true is None else str(log.phase_true[i])
        writer.writerow(row)


def read_flight_csv(path: str | Path) -> FlightLog:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"No CSV at {source}.")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{source.name} is not a UTF-8 text file.") from exc
    return read_flight_csv_text(text, label=source.name)


def read_flight_csv_text(text: str, *, label: str = "this file") -> FlightLog:
    """Read the flightlog CSV schema from text. ``label`` is only used in errors."""
    source = label
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            body = stripped[1:].strip()
            if ":" in body:
                key, value = body.split(":", 1)
                metadata[key.strip()] = value.strip()
            continue
        data_lines.append(line)
    if not data_lines:
        raise ValueError(f"{source} has no CSV rows.")
    data_lines[0] = data_lines[0].lstrip("\ufeff")
    reader = csv.DictReader(data_lines)
    if not reader.fieldnames:
        raise ValueError(f"{source} has no header row.")
    rows = []
    for row in reader:
        rows.append({(key or "").strip(): (value or "").strip() for key, value in row.items()})
    if not rows:
        raise ValueError(f"{source} has a header but no data rows.")
    fields = {(key or "").strip() for key in reader.fieldnames}
    if "time_s" not in fields:
        raise ValueError(
            f"{source} is missing time_s. Columns found: {', '.join(sorted(fields))}."
        )
    time_s = _float_column(source, rows, "time_s", required=True)
    if time_s is None or np.any(~np.isfinite(time_s)):
        raise ValueError(f"{source} has an empty or non-numeric time_s.")
    pressure = _float_column(source, rows, "pressure_pa", required=False)
    temperature = _float_column(source, rows, "temperature_c", required=False)
    altitude = _float_column(source, rows, "altitude_m", required=False)
    derived = False
    if altitude is None or np.all(np.isnan(altitude)):
        if pressure is None or np.any(np.isnan(pressure)):
            raise ValueError(
                f"{source} needs altitude_m, or pressure_pa so altitude can be derived. "
                f"Columns found: {', '.join(sorted(fields))}."
            )
        atmosphere = atmosphere_from_metadata(metadata)
        site = _meta_float(metadata, "site_elevation_m", 0.0)
        altitude = np.asarray(
            altitude_agl_from_pressure(pressure, atmosphere, site),
            dtype=float,
        )
        derived = True
    if np.any(~np.isfinite(altitude)):
        raise ValueError(f"{source} has an empty or non-numeric altitude_m.")
    origin = _origin(rows, metadata)
    return FlightLog(
        time_s=time_s,
        altitude_m=np.asarray(altitude, dtype=float),
        pressure_pa=None if pressure is None or np.all(np.isnan(pressure)) else pressure,
        temperature_c=None
        if temperature is None or np.all(np.isnan(temperature))
        else temperature,
        timestamp_utc=_text_column(rows, "timestamp_utc"),
        data_origin=origin,
        altitude_m_true=_complete_float(rows, "altitude_m_true"),
        pressure_pa_true=_complete_float(rows, "pressure_pa_true"),
        temperature_c_true=_complete_float(rows, "temperature_c_true"),
        phase_true=_text_column(rows, "phase_true"),
        altitude_derived=derived,
        metadata=metadata,
    )


def rederive_altitude(
    log: FlightLog,
    *,
    reference_pressure_pa: float | None = None,
    site_elevation_m: float | None = None,
) -> FlightLog:
    """Replace ``altitude_m`` using ``pressure_pa`` and the ISA inversion."""
    if log.pressure_pa is None:
        raise ValueError(
            "This file has no pressure_pa column, so altitude cannot be derived from pressure."
        )
    metadata = dict(log.metadata)
    if reference_pressure_pa is not None:
        metadata["reference_pressure_pa"] = f"{reference_pressure_pa:.10g}"
    if site_elevation_m is not None:
        metadata["site_elevation_m"] = f"{site_elevation_m:.10g}"
    atmosphere = atmosphere_from_metadata(metadata)
    site = _meta_float(metadata, "site_elevation_m", 0.0)
    altitude = np.asarray(
        altitude_agl_from_pressure(log.pressure_pa, atmosphere, site),
        dtype=float,
    )
    metadata["altitude_m_derived"] = "true"
    return replace(log, altitude_m=altitude, altitude_derived=True, metadata=metadata)


def atmosphere_from_metadata(metadata: dict[str, str]) -> Atmosphere:
    atmosphere = Atmosphere(
        reference_pressure_pa=_meta_float(metadata, "reference_pressure_pa", SEA_LEVEL_PRESSURE_PA),
        reference_temperature_k=_meta_float(
            metadata, "reference_temperature_k", SEA_LEVEL_TEMPERATURE_K
        ),
        lapse_rate_k_per_m=_meta_float(metadata, "lapse_rate_k_per_m", LAPSE_RATE_K_PER_M),
        gravity_mps2=_meta_float(metadata, "gravity_mps2", GRAVITY_MPS2),
        gas_constant_j_per_kg_k=_meta_float(
            metadata, "gas_constant_j_per_kg_k", GAS_CONSTANT_J_PER_KG_K
        ),
        tropopause_m=_meta_float(metadata, "tropopause_m", TROPOPAUSE_M),
    )
    atmosphere.validate()
    return atmosphere


def _has_truth(log: FlightLog) -> bool:
    return log.altitude_m_true is not None or log.phase_true is not None


def _format_float(value: float) -> str:
    if not math.isfinite(value):
        return ""
    return f"{value:.9f}"


def _format_optional(values: np.ndarray | None, index: int) -> str:
    if values is None:
        return ""
    return _format_float(float(values[index]))


def _float_column(
    path: Path | str, rows: list[dict[str, str]], name: str, *, required: bool
) -> np.ndarray | None:
    if name not in rows[0]:
        if required:
            raise ValueError(f"{path} is missing the {name} column.")
        return None
    values = []
    for i, row in enumerate(rows, start=2):
        raw = row.get(name, "")
        if raw == "":
            values.append(math.nan)
            continue
        try:
            values.append(float(raw))
        except ValueError as exc:
            raise ValueError(f"{path}: row {i} column {name} is not a number ({raw!r}).") from exc
    return np.asarray(values, dtype=float)


def _complete_float(rows: list[dict[str, str]], name: str) -> np.ndarray | None:
    if name not in rows[0]:
        return None
    values = []
    for row in rows:
        raw = row.get(name, "")
        if raw == "":
            return None
        values.append(float(raw))
    return np.asarray(values, dtype=float)


def _text_column(rows: list[dict[str, str]], name: str) -> np.ndarray | None:
    if name not in rows[0]:
        return None
    return np.asarray([row.get(name, "") for row in rows], dtype=object)


def _origin(rows: list[dict[str, str]], metadata: dict[str, str]) -> str:
    if rows and "data_origin" in rows[0]:
        labels = {row.get("data_origin", "") for row in rows if row.get("data_origin", "")}
        if len(labels) == 1:
            return next(iter(labels))
        if len(labels) > 1:
            return "mixed"
    return metadata.get("data_origin", "unknown")


def _meta_float(metadata: dict[str, str], key: str, default: float) -> float:
    raw = metadata.get(key, "")
    if raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Header {key} is not a number ({raw!r}).") from exc
    return value
