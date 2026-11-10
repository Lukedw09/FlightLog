# Starlink Mission — 2026-10-27 — FlightLog raw webcast observations

## Provenance and identity
- Post: https://x.com/SpaceX/status/2114979142638960965
- Post text: Watch Falcon 9 launch 27 @Starlink satellites to orbit from California https://t.co/Uxe26aH965
- Verified public webcast title: **Starlink Mission**. Launch date: **2026-10-27 (EDT)**. No unverified Starlink group number assigned. The spoken group designation was not reliably deciphered.
- Launch site: **SLC-4E, Space Launch Complex 4E, Vandenberg, California**, explicitly on the webcast location card (`location_check.jpg`). Landing platform/name not verified. Both additional datasets are Vandenberg; this one is nighttime footage. No Florida contrast was established by the source search.
- Post published 2026-10-27 03:14:56 EDT; replay release metadata 2026-10-27 03:15:00 EDT. These are **not independently verified liftoff wall-clock times**; broadcast latency unknown. Do not derive a precise wall-clock launch time by adding the webcast offset.
- Replay: https://x.com/i/broadcasts/1mGPaZgYgLDJN; exactly **one** 1080p download (`replay-5500`), **1920×1080, nominal 30000/1001 fps**. 4K was unnecessary. Duration see probe.json s (container timing in `probe.json`).
- Video SHA256: `6967dcb777d7079ddc6e281ce65c8373ef884084c3217b5bd32c082cfff6d612`; 230983104 bytes. Original source post/metadata, logs, crops, and audio remain local.
- Download succeeded without cookies. An initial shell-format quoting error occurred before any download ran; fixed by quoting the output template. No failed actual media downloads.

## Time base and representative coverage — NOT a complete 1 Hz flight
**Graphics T+0 = video 653.052 s**, first frame displaying `T+00:00:00`; preceding frame still displayed T−0. Video frame boundary uncertainty approximately one frame (33 ms), not absolute physical liftoff accuracy. `t0_check.jpg`, `t0/`, and `t0.log` preserve evidence.

`mission_time_s` is each real selected source presentation time minus that T0, to 0.001 s. It is **not rounded to whole seconds**. `video_time_s` is the separate replay offset. `mission_clock_text` preserves the on-screen whole-second clock and sign, so samples approximately halfway into a displayed second need not equal its integer text.

Representative policy permitted by the extended task: one actual source frame per second from displayed **T−5 through T+180**, **T+350 through T+400**, and **T+470 through T+540**; otherwise only displayed positive seconds divisible by 10, plus the final visible **T+558**. Earlier countdown telemetry is outside this dataset. Vehicle cadences reflect real displayed fields and intentional decimation, not synthesized synchronization. Blank transition rows at +511/+512 explicitly mark the cutaway; they are contextual missing rows, not claimed numeric observations. There are no post-card booster rows.

| Vehicle | Rows | Actual relative sample times (s) | Displayed clock range | Speed / altitude values |
|---|---:|---|---|---:|
| combined_stack | 159 | -5.472 to 152.519 | T-00:00:05 to T+00:02:32 | 159 / 159 |
| booster | 142 | 153.520 to 510.510 | T+00:02:33 to T+00:08:30 | 75 / 142 |
| upper_stage | 174 | 153.520 to 558.525 | T+00:02:33 to T+00:09:18 | 172 / 161 |

Total **475 long-format rows**. The source ends telemetry after displayed T+9:18; later deployment is not present. The source-frame PTS audit found **0 gaps over 0.1002 s**, maximum adjacent PTS spacing 0.034 s (`packet_timing_audit.json`). Intentional 10 s decimation is not a source recording gap.

### Overlay changes / missing fields
- One shared stack readout through displayed +152; explicit dual-stage cards begin +153. Shared values are never copied to booster/upper_stage. Attribution follows the displayed card, not a retroactive physical-separation model; announcement and graphics transitions can differ.
- G-force is numeric on the stack's right panel through +151; the next frame is a panel transition. No uncalibrated arc is converted into a percentage.
- Upper-stage altitude is absent until +164: engine schematic or transition replaces it. Upper-stage speed is retained.
- Booster speed is absent +361..390 and +474..510: schematic/transition replaces speed. Booster altitude remains visible. Schematic illumination counts are extra fields, not substitute speed values.
- Dual-stage cards last through +510. At +511/+512 speed and altitude are absent; faint mission clock alone returns at +512. Upper-stage-only centered card starts +513. Last telemetry +558; +559 onward is outro. Upper-stage attribution follows the preceding stage-2 card/camera continuity.
- No propellant gauges with a calibrated readable percent scale were identified. The decorative arcs are not estimated as fuel percentage. No numeric throttle readout found.
- `coverage_gaps.csv` lists deliberate decimation, field replacement, and card gaps. Actual sample gaps are also noted in the telemetry rows. No unobserved values have been zero-filled/interpolated.

