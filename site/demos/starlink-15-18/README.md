# Starlink 15-18: complete visible webcast telemetry

## Source and scope
- Post: https://x.com/SpaceX/status/2116378109218009267
- Exact post text: **Watch Falcon 9 launch 27 @Starlink satellites to orbit from California https://t.co/aLuStYQVeG**
- Linked replay: https://x.com/i/broadcasts/1DGleVlqoaqJL
- Replay title: **Starlink Mission**. Mission designation identified from SpaceX's mission page: https://www.spacex.com/launches/sl-15-18 . No telemetry or event times were imported from that page.
- Launch date in New York: **October 31, 2026, 12:04 AM EDT**; mission named for October 30 at the California launch site. The folder uses that local mission date.
- Highest listed format downloaded: `replay-16000`, **3840 × 2160**, H.264, nominal **30000/1001 = 29.970 fps**, AAC. Actual packet-count/duration average is about 29.79 fps because source timestamps have gaps. Replay duration **1216.782 s**. No cookies/account login used.
- `webcast.info.json` has a broadcast-creation timestamp of October 19, 2026, 9:58:42 AM EDT, but the release timestamp is October 30, 2026, 11:54 PM EDT. The older creation timestamp is not treated as the launch date.

**Important:** the replay's telemetry ends at displayed **T+00:09:17**. It does not contain later SES-2, SECO-2, or payload deployment. “Complete” here means all telemetry shown in this specific replay, not an imagined complete orbital mission.

## Files
- `telemetry.csv`: main **long-format FlightLog import**, one vehicle observation per actual sample time. The shared stack is never duplicated onto both stages.
- `events.csv`: graphic/announcement observations; see timing caveat below. `timeline_labels.csv` catalogs all other timeline labels without inventing physical-event timestamps.
- `plot.png`: raw displayed speed/altitude, with breaks for missing readouts.
- `contact_sheets/`: 107 labelled, full-width telemetry-strip sheets, every sampled second from the first countdown overlay through the last telemetry. Both mission sample time and exact video PTS are labelled.
- `compact_sheets/`: 57 larger-glyph sheets for the numerical flight portion, retaining the clock, both numerical panels, g-force, and engine diagrams.
- `crops_exact/`: all 1212 original-resolution, full-width bottom-strip samples, including intro/outro without telemetry. `frame_times.json` maps crop numbers to original video presentation timestamps. Labels on the two sheet sets, not numeric filename offsets, are authoritative.
- `manual_corrections.csv`, `review/`, `glyph_checks.json`, `ocr_raw.jsonl`: OCR verification audit trail.
- `coverage_gaps.csv`, `source_frame_gaps.csv`: missing/undisplayed intervals and source timestamp discontinuities.
- `summary.json`, `verification.txt`, `probe.json`, `formats.log`, `source_post.txt`: counts, checks, and source provenance.
- `webcast.mp4`: unmodified downloaded 4K replay. Builder scripts remain alongside it for reproducibility.

## Time and precision
First observed **T+00:00:00** frame is at video **636.436 s**, after T-00:00:00 at 636.403 s. This defines T0 to one source frame (about 0.033 s). `t0_exact.jpg` is the frame-level check. This is the graphics clock reference, not an independent physical liftoff measurement.

`video_time_s` is the actual selected source frame PTS. `mission_time_s = video_time_s − 636.436`, retained to milliseconds. This is time-coordinate alignment only, not interpolated telemetry. `mission_clock_text` preserves the displayed whole-second T-/T+ clock, including T-00:00:00 versus T+00:00:00. An observation at +153.520 s therefore carries the actual displayed clock T+00:02:33.

Samples target roughly one per second, selecting the first available source frame after each target boundary. Missing source frames are not synthesized. Immediately after a source timestamp gap, two real samples can fall within the same displayed clock second; their actual timestamps remain distinct. Consumers must not replace them with fabricated synchronized observations.

Speed retains whole km/h. Altitude retains exactly its displayed precision: e.g. `99.7`, then `100`, not an invented `100.0`. G-force retains displayed tenths of g. All altitude/speed references are **unknown**, because the replay does not identify them. Blank is absent/unobserved, **not zero**. Displayed `0`, `0.0`, and prelaunch `0.1` are preserved as real readouts.

## Coverage and counts
| Vehicle | First–last displayed clock | Rows | Speed values | Altitude values |
|---|---|---:|---:|---:|
| combined_stack | T−08:28 to T+02:32 | 659 | 159 | 159 |
| booster | T+02:33 to T+08:30 | 357 | 291 | 357 |
| upper_stage | T+02:33 to T+09:17 | 404 | 402 | 391 |

**1420 total long-format rows.** Countdown rows before T−00:06 have clock only. Shared-stack numerical values run T−00:06 through T+02:32. The one shared readout remains labelled `combined_stack` until the two explicit stage cards appear at T+02:33; its transition is noted, without back-projecting separate stage values.

