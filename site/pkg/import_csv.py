"""Map a generic CSV onto the flight-log columns.

This is not a parser for any particular flight controller. Headers are
matched only when they spell the unit themselves (``t_ms``, ``alt_ft``,
``pressure_hpa``). A bare ``time`` or ``altitude`` is offered as a column
and left without a unit until a person chooses one.

Native flightlog files (comma-separated ``time_s`` plus ``altitude_m`` or
``pressure_pa``) are recognized and left to the existing reader.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass

import numpy as np

from flightlog.atmosphere import Atmosphere, altitude_agl_from_pressure
from flightlog.constants import (
    DISCLAIMER,
    MIN_VALID_ALTITUDE_AMSL_M,
    SCHEMA,
    SEA_LEVEL_PRESSURE_PA,
    TROPOPAUSE_M,
)
from flightlog.log import FlightLog
from flightlog.session import FormError

FOOT_TO_METER = 0.3048
MAX_ROWS = 500_000
MAX_COLUMNS = 128
MAX_CELL_CHARS = 100_000

_DELIMITERS = {
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
}

_TIME_S = {
    "time_s",
    "elapsed_s",
    "t_s",
    "seconds",
    "time_sec",
    "time_seconds",
    "elapsed_seconds",
    "elapsed_time_s",
}
_TIME_MS = {
    "time_ms",
    "elapsed_ms",
    "t_ms",
    "milliseconds",
    "millis",
    "time_millis",
    "elapsed_millis",
    "elapsed_time_ms",
}
_TIME_BARE = {"time", "t", "elapsed", "timestamp", "clock"}

_ALT_M = {
    "altitude_m",
    "alt_m",
    "height_m",
    "agl_m",
    "msl_m",
    "amsl_m",
    "altitude_meters",
    "alt_meters",
    "height_meters",
}
_ALT_FT = {
    "altitude_ft",
    "alt_ft",
    "height_ft",
    "agl_ft",
    "msl_ft",
    "amsl_ft",
    "altitude_feet",
    "alt_feet",
    "height_feet",
}
_ALT_BARE = {"altitude", "alt", "height", "agl", "msl", "amsl"}

_PRESS_PA = {"pressure_pa", "press_pa", "static_pa", "baro_pa"}
_PRESS_HPA = {
    "pressure_hpa",
    "press_hpa",
    "static_hpa",
    "baro_hpa",
    "hpa",
    "mbar",
    "millibar",
    "pressure_mbar",
}
_PRESS_KPA = {"pressure_kpa", "press_kpa", "static_kpa", "kpa"}
_PRESS_BARE = {"pressure", "press", "static", "baro", "barometer"}

_TEMP_C = {"temperature_c", "temp_c", "t_c", "celsius", "deg_c", "degc"}
_TEMP_F = {"temperature_f", "temp_f", "t_f", "fahrenheit", "deg_f", "degf"}
_TEMP_BARE = {"temperature", "temp"}

_NATIVE_COLUMNS = {
    "time_s",
    "timestamp_utc",
    "data_origin",
    "pressure_pa",
    "temperature_c",
    "altitude_m",
    "pressure_pa_true",
    "temperature_c_true",
    "altitude_m_true",
    "phase_true",
}


@dataclass(frozen=True)
class ImportResult:
    log: FlightLog
    summary: tuple[str, ...]
    track_name: str = "Track"
    speed_kmh: np.ndarray | None = None
    speed_frame: str = ""
    altitude_reference: str = ""
    time_basis: str = "keep"
    video_time_s: np.ndarray | None = None
    source_note: str = ""


def inspect_csv(text: str, *, delimiter: str | None = None, header: str | None = None) -> dict:
    """Suggest a delimiter, a header, and column roles. Does not convert numbers."""
    _require_text(text)
    chosen = delimiter or _suggest_delimiter(text)
    if chosen not in _DELIMITERS.values() and chosen not in _DELIMITERS:
        raise FormError("Delimiter must be a comma, semicolon, or tab.", "delimiter")
    if chosen in _DELIMITERS:
        chosen = _DELIMITERS[chosen]
    rows = _rows(text, chosen)
    if len(rows) < 2:
        raise FormError(
            "This file needs a header or at least two data rows before it can be mapped.",
            "csv",
        )
    header_mode = header or ("present" if _looks_like_header(rows[0][1]) else "absent")
    if header_mode not in ("present", "absent"):
        raise FormError("Header must be present or absent.", "header")
    if header_mode == "present":
        names = rows[0][1]
        data = rows[1:]
    else:
        width = max(len(row) for _, row in rows)
        names = [f"Column {i + 1}" for i in range(width)]
        data = rows
    if not data:
        raise FormError("This file has column names but no data rows.", "csv")
    native = _is_native(text, chosen, names if header_mode == "present" else [])
    columns = []
    for index, name in enumerate(names):
        samples = []
        for _, row in data[:6]:
            samples.append(row[index] if index < len(row) else "")
        hint = _hint(name) if header_mode == "present" else None
        columns.append(
            {
                "index": index,
                "header": name,
                "samples": samples,
                "role": None if hint is None else hint["role"],
                "unit": None if hint is None else hint["unit"],
                "unit_confident": False if hint is None else hint["unit_confident"],
                "reference": None if hint is None else hint["reference"],
                "reference_confident": False if hint is None else hint["reference_confident"],
            }
        )
    warnings = _warnings(columns, header_mode)
    return {
        "delimiter": {",": "comma", ";": "semicolon", "\t": "tab"}[chosen],
        "header": header_mode,
        "columns": columns,
        "warnings": warnings,
        "data_rows": len(data),
        "comment_lines_skipped": _comment_count(text),
        "native": native,
    }


def apply_groups(text: str, raw: dict) -> list[ImportResult]:
    """One result, or one result per stage name. Readings are not copied across stages."""
    stage = raw.get("stage")
    if stage in (None, "", {}):
        return [apply_mapping(text, raw)]
    delimiter_name = _required_choice(raw, "delimiter", "delimiter", set(_DELIMITERS))
    delimiter = _delimiter_char(delimiter_name)
    header_mode = _required_choice(raw, "header", "header", {"present", "absent"})
    rows = _rows(text, delimiter)
    if header_mode == "present":
        header_cells = rows[0][1]
        data = rows[1:]
    else:
        width = max(len(row) for _, row in rows)
        header_cells = [f"Column {i + 1}" for i in range(width)]
        data = rows
    stage_index = _stage_index(raw, len(header_cells))
    groups: dict[str, list[tuple[int, list[str]]]] = {}
    order: list[str] = []
    for line_no, row in data:
        if stage_index is None or stage_index >= len(row) or not row[stage_index].strip():
            raise FormError(
                f"Line {line_no} has no stage or vehicle name. "
                "It was not copied onto another track.",
                "stage",
            )
        name = row[stage_index].strip()
        if name not in groups:
            order.append(name)
            groups[name] = []
        groups[name].append((line_no, row))
    if len(order) < 1:
        raise FormError("No stage names were found.", "stage")
    results = []
    for name in order:
        if len(groups[name]) < 2:
            raise FormError(
                f"Track {name!r} has only {len(groups[name])} row. A track needs at least two rows.",
                "stage",
            )
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header_cells)
        for _, row in groups[name]:
            writer.writerow(row)
        child = dict(raw)
        child.pop("stage", None)
        child["track_name"] = name
        child["header"] = "present"
        results.append(apply_mapping(buffer.getvalue(), child))
    return results


_READOUT_ATTRIBUTION = (
    "Attributed, not independently authenticated by this program. "
    "Luke states this is Falcon 9 Transporter-18 displayed data, mission date 1 October 2026, not a simulation. "
    "Astraeus, consulted at Luke's request, describes his 8 October readout as an OCR and visual check of "
    "on-screen SpaceX webcast speed and altitude, not a raw telemetry downlink. "
    "This file matches that stated shape: 81 rows, mission time T+30 through T+110 at 1 second, "
    "combined stack before separation. That window does not include liftoff, apogee, staging, or landing. "
    "Only the area around T+67 was cross-checked by Ares. Every row is not independently verified. "
    "Altitude reference is unknown. Displayed speed is total speed, not vertical speed and not d(altitude)/dt. "
    "Dynamic pressure is not in the file and is not calculated."
)


def readout_profile(text: str) -> dict | None:
    """Column meanings for a speed/altitude readout. The mission name is attached only on an exact shape match."""
    try:
        preview = inspect_csv(text)
    except FormError:
        return None
    if preview.get("header") != "present":
        return None
    indexes = {_norm(column["header"]): column["index"] for column in preview["columns"]}
    if not {"t_s", "speed_kmh", "altitude_km"} <= set(indexes):
        return None
    delimiter = _DELIMITERS[preview["delimiter"]]
    data = _rows(text, delimiter)[1:]
    times: list[float] = []
    for _, row in data:
        index = indexes["t_s"]
        if index >= len(row):
            return _readout_body(False, None, None, len(times))
        try:
            times.append(float(row[index]))
        except ValueError:
            return _readout_body(False, None, None, len(times))
    coverage = (
        len(times) == 81
        and times[0] == 30.0
        and times[-1] == 110.0
        and all(abs((times[i + 1] - times[i]) - 1.0) < 1e-9 for i in range(len(times) - 1))
    )
    return _readout_body(coverage, times[0] if times else None, times[-1] if times else None, len(times))


def _readout_body(coverage: bool, first: float | None, last: float | None, rows: int) -> dict:
    return {
        "columns_match": True,
        "coverage_match": coverage,
        "rows": rows,
        "t_first_s": first,
        "t_last_s": last,
        "suggested_track_name": "Combined stack" if coverage else "Track",
        "attribution": _READOUT_ATTRIBUTION if coverage else None,
        "note": (
            "This table matches the 81-row T+30 through T+110 shape described for the Transporter-18 webcast readout. "
            "Confirm before that name is attached. Mission time will stay as written."
            if coverage
            else "These headers give seconds, km/h, and kilometers. "
            "The altitude reference is not in the header, and the speed frame is not stated. "
            "Mission time will stay as written."
        ),
    }


def parse_event_markers(text: str) -> list[dict]:
    """Read a recommended event list. These are source markers, not detected events."""
    _require_text(text)
    delimiter = _suggest_delimiter(text)
    rows = _rows(text, delimiter)
    if not rows or not _looks_like_header(rows[0][1]):
        raise FormError("An event list needs a header row.", "events")
    headers = [_norm(cell) for cell in rows[0][1]]
    if "mission_time_s" not in headers or "event" not in headers:
        raise FormError(
            "An event list needs mission_time_s and event. "
            "Optional columns are vehicle, source, and notes.",
            "events",
        )
    index = {name: headers.index(name) for name in headers if name}
    markers = []
    for line_no, row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        raw_time = row[index["mission_time_s"]] if index["mission_time_s"] < len(row) else ""
        label = row[index["event"]] if index["event"] < len(row) else ""
        if raw_time.strip() == "" or label.strip() == "":
            raise FormError(
                f"Line {line_no} is missing mission_time_s or event. The row was not filled in from another marker.",
                "events",
            )
        try:
            mission_time = float(raw_time)
        except ValueError as exc:
            raise FormError(f"Line {line_no} mission_time_s is not a number ({raw_time!r}).", "events") from exc
        if not math.isfinite(mission_time):
            raise FormError(f"Line {line_no} mission_time_s is not finite.", "events")
        def cell(name: str) -> str:
            if name not in index or index[name] >= len(row):
                return ""
            return row[index[name]].strip()
        markers.append(
            {
                "kind": "source_marker",
                "mission_time_s": mission_time,
                "vehicle": cell("vehicle"),
                "event": label.strip(),
                "source": cell("source"),
                "notes": cell("notes"),
            }
        )
    if not markers:
        raise FormError("The event list has no markers.", "events")
    return markers


def is_native_flightlog(text: str) -> bool:
    preview = inspect_csv(text)
    return bool(preview["native"])


def apply_mapping(text: str, raw: dict) -> ImportResult:
    """Convert a reviewed mapping into a flight log. Rejects bad rows."""
    _require_text(text)
    delimiter = _delimiter_char(_required_choice(raw, "delimiter", "delimiter", set(_DELIMITERS)))
    header_mode = _required_choice(raw, "header", "header", {"present", "absent"})
    provenance = _required_choice(raw, "provenance", "provenance", {"imported", "measured"})
    rows = _rows(text, delimiter)
    if header_mode == "present":
        if not rows:
            raise FormError("No header row was found.", "header")
        data = rows[1:]
        width = len(rows[0][1])
    else:
        data = rows
        width = max((len(row) for _, row in data), default=0)
    if len(data) < 2:
        raise FormError(
            f"Only {len(data)} data row was found. A track needs at least two rows.",
            "csv",
        )
    if len(data) > MAX_ROWS:
        raise FormError(
            f"This file has {len(data)} data rows, above the {MAX_ROWS} limit.",
            "csv",
        )

    time_index = _mapped_column(raw, "time", width, required=True)
    time_unit = _required_choice(raw.get("time") or {}, "unit", "time", {"s", "ms"})
    altitude = _optional_column(raw, "altitude", width)
    pressure = _optional_column(raw, "pressure", width)
    temperature = _optional_column(raw, "temperature", width)
    speed = _speed_column(raw, width)
    stage_index = _stage_index(raw, width)
    video_index = _plain_index(raw, "video_time", width)
    alt_ref_index = _plain_index(raw, "altitude_reference", width)
    speed_ref_index = _plain_index(raw, "speed_reference", width)
    origin_index = _plain_index(raw, "data_origin", width)
    source_index = _plain_index(raw, "source", width)
    chosen = [time_index]
    for item in (altitude, pressure, temperature, speed):
        if item is not None:
            chosen.append(item[0])
    for index in (stage_index, video_index, alt_ref_index, speed_ref_index, origin_index, source_index):
        if index is not None:
            chosen.append(index)
    if len(chosen) != len(set(chosen)):
        raise FormError("Each column can only be used once.", "mapping")
    if altitude is None and pressure is None:
        raise FormError("Choose an altitude column or a pressure column.", "altitude")

    site = None
    reference = None
    if altitude is not None and altitude[2] == "msl":
        site = _elevation(raw)
    if altitude is None:
        site = _elevation(raw)
        reference = _reference_pressure(raw)

    summary = []
    decimal_commas = [0]
    times = []
    altitudes = [] if altitude is not None else None
    pressures = [] if pressure is not None else None
    temperatures = [] if temperature is not None else None
    speeds = [] if speed is not None else None
    video_times = [] if video_index is not None else None
    alt_refs = [] if alt_ref_index is not None else None
    speed_refs = [] if speed_ref_index is not None else None
    origins = [] if origin_index is not None else None
    sources = [] if source_index is not None else None
    for line_no, row in data:
        times.append(_cell(row, time_index, line_no, "time", delimiter, decimal_commas))
        if altitude is not None:
            altitudes.append(_optional_cell(row, altitude[0], line_no, "altitude", delimiter, decimal_commas))
        if pressure is not None:
            pressures.append(_optional_cell(row, pressure[0], line_no, "pressure", delimiter, decimal_commas))
        if temperature is not None:
            temperatures.append(_optional_cell(row, temperature[0], line_no, "temperature", delimiter, decimal_commas))
        if speed is not None:
            speeds.append(_optional_cell(row, speed[0], line_no, "speed", delimiter, decimal_commas))
        if video_index is not None:
            video_times.append(_optional_cell(row, video_index, line_no, "video time", delimiter, decimal_commas))
        if alt_ref_index is not None:
            alt_refs.append(_text_cell(row, alt_ref_index))
        if speed_ref_index is not None:
            speed_refs.append(_text_cell(row, speed_ref_index))
        if origin_index is not None:
            origins.append(_text_cell(row, origin_index))
        if source_index is not None:
            sources.append(_text_cell(row, source_index))

    time_s = np.asarray(times, dtype=float)
    if time_unit == "ms":
        time_s = time_s / 1000.0
    _reject_time_order(time_s, [line for line, _ in data])
    time_basis = raw.get("time_basis") or "keep"
    if time_basis not in ("keep", "start_at_zero"):
        raise FormError("Time handling must be keep or start_at_zero.", "time_basis")
    shift = 0.0
    if time_basis == "start_at_zero":
        shift = float(time_s[0])
        time_s = time_s - shift
        summary.append(
            "You chose to shift time so the first sample is 0 s. "
            f"That sample was {shift:.6g} s in the file"
            + (" after converting milliseconds." if time_unit == "ms" else ".")
        )
    else:
        summary.append(
            "Mission time was kept as written. "
            f"The first sample stays at {float(time_s[0]):.6g} s. "
            "It was not moved to 0. Add a time offset on the track if the clocks need to line up."
        )

    altitude_m = None
    pressure_pa = None
    temperature_c = None
    if alt_refs is not None and altitude is not None:
        stated = _uniform_token(alt_refs, "altitude_reference", {"unknown", "agl", "msl", "pad"}, summary)
        altitude = (altitude[0], altitude[1], "unknown" if stated is None else stated)
    if speed_refs is not None and speed is not None:
        stated_speed = _uniform_token(
            speed_refs, "speed_reference", {"unknown", "total", "vertical"}, summary
        )
        if stated_speed is not None:
            speed = (speed[0], speed[1], stated_speed)
        else:
            speed = (speed[0], speed[1], "unknown")
    if origins is not None:
        stated_origin = _uniform_token(
            origins,
            "data_origin",
            {"webcast_readout", "imported", "measured", "simulated"},
            summary,
        )
        if stated_origin == "simulated":
            summary.append(
                "The file said data_origin simulated. A mapped table is not marked simulated."
            )
        elif stated_origin in {"webcast_readout", "imported", "measured"}:
            provenance = stated_origin
            summary.append(
                f"data_origin from the file is {stated_origin}. It is kept as written and is not a simulation label unless the file itself is a flightlog simulation."
            )
    source_note = ""
    if sources is not None:
        unique_sources = []
        for value in sources:
            if value and value not in unique_sources:
                unique_sources.append(value)
        source_note = "; ".join(unique_sources)
        if any(not value for value in sources):
            summary.append("Some source cells are blank. They were left blank, not filled from another row.")
    if video_times is not None:
        summary.append("video_time_s is kept separate from mission time and is not the chart axis.")
    if altitude is not None:
        _, unit, reference_name = altitude
        meters = np.asarray(altitudes, dtype=float)
        if unit == "ft":
            meters = meters * FOOT_TO_METER
            summary.append("Altitude was converted from feet to meters (1 ft = 0.3048 m).")
        elif unit == "km":
            meters = meters * 1000.0
            summary.append("Altitude was converted from kilometers to meters (× 1000).")
        else:
            summary.append("Altitude was read as meters.")
        if reference_name == "msl":
            altitude_m = meters - float(site)
            summary.append(
                f"Those meters were above sea level. "
                f"{site:g} m was subtracted so the chart is above the launch site. "
                "That site elevation was entered on the import screen. It was not read from the file."
            )
            _reject_amsl(meters, [line for line, _ in data], "altitude")
        elif reference_name in {"unknown", "pad"}:
            altitude_m = meters
            if reference_name == "pad":
                summary.append(
                    "The file says the altitude reference is pad. It was not rewritten as mean sea level."
                )
            else:
                summary.append(
                    "Altitude reference is unknown. The numbers were not treated as above the launch site or as mean sea level."
                )
        else:
            altitude_m = meters
            summary.append("Altitude was taken as meters above the launch site, as chosen on the import screen.")
    if altitude_m is not None and not np.any(np.isfinite(altitude_m)):
        raise FormError("Altitude is blank on every row of this track. Blank cells were not filled in.", "altitude")
    if pressure is not None:
        _, unit = pressure
        pressure_pa = np.asarray(pressures, dtype=float)
        if unit == "hPa":
            pressure_pa = pressure_pa * 100.0
            summary.append("Pressure was converted from hPa to pascals (× 100).")
        elif unit == "kPa":
            pressure_pa = pressure_pa * 1000.0
            summary.append("Pressure was converted from kPa to pascals (× 1000).")
        else:
            summary.append("Pressure was read as pascals.")
        finite_pressure = np.isfinite(pressure_pa)
        if np.any(finite_pressure & (pressure_pa <= 0)):
            bad = int(np.argmax(finite_pressure & (pressure_pa <= 0)))
            raise FormError(
                f"Row {data[bad][0]} has a pressure that is not positive after the unit conversion.",
                "pressure",
            )
    if altitude_m is None:
        atmosphere = Atmosphere(reference_pressure_pa=float(reference))
        atmosphere.validate()
        try:
            amsl = np.asarray(atmosphere.altitude_amsl_m(pressure_pa), dtype=float)
        except ValueError as exc:
            raise FormError(str(exc), "pressure") from exc
        _reject_amsl(amsl, [line for line, _ in data], "pressure altitude")
        altitude_m = np.asarray(
            altitude_agl_from_pressure(pressure_pa, atmosphere, float(site)),
            dtype=float,
        )
        summary.append(
            "No altitude column was mapped. Altitude above the launch site was calculated "
            f"from pressure with the ISA troposphere formula, reference pressure {reference:g} Pa, "
            f"and site elevation {site:g} m. Both numbers were entered on the import screen. "
            "The formula is not used above 11 km."
        )
    if temperatures is not None:
        temperature_c = np.asarray(temperatures, dtype=float)
        if temperature[1] == "F":
            temperature_c = (temperature_c - 32.0) * (5.0 / 9.0)
            summary.append("Temperature was converted from Fahrenheit to Celsius.")
        else:
            summary.append("Temperature was read as Celsius.")
    speed_kmh = None
    speed_frame = ""
    if speeds is not None:
        _, unit, speed_frame = speed
        speed_values = np.asarray(speeds, dtype=float)
        if unit == "m_s":
            speed_kmh = speed_values * 3.6
            summary.append("Speed was converted from m/s to km/h (× 3.6) for the speed chart.")
        else:
            speed_kmh = speed_values
            summary.append("Speed was read as km/h.")
        if speed_frame == "total":
            summary.append(
                "You marked this as displayed total speed. It is not vertical speed and it is not d(altitude)/dt."
            )
        elif speed_frame == "vertical":
            summary.append(
                "You marked this as vertical speed. It is still not checked against the change in altitude."
            )
        else:
            summary.append("The speed frame was left unknown. It is not treated as vertical speed.")
    if decimal_commas[0]:
        summary.append(
            f"{decimal_commas[0]} values used a comma as the decimal mark and were read that way "
            "because the column separator was not a comma."
        )

    metadata = {
        "schema": SCHEMA,
        "data_origin": provenance,
        "disclaimer": (
            "Imported by column mapping in the flight log page. "
            "Not a parser for a particular flight controller. " + DISCLAIMER
        ),
        "units": (
            "time_s seconds; altitude_m meters as chosen on import; "
            "pressure_pa pascals; temperature_c degrees Celsius; speed_kmh kilometers per hour when present"
        ),
        "track_name": str(raw.get("track_name") or "Track").strip() or "Track",
        "import_time_unit": time_unit,
        "import_time_basis": time_basis,
        "import_time_shift_s": f"{shift:.10g}",
        "import_altitude_unit": "" if altitude is None else altitude[1],
        "import_altitude_reference": "" if altitude is None else altitude[2],
        "import_pressure_unit": "" if pressure is None else pressure[1],
        "import_temperature_unit": "" if temperature is None else temperature[1],
        "altitude_m_derived": "true" if altitude is None else "false",
        "source": source_note,
    }
    if site is not None:
        metadata["site_elevation_m"] = f"{float(site):.10g}"
    if reference is not None:
        metadata["reference_pressure_pa"] = f"{float(reference):.10g}"
    log = FlightLog(
        time_s=np.asarray(time_s, dtype=float),
        altitude_m=np.asarray(altitude_m, dtype=float),
        pressure_pa=None if pressure_pa is None else np.asarray(pressure_pa, dtype=float),
        temperature_c=None if temperature_c is None else np.asarray(temperature_c, dtype=float),
        data_origin=provenance,
        altitude_derived=altitude is None,
        metadata=metadata,
    )
    return ImportResult(
        log=log,
        summary=tuple(summary),
        track_name=str(raw.get("track_name") or "Track").strip() or "Track",
        speed_kmh=None if speed_kmh is None else np.asarray(speed_kmh, dtype=float),
        speed_frame=speed_frame,
        altitude_reference="" if altitude is None else altitude[2],
        time_basis=time_basis,
        video_time_s=None if video_times is None else np.asarray(video_times, dtype=float),
        source_note=source_note,
    )


def _require_text(text: str) -> None:
    if text is None or not str(text).strip():
        raise FormError("Choose a CSV file to open.", "csv")
    if "\0" in text:
        raise FormError("This file contains a null byte. It was not opened.", "csv")
    if len(text) > 20_000_000:
        raise FormError("That file is over 20 MB. This page will not open a file that large.", "csv")


def _suggest_delimiter(text: str) -> str:
    scores = {",": _delimiter_score(text, ","), ";": _delimiter_score(text, ";"), "\t": _delimiter_score(text, "\t")}
    return max(scores, key=lambda item: (scores[item], item == ","))


def _delimiter_score(text: str, delimiter: str) -> tuple[int, int]:
    rows = _rows(text, delimiter)
    if not rows:
        return (0, 0)
    widths = [len(row) for _, row in rows[:30]]
    if not widths:
        return (0, 0)
    common = max(set(widths), key=widths.count)
    consistent = sum(1 for width in widths if width == common)
    return (common if common >= 2 else 0, consistent)


def _rows(text: str, delimiter: str) -> list[tuple[int, list[str]]]:
    rows = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line_no == 1:
            line = line.lstrip("\ufeff")
        parsed = next(csv.reader([line], delimiter=delimiter))
        if len(parsed) > MAX_COLUMNS:
            raise FormError(
                f"Line {line_no} has {len(parsed)} columns. This page stops at {MAX_COLUMNS}.",
                "csv",
            )
        for cell in parsed:
            if len(cell) > MAX_CELL_CHARS:
                raise FormError(
                    f"Line {line_no} has a cell longer than {MAX_CELL_CHARS} characters.",
                    "csv",
                )
        rows.append((line_no, [cell.strip() for cell in parsed]))
    return rows


def _comment_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip().startswith("#"))


def _looks_like_header(cells: list[str]) -> bool:
    if not cells:
        return False
    return any(_float_or_none(cell) is None and cell != "" for cell in cells)


def _is_native(text: str, delimiter: str, names: list[str]) -> bool:
    if delimiter != ",":
        return False
    normalized = {_norm(name) for name in names}
    if "time_s" not in normalized:
        return False
    if "altitude_m" not in normalized and "pressure_pa" not in normalized:
        return False
    # Extra columns are still our file when every name is part of the schema
    # or a comment header already skipped. Unknown names go through mapping.
    return normalized <= _NATIVE_COLUMNS


def _hint(header: str) -> dict | None:
    key = _norm(header)
    if not key:
        return None
    parts = set(key.split("_"))
    if key in {"video_time_s", "video_time"} or ("video" in parts and "time" in parts):
        return _hint_body("video_time", "s", True, None, False)
    if key in {"mission_time_s", "mission_time"}:
        return _hint_body("time", "s", True, None, False)
    if key in {"altitude_reference", "alt_reference"}:
        return _hint_body("altitude_reference", None, False, None, False)
    if key in {"speed_reference"}:
        return _hint_body("speed_reference", None, False, None, False)
    if key in {"data_origin", "origin"}:
        return _hint_body("data_origin", None, False, None, False)
    if key == "source":
        return _hint_body("source", None, False, None, False)
    if key in _TIME_MS or ("ms" in parts and parts & {"time", "elapsed", "t"}):
        return _hint_body("time", "ms", True, None, False)
    if key in _TIME_S or ("s" in parts and parts & {"time", "elapsed", "t"} and "ms" not in parts):
        return _hint_body("time", "s", True, None, False)
    if key in _TIME_BARE:
        return _hint_body("time", None, False, None, False)
    reference, reference_confident = _reference(key)
    if key in {"altitude_km", "alt_km", "height_km"} or (
        "km" in parts and parts & {"altitude", "alt", "height"}
    ):
        return _hint_body("altitude", "km", True, reference, reference_confident)
    if key in _ALT_M or ("m" in parts and parts & {"altitude", "alt", "height"} and "amsl" not in key):
        return _hint_body("altitude", "m", True, reference, reference_confident)
    if key in _ALT_FT or ("ft" in parts and parts & {"altitude", "alt", "height"}):
        return _hint_body("altitude", "ft", True, reference, reference_confident)
    if key in _ALT_BARE or reference_confident and parts & {"agl", "msl", "amsl"}:
        return _hint_body("altitude", None, False, reference, reference_confident)
    if key in _PRESS_HPA or "hpa" in parts or "mbar" in parts or "millibar" in parts:
        return _hint_body("pressure", "hPa", True, None, False)
    if key in _PRESS_KPA or "kpa" in parts:
        return _hint_body("pressure", "kPa", True, None, False)
    if key in _PRESS_PA or ("pa" in parts and "hpa" not in parts and "kpa" not in parts):
        return _hint_body("pressure", "Pa", True, None, False)
    if key in _PRESS_BARE:
        return _hint_body("pressure", None, False, None, False)
    if key in _TEMP_F or "fahrenheit" in parts or "degf" in parts:
        return _hint_body("temperature", "F", True, None, False)
    if key in _TEMP_C or "celsius" in parts or "degc" in parts:
        return _hint_body("temperature", "C", True, None, False)
    if key in _TEMP_BARE:
        return _hint_body("temperature", None, False, None, False)
    if key in {"speed_kmh", "speed_kph", "velocity_kmh"} or ("kmh" in parts and "speed" in parts):
        return _hint_body("speed", "kmh", True, None, False)
    if key in {"speed_m_s", "velocity_m_s"}:
        return _hint_body("speed", "m_s", True, None, False)
    if key in {"speed", "velocity"}:
        return _hint_body("speed", None, False, None, False)
    if key in {"stage", "vehicle", "track", "stage_name", "vehicle_name"}:
        return _hint_body("stage", None, False, None, False)
    return None


def _reference(key: str) -> tuple[str | None, bool]:
    parts = set(key.split("_"))
    agl = "agl" in parts or "above_ground" in key
    msl = bool(parts & {"msl", "amsl", "asl"}) or "above_sea" in key
    if agl and not msl:
        return "agl", True
    if msl and not agl:
        return "msl", True
    return None, False


def _hint_body(role, unit, unit_confident, reference, reference_confident) -> dict:
    return {
        "role": role,
        "unit": unit,
        "unit_confident": unit_confident,
        "reference": reference,
        "reference_confident": reference_confident,
    }


def _warnings(columns: list[dict], header_mode: str) -> list[str]:
    warnings = []
    if header_mode == "absent":
        warnings.append("No column names were found. Choose what each column is, and its unit.")
        return warnings
    roles = [column for column in columns if column["role"]]
    if not any(column["role"] == "time" for column in roles):
        warnings.append("No time column was recognized. Choose the elapsed-time column and its unit.")
    for column in roles:
        if column["role"] == "time" and not column["unit_confident"]:
            warnings.append(
                f"“{column['header']}” looks like time, but the header does not say seconds or milliseconds. Choose the unit."
            )
        if column["role"] == "altitude" and not column["unit_confident"]:
            warnings.append(
                f"“{column['header']}” looks like altitude, but the header does not say meters or feet. Choose the unit."
            )
        if column["role"] == "altitude" and not column["reference_confident"]:
            warnings.append(
                f"“{column['header']}” does not say whether altitude is above the launch site or above sea level. Choose one."
            )
        if column["role"] == "pressure" and not column["unit_confident"]:
            warnings.append(
                f"“{column['header']}” looks like pressure, but the header does not say Pa, hPa, or kPa. Choose the unit."
            )
        if column["role"] == "temperature" and not column["unit_confident"]:
            warnings.append(
                f"“{column['header']}” looks like temperature, but the header does not say Celsius or Fahrenheit. Choose the unit."
            )
        if column["role"] == "speed" and not column["unit_confident"]:
            warnings.append(
                f"“{column['header']}” looks like speed, but the header does not say km/h or m/s. Choose the unit and the frame."
            )
        if column["role"] == "speed" and column["unit_confident"]:
            warnings.append(
                f"“{column['header']}” gives the speed unit. It does not say whether the speed is total or vertical. Choose the frame."
            )
    if not any(column["role"] in ("altitude", "pressure") for column in roles):
        warnings.append("Choose an altitude column or a pressure column.")
    names = {_norm(column["header"]) for column in columns}
    if "g_force_g" in names or "engines_lit" in names or "engine_icons_total" in names:
        warnings.append(
            "g-force and engine-icon columns are display extras, not throttle and not speed. "
            "Leave them unused. A blank cell is missing, not zero."
        )
    return warnings


def _mapped_column(raw: dict, name: str, width: int, *, required: bool):
    spec = raw.get(name)
    if spec in (None, "", {}):
        if required:
            raise FormError(f"Choose the {name} column.", name)
        return None
    if not isinstance(spec, dict):
        raise FormError(f"The {name} mapping is not readable.", name)
    index = spec.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= width:
        raise FormError(f"Choose a valid {name} column.", name)
    return index


def _optional_column(raw: dict, name: str, width: int):
    if raw.get(name) in (None, "", {}):
        return None
    index = _mapped_column(raw, name, width, required=True)
    if name == "altitude":
        unit = _required_choice(raw[name], "unit", name, {"m", "ft", "km"})
        reference = _required_choice(
            raw[name], "reference", "altitude_reference", {"agl", "msl", "unknown"}
        )
        return index, unit, reference
    if name == "pressure":
        unit = _required_choice(raw[name], "unit", name, {"Pa", "hPa", "kPa"})
        return index, unit
    unit = _required_choice(raw[name], "unit", name, {"C", "F"})
    return index, unit


def _speed_column(raw: dict, width: int):
    if raw.get("speed") in (None, "", {}):
        return None
    index = _mapped_column(raw, "speed", width, required=True)
    unit = _required_choice(raw["speed"], "unit", "speed", {"kmh", "m_s"})
    frame = _required_choice(raw["speed"], "frame", "speed_frame", {"total", "vertical", "unknown"})
    return index, unit, frame


def _plain_index(raw: dict, name: str, width: int) -> int | None:
    spec = raw.get(name)
    if spec in (None, "", {}):
        return None
    if not isinstance(spec, dict):
        raise FormError(f"The {name} mapping is not readable.", name)
    index = spec.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= width:
        raise FormError(f"Choose a valid {name} column.", name)
    return index


def _stage_index(raw: dict, width: int) -> int | None:
    stage = raw.get("stage")
    if stage in (None, "", {}):
        return None
    if not isinstance(stage, dict):
        raise FormError("The stage mapping is not readable.", "stage")
    index = stage.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= width:
        raise FormError("Choose a valid stage or vehicle column.", "stage")
    return index


def _required_choice(raw: dict, key: str, field: str, allowed: set[str]) -> str:
    value = raw.get(key) if isinstance(raw, dict) else None
    if value not in allowed:
        labels = ", ".join(sorted(allowed))
        raise FormError(f"Choose one of: {labels}.", field)
    return str(value)


def _delimiter_char(name: str) -> str:
    return _DELIMITERS[name]


def _elevation(raw: dict) -> float:
    value = _plain_number(raw.get("site_elevation_m"), "Launch site elevation", "site_elevation_m")
    if value < -500 or value > 5000:
        raise FormError("Launch site elevation must be between -500 m and 5000 m.", "site_elevation_m")
    return value


def _reference_pressure(raw: dict) -> float:
    value = _plain_number(raw.get("reference_pressure_pa"), "Reference pressure", "reference_pressure_pa")
    if value <= 0:
        raise FormError("Reference pressure needs to be greater than zero.", "reference_pressure_pa")
    return value


def _plain_number(value, label: str, field: str) -> float:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise FormError(f"Enter {label.lower()}. It is not read from the file.", field)
    if isinstance(value, str) and "," in value:
        raise FormError(f"Enter {label.lower()} as a plain number, without commas.", field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise FormError(f"{label} needs to be a number.", field) from None
    if not math.isfinite(number):
        raise FormError(f"{label} needs to be a finite number.", field)
    return number


def _optional_cell(
    row: list[str], index: int, line_no: int, label: str, delimiter: str, counter: list[int]
) -> float:
    if index >= len(row) or row[index].strip() == "":
        return float("nan")
    return _cell(row, index, line_no, label, delimiter, counter)


def _text_cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index].strip()


def _uniform_token(
    values: list[str], label: str, allowed: set[str], summary: list[str]
) -> str | None:
    filled = [value.strip() for value in values if value.strip()]
    if not filled:
        summary.append(f"{label} is blank. No value was assumed.")
        return None
    if any(not value.strip() for value in values):
        summary.append(
            f"Some {label} cells are blank. A value from another row was not copied into them."
        )
    tokens = {value.lower() for value in filled}
    if len(tokens) > 1:
        raise FormError(
            f"{label} has more than one value in this track ({', '.join(sorted(tokens))}). "
            "It was not guessed.",
            label,
        )
    token = filled[0].lower()
    if token not in allowed:
        raise FormError(
            f"{label} value {token!r} is not one of: {', '.join(sorted(allowed))}.",
            label,
        )
    return token


def _cell(
    row: list[str], index: int, line_no: int, label: str, delimiter: str, counter: list[int]
) -> float:
    if index >= len(row) or row[index].strip() == "":
        raise FormError(f"Line {line_no} has no {label} value.", label)
    text = row[index].strip()
    number = _float_or_none(text)
    if number is None and delimiter != "," and re.fullmatch(r"[+-]?\d+,\d+", text):
        number = float(text.replace(",", "."))
        counter[0] += 1
    if number is None or not math.isfinite(number):
        raise FormError(f"Line {line_no} {label} is not a finite number ({text!r}).", label)
    return float(number)


def _float_or_none(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _reject_time_order(time_s: np.ndarray, lines: list[int]) -> None:
    if np.any(~np.isfinite(time_s)):
        bad = int(np.argmax(~np.isfinite(time_s)))
        raise FormError(f"Line {lines[bad]} has a time that is not finite.", "time")
    diffs = np.diff(time_s)
    backwards = np.flatnonzero(diffs < 0)
    if len(backwards):
        index = int(backwards[0]) + 1
        raise FormError(
            f"Line {lines[index]} goes backwards in time "
            f"({time_s[index]:.6g} s is before {time_s[index - 1]:.6g} s). "
            "The rows were not reordered.",
            "time",
        )
    duplicates = np.flatnonzero(diffs == 0)
    if len(duplicates):
        index = int(duplicates[0]) + 1
        raise FormError(
            f"Line {lines[index]} repeats the previous time ({time_s[index]:.6g} s). "
            "Duplicate times were not dropped.",
            "time",
        )


def _reject_amsl(amsl: np.ndarray, lines: list[int], label: str) -> None:
    if np.any(amsl > TROPOPAUSE_M + 1e-6):
        bad = int(np.argmax(amsl > TROPOPAUSE_M + 1e-6))
        raise FormError(
            f"Line {lines[bad]} {label} is above 11 km. "
            "The ISA troposphere formula stops there, and this row was not clamped.",
            "pressure" if "pressure" in label else "altitude",
        )
    if np.any(amsl < MIN_VALID_ALTITUDE_AMSL_M):
        bad = int(np.argmax(amsl < MIN_VALID_ALTITUDE_AMSL_M))
        raise FormError(
            f"Line {lines[bad]} {label} is below {MIN_VALID_ALTITUDE_AMSL_M:.0f} m, "
            "outside the range this page will convert.",
            "altitude",
        )


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")