## Fields and quality
Main header: `mission_time_s,vehicle,speed_kmh,altitude_km,altitude_reference,speed_reference,data_origin,source,video_time_s` plus `mission_clock_text,g_force_g,engines_lit,engine_icons_total,frame_file,quality,notes`.
- Readout speed km/h and altitude km, preserving displayed text precision (including integer altitude above 100 km). All speed/altitude references **unknown**: no MSL/AGL/inertial/Earth-fixed claim. `data_origin=webcast_readout`.
- `g_force_g` is the displayed G-FORCE panel only. `engines_lit` counts illuminated schematic centers, with `engine_icons_total` 9 or 1; **not throttle, thrust, or verified physical engine operation**. Faded/ambiguous illumination is blank.
- Zero numbers are included only where the graphic actually displays zero. Empty CSV values mean unshown/uncertain, not zero. Engine counts may legitimately be zero when a visible schematic is dark.
- Displayed mission-clock labels and representative source crops in `contact_sheets/` are retained for independent checking. Detailed `phase_*.jpg` sheets include every second near overlay changes.

## OCR and visual QA limits
EasyOCR read 1080p source telemetry crops (original bottom strip y=870..1080). A separate glyph-template comparison, seeded from high-confidence actual glyphs, checked numerical readings. This is an error-detection cross-check, **not statistically independent ground truth**. All 148 numerical flagged cells were visually reviewed on `review/flags_*.jpg`; corrected/confirmed values are in `manual_corrections.csv`. All unflagged numerical cells agreed with the glyph pass. Clock text was checked against the displayed clock progression; 1 clock correction(s). Phase-transition source sheets and min/max speed/altitude for all vehicles were visually checked (`qa_extremes.jpg`). This is not a claim of two humans independently reading every digit.

- Numerical cells audited: **1026** (includes G-force).
- Numerical flags resolved by visual review: **148**; unresolved **displayed numerical** values: **0**.
- Blank speed/altitude CSV cells: **82**, due to actual panel replacement/cutaway, not manufactured telemetry.
- Ambiguous illuminated-engine count rows: **0**, left blank and noted.
- Original `ocr_raw.jsonl`, `glyph_checks.json`, `review_flags.json`, `manual_corrections.csv` preserve audit lineage. Not every unflagged value was manually re-read individually; residual OCR/template systematic error remains possible. Representative sampling can miss extrema between retained samples. No aerodynamic or trajectory quantities have been computed.

## Events — evidence and uncertainty
`events.csv` uses displayed clock seconds. Graphics entries are observations of clock/card/indicator transitions, **not assertions that physical events happened exactly at those times**. All audio-derived entries are **PROVISIONAL ASR**, with the imperfect verbatim ASR and approximate video announcement timestamp preserved in notes. No manual listening pass was completed. These are announcement-time clock estimates, potentially offset from physical event timing; jargon normalization (especially SES-1/SECO-1) remains uncertain. Do not promote provisional events to certified ground truth. A timeline label alone is not treated as timed event evidence. No boostback event was independently observed/called clearly enough to log; do not infer one from trajectory or an ending.

| Mission clock seconds | Vehicle | Observed event/callout | Evidence |
|---:|---|---|---|
| 0 | combined_stack | T+0 clock transition | graphic: mission clock |
| 62 | combined_stack | Supersonic callout | audio: ASR provisional |
| 74 | combined_stack | Max Q callout | audio: ASR provisional |
| 149 | combined_stack | MECO indicator observed | graphic: engine diagram |
| 149 | combined_stack | MECO callout | audio: ASR provisional |
| 153 | booster | Dual-stage cards appear | graphic: stage labels |
| 153 | booster | Stage separation confirmed | audio: ASR provisional |
| 159 | upper_stage | Possible SES-1 / MVac startup callout | audio: ASR provisional |
| 186 | upper_stage | Fairing separation confirmed | audio: ASR provisional |
| 360 | booster | FTS safed callout | audio: ASR provisional |
| 364 | booster | Entry burn startup callout | audio: ASR provisional |
| 387 | booster | Entry burn shutdown callout | audio: ASR provisional |
| 447 | booster | Transonic callout | audio: ASR provisional |
| 479 | booster | Landing burn callout | audio: ASR provisional |
| 482 | upper_stage | Terminal guidance callout | audio: ASR provisional |
| 496 | booster | Landing legs deploy callout | audio: ASR provisional |
| 505 | booster | Landing confirmed | audio: ASR provisional |
| 524 | upper_stage | Possible SECO-1 / MVac shutdown callout | audio: ASR provisional |
| 534 | upper_stage | Nominal orbit insertion callout | audio: ASR provisional |

## Files and import
- `telemetry.csv`: main FlightLog long dataset; sort `(mission_time_s, vehicle)`, unique keys.
- `events.csv`: explicit graphics / provisional ASR event observations.
- `README.md`, `provenance.json`, `source_post.json`, `webcast.info.json`, `probe.json`, `packet_timing_audit.json`: provenance and method.
- `plot.png`: actual speed/altitude observations; lines only across adjacent one-second samples, gaps not bridged. No derived quantities.
- `coverage_gaps.csv`, `manual_corrections.csv`, `qa_extremes.jpg`, `contact_sheets/`, `review/`, `phase_*.jpg`: audit artifacts.
- `starlink-2026-10-27-flightlog.zip`: **only telemetry.csv, events.csv, README.md**; small import bundle, no video/images/large review archive.
- Reusable local scripts in the parent telemetry directory: `extract_additional.py`, `ocr_additional.py`, `audit_additional.py`, `calls_additional.py`, `add_endpoints.py`, `finalize_additional.py`, `packet_audit_additional.py`, `document_additional.py`, `verify_additional.py`.

Everything stayed on the box. Nothing posted, sent, or uploaded.
