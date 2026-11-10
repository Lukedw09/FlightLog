"""Build the page payload from the same functions the CLI uses.

The browser does not carry its own flight model. Simulation calls
``generate_flight``. Detection calls ``detect`` with time and altitude
only. CSV text comes from ``flight_csv_text`` / ``read_flight_csv_text``.
"""

from __future__ import annotations

import math

import numpy as np

from flightlog.atmosphere import Atmosphere
from flightlog.constants import DISCLAIMER, SEA_LEVEL_PRESSURE_PA
from flightlog.detect import DetectionConfig, DetectionResult, FlightEvent, detect
from flightlog.generate import generate_flight
from flightlog.io import flight_csv_text, read_flight_csv_text
from flightlog.log import FlightLog
from flightlog.trajectory import FlightSpec

MAX_CHART_POINTS = 4000
MAX_CSV_CHARS = 20_000_000


class FormError(ValueError):
    """A plain-language problem with one form field."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def form_defaults() -> dict[str, float | int]:
    spec = FlightSpec()
    detector = DetectionConfig()
    return {
        "ground_s": spec.ground_s,
        "boost_s": spec.boost_s,
        "boost_accel": spec.boost_accel_mps2,
        "descent_rate": spec.descent_rate_mps,
        "landed_s": spec.landed_s,
        "sample_hz": spec.sample_hz,
        "site_elevation_m": spec.site_elevation_m,
        "reference_pressure_pa": SEA_LEVEL_PRESSURE_PA,
        "seed": 42,
        "pressure_noise_pa": 18.0,
        "temperature_noise_c": 0.25,
        "smooth_s": detector.smooth_window_s,
        "min_liftoff_m": detector.min_liftoff_altitude_m,
        "liftoff_sustain_s": detector.liftoff_sustain_s,
        "landing_band_m": detector.landing_band_m,
    }


def simulate_form(raw: dict) -> dict:
    spec = _spec(raw)
    seed = _seed(raw)
    pressure_noise = _number(
        raw,
        "pressure_noise_pa",
        "Pressure noise",
        minimum=0,
        allow_zero=True,
    )
    temperature_noise = _number(
        raw,
        "temperature_noise_c",
        "Temperature noise",
        minimum=0,
        allow_zero=True,
    )
    reference = _number(raw, "reference_pressure_pa", "Reference pressure", minimum=0)
    atmosphere = Atmosphere(reference_pressure_pa=float(reference))
    try:
        atmosphere.validate()
    except ValueError as exc:
        raise FormError(str(exc), "reference_pressure_pa") from exc
    detector = _detector(raw)
    generated = generate_flight(
        spec,
        seed=seed,
        pressure_noise_pa=float(pressure_noise),
        temperature_noise_c=float(temperature_noise),
        atmosphere=atmosphere,
    )
    events = detect(generated.log.time_s, generated.log.altitude_m, detector)
    return payload_for(
        generated.log,
        events,
        flight_csv_text(generated.log),
        download_name="simulated_flight.csv",
    )


def _finite_list(values) -> list[float | None] | None:
    if values is None:
        return None
    out: list[float | None] = []
    for value in values:
        number = float(value)
        out.append(None if not np.isfinite(number) else round(number, 4))
    return out


def _track_payload(result, raw: dict, run_model: bool, profile: dict | None) -> dict:
    log = result.log
    notes = []
    if run_model and len(log) >= 10 and result.altitude_reference == "agl":
        events = detect(log.time_s, log.altitude_m, _detector(raw))
        analysis = "model_rocket"
        notes.append(
            "Model-rocket liftoff, apogee, and landing were checked on this track only. "
            "That apogee is the peak of this smoothed altitude, not an orbital apogee."
        )
    else:
        events = DetectionResult(
            liftoff=None,
            apogee=None,
            landing=None,
            baseline_m=float(np.nanmedian(log.altitude_m)),
            robust_sigma_m=0.0,
            altitude_clearance_m=0.0,
            smoothed_altitude_m=np.asarray(log.altitude_m, dtype=float),
            notes=(),
        )
        analysis = "record_only"
        notes.append(
            "Liftoff, apogee, and landing were not detected on this track. "
            "The highest altitude is only the maximum inside this record, not an orbital apogee. "
            "The last row is not a landing."
        )
    payload = payload_for(
        log,
        events,
        flight_csv_text(log),
        download_name="imported_flight.csv",
    )
    payload["track_name"] = result.track_name
    payload["analysis"] = analysis
    payload["time_offset_s"] = 0.0
    payload["time_basis"] = result.time_basis
    payload["altitude_reference"] = result.altitude_reference or "unknown"
    payload["speed_frame"] = result.speed_frame
    payload["source_note"] = result.source_note
    payload["video_time_s"] = (
        None
        if result.video_time_s is None
        else [None if not np.isfinite(value) else round(float(value), 4) for value in result.video_time_s]
    )
    payload["import_summary"] = list(result.summary) + notes
    payload["channels"] = {
        "altitude": "present" if log.altitude_m is not None else "unavailable",
        "pressure": "present" if log.pressure_pa is not None else "unavailable",
        "temperature": "present" if log.temperature_c is not None else "unavailable",
        "speed": "present" if result.speed_kmh is not None else "unavailable",
    }
    payload["speed_kmh"] = _finite_list(result.speed_kmh)
    finite_alt = np.asarray(log.altitude_m, dtype=float)
    finite_mask = np.isfinite(finite_alt)
    speed = None if result.speed_kmh is None else np.asarray(result.speed_kmh, dtype=float)
    speed_mask = None if speed is None else np.isfinite(speed)
    n_blank_alt = int(np.size(finite_alt) - np.count_nonzero(finite_mask))
    if n_blank_alt:
        payload["import_summary"].append(
            f"{n_blank_alt} rows have no altitude. They stay on this track as missing readings, not zeros."
        )
    n_blank_speed = 0 if speed_mask is None else int(np.size(speed) - np.count_nonzero(speed_mask))
    if n_blank_speed:
        payload["import_summary"].append(
            f"{n_blank_speed} rows have no speed. "
            "Those gaps were not filled and were not given to another track."
        )
    if result.source_note:
        payload["import_summary"].append(
            "Source text from the file, not checked here: " + result.source_note
        )
    if n_blank_alt or n_blank_speed:
        gap_note = (
            "The chart breaks the line where a readout is missing. "
            "Missing cells are not drawn as zero and were not interpolated."
        )
        existing = payload.get("chart_note")
        payload["chart_note"] = gap_note if not existing else f"{existing} {gap_note}"
    payload["extrema"] = {
        "t_first_s": float(log.time_s[0]),
        "t_last_s": float(log.time_s[-1]),
        "altitude_min_m": None if not np.any(finite_mask) else float(np.nanmin(finite_alt)),
        "altitude_max_m": None if not np.any(finite_mask) else float(np.nanmax(finite_alt)),
        "altitude_max_t_s": None
        if not np.any(finite_mask)
        else float(log.time_s[int(np.argmax(np.where(finite_mask, finite_alt, -np.inf)))]),
        "speed_min_kmh": None if speed_mask is None or not np.any(speed_mask) else float(np.nanmin(speed)),
        "speed_max_kmh": None if speed_mask is None or not np.any(speed_mask) else float(np.nanmax(speed)),
        "speed_max_t_s": None
        if speed_mask is None or not np.any(speed_mask)
        else float(log.time_s[int(np.argmax(np.where(speed_mask, speed, -np.inf)))]),
    }
    if profile and profile.get("coverage_match") and raw.get("confirm_attribution"):
        payload["data_origin"] = "attributed_readout"
        payload["attribution"] = profile["attribution"]
        payload["import_summary"] = [profile["attribution"], *payload["import_summary"]]
    else:
        payload["attribution"] = None
    payload["simulated"] = False
    return payload


def preview_import(csv_text: str, raw: dict | None = None) -> dict:
    """Native flightlog files open immediately. Anything else returns a mapping preview."""
    from flightlog.import_csv import inspect_csv

    options = raw or {}
    decoded = _xlsx_csv(options)
    if isinstance(decoded, dict):
        return decoded
    if decoded is not None:
        csv_text = decoded
    preview = inspect_csv(
        csv_text,
        delimiter=options.get("delimiter"),
        header=options.get("header"),
    )
    forced = bool(options.get("delimiter") or options.get("header"))
    if preview["native"] and not forced:
        flight = replay_csv(csv_text, options)
        return {"ok": True, "native": True, "flight": flight, "preview": preview}
    from flightlog.import_csv import readout_profile

    preview["readout"] = readout_profile(csv_text)
    return {"ok": True, "native": False, "preview": preview}


def _xlsx_csv(raw: dict):
    encoded = raw.get("xlsx_base64")
    if not encoded:
        return None
    import base64

    from flightlog.xlsx_io import sheet_names, sheet_to_csv

    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise FormError("The workbook could not be read.", "xlsx") from exc
    if len(data) > 20_000_000:
        raise FormError("That workbook is over 20 MB.", "xlsx")
    if not raw.get("sheet"):
        return {"ok": True, "native": False, "need_sheet": True, "sheets": sheet_names(data)}
    return sheet_to_csv(data, str(raw["sheet"]))


def import_mapped_csv(csv_text: str, raw: dict) -> dict:
    from flightlog.import_csv import apply_groups, readout_profile

    if not isinstance(raw, dict):
        raise FormError("The import mapping could not be read.", "mapping")
    if raw.get("provenance") == "simulated":
        raise FormError(
            "A mapped file cannot be marked simulated. "
            "Simulated is only for a flight this page generates, or for a flightlog file that already says so.",
            "provenance",
        )
    decoded = _xlsx_csv(raw)
    if isinstance(decoded, dict):
        return decoded
    if decoded is not None:
        csv_text = decoded
    profile = readout_profile(csv_text)
    if profile is not None and raw.get("profile") == "webcast_readout":
        raw = {**raw, "time_basis": "keep"}
        if profile.get("coverage_match") and raw.get("confirm_attribution") and not raw.get("track_name"):
            raw = {**raw, "track_name": "Combined stack"}
    results = apply_groups(csv_text, raw)
    run_model = bool(raw.get("model_rocket_events"))
    attach = bool(
        profile
        and profile.get("coverage_match")
        and raw.get("confirm_attribution")
        and not raw.get("stage")
    )
    tracks = [_track_payload(result, raw, run_model, profile if attach else None) for result in results]
    return {"ok": True, "tracks": tracks}


def import_event_file(csv_text: str) -> dict:
    from flightlog.import_csv import parse_event_markers

    return {"ok": True, "markers": parse_event_markers(csv_text)}


def replay_csv(csv_text: str, raw: dict | None = None) -> dict:
    if csv_text is None or not str(csv_text).strip():
        raise FormError("Choose a CSV file to open.", "csv")
    if len(csv_text) > MAX_CSV_CHARS:
        raise FormError(
            "That file is over 20 MB. flightlog keeps uploads on this computer, "
            "but this page will not open a file that large.",
            "csv",
        )
    detector = _detector(raw or {})
    log = read_flight_csv_text(csv_text, label="this file")
    events = detect(log.time_s, log.altitude_m, detector)
    return payload_for(log, events, csv_text, download_name="flight_log.csv")


def payload_for(
    log: FlightLog,
    events: DetectionResult,
    csv_text: str,
    *,
    download_name: str,
) -> dict:
    index, stride = _chart_index(len(log))
    truth = _truth(log)
    return {
        "ok": True,
        "simulated": bool(log.simulated),
        "data_origin": log.data_origin,
        "disclaimer": DISCLAIMER,
        "samples": len(log),
        "duration_s": float(log.time_s[-1] - log.time_s[0]),
        "chart_stride": stride,
        "chart_note": (
            None
            if stride == 1
            else (
                f"The chart draws every {stride}th sample so the page stays quick. "
                "Detection and the downloaded CSV still use every sample."
            )
        ),
        "time_s": _round_list(log.time_s, index, 6),
        "altitude_m": _round_list(log.altitude_m, index, 3),
        "pressure_pa": _round_optional(log.pressure_pa, index, 2),
        "temperature_c": _round_optional(log.temperature_c, index, 3),
        "altitude_m_true": _round_optional(log.altitude_m_true, index, 3),
        "pressure_pa_true": _round_optional(log.pressure_pa_true, index, 2),
        "temperature_c_true": _round_optional(log.temperature_c_true, index, 3),
        "events": {
            "liftoff": _event(events.liftoff, truth, "liftoff_s", None),
            "apogee": _event(events.apogee, truth, "apogee_s", "apogee_m"),
            "landing": _event(events.landing, truth, "landing_s", None),
        },
        "baseline_m": events.baseline_m,
        "robust_sigma_m": events.robust_sigma_m,
        "clearance_m": events.altitude_clearance_m,
        "notes": list(events.notes),
        "truth": truth,
        "csv": csv_text,
        "download_name": download_name,
    }


def _spec(raw: dict) -> FlightSpec:
    spec = FlightSpec(
        ground_s=float(
            _number(raw, "ground_s", "Time on the pad", minimum=0, allow_zero=True)
        ),
        boost_s=float(_number(raw, "boost_s", "Powered climb")),
        boost_accel_mps2=float(_number(raw, "boost_accel", "Net upward acceleration")),
        descent_rate_mps=float(_number(raw, "descent_rate", "Parachute sink rate")),
        landed_s=float(
            _number(raw, "landed_s", "Time after touchdown", minimum=0, allow_zero=True)
        ),
        sample_hz=float(_number(raw, "sample_hz", "Sample rate")),
        site_elevation_m=float(
            _number(
                raw,
                "site_elevation_m",
                "Launch site elevation",
                minimum=-500,
                maximum=5000,
                allow_zero=True,
            )
        ),
    )
    try:
        spec.validate()
    except ValueError as exc:
        raise FormError(str(exc)) from exc
    return spec


def _detector(raw: dict) -> DetectionConfig:
    # Missing detector keys fall back to defaults so a short JSON body still runs.
    defaults = form_defaults()
    merged = {**defaults, **{key: value for key, value in raw.items() if value is not None}}
    config = DetectionConfig(
        smooth_window_s=float(_number(merged, "smooth_s", "Smooth window")),
        min_liftoff_altitude_m=float(_number(merged, "min_liftoff_m", "Liftoff bar")),
        liftoff_sustain_s=float(_number(merged, "liftoff_sustain_s", "Liftoff hold time")),
        landing_band_m=float(_number(merged, "landing_band_m", "Landing band")),
    )
    try:
        config.validate()
    except ValueError as exc:
        raise FormError(str(exc)) from exc
    return config


def _seed(raw: dict) -> int:
    number = _number(raw, "seed", "Noise seed", minimum=0, allow_zero=True, integer=True)
    return int(number)


def _number(
    raw: dict,
    key: str,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    allow_zero: bool = False,
    integer: bool = False,
) -> float:
    if key not in raw or raw[key] is None:
        raise FormError(f"Enter {label.lower()}.", key)
    original = raw[key]
    if isinstance(original, str):
        text = original.strip()
        if text == "":
            raise FormError(f"Enter {label.lower()}.", key)
        if "," in text:
            raise FormError(f"Enter {label.lower()} as a plain number, without commas.", key)
        token = text
    else:
        token = original
    try:
        number = float(token)
    except (TypeError, ValueError):
        raise FormError(f"{label} needs to be a number.", key) from None
    if not math.isfinite(number):
        raise FormError(f"{label} needs to be a finite number.", key)
    if integer and not number.is_integer():
        raise FormError(f"{label} needs to be a whole number.", key)
    if minimum is not None and number < minimum:
        raise FormError(f"{label} must be at least {minimum:g}.", key)
    if maximum is not None and number > maximum:
        raise FormError(f"{label} must be at most {maximum:g}.", key)
    if not allow_zero and number <= 0:
        raise FormError(f"{label} needs to be greater than zero.", key)
    if allow_zero and minimum is None and number < 0:
        raise FormError(f"{label} cannot be negative.", key)
    return number


def _chart_index(count: int) -> tuple[np.ndarray, int]:
    if count <= MAX_CHART_POINTS:
        return np.arange(count), 1
    stride = int(math.ceil(count / MAX_CHART_POINTS))
    index = np.arange(0, count, stride)
    if index[-1] != count - 1:
        index = np.append(index, count - 1)
    return index, stride


def _round_list(values: np.ndarray, index: np.ndarray, digits: int) -> list[float | None]:
    picked = np.asarray(values, dtype=float)[index]
    out: list[float | None] = []
    for value in picked:
        if not math.isfinite(float(value)):
            out.append(None)
        else:
            out.append(round(float(value), digits))
    return out


def _round_optional(
    values: np.ndarray | None, index: np.ndarray, digits: int
) -> list[float | None] | None:
    if values is None:
        return None
    return _round_list(values, index, digits)


def _truth(log: FlightLog) -> dict | None:
    found: dict[str, float | str] = {}
    for name, key in (
        ("liftoff_s", "truth_liftoff_s"),
        ("apogee_s", "truth_apogee_s"),
        ("apogee_m", "truth_apogee_m"),
        ("landing_s", "truth_landing_s"),
    ):
        raw = log.metadata.get(key, "")
        if raw:
            found[name] = float(raw)
    if found:
        return found
    if log.altitude_m_true is not None:
        peak = int(np.argmax(log.altitude_m_true))
        return {
            "apogee_s": float(log.time_s[peak]),
            "apogee_m": float(log.altitude_m_true[peak]),
        }
    return None


def _event(
    event: FlightEvent | None,
    truth: dict | None,
    time_key: str,
    altitude_key: str | None,
) -> dict | None:
    if event is None:
        return None
    body: dict[str, float | None] = {
        "time_s": event.time_s,
        "altitude_m": event.altitude_m,
        "delta_s": None,
        "delta_m": None,
    }
    if truth is not None and time_key in truth:
        body["delta_s"] = event.time_s - float(truth[time_key])
    if truth is not None and altitude_key and altitude_key in truth:
        body["delta_m"] = event.altitude_m - float(truth[altitude_key])
    return body