Extras: 158 g-force observations; engine diagrams are recorded as `engines_lit` and `engine_icons_total` (158 stack, 63 booster, 10 upper-stage observations). These are counts of visibly illuminated schematic dots, **not throttle percentages** or independently verified engine operation. No calibrated propellant gauges were shown. Semicircular arcs around readouts are not assigned an invented percent scale.

## Gaps and changing overlays
- Intro/outro contain no flight readouts. Promotional prelaunch cutaways keep the countdown clock but show no speed/altitude.
- Source video frame gaps near video 321.722–324.324 s, 654.988–657.657 s, and 1025.091–1027.026 s; smaller drops are in `source_frame_gaps.csv`. No postlaunch samples for displayed T+19, T+20, and T+389 are fabricated.
- At T−00:07 the numeric panel is animating in, with no numbers yet.
- Stage-2 altitude is not shown at T+153–163 while its engine diagram is shown/removed. It appears at T+164.
- Booster speed is replaced by the engine diagram at T+361–388 (entry-burn interval), and T+473–510 (landing-burn/landing interval). **Speed was not estimated during either interval.** Booster altitude remains visible.
- At T+511 the entire strip/clock disappears during the upper-stage-only card cut. The actual timestamp is retained as a blank, `no_overlay` upper-stage-context row. At T+512 the clock/labels return, but numeric values are not yet shown. Both values return at T+513.
- Booster readouts end at T+510. That endpoint is not used to infer landing time.

## Extraction and confidence
1. Used yt-dlp to inspect all public replay formats and download the highest available 4K format. ffprobe checked dimensions, cadence, duration, packets, and timestamp gaps.
2. Reused the Transporter-18 bottom-strip/contact-sheet approach, extended to the entire replay. Original 3840 × 420 strips preserve all numerical panels, engine diagrams, and the timeline.
3. EasyOCR read fixed numerical regions and the clock on every sample. Clock digits were checked against frame-time alignment; **zero unresolved clock disagreements**.
4. Independently segmented white glyphs and matched their shapes against actual, high-confidence webcast glyph exemplars. This caught decimal omissions, gauge-arc contamination, and attempts to OCR engine diagrams as numbers.
5. **130 numerical-region disagreements were visually reviewed** in `review/flags_00.jpg` through `flags_04.jpg`: **97 actual numeric cells corrected/confirmed**, **33 nonnumeric/not-yet-displayed cells left blank**. The original OCR text and image-read result are retained. There are **zero unresolved displayed numeric cells**. This is not a claim of infallibility or a second human transcription of every accepted cell; unflagged cells have OCR-plus-independent-glyph agreement, supplemented by visual layout/spot checks.
6. Final CSV has **1081 blank speed/altitude cells**: these predominantly represent clock-only countdown rows and intentionally undisplayed fields, not 1081 OCR failures. Row `quality` and `notes` distinguish these states.

## Events: announcement time is not physical-event time
`events.csv` logs only timings supported by this replay's graphics or audio. Its integer event times are the whole seconds displayed when a graphic observation/callout occurs. Audio timing/wording is **ASR-assisted and provisional: no manual listening pass was available**. Radio phrases such as MVac, fairing separation, and entry burn were normalized from imperfect automatic transcripts in context. Do not treat announcement timing as precision physical-event timing; callouts can lag visible indicator changes.

Event list: T0 clock; supersonic +54; Max Q +68; MECO indicator observed +149; stage-separation confirmation +153; SES-1/MVac-startup callout +156; upper-stage engine-indicator illumination +158; fairing-separation confirmation +186; entry-burn startup callout +365; booster FTS-safed +367; entry-burn shutdown +386; booster transonic +449; upper-stage FTS-safed +463; terminal guidance +479; landing-burn callout +482; landing-legs deploy +496; landing confirmation +506; SECO-1/MVac-shutdown callout +527.

The on-screen timeline also labels ENGINE CHILL, STRONGBACK RETRACT, STARTUP, LIFTOFF, MAX Q, STAGE SEP, FAIRING, ENTRY BURN, LANDING BURN, and SECO-1. Labels alone were not promoted to independently confirmed physical-event timestamps. No boostback callout/marker was identified; no boostback, later orbital burn, or payload-deployment timing has been invented.

## Problems encountered
- The video download succeeded at the first selected 4K format; no lower-resolution fallback, login, or cookies were needed.
- apt's package index returned HTTP 500/unsigned-index errors; OCR was instead installed successfully in an isolated Python venv. A direct system pip install was rejected by Python's externally-managed-environment rule; the venv resolved it.
- The first audio decoder API attempt was incompatible with installed PyAV. Decoded PCM arrays resolved that. A timestamp-preserving resample was then used so missing source audio packets did not shift callouts relative to the video. Early unaligned/unsuitable ASR experiments are not the event timing source; the aligned `radio_callouts.jsonl` is the retained audit input, with the limitations above.
- An early FPS-filter sampling experiment was abandoned before use; only `crops_exact/` and its logged PTS mapping feed the final data.

No q, acceleration, trajectory fit, interpolation, or other derived aerospace quantities were computed. Nothing was posted, uploaded, or sent externally.
