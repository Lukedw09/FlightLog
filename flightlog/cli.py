"""Command line for simulate, detect, replay, and plot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flightlog.atmosphere import Atmosphere
from flightlog.constants import SEA_LEVEL_PRESSURE_PA, VERSION
from flightlog.detect import DetectionConfig, detect
from flightlog.generate import SYNTHETIC_CLOCK, generate_flight
from flightlog.io import read_flight_csv, rederive_altitude, write_flight_csv
from flightlog.report import render_report
from flightlog.trajectory import FlightSpec


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "simulate":
            return _simulate(args)
        if args.command == "detect":
            return _report_file(args, plot_path=None)
        if args.command == "replay":
            return _report_file(args, plot_path=args.plot)
        if args.command == "plot":
            return _report_file(args, plot_path=args.output)
        if args.command == "ui":
            from flightlog.web import serve

            serve(host=args.host, port=args.port, open_browser=not args.no_browser)
            return 0
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"error: unknown command {args.command}", file=sys.stderr)
    return 1


def cli_entry() -> None:
    raise SystemExit(main())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightlog",
        description=(
            "Educational simulated flight-data logger. "
            "Generates synthetic barometric telemetry, writes a CSV, "
            "and detects liftoff, apogee, and landing from the altitude "
            "estimate. Not validated flight physics."
        ),
        epilog=(
            "example:\n"
            "  python -m flightlog ui\n"
            "  python -m flightlog simulate --output demo/sample_flight.csv "
            "--plot demo/sample_flight.png --seed 42\n"
            "  python -m flightlog replay demo/sample_flight.csv"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"flightlog {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    simulate = commands.add_parser(
        "simulate",
        help="Generate a simulated flight and write CSV.",
    )
    simulate.add_argument("--output", required=True, type=Path, help="CSV path to write.")
    simulate.add_argument("--plot", type=Path, help="Optional PNG path.")
    _add_flight_args(simulate)
    _add_noise_args(simulate)
    _add_detector_args(simulate)

    detect_cmd = commands.add_parser(
        "detect",
        help="Detect liftoff, apogee, and landing from a CSV.",
    )
    detect_cmd.add_argument("csv", type=Path)
    _add_detector_args(detect_cmd)
    _add_rederive_args(detect_cmd)

    replay = commands.add_parser(
        "replay",
        help="Reload a CSV, detect events, and optionally plot.",
    )
    replay.add_argument("csv", type=Path)
    replay.add_argument("--plot", type=Path, help="Optional PNG path.")
    _add_detector_args(replay)
    _add_rederive_args(replay)

    plot_cmd = commands.add_parser(
        "plot",
        help="Plot a CSV using events detected from its altitude column.",
    )
    plot_cmd.add_argument("csv", type=Path)
    plot_cmd.add_argument("--output", required=True, type=Path, help="PNG path to write.")
    _add_detector_args(plot_cmd)
    _add_rederive_args(plot_cmd)

    ui = commands.add_parser(
        "ui",
        help="Open the flight log page in your browser.",
    )
    ui.add_argument("--host", default="127.0.0.1", help="Bind address. Leave this as 127.0.0.1.")
    ui.add_argument("--port", type=int, default=47231, help="Local port. Tries the next ports if it is taken.")
    ui.add_argument("--no-browser", action="store_true", help="Do not open a browser window.")
    return parser


def _simulate(args: argparse.Namespace) -> int:
    atmosphere = Atmosphere(reference_pressure_pa=args.reference_pressure_pa)
    generated = generate_flight(
        _spec(args),
        seed=args.seed,
        pressure_noise_pa=args.pressure_noise_pa,
        temperature_noise_c=args.temperature_noise_c,
        atmosphere=atmosphere,
        start_utc=args.start_utc,
    )
    write_flight_csv(args.output, generated.log)
    print(f"Wrote {args.output}")
    # Detection sees the estimate only. Phase labels stay in the file for humans.
    config = _config(args)
    events = detect(generated.log.time_s, generated.log.altitude_m, config)
    if args.plot is not None:
        from flightlog.plot import plot_flight

        plot_flight(generated.log, args.plot, events)
        print(f"Wrote {args.plot}")
    print(render_report(generated.log, events, config), end="")
    return 0


def _report_file(args: argparse.Namespace, plot_path: Path | None) -> int:
    log = read_flight_csv(args.csv)
    log = _maybe_rederive(args, log)
    config = _config(args)
    events = detect(log.time_s, log.altitude_m, config)
    if plot_path is not None:
        from flightlog.plot import plot_flight

        plot_flight(log, plot_path, events)
        print(f"Wrote {plot_path}")
    print(render_report(log, events, config), end="")
    return 0


def _maybe_rederive(args: argparse.Namespace, log):
    site = args.site_elevation_m
    pressure = args.reference_pressure_pa
    overrides = site is not None or pressure is not None
    if args.rederive_altitude or (log.altitude_derived and overrides):
        return rederive_altitude(
            log,
            reference_pressure_pa=pressure,
            site_elevation_m=site,
        )
    if overrides:
        print(
            "note: altitude_m is already in the file, so the reference pressure and "
            "site elevation flags did not change it. Pass --rederive-altitude to "
            "recompute altitude from pressure_pa.",
            file=sys.stderr,
        )
    return log


def _spec(args: argparse.Namespace) -> FlightSpec:
    return FlightSpec(
        ground_s=args.ground_s,
        boost_s=args.boost_s,
        boost_accel_mps2=args.boost_accel,
        descent_rate_mps=args.descent_rate,
        landed_s=args.landed_s,
        sample_hz=args.sample_hz,
        site_elevation_m=args.site_elevation_m,
    )


def _config(args: argparse.Namespace) -> DetectionConfig:
    return DetectionConfig(
        smooth_window_s=args.smooth_s,
        min_liftoff_altitude_m=args.min_liftoff_m,
        liftoff_sustain_s=args.liftoff_sustain_s,
        landing_band_m=args.landing_band_m,
    )


def _add_flight_args(parser: argparse.ArgumentParser) -> None:
    spec = FlightSpec()
    parser.add_argument("--ground-s", type=float, default=spec.ground_s, help="Seconds on the pad before liftoff.")
    parser.add_argument("--boost-s", type=float, default=spec.boost_s, help="Seconds of constant net upward acceleration.")
    parser.add_argument(
        "--boost-accel",
        type=float,
        default=spec.boost_accel_mps2,
        help="Net upward acceleration during ascent, m/s^2. Already includes gravity. Not a motor name.",
    )
    parser.add_argument(
        "--descent-rate",
        type=float,
        default=spec.descent_rate_mps,
        help="Constant sink rate after apogee, m/s. Assumes the parachute opens at apogee.",
    )
    parser.add_argument("--landed-s", type=float, default=spec.landed_s, help="Seconds sitting on the pad after touchdown.")
    parser.add_argument("--sample-hz", type=float, default=spec.sample_hz, help="Samples per second.")
    parser.add_argument(
        "--site-elevation-m",
        type=float,
        default=spec.site_elevation_m,
        help="Launch site elevation above mean sea level, meters. Altitude in the file is above this site.",
    )
    parser.add_argument(
        "--reference-pressure-pa",
        type=float,
        default=SEA_LEVEL_PRESSURE_PA,
        help="ISA reference pressure p0 in pascals. Default 101325.",
    )
    parser.add_argument(
        "--start-utc",
        default=SYNTHETIC_CLOCK,
        help="Synthetic clock origin. The log is not a real recording at this time.",
    )


def _add_noise_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=42, help="RNG seed. Same seed repeats the same noise.")
    parser.add_argument(
        "--pressure-noise-pa",
        type=float,
        default=18.0,
        help="Gaussian pressure noise, standard deviation in pascals. Not a sensor datasheet.",
    )
    parser.add_argument(
        "--temperature-noise-c",
        type=float,
        default=0.25,
        help="Gaussian temperature noise, standard deviation in degrees Celsius.",
    )


def _add_detector_args(parser: argparse.ArgumentParser) -> None:
    cfg = DetectionConfig()
    parser.add_argument("--smooth-s", type=float, default=cfg.smooth_window_s, help="Trailing smooth window, seconds.")
    parser.add_argument(
        "--min-liftoff-m",
        type=float,
        default=cfg.min_liftoff_altitude_m,
        help="Minimum climb above the pad before liftoff, meters. Noise can raise this further.",
    )
    parser.add_argument(
        "--liftoff-sustain-s",
        type=float,
        default=cfg.liftoff_sustain_s,
        help="How long the climb must hold before liftoff is declared, seconds.",
    )
    parser.add_argument(
        "--landing-band-m",
        type=float,
        default=cfg.landing_band_m,
        help="How close to the pad counts as landed, meters.",
    )


def _add_rederive_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--rederive-altitude",
        action="store_true",
        help="Recompute altitude_m from pressure_pa before detecting. The CSV is not modified.",
    )
    parser.add_argument(
        "--site-elevation-m",
        type=float,
        default=None,
        help="Site elevation in meters, used only when deriving altitude from pressure.",
    )
    parser.add_argument(
        "--reference-pressure-pa",
        type=float,
        default=None,
        help="Reference pressure in pascals, used only when deriving altitude from pressure.",
    )
