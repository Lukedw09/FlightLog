"""Overview figure: full flight on the left, magnified pad on the right.

The full-scale altitude, pressure, and temperature traces hide a few pascals
of sensor noise. The right-hand altitude and pressure panels use a tight
axis so the pad wiggle and the liftoff bar are visible. Vertical lines are
events from the altitude estimate, not from the simulator's phase labels.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flightlog.detect import DetectionConfig, DetectionResult, detect
from flightlog.log import FlightLog

_TRUE = "#3d4654"
_SMOOTH = "#0c4a6e"
_RAW = "#3d8ea8"
_BAR = "#1f7a3a"
_EVENTS = {
    "liftoff": ("#1f7a3a", "-", "Liftoff"),
    "apogee": ("#c45c26", "--", "Apogee"),
    "landing": ("#3d348b", ":", "Landing"),
}


def plot_flight(
    log: FlightLog,
    output: str | Path,
    events: DetectionResult | None = None,
    config: DetectionConfig | None = None,
) -> DetectionResult:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if events is None:
        events = detect(log.time_s, log.altitude_m, config)

    time = np.asarray(log.time_s, dtype=float)
    raw = np.asarray(log.altitude_m, dtype=float)
    smooth = np.asarray(events.smoothed_altitude_m, dtype=float)
    truth = None if log.altitude_m_true is None else np.asarray(log.altitude_m_true, dtype=float)

    with plt.rc_context(
        {
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "legend.fontsize": 8,
            "figure.titlesize": 13,
            "font.size": 10,
        }
    ):
        fig = plt.figure(figsize=(13.2, 9.0), constrained_layout=True)
        grid = fig.add_gridspec(3, 2, width_ratios=[1.35, 1.0])
        ax_alt = fig.add_subplot(grid[0, 0])
        ax_prs = fig.add_subplot(grid[1, 0], sharex=ax_alt)
        ax_tmp = fig.add_subplot(grid[2, 0], sharex=ax_alt)
        ax_zoom_alt = fig.add_subplot(grid[0, 1])
        ax_zoom_prs = fig.add_subplot(grid[1, 1], sharex=ax_zoom_alt)
        ax_res = fig.add_subplot(grid[2, 1], sharex=ax_alt)

        _plot_altitude(ax_alt, time, smooth, truth)
        _draw_events(ax_alt, events, labeled=True)
        ax_alt.legend(loc="upper right", frameon=False)
        ax_alt.set_ylabel("Altitude (m above site)")
        ax_alt.set_title("Altitude, full flight")

        _plot_quantity(
            ax_prs,
            time,
            log.pressure_pa,
            None if log.pressure_pa_true is None else log.pressure_pa_true,
            "No pressure column",
        )
        _draw_events(ax_prs, events, labeled=False)
        ax_prs.set_ylabel("Pressure (Pa)")
        ax_prs.set_title("Pressure, full flight")

        _plot_quantity(
            ax_tmp,
            time,
            log.temperature_c,
            None if log.temperature_c_true is None else log.temperature_c_true,
            "No temperature column",
        )
        _draw_events(ax_tmp, events, labeled=False)
        ax_tmp.set_ylabel("Temperature (°C)")
        ax_tmp.set_xlabel("Time since start (s)")
        ax_tmp.set_title("Temperature, full flight")

        t_zoom = _zoom_end(time, events)
        _plot_pad_altitude(ax_zoom_alt, time, raw, smooth, truth, events, t_zoom)
        _plot_pad_pressure(ax_zoom_prs, time, log, events, t_zoom)
        _plot_residual(ax_res, time, raw, smooth, truth)
        ax_res.set_xlabel("Time since start (s)")

        for axis in (ax_alt, ax_prs, ax_tmp, ax_zoom_alt, ax_zoom_prs, ax_res):
            _quiet_spines(axis)

        fig.suptitle(_title(log, events))
        fig.savefig(destination, dpi=130)
        plt.close(fig)
    return events


def _plot_altitude(axis, time, smooth, truth) -> None:
    if truth is not None:
        axis.plot(
            time,
            truth,
            color=_TRUE,
            linestyle="--",
            linewidth=1.3,
            zorder=2,
            label="True simulated path",
        )
    axis.plot(time, smooth, color=_SMOOTH, linewidth=1.8, zorder=3, label="Smoothed estimate")
    axis.axhline(0.0, color="#b0b6be", linewidth=0.6, zorder=1)


def _plot_quantity(axis, time, measured, truth, missing: str) -> None:
    if measured is None:
        axis.text(0.5, 0.5, missing, ha="center", va="center", transform=axis.transAxes)
        axis.set_xlim(float(time[0]), float(time[-1]))
        return
    if truth is not None:
        axis.plot(time, truth, color=_TRUE, linestyle="--", linewidth=1.3, zorder=2)
    axis.plot(time, measured, color=_SMOOTH, linewidth=1.2, zorder=3)


def _plot_pad_altitude(axis, time, raw, smooth, truth, events, t_zoom: float) -> None:
    mask = time <= t_zoom
    if truth is not None:
        axis.plot(
            time[mask],
            truth[mask],
            color=_TRUE,
            linestyle="--",
            linewidth=1.3,
            zorder=2,
        )
    axis.plot(time[mask], raw[mask], color=_RAW, linewidth=1.0, zorder=3)
    axis.plot(time[mask], smooth[mask], color=_SMOOTH, linewidth=1.6, zorder=4)
    bar = events.baseline_m + events.altitude_clearance_m
    axis.axhline(bar, color=_BAR, linestyle="-.", linewidth=1.0, zorder=2)
    axis.text(
        0.02,
        bar,
        " liftoff bar",
        color=_BAR,
        fontsize=8,
        va="bottom",
        transform=axis.get_yaxis_transform(),
    )
    _draw_events(axis, events, labeled=False)
    sigma = max(events.robust_sigma_m, 0.2)
    lo = events.baseline_m - max(5.0 * sigma, 2.5)
    hi = bar + max(3.0, 2.0 * sigma)
    axis.set_ylim(lo, hi)
    axis.set_xlim(float(time[0]), t_zoom)
    axis.set_title("Pad magnified (cyan = noisy estimate)")
    axis.set_ylabel("Altitude (m above site)")


def _plot_pad_pressure(axis, time, log: FlightLog, events: DetectionResult, t_zoom: float) -> None:
    axis.set_title("Pad pressure, magnified")
    axis.set_ylabel("Pressure (Pa)")
    if log.pressure_pa is None:
        axis.text(0.5, 0.5, "No pressure column", ha="center", va="center", transform=axis.transAxes)
        axis.set_xlim(float(time[0]), t_zoom)
        return
    mask = time <= t_zoom
    measured = np.asarray(log.pressure_pa, dtype=float)
    axis.plot(time[mask], measured[mask], color=_RAW, linewidth=1.0, zorder=3)
    if log.pressure_pa_true is not None:
        truth = np.asarray(log.pressure_pa_true, dtype=float)
        axis.plot(time[mask], truth[mask], color=_TRUE, linestyle="--", linewidth=1.3, zorder=2)
    _draw_events(axis, events, labeled=False)
    pre_end = events.liftoff.time_s if events.liftoff is not None else min(t_zoom, float(time[0]) + 2.0)
    pre = measured[time <= pre_end]
    pre = pre[np.isfinite(pre)]
    center = float(np.median(pre)) if len(pre) else float(np.nanmedian(measured))
    spread = max(float(np.std(pre)) * 8.0 if len(pre) else 0.0, 12.0)
    axis.set_ylim(center - spread * 1.35, center + spread * 0.65)
    axis.set_xlim(float(time[0]), t_zoom)


def _plot_residual(axis, time, raw, smooth, truth) -> None:
    if truth is not None:
        residual = raw - truth
        label = "Estimate minus true (m)"
        title = "Altitude error"
    else:
        residual = raw - smooth
        label = "Estimate minus smooth (m)"
        title = "Estimate minus smooth"
    axis.plot(time, residual, color=_RAW, linewidth=0.8, zorder=3)
    axis.axhline(0.0, color="#b0b6be", linewidth=0.6, zorder=1)
    finite = residual[np.isfinite(residual)]
    if len(finite):
        lo, hi = np.percentile(finite, [1, 99])
        span = max(float(hi - lo), 2.0)
        mid = 0.0
        axis.set_ylim(mid - span, mid + span)
    axis.set_ylabel(label)
    axis.set_title(title)


def _draw_events(axis, events: DetectionResult, *, labeled: bool) -> None:
    for event in (events.liftoff, events.apogee, events.landing):
        if event is None:
            continue
        color, style, name = _EVENTS[event.name]
        axis.axvline(
            event.time_s,
            color=color,
            linestyle=style,
            linewidth=1.15,
            zorder=1,
            label=name if labeled else None,
        )


def _zoom_end(time: np.ndarray, events: DetectionResult) -> float:
    end = float(time[-1])
    if events.liftoff is None:
        return min(end, max(8.0, float(time[0]) + 8.0))
    return min(end, events.liftoff.time_s + 0.4)


def _title(log: FlightLog, events: DetectionResult) -> str:
    bits = []
    for event, word in (
        (events.liftoff, "liftoff"),
        (events.apogee, "apogee"),
        (events.landing, "landing"),
    ):
        if event is None:
            bits.append(f"{word} not detected")
        else:
            bits.append(f"{word} {event.time_s:.2f} s")
    summary = "   ".join(bits)
    if log.simulated:
        return "SIMULATED flight telemetry — not a real flight\n" + summary
    return f"Flight telemetry ({log.data_origin})\n" + summary


def _quiet_spines(axis) -> None:
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.grid(True, color="#e2e4e8", linewidth=0.6)
    axis.tick_params(length=0)
