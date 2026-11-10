const defaults = JSON.parse(document.getElementById("defaults").textContent);
const form = document.getElementById("controls");
const formError = document.getElementById("form-error");
const strip = document.getElementById("origin-strip");
const readout = document.getElementById("readout");
const notes = document.getElementById("notes");
const chartNote = document.getElementById("chart-note");
const downloadButton = document.getElementById("download");
const againButton = document.getElementById("again");
const showTruth = document.getElementById("show-truth");
const truthToggle = document.getElementById("truth-toggle");

const charts = [
  { id: "chart-altitude", key: "altitude_m", truth: "altitude_m_true", digits: 1, unit: "m" },
  { id: "chart-pressure", key: "pressure_pa", truth: "pressure_pa_true", digits: 0, unit: "Pa" },
  { id: "chart-temperature", key: "temperature_c", truth: "temperature_c_true", digits: 2, unit: "°C" },
].map((spec) => ({ ...spec, canvas: document.getElementById(spec.id) }));

const COLORS = {
  estimate: "#0e4d6c",
  truth: "#3d4654",
  liftoff: "#1f7a3a",
  apogee: "#b4532a",
  landing: "#3d348b",
  grid: "#ece4d6",
  ink: "#1d1a16",
  muted: "#6b645b",
  hover: "#8c2f14",
};

const viewState = {
  payload: null,
  openedCsv: null,
  openedName: "flight_log.csv",
  t0: null,
  t1: null,
  hover: null,
  drag: null,
  tracks: [],
  markers: [],
  overlay: null,
  focus: "all",
  userZoom: false,
};
let requestSerial = 0;

try {
  fillForm(defaults);
  wireForm();
  wireModes();
  wireCharts();
  setMode("analyze");
} catch (error) {
  strip.classList.add("idle");
  strip.textContent = "The page could not start: " + error.message;
}

function fillForm(values) {
  for (const [key, value] of Object.entries(values)) {
    const input = form.elements[key];
    if (input) input.value = value;
  }
}

function readForm() {
  const body = {};
  for (const input of form.querySelectorAll("input[name]")) {
    body[input.name] = input.value.trim();
  }
  return body;
}

function wireForm() {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    viewState.openedCsv = null;
    againButton.hidden = true;
    runSimulation();
  });
  document.getElementById("reset").addEventListener("click", () => {
    fillForm(defaults);
    clearErrors();
    viewState.openedCsv = null;
    againButton.hidden = true;
    viewState.t0 = null;
    viewState.t1 = null;
    runSimulation();
  });
  document.getElementById("file").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      showError("That file is over 20 MB. This page will not open a file that large.");
      return;
    }
    viewState.openedName = file.name || "flight_log.csv";
    importState.sheet = "";
    try {
      await openFile(file);
    } catch (error) {
      importState.pendingEvents = "";
      showError(error.message || "That file could not be read on this computer.");
    }
  });
  againButton.addEventListener("click", () => {
    if (viewState.openedCsv) replay(viewState.openedCsv);
  });
  downloadButton.addEventListener("click", () => {
    const payload = viewState.payload;
    if (!payload || !payload.csv) return;
    const blob = new Blob([payload.csv], { type: "text/csv;charset=utf-8" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = viewState.openedCsv ? viewState.openedName : payload.download_name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  });
  document.getElementById("zoom-full").addEventListener("click", zoomFull);
  document.getElementById("zoom-pad").addEventListener("click", () => {
    const [full0, full1] = axisTime();
    if (!viewState.payload) return;
    viewState.userZoom = true;
    const liftoff = viewState.payload.events && viewState.payload.events.liftoff;
    viewState.t0 = full0;
    viewState.t1 = liftoff ? Math.min(full1, liftoff.time_s + 0.8) : Math.min(full1, full0 + 12);
    if (!(viewState.t1 > viewState.t0)) viewState.t1 = full1;
    draw();
  });
  document.getElementById("window-form").addEventListener("submit", (event) => {
    event.preventDefault();
    applyWindowForm();
  });
  showTruth.addEventListener("change", draw);
  form.addEventListener("input", (event) => {
    if (event.target.name) clearField(event.target.name);
  });
}

async function runSimulation() {
  await post("/api/simulate", readForm(), "Running the sketch…");
}

async function replay(csv) {
  const body = readForm();
  body.csv = csv;
  await post("/api/replay", body, "Reading the file…");
}

async function callApi(url, body) {
  if (window.flightlogEngine) {
    const payload = await window.flightlogEngine.request(url, body);
    return { ok: payload.ok !== false, payload };
  }
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error("The flight log program sent a response this page could not read.");
  }
  return { ok: response.ok && payload.ok !== false, payload };
}

async function post(url, body, pending) {
  const serial = ++requestSerial;
  clearErrors();
  setBusy(true, pending);
  try {
    const { ok, payload } = await callApi(url, body);
    if (serial !== requestSerial) return;
    if (!ok) {
      showError(payload.error || "The flight log could not run that request.", payload.field);
      return;
    }
    showPayload(payload);
  } catch (error) {
    if (serial !== requestSerial) return;
    showError(error.message || "The page lost contact with the flight log program.");
  } finally {
    if (serial === requestSerial) setBusy(false);
  }
}

function showPayload(payload) {
  if (!payload.track_name) viewState.overlay = null;
  if (payload.simulated && !viewState.openedCsv && !payload.track_name) viewState.simPayload = payload;
  viewState.payload = payload;
  revealLoaded();
  const altitudeCard = document.querySelector("#chart-altitude").closest(".chart-card");
  const speedCard = document.querySelector("#chart-pressure").closest(".chart-card");
  if (payload.altitude_reference === "unknown" || payload.altitude_reference === "pad") {
    altitudeCard.querySelector(".unit-label").textContent = "m, reference not stated in the file";
  } else if (payload.altitude_reference === "msl") {
    altitudeCard.querySelector(".unit-label").textContent = "m above sea level, site elevation subtracted";
  } else if (payload.track_name) {
    altitudeCard.querySelector(".unit-label").textContent = "m above the launch site";
  }
  if (payload.speed_kmh && !payload.pressure_pa) {
    speedCard.querySelector("h2").textContent = "Speed";
    speedCard.querySelector(".unit-label").textContent = "km/h";
    charts[1].key = "speed_kmh";
  } else if (!viewState.overlay) {
    speedCard.querySelector("h2").textContent = "Pressure";
    speedCard.querySelector(".unit-label").textContent = "Pa";
    charts[1].key = "pressure_pa";
  }
  viewState.hover = null;
  downloadButton.disabled = !payload.csv;
  const hasTruth = Array.isArray(payload.altitude_m_true);
  truthToggle.hidden = !hasTruth;
  if (!hasTruth) showTruth.checked = false;
  const legend = altitudeCard.querySelector(".legend");
  if (payload.track_name) showReadoutLegend(legend, viewState.tracks.filter((track) => track.id === payload.id));
  else restoreEstimateLegend(legend);
  renderStrip(payload);
  const imported = (payload.import_summary || []).join(" ");
  const detected = (payload.notes || []).join(" ");
  notes.textContent = [imported, detected].filter(Boolean).join(" ");
  const readNotes = document.getElementById("read-notes");
  if (readNotes) readNotes.hidden = !notes.textContent;
  const stats = document.getElementById("track-stats");
  if (stats) {
    stats.hidden = !payload.track_name;
    stats.textContent = payload.track_name ? trackSummary(payload) : "";
  }
  renderEvents(payload);
  const sparse = sparseSpacingNote(viewState.tracks.length ? viewState.tracks : [payload]);
  const note = [payload.chart_note, sparse].filter(Boolean).join(" ");
  chartNote.hidden = !note;
  chartNote.textContent = note;
  const zoomPad = document.getElementById("zoom-pad");
  if (zoomPad) zoomPad.textContent = payload.analysis === "record_only" ? "Start of record" : "Pad and liftoff";
  draw();
}

function renderStrip(payload) {
  strip.classList.remove("measured", "idle");
  if (payload.simulated) {
    strip.textContent = viewState.openedCsv
      ? "SIMULATED DATA. This opened file was generated, not recorded from a vehicle."
      : "SIMULATED DATA. This is a generated flight, not a recording from a vehicle.";
    return;
  }
  if (payload.data_origin === "measured") {
    strip.classList.add("measured");
    strip.textContent = "MEASURED FILE. Events come from the altitude column. This is not flight-control software.";
    return;
  }
  strip.classList.add("idle");
  if (payload.data_origin === "webcast_readout" || payload.data_origin === "attributed_readout") {
    strip.textContent = payload.attribution
      ? payload.attribution
      : "WEBCAST READOUT. data_origin is webcast_readout. This is not a simulation, and it is not independently authenticated here.";
    return;
  }
  if (payload.data_origin === "imported") {
    strip.textContent = "IMPORTED FILE. Columns and units were confirmed on the import screen. This is not marked as a simulated flight.";
    return;
  }
  strip.textContent = `Opened file (data origin: ${payload.data_origin}). Events come from the altitude column only.`;
}

function renderEvents(payload) {
  for (const name of ["liftoff", "apogee", "landing"]) {
    const card = document.querySelector(`.event[data-event="${name}"]`);
    const event = payload.events[name];
    const time = card.querySelector(".event-time");
    const alt = card.querySelector(".event-alt");
    const delta = card.querySelector(".event-delta");
    if (payload.analysis === "record_only") {
      const extrema = payload.extrema || {};
      if (name === "apogee") {
        card.querySelector("h2").textContent = "Highest in this record";
        time.textContent = `${formatNumber(extrema.altitude_max_t_s, 2)} s`;
        alt.textContent = `${formatNumber(extrema.altitude_max_m, 1)} m displayed. Not an orbital apogee.`;
        delta.textContent = "";
      } else {
        card.querySelector("h2").textContent = name === "liftoff" ? "Liftoff" : "Landing";
        time.textContent = "Not in this record";
        alt.textContent = name === "landing" ? "The last row is not a landing." : "This track does not include liftoff.";
        delta.textContent = "";
      }
      continue;
    }
    card.querySelector("h2").textContent = name === "apogee" ? "Apogee" : name === "liftoff" ? "Liftoff" : "Landing";
    if (!event) {
      time.textContent = "Not detected";
      alt.textContent = "";
      delta.textContent = "";
      continue;
    }
    time.textContent = `${formatNumber(event.time_s, 2)} s`;
    alt.textContent = `${formatNumber(event.altitude_m, 1)} m above site, smoothed`;
    delta.textContent = deltaText(event);
  }
  if (payload.analysis === "record_only") return;
  const pad = `Pad baseline ${formatNumber(payload.baseline_m, 2)} m. Liftoff clearance ${formatNumber(payload.clearance_m, 2)} m.`;
  if (!notes.textContent) notes.textContent = pad;
  else notes.textContent = `${pad} ${notes.textContent}`;
}

function deltaText(event) {
  if (event.delta_s === null || event.delta_s === undefined) return "";
  const seconds = Math.abs(event.delta_s);
  const when = event.delta_s >= 0 ? "later than the sketch" : "earlier than the sketch";
  let text = `${formatNumber(seconds, 2)} s ${when}`;
  if (event.delta_m !== null && event.delta_m !== undefined) {
    const meters = Math.abs(event.delta_m);
    const side = event.delta_m >= 0 ? "higher" : "lower";
    text += `, ${formatNumber(meters, 1)} m ${side}`;
  }
  return text;
}

function showError(message, field) {
  formError.hidden = false;
  formError.textContent = message;
  if (document.getElementById("controls").hidden) {
    strip.classList.add("idle");
    strip.textContent = message;
  }
  if (field) {
    const slot = form.querySelector(`[data-for="${field}"]`);
    const input = form.elements[field];
    if (slot) slot.textContent = message;
    if (input) {
      input.closest(".field").classList.add("invalid");
      input.focus();
    }
  }
}

function clearErrors() {
  formError.hidden = true;
  formError.textContent = "";
  for (const slot of form.querySelectorAll(".field-error")) slot.textContent = "";
  for (const field of form.querySelectorAll(".field.invalid")) field.classList.remove("invalid");
}

function clearField(name) {
  const slot = form.querySelector(`[data-for="${name}"]`);
  if (slot) slot.textContent = "";
  const input = form.elements[name];
  if (input) input.closest(".field").classList.remove("invalid");
  if (![...form.querySelectorAll(".field-error")].some((node) => node.textContent)) {
    formError.hidden = true;
  }
}

function setBusy(busy, message) {
  form.setAttribute("aria-busy", busy ? "true" : "false");
  for (const button of form.querySelectorAll("button")) button.disabled = busy;
  document.getElementById("file").disabled = busy;
  if (!busy) {
    downloadButton.disabled = !(viewState.payload && viewState.payload.csv);
    if (viewState.payload) renderStrip(viewState.payload);
    else {
      strip.classList.add("idle");
      strip.textContent = "The flight did not load. Correct the form and press Run simulation.";
    }
  }
  if (busy) {
    strip.classList.add("idle");
    strip.classList.remove("measured");
    strip.textContent = message;
  }
}

const DRAG_ZOOM_PX = 8;

function wireModes() {
  document.getElementById("mode-analyze").addEventListener("click", () => setMode("analyze"));
  document.getElementById("mode-simulate").addEventListener("click", () => setMode("simulate"));
}

function setMode(mode) {
  viewState.mode = mode;
  document.body.dataset.mode = mode;
  document.getElementById("mode-analyze").setAttribute("aria-selected", mode === "analyze" ? "true" : "false");
  document.getElementById("mode-simulate").setAttribute("aria-selected", mode === "simulate" ? "true" : "false");
  document.getElementById("controls").hidden = mode !== "simulate";
  const simLimits = document.getElementById("sim-limits");
  if (simLimits) simLimits.hidden = mode !== "simulate";
  if (mode === "simulate") {
    revealLoaded();
    if (!viewState.simPayload) runSimulation();
    else showPayload(viewState.simPayload);
    return;
  }
  if (viewState.tracks.length) {
    revealLoaded();
    focusTracks(viewState.focus || "all");
    return;
  }
  showEmpty();
}

function showEmpty() {
  const loaded = document.getElementById("loaded");
  const empty = document.getElementById("empty-state");
  if (loaded) loaded.hidden = true;
  if (empty) empty.hidden = false;
  if (document.body.dataset.runtime === "loading" || document.body.dataset.runtime === "error") return;
  strip.classList.add("idle");
  strip.classList.remove("measured");
  strip.textContent = "Open a CSV or workbook to begin.";
}

function revealLoaded() {
  const loaded = document.getElementById("loaded");
  const empty = document.getElementById("empty-state");
  if (loaded) loaded.hidden = false;
  if (empty) empty.hidden = true;
}

function zoomFull() {
  viewState.userZoom = true;
  viewState.t0 = null;
  viewState.t1 = null;
  viewState.drag = null;
  draw();
}

function applyWindowForm() {
  const from = Number(String(document.getElementById("window-from").value).replace(/,/g, ""));
  const to = Number(String(document.getElementById("window-to").value).replace(/,/g, ""));
  if (!Number.isFinite(from) || !Number.isFinite(to) || from === to) {
    readout.textContent = "Enter two different mission times, in seconds.";
    return;
  }
  viewState.userZoom = true;
  viewState.t0 = Math.min(from, to);
  viewState.t1 = Math.max(from, to);
  draw();
}

function wireCharts() {
  for (const chart of charts) {
    if (!chart.canvas) continue;
    chart.canvas.addEventListener("pointerdown", onChartPointerDown);
    chart.canvas.addEventListener("pointermove", (event) => {
      if (viewState.drag) return;
      if (!viewState.payload) return;
      viewState.hover = timeFromClient(event.clientX, event.currentTarget);
      updateReadout(viewState.hover);
      draw();
    });
    chart.canvas.addEventListener("pointerleave", () => {
      if (viewState.drag) return;
      viewState.hover = null;
      readout.textContent = "Move across a chart to read a sample. Drag across time to zoom.";
      draw();
    });
    chart.canvas.addEventListener("dblclick", zoomFull);
  }
  window.addEventListener("resize", draw);
}

function onChartPointerDown(event) {
  if (event.button !== 0 || !viewState.payload) return;
  event.preventDefault();
  const time = timeFromClient(event.clientX, event.currentTarget);
  viewState.drag = {
    t: time,
    current: time,
    originX: event.clientX,
    pointerId: event.pointerId,
    canvas: event.currentTarget,
  };
  viewState.hover = null;
  window.addEventListener("pointermove", onDragMove);
  window.addEventListener("pointerup", onDragEnd);
  window.addEventListener("pointercancel", onDragEnd);
  updateDragReadout();
  draw();
}

function onDragMove(event) {
  const drag = viewState.drag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  event.preventDefault();
  drag.current = timeFromClient(event.clientX, drag.canvas);
  drag.lastX = event.clientX;
  updateDragReadout();
  draw();
}

function onDragEnd(event) {
  const drag = viewState.drag;
  if (!drag || event.pointerId !== drag.pointerId) return;
  window.removeEventListener("pointermove", onDragMove);
  window.removeEventListener("pointerup", onDragEnd);
  window.removeEventListener("pointercancel", onDragEnd);
  drag.current = timeFromClient(event.clientX, drag.canvas);
  const dx = Math.abs(event.clientX - drag.originX);
  const start = Math.min(drag.t, drag.current);
  const end = Math.max(drag.t, drag.current);
  viewState.drag = null;
  if (dx >= DRAG_ZOOM_PX && end > start) {
    viewState.userZoom = true;
    viewState.t0 = start;
    viewState.t1 = end;
    readout.textContent = `Zoomed to ${formatNumber(start, 2)} s – ${formatNumber(end, 2)} s.`;
  } else {
    readout.textContent = "Move across a chart to read a sample. Drag across time to zoom.";
  }
  draw();
}

function updateDragReadout() {
  const drag = viewState.drag;
  if (!drag) return;
  const start = Math.min(drag.t, drag.current);
  const end = Math.max(drag.t, drag.current);
  readout.textContent = `Selecting ${formatNumber(start, 2)} s to ${formatNumber(end, 2)} s`;
}

function updateReadout(time) {
  const payload = viewState.payload;
  const index = nearestIndex(payload.time_s, time);
  const parts = [`t ${formatNumber(payload.time_s[index], 2)} s`];
  const altitude = payload.altitude_m[index];
  if (altitude !== null) parts.push(`${formatNumber(altitude, 1)} m`);
  const pressure = payload.pressure_pa && payload.pressure_pa[index];
  if (pressure !== null && pressure !== undefined) parts.push(`${formatNumber(pressure, 0)} Pa`);
  const temperature = payload.temperature_c && payload.temperature_c[index];
  if (temperature !== null && temperature !== undefined) parts.push(`${formatNumber(temperature, 2)} °C`);
  readout.textContent = parts.join("   ·   ");
}

function draw() {
  const payload = viewState.payload;
  if (!payload) return;
  syncWindowInputs();
  syncChartCards();
  if (viewState.overlay && viewState.overlay.length > 1) {
    drawOverlay(viewState.overlay);
    return;
  }
  for (const chart of charts) {
    if (chart.canvas.closest(".chart-card").hidden) continue;
    drawChart(chart, payload);
  }
  drawMarkers(payload);
}

function seriesHasNumbers(tracks, key) {
  return tracks.some((track) => Array.isArray(track[key]) && track[key].some((value) => value !== null && value !== undefined && Number.isFinite(value)));
}

function syncChartCards() {
  const tracks = viewState.overlay && viewState.overlay.length > 1
    ? viewState.overlay
    : viewState.payload
      ? [viewState.payload]
      : [];
  const pressureCard = document.getElementById("card-pressure");
  const temperatureCard = document.getElementById("card-temperature");
  if (pressureCard) pressureCard.hidden = !(seriesHasNumbers(tracks, "pressure_pa") || seriesHasNumbers(tracks, "speed_kmh"));
  if (temperatureCard) temperatureCard.hidden = !seriesHasNumbers(tracks, "temperature_c");
}

function drawOverlay(tracks) {
  const prepared = tracks.map((track) => displayTrack(track));
  const [t0, t1] = axisTime();
  drawMulti(charts[0], prepared, "altitude_m", t0, t1, "No altitude on the selected tracks");
  if (!document.getElementById("card-pressure").hidden) {
    drawMulti(charts[1], prepared, "speed_kmh", t0, t1, "Speed was not in these tracks");
  }
  if (!document.getElementById("card-temperature").hidden) {
    drawMulti(charts[2], prepared, "temperature_c", t0, t1, "Temperature was not in these tracks");
  }
}

function drawMulti(chart, tracks, key, t0, t1, missing) {
  const canvas = chart.canvas;
  if (!canvas) return;
  const { ctx, rect, box } = prepareCanvas(canvas);
  if (!ctx) return;
  const values = [];
  for (const track of tracks) {
    const series = track[key];
    if (!series) continue;
    series.forEach((value) => {
      if (value !== null && value !== undefined && Number.isFinite(value)) values.push(value);
    });
  }
  if (!values.length) {
    ctx.fillStyle = COLORS.muted;
    ctx.font = "14px Segoe UI, Helvetica Neue, Arial, sans-serif";
    ctx.fillText(missing, box.left, (box.top + box.bottom) / 2);
    paintSelection(ctx, box, t0, t1);
    return;
  }
  const span = { min: Math.min(...values), max: Math.max(...values) };
  if (span.min === span.max) {
    span.min -= 1;
    span.max += 1;
  }
  const pad = (span.max - span.min) * 0.08;
  span.min -= pad;
  span.max += pad;
  drawGrid(ctx, box, t0, t1, span);
  tracks.forEach((track) => {
    if (!track[key]) return;
    strokeSeries(ctx, { time_s: track.time_s }, track[key], box, t0, t1, span, track.color, [], 1.8);
  });
  if (key === "altitude_m") drawMarkerLines(ctx, box, t0, t1);
  paintSelection(ctx, box, t0, t1);
}

function drawMarkers(payload) {
  const canvas = charts[0].canvas;
  const rect = canvas.getBoundingClientRect();
  const ctx = canvas.getContext("2d");
  const box = { left: 62, right: rect.width - 12, top: 12, bottom: rect.height - 22 };
  const [t0, t1] = visibleTime(payload);
  drawMarkerLines(ctx, box, t0, t1);
}

function visibleMarkers() {
  const ids = viewState.overlay
    ? new Set(viewState.overlay.map((track) => track.id))
    : viewState.payload && viewState.payload.id
      ? new Set([viewState.payload.id])
      : null;
  if (!ids) return viewState.markers;
  return viewState.markers.filter((marker) => ids.has(marker.trackId));
}

function timingLabel(marker) {
  const source = marker.source || "";
  const notes = marker.notes || "";
  if (source.startsWith("graphic")) return "graphic";
  if (source.startsWith("audio")) {
    return /ASR|provisional/i.test(`${source} ${notes}`) ? "audio, ASR-assisted/provisional" : "audio";
  }
  if (marker.kind === "user_marker") return "marker you added";
  return "source marker";
}

function drawMarkerLines(ctx, box, t0, t1) {
  ctx.font = "11px Segoe UI, Helvetica Neue, Arial, sans-serif";
  let slot = 0;
  for (const marker of visibleMarkers()) {
    const track = viewState.tracks.find((item) => item.id === marker.trackId);
    const offset = track ? Number(track.time_offset_s) || 0 : 0;
    const time = marker.mission_time_s + offset;
    if (time < t0 || time > t1) continue;
    const x = xOf(time, box, t0, t1);
    const timing = timingLabel(marker);
    const graphic = timing === "graphic";
    const audio = timing.startsWith("audio");
    ctx.strokeStyle = graphic ? "#0e4d6c" : audio ? "#6b4f2a" : "#6b21a8";
    ctx.setLineDash(marker.kind === "source_marker" ? [2, 2] : [6, 3]);
    ctx.beginPath();
    ctx.moveTo(x, box.top);
    ctx.lineTo(x, box.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillText(timing.startsWith("audio") ? "audio" : timing, x + 3, box.top + 12 + (slot % 5) * 12);
    slot += 1;
  }
}

function sparseSpacingNote(tracks) {
  const sparse = tracks.some((track) =>
    (track.time_s || []).some((time, index) => index > 0 && time - track.time_s[index - 1] > 2.5)
  );
  if (!sparse) return "";
  return "Some neighboring samples are several seconds apart. The line stops there instead of bridging them. That spacing is not the same thing as a blank cell, and it does not mean every second was read.";
}

function renderSourceMarkers() {
  const list = document.getElementById("source-markers");
  if (!list) return;
  const filter = document.getElementById("marker-filter");
  const selected = filter ? filter.value : "all";
  let markers = visibleMarkers();
  if (selected === "graphic") markers = markers.filter((marker) => timingLabel(marker) === "graphic");
  if (selected === "audio") markers = markers.filter((marker) => timingLabel(marker).startsWith("audio"));
  list.hidden = markers.length === 0;
  list.replaceChildren();
  for (const marker of markers) {
    const track = viewState.tracks.find((item) => item.id === marker.trackId);
    const timing = timingLabel(marker);
    const item = document.createElement("li");
    item.dataset.timing = timing.startsWith("graphic") ? "graphic" : timing.startsWith("audio") ? "audio" : "other";
    const time = document.createElement("strong");
    time.textContent = `${formatNumber(marker.mission_time_s, 3)} s`;
    const tag = document.createElement("span");
    tag.className = "timing";
    tag.textContent = timing;
    item.append(time, document.createTextNode(` ${track ? track.track_name : marker.vehicle || ""} — ${marker.event} `), tag);
    list.appendChild(item);
  }
}

function drawChart(chart, payload) {
  const canvas = chart.canvas;
  if (!canvas) return;
  const prepared = prepareCanvas(canvas);
  if (!prepared.ctx) return;
  const { ctx, box } = prepared;
  if (box.right <= box.left || box.bottom <= box.top) return;

  const [t0, t1] = axisTime();
  const i0 = nearestIndex(payload.time_s, t0);
  const i1 = nearestIndex(payload.time_s, t1);
  const start = Math.min(i0, i1);
  const end = Math.max(i0, i1);
  const series = [payload[chart.key]];
  if (showTruth.checked && payload[chart.truth]) series.push(payload[chart.truth]);
  const span = ySpan(series, start, end);
  if (!span) {
    ctx.fillStyle = COLORS.muted;
    ctx.font = "14px Segoe UI, Helvetica Neue, Arial, sans-serif";
    ctx.fillText("No column in this file", box.left, (box.top + box.bottom) / 2);
    paintSelection(ctx, box, t0, t1);
    return;
  }

  drawGrid(ctx, box, t0, t1, span);
  if (showTruth.checked && payload[chart.truth]) {
    strokeSeries(ctx, payload, payload[chart.truth], box, t0, t1, span, COLORS.truth, [5, 4], 1.4);
  }
  if (payload[chart.key]) {
    strokeSeries(ctx, payload, payload[chart.key], box, t0, t1, span, COLORS.estimate, [], 1.8);
  }
  if (chart.key === "altitude_m") drawEvents(ctx, payload, box, t0, t1);
  if (viewState.hover !== null && viewState.hover >= t0 && viewState.hover <= t1) {
    const x = xOf(viewState.hover, box, t0, t1);
    ctx.strokeStyle = COLORS.hover;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(x, box.top);
    ctx.lineTo(x, box.bottom);
    ctx.stroke();
  }
  paintSelection(ctx, box, t0, t1);
}

function prepareCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return { ctx: null, rect, box: { left: 0, right: 0, top: 0, bottom: 0 } };
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  return {
    ctx,
    rect,
    box: { left: 62, right: rect.width - 12, top: 12, bottom: rect.height - 22 },
  };
}

function paintSelection(ctx, box, t0, t1) {
  const drag = viewState.drag;
  if (!drag || !(t1 > t0)) return;
  const x1 = xOf(drag.t, box, t0, t1);
  const x2 = xOf(drag.current, box, t0, t1);
  const left = Math.min(x1, x2);
  const width = Math.abs(x2 - x1);
  ctx.save();
  ctx.fillStyle = "rgba(14, 77, 108, 0.22)";
  ctx.fillRect(left, box.top, Math.max(width, 2), box.bottom - box.top);
  ctx.strokeStyle = "#0e4d6c";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([]);
  ctx.strokeRect(left + 0.5, box.top + 0.5, Math.max(width - 1, 0), box.bottom - box.top - 1);
  ctx.fillStyle = "#0e4d6c";
  ctx.font = "12px Segoe UI, Helvetica Neue, Arial, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  const start = Math.min(drag.t, drag.current);
  const end = Math.max(drag.t, drag.current);
  const label = `${formatTick(start)} s – ${formatTick(end)} s`;
  const textX = Math.min(Math.max(left + 6, box.left), box.right - 120);
  ctx.fillText(label, textX, box.top + 6);
  ctx.restore();
}

function drawGrid(ctx, box, t0, t1, span) {
  ctx.font = "11px Segoe UI, Helvetica Neue, Arial, sans-serif";
  ctx.fillStyle = COLORS.muted;
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const yStep = niceStep(span.max - span.min, 4);
  const yStart = Math.ceil(span.min / yStep) * yStep;
  for (let value = yStart; value <= span.max + yStep * 0.01; value += yStep) {
    const y = yOf(value, box, span);
    ctx.beginPath();
    ctx.moveTo(box.left, y);
    ctx.lineTo(box.right, y);
    ctx.stroke();
    ctx.fillText(formatTick(value), box.left - 8, y);
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const xStep = niceStep(t1 - t0, 6);
  const xStart = Math.ceil(t0 / xStep) * xStep;
  for (let value = xStart; value <= t1 + xStep * 0.01; value += xStep) {
    const x = xOf(value, box, t0, t1);
    ctx.fillText(`${formatTick(value)} s`, x, box.bottom + 6);
  }
}

function strokeSeries(ctx, payload, values, box, t0, t1, span, color, dash, width) {
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.setLineDash(dash);
  let drawing = false;
  let lastTime = null;
  for (let i = 0; i < payload.time_s.length; i += 1) {
    const time = payload.time_s[i];
    const value = values[i];
    if (time < t0 || time > t1 || value === null || value === undefined || !Number.isFinite(value)) {
      drawing = false;
      continue;
    }
    const x = xOf(time, box, t0, t1);
    const y = yOf(value, box, span);
    const sparseStep = lastTime !== null && time - lastTime > 2.5;
    if (!drawing || sparseStep) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
    drawing = true;
    lastTime = time;
  }
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawEvents(ctx, payload, box, t0, t1) {
  ctx.font = "11px Segoe UI, Helvetica Neue, Arial, sans-serif";
  ctx.textBaseline = "top";
  for (const name of ["liftoff", "apogee", "landing"]) {
    const event = payload.events[name];
    if (!event || event.time_s < t0 || event.time_s > t1) continue;
    const x = xOf(event.time_s, box, t0, t1);
    ctx.strokeStyle = COLORS[name];
    ctx.lineWidth = 1.25;
    ctx.setLineDash(name === "apogee" ? [4, 3] : name === "landing" ? [1, 3] : []);
    ctx.beginPath();
    ctx.moveTo(x, box.top);
    ctx.lineTo(x, box.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = COLORS[name];
    ctx.textAlign = "left";
    ctx.fillText(name, x + 4, box.top + 2);
  }
}

function visibleTime(payload) {
  return axisTime(payload);
}

function axisTime(payload) {
  const source = payload || viewState.payload;
  let full0 = 0;
  let full1 = 1;
  if (viewState.overlay && viewState.overlay.length > 1) {
    const times = viewState.overlay.flatMap((track) => displayTrack(track).time_s);
    if (times.length) {
      full0 = Math.min(...times);
      full1 = Math.max(...times);
    }
  } else if (source && source.time_s && source.time_s.length) {
    full0 = source.time_s[0];
    full1 = source.time_s[source.time_s.length - 1];
  }
  const t0 = viewState.t0 === null ? full0 : Math.max(full0, viewState.t0);
  const t1 = viewState.t1 === null ? full1 : Math.min(full1, viewState.t1);
  if (!(t1 > t0)) return [full0, full1];
  return [t0, t1];
}

function syncWindowInputs() {
  const from = document.getElementById("window-from");
  const to = document.getElementById("window-to");
  if (!from || !to || !viewState.payload) return;
  if (document.activeElement === from || document.activeElement === to) return;
  const [t0, t1] = axisTime();
  from.value = plainNumber(t0);
  to.value = plainNumber(t1);
}

function plainNumber(value) {
  return String(Math.round(value * 1000) / 1000);
}

function timeFromClient(clientX, canvas) {
  const rect = canvas.getBoundingClientRect();
  const [t0, t1] = axisTime();
  const plotLeft = rect.left + 62;
  const plotRight = rect.right - 12;
  const span = Math.max(1, plotRight - plotLeft);
  const fraction = Math.min(1, Math.max(0, (clientX - plotLeft) / span));
  return t0 + fraction * (t1 - t0);
}

function ySpan(series, start, end) {
  let min = Infinity;
  let max = -Infinity;
  for (const values of series) {
    if (!values) continue;
    for (let i = start; i <= end; i += 1) {
      const value = values[i];
      if (value === null || value === undefined) continue;
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  if (max === min) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.08;
  return { min: min - pad, max: max + pad };
}

function plotBox(canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    left: rect.left + 62,
    right: rect.right - 12,
    width: rect.width,
  };
}

function timeAt(clientX, box) {
  const payload = viewState.payload;
  const [t0, t1] = visibleTime(payload);
  const fraction = (clientX - box.left) / Math.max(1, box.right - box.left);
  return t0 + Math.min(1, Math.max(0, fraction)) * (t1 - t0);
}

function xOf(time, box, t0, t1) {
  return box.left + ((time - t0) / (t1 - t0)) * (box.right - box.left);
}

function yOf(value, box, span) {
  return box.bottom - ((value - span.min) / (span.max - span.min)) * (box.bottom - box.top);
}

function nearestIndex(times, time) {
  let low = 0;
  let high = times.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (times[mid] < time) low = mid + 1;
    else high = mid;
  }
  if (low > 0 && Math.abs(times[low - 1] - time) < Math.abs(times[low] - time)) return low - 1;
  return low;
}

function niceStep(span, count) {
  const rough = Math.max(span, 1e-9) / Math.max(count, 1);
  const power = 10 ** Math.floor(Math.log10(rough));
  const error = rough / power;
  const multiple = error >= 7.5 ? 10 : error >= 3.5 ? 5 : error >= 1.5 ? 2 : 1;
  return multiple * power;
}

function formatTick(value) {
  const abs = Math.abs(value);
  if (abs >= 1000) return formatNumber(value, 0);
  if (abs >= 100) return formatNumber(value, 0);
  if (abs >= 10) return formatNumber(value, 1);
  return formatNumber(value, 2);
}

function formatNumber(value, digits) {
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

const importDialog = document.getElementById("import-dialog");
const importState = { csv: "", xlsx: "", sheet: "", name: "", preview: null };

document.getElementById("import-cancel").addEventListener("click", closeImport);
document.getElementById("import-apply").addEventListener("click", applyImport);
document.getElementById("import-header").addEventListener("change", refreshImportPreview);
document.getElementById("import-measured").addEventListener("change", updateImportPlan);
importDialog.addEventListener("change", (event) => {
  if (event.target.closest("#import-table") || event.target.closest("#import-extra")) updateImportPlan();
});

async function openFile(file) {
  const body = await fileBody(file);
  const result = await requestJson("/api/import/preview", body);
  if (result.need_sheet) {
    if (result.sheets.length === 1) {
      importState.sheet = result.sheets[0];
      return openFile(file);
    }
    importState.pendingSheets = result.sheets;
    showError("This workbook has more than one sheet: " + result.sheets.join(", ") + ". Sheet choice for several sheets is not on this screen yet; keep one sheet per file.");
    return;
  }
  if (result.native) {
    viewState.openedCsv = body.csv;
    againButton.hidden = false;
    closeImport();
    showNativeFlight(result.flight);
    return;
  }
  importState.csv = body.csv || "";
  importState.xlsx = body.xlsx_base64 || "";
  importState.name = file.name;
  const appendBox = document.getElementById("import-append");
  if (appendBox) appendBox.checked = false;
  importState.preview = result.preview;
  renderImport();
  importDialog.hidden = false;
}

async function fileBody(file) {
  if (file.name.toLowerCase().endsWith(".xlsx")) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    const body = { xlsx_base64: btoa(binary) };
    if (importState.sheet) body.sheet = importState.sheet;
    return body;
  }
  return { csv: await file.text() };
}

async function openCsv(text, name) {
  importState.csv = text;
  importState.name = name;
  importState.xlsx = "";
  try {
    const result = await requestJson("/api/import/preview", { csv: text });
    if (result.native) {
      viewState.openedCsv = text;
      againButton.hidden = false;
      closeImport();
      showNativeFlight(result.flight);
      return;
    }
    importState.preview = result.preview;
    const appendBox = document.getElementById("import-append");
    if (appendBox) appendBox.checked = false;
    renderImport();
    importDialog.hidden = false;
  } catch (error) {
    importState.pendingEvents = "";
    showError(error.message);
  }
}

async function refreshImportPreview() {
  const delimiter = selectedDelimiter();
  const header = document.getElementById("import-header").checked ? "present" : "absent";
  try {
    const result = await requestJson("/api/import/preview", {
      csv: importState.csv,
      delimiter,
      header,
    });
    importState.preview = result.preview;
    renderImport();
  } catch (error) {
    showImportError(error.message);
  }
}

function renderImport() {
  const preview = importState.preview;
  const appendRow = document.getElementById("import-append-row");
  const appendHint = document.getElementById("import-append-hint");
  const hasFlight = viewState.tracks.length > 0;
  if (appendRow) appendRow.hidden = !hasFlight;
  if (appendHint) appendHint.hidden = !hasFlight;
  document.getElementById("import-file").textContent = `${importState.name}${importState.sheet ? " · sheet " + importState.sheet : ""} · ${preview.data_rows} data rows${preview.readout && preview.readout.note ? " · " + preview.readout.note : ""}`;
  document.getElementById("import-header").checked = preview.header === "present";
  const choices = document.getElementById("delimiter-choices");
  choices.replaceChildren();
  for (const [id, label] of [["comma", "Comma"], ["semicolon", "Semicolon"], ["tab", "Tab"]]) {
    const choice = document.createElement("label");
    choice.className = "check";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "delimiter";
    input.value = id;
    input.checked = preview.delimiter === id;
    input.addEventListener("change", refreshImportPreview);
    choice.append(input, document.createTextNode(label));
    choices.appendChild(choice);
  }
  const warnings = document.getElementById("import-warnings");
  warnings.replaceChildren();
  for (const warning of preview.warnings || []) {
    const paragraph = document.createElement("p");
    paragraph.textContent = warning;
    warnings.appendChild(paragraph);
  }
  const table = document.getElementById("import-table");
  table.replaceChildren();
  const head = document.createElement("tr");
  for (const title of ["Column", "Example values", "Use as", "Unit"]) {
    const cell = document.createElement("th");
    cell.textContent = title;
    head.appendChild(cell);
  }
  table.appendChild(head);
  for (const column of preview.columns) {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = column.header;
    const samples = document.createElement("td");
    samples.className = "samples";
    samples.textContent = column.samples.filter(Boolean).slice(0, 4).join(", ");
    const roleCell = document.createElement("td");
    const role = document.createElement("select");
    role.dataset.index = String(column.index);
    role.dataset.kind = "role";
    for (const [value, label] of [
      ["", "Ignore"],
      ["time", "Mission time"],
      ["video_time", "Video time (separate)"],
      ["stage", "Stage or vehicle"],
      ["altitude", "Altitude"],
      ["altitude_reference", "Altitude reference"],
      ["speed", "Speed"],
      ["speed_reference", "Speed reference"],
      ["pressure", "Pressure"],
      ["temperature", "Temperature"],
      ["data_origin", "Data origin"],
      ["source", "Source note"],
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      role.appendChild(option);
    }
    role.value = column.role || "";
    role.addEventListener("change", () => {
      fillUnitSelect(row.querySelector("[data-kind='unit']"), role.value, column);
      renderImportExtra();
      updateImportPlan();
    });
    roleCell.appendChild(role);
    const unitCell = document.createElement("td");
    const unit = document.createElement("select");
    unit.dataset.kind = "unit";
    unit.dataset.index = String(column.index);
    fillUnitSelect(unit, role.value, column);
    unit.addEventListener("change", () => {
      renderImportExtra();
      updateImportPlan();
    });
    unitCell.appendChild(unit);
    row.append(name, samples, roleCell, unitCell);
    table.appendChild(row);
  }
  renderImportExtra();
  updateImportPlan();
  showImportError("");
}

function fillUnitSelect(select, role, column) {
  const previous = select.value;
  const options = {
    time: [["", "Choose unit"], ["s", "Seconds"], ["ms", "Milliseconds"]],
    altitude: [["", "Choose unit"], ["m", "Meters"], ["km", "Kilometers"], ["ft", "Feet"]],
    video_time: [["s", "Seconds"]],
    speed: [["", "Choose unit"], ["kmh", "km/h"], ["m_s", "m/s"]],
    pressure: [["", "Choose unit"], ["Pa", "Pa"], ["hPa", "hPa"], ["kPa", "kPa"]],
    temperature: [["", "Choose unit"], ["C", "Celsius"], ["F", "Fahrenheit"]],
  }[role] || [["", "—"]];
  select.replaceChildren();
  for (const [value, label] of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  select.disabled = !role;
  const suggested = column && String(column.index) === select.dataset.index && column.unit_confident ? column.unit : "";
  if ([...select.options].some((option) => option.value === previous && previous)) select.value = previous;
  else if (suggested && [...select.options].some((option) => option.value === suggested)) select.value = suggested;
  else select.value = "";
}

function mappingFromDialog() {
  const mapping = {
    time: null,
    video_time: null,
    stage: null,
    altitude: null,
    altitude_reference: null,
    speed: null,
    speed_reference: null,
    pressure: null,
    temperature: null,
    data_origin: null,
    source: null,
  };
  for (const role of document.querySelectorAll("#import-table [data-kind='role']")) {
    if (!role.value) continue;
    const unit = document.querySelector(`#import-table [data-kind='unit'][data-index='${role.dataset.index}']`);
    mapping[role.value] = { index: Number(role.dataset.index), unit: unit.value };
  }
  const reference = document.querySelector("input[name='altitude-reference']:checked");
    if (mapping.altitude) mapping.altitude.reference = reference ? reference.value : "";
    if (mapping.speed) {
      const frame = document.querySelector("input[name='speed-frame']:checked");
      mapping.speed.frame = frame ? frame.value : "";
    }
  return mapping;
}

function renderImportExtra() {
  const extra = document.getElementById("import-extra");
  const mapping = mappingFromDialog();
  const keepElevation = extra.querySelector("[name='import-site']");
  const keepPressure = extra.querySelector("[name='import-p0']");
  const siteValue = keepElevation ? keepElevation.value : "";
  const pressureValue = keepPressure ? keepPressure.value : "";
  const previousReference = document.querySelector("input[name='altitude-reference']:checked");
  let reference = previousReference ? previousReference.value : "";
  if (!reference && mapping.altitude) {
    const column = importState.preview.columns.find((item) => item.index === mapping.altitude.index);
    if (column && column.reference_confident) reference = column.reference || "";
  }
  extra.replaceChildren();
  if (mapping.altitude) {
    const box = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = "Altitude reference";
    box.appendChild(legend);
    for (const [value, label] of [["agl", "Above the launch site"], ["msl", "Above sea level"], ["unknown", "Unknown — do not assume"]]) {
      const choice = document.createElement("label");
      choice.className = "check";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "altitude-reference";
      input.value = value;
      input.checked = reference === value;
      input.addEventListener("change", () => {
        renderImportExtra();
        updateImportPlan();
      });
      choice.append(input, document.createTextNode(" " + label));
      box.appendChild(choice);
    }
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = "This is not guessed. Above sea level asks for the launch-site elevation and subtracts it.";
    box.appendChild(note);
    extra.appendChild(box);
  }
  if (mapping.speed && !mapping.speed_reference) {
    const box = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = "Speed frame";
    box.appendChild(legend);
    const previous = document.querySelector("input[name='speed-frame']:checked");
    for (const [value, label] of [["total", "Displayed total speed, not vertical"], ["vertical", "Vertical speed"], ["unknown", "Unknown — do not treat as vertical"]]) {
      const choice = document.createElement("label");
      choice.className = "check";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "speed-frame";
      input.value = value;
      input.checked = previous ? previous.value === value : false;
      input.addEventListener("change", updateImportPlan);
      choice.append(input, document.createTextNode(" " + label));
      box.appendChild(choice);
    }
    extra.appendChild(box);
  }
  const needsSite = reference === "msl" || (mapping.pressure && !mapping.altitude);
  const needsP0 = Boolean(mapping.pressure && !mapping.altitude);
  if (needsSite) {
    addImportNumber(extra, "import-site", "Launch site elevation", "m", siteValue, "Entered here. Not read from the file.");
  }
  if (needsP0) {
    addImportNumber(
      extra,
      "import-p0",
      "Reference pressure",
      "Pa",
      pressureValue,
      "ISA sea level is 101325 Pa. Used only to turn pressure into altitude. The formula stops at 11 km.",
    );
  }
}

function addImportNumber(parent, name, label, unit, value, hint) {
  const field = document.createElement("label");
  field.className = "field";
  field.innerHTML = `<span class="field-label">${label}</span>`;
  const control = document.createElement("span");
  control.className = "control";
  const input = document.createElement("input");
  input.name = name;
  input.inputMode = "decimal";
  input.value = value;
  input.addEventListener("input", updateImportPlan);
  const unitLabel = document.createElement("span");
  unitLabel.className = "unit";
  unitLabel.textContent = unit;
  control.append(input, unitLabel);
  field.appendChild(control);
  const note = document.createElement("span");
  note.className = "hint";
  note.textContent = hint;
  field.appendChild(note);
  parent.appendChild(field);
}

function updateImportPlan() {
  const mapping = mappingFromDialog();
  const parts = [];
  const zeroTime = document.getElementById("import-zero-time");
  if (mapping.time && mapping.time.unit) {
    const unit = mapping.time.unit === "ms" ? "milliseconds converted to seconds" : "seconds";
    parts.push(zeroTime && zeroTime.checked
      ? `Time will be ${unit}, then shifted so the first row is 0 s.`
      : `Mission time will stay ${unit} as written. The first row is not moved to 0.`);
  } else parts.push("Choose the mission-time column and whether it is seconds or milliseconds.");
  if (mapping.video_time) parts.push("Video time stays a separate column and is not the chart axis.");
  if (mapping.altitude && mapping.altitude.unit && (mapping.altitude.reference || mapping.altitude_reference)) {
    const unit = mapping.altitude.unit === "ft" ? "feet converted to meters" : mapping.altitude.unit === "km" ? "kilometers converted to meters" : "meters";
    if (!mapping.altitude.reference && mapping.altitude_reference) {
      parts.push(`Altitude will be ${unit}. The altitude_reference column is used as written, including unknown.`);
    } else {
      const reference = mapping.altitude.reference === "msl"
        ? "above sea level, minus the site elevation you enter"
        : mapping.altitude.reference === "unknown"
          ? "with reference left unknown"
          : "above the launch site";
      parts.push(`Altitude will be ${unit}, ${reference}.`);
    }
  } else if (mapping.pressure && mapping.pressure.unit && !mapping.altitude) {
    parts.push(`Pressure will be ${mapping.pressure.unit}, then converted to altitude with the ISA troposphere formula and the reference pressure and site elevation you enter.`);
  } else if (!mapping.altitude && !mapping.pressure) {
    parts.push("Choose altitude or pressure.");
  } else if (mapping.altitude) {
    parts.push("Choose the altitude unit and whether it is above the launch site or above sea level.");
  }
  if (mapping.temperature && mapping.temperature.unit) {
    parts.push(mapping.temperature.unit === "F" ? "Temperature will be converted from Fahrenheit to Celsius." : "Temperature will be read as Celsius.");
  }
  document.getElementById("import-plan").textContent = parts.join(" ");
  const speedOk = !mapping.speed || (mapping.speed.unit && (mapping.speed.frame || mapping.speed_reference));
  const referenceFromColumn = Boolean(mapping.altitude_reference);
  const altitudeReady = mapping.altitude && mapping.altitude.unit && (mapping.altitude.reference || referenceFromColumn);
  const pressureReady = mapping.pressure && mapping.pressure.unit && !mapping.altitude;
  const pressureOk = !mapping.pressure || mapping.pressure.unit;
  const temperatureOk = !mapping.temperature || mapping.temperature.unit;
  const ready = mapping.time && mapping.time.unit && (altitudeReady || pressureReady) && pressureOk && temperatureOk && speedOk;
  document.getElementById("import-apply").disabled = !ready;
}

function selectedDelimiter() {
  const picked = document.querySelector("#delimiter-choices input:checked");
  return picked ? picked.value : importState.preview.delimiter;
}

async function applyImport() {
  const mapping = mappingFromDialog();
  const site = document.querySelector("[name='import-site']");
  const pressure = document.querySelector("[name='import-p0']");
  const body = {
    ...readForm(),
    csv: importState.csv || "",
    xlsx_base64: importState.xlsx || "",
    sheet: importState.sheet || "",
    delimiter: selectedDelimiter(),
    header: document.getElementById("import-header").checked ? "present" : "absent",
    provenance: document.getElementById("import-measured").checked ? "measured" : "imported",
    time_basis: document.getElementById("import-zero-time").checked ? "start_at_zero" : "keep",
    confirm_attribution: document.getElementById("import-attribution").checked,
    profile: document.getElementById("import-attribution").checked ? "webcast_readout" : "",
    model_rocket_events: document.getElementById("import-model-events").checked,
    track_name: document.getElementById("import-track-name").value.trim(),
    time: mapping.time,
    video_time: mapping.video_time,
    stage: mapping.stage,
    altitude: mapping.altitude,
    altitude_reference: mapping.altitude_reference,
    speed: mapping.speed,
    speed_reference: mapping.speed_reference,
    pressure: mapping.pressure,
    temperature: mapping.temperature,
    data_origin: mapping.data_origin,
    source: mapping.source,
  };
  if (mapping.altitude && !mapping.altitude.reference && mapping.altitude_reference) mapping.altitude.reference = "unknown";
  if (mapping.speed && !mapping.speed.frame) mapping.speed.frame = "unknown";
  body.time = mapping.time;
  body.speed = mapping.speed;
  body.altitude = mapping.altitude;
  delete body.site_elevation_m;
  delete body.reference_pressure_pa;
  if (site) body.site_elevation_m = site.value.trim();
  if (pressure) body.reference_pressure_pa = pressure.value.trim();
  try {
    const payload = await requestJson("/api/import/apply", body);
    const tracks = payload.tracks || [payload];
    const appendBox = document.getElementById("import-append");
    const append = Boolean(appendBox && appendBox.checked && viewState.tracks.length);
    adoptTracks(tracks, append);
    const pendingEvents = importState.pendingEvents;
    importState.pendingEvents = "";
    closeImport();
    if (pendingEvents) {
      const events = await fetch(pendingEvents);
      if (!events.ok) throw new Error("The event list could not be loaded from this site.");
      await adoptEventCsv(await events.text());
    }
  } catch (error) {
    if (importDialog.hidden) showError(error.message);
    else showImportError(error.message);
  }
}

const trackColors = ["#0e4d6c", "#b4532a", "#1f7a3a", "#3d348b", "#9a3412", "#0f766e"];
let trackSerial = 0;

function showNativeFlight(payload) {
  clearOpenedFlight();
  showPayload(payload);
}

function clearOpenedFlight() {
  viewState.tracks = [];
  viewState.markers = [];
  viewState.overlay = null;
  viewState.userZoom = false;
  viewState.t0 = null;
  viewState.t1 = null;
  const section = document.getElementById("tracks");
  if (section) section.hidden = true;
  renderTrackBar();
}

function adoptTracks(tracks, append) {
  const section = document.getElementById("tracks");
  section.hidden = false;
  if (!append) clearOpenedFlight();
  section.hidden = false;
  viewState.userZoom = false;
  viewState.t0 = null;
  viewState.t1 = null;
  for (const track of tracks) {
    track.id = `track-${trackSerial += 1}`;
    track.color = trackColors[(trackSerial - 1) % trackColors.length];
    track.time_offset_s = Number(track.time_offset_s) || 0;
    viewState.tracks.push(track);
  }
  renderTrackBar();
  focusTracks("all");
}

function renderTrackBar() {
  const bar = document.getElementById("track-bar");
  const select = document.getElementById("marker-track");
  bar.replaceChildren();
  select.replaceChildren();
  const all = document.createElement("button");
  all.type = "button";
  all.textContent = "All tracks";
  all.addEventListener("click", () => focusTracks("all"));
  bar.appendChild(all);
  for (const track of viewState.tracks) {
    const button = document.createElement("button");
    button.type = "button";
    const swatch = document.createElement("i");
    swatch.className = "swatch-track";
    swatch.style.background = track.color;
    button.append(swatch, document.createTextNode(track.track_name || "Track"));
    button.style.borderColor = track.color;
    button.addEventListener("click", () => focusTracks(track.id));
    bar.appendChild(button);
    const option = document.createElement("option");
    option.value = track.id;
    option.textContent = track.track_name || "Track";
    select.appendChild(option);
    const offset = document.createElement("label");
    offset.className = "check";
    offset.append(document.createTextNode(`${track.track_name} offset s `));
    const input = document.createElement("input");
    input.value = String(track.time_offset_s || 0);
    input.inputMode = "decimal";
    input.addEventListener("change", () => {
      const number = Number(input.value);
      if (!Number.isFinite(number)) {
        input.value = String(track.time_offset_s || 0);
        return;
      }
      track.time_offset_s = number;
      focusTracks(viewState.focus || "all");
    });
    offset.appendChild(input);
    const offsets = document.getElementById("offset-fields");
    (offsets || bar).appendChild(offset);
  }
}

function focusTracks(id) {
  viewState.focus = id;
  const selected = id === "all" ? viewState.tracks : viewState.tracks.filter((track) => track.id === id);
  viewState.overlay = selected;
  if (!selected.length) return;
  revealLoaded();
  renderStrip(selected[0]);
  if (selected.length === 1) {
    viewState.overlay = null;
    showPayload(displayTrack(selected[0]));
    renderSourceMarkers();
    return;
  }
  viewState.payload = displayTrack(selected[0]);
  const altitudeCard = document.querySelector("#chart-altitude").closest(".chart-card");
  altitudeCard.querySelector(".unit-label").textContent = "m, reference stated on each track";
  showReadoutLegend(altitudeCard.querySelector(".legend"), selected);
  truthToggle.hidden = true;
  showTruth.checked = false;
  const speedCard = document.querySelector("#chart-pressure").closest(".chart-card");
  speedCard.querySelector("h2").textContent = "Speed";
  speedCard.querySelector(".unit-label").textContent = "km/h displayed";
  const stats = document.getElementById("track-stats");
  if (stats) {
    stats.hidden = false;
    stats.textContent = selected.map((track) => trackSummary(track)).join(" ");
  }
  notes.textContent = selected.map((track) => (track.import_summary || []).join(" ")).join(" ");
  if (selected[0].source_note) {
    notes.textContent += ` Source column, not checked here: ${selected[0].source_note}`;
  }
  const readNotes = document.getElementById("read-notes");
  if (readNotes) readNotes.hidden = !notes.textContent;
  renderEvents(selected[0]);
  writeOverlayCards();
  const sparse = sparseSpacingNote(selected);
  chartNote.hidden = false;
  chartNote.textContent = [
    "Rows with no speed or altitude stay on their own track. The line breaks at a missing readout. Those cells are not drawn as zero, and they were not copied onto another stage.",
    sparse,
  ].filter(Boolean).join(" ");
  renderSourceMarkers();
  draw();
}

function restoreEstimateLegend(legend) {
  if (!legend) return;
  legend.replaceChildren();
  const estimate = document.createElement("i");
  estimate.className = "swatch estimate";
  const truth = document.createElement("i");
  truth.className = "swatch truth";
  legend.append(estimate, document.createTextNode(" Estimate "), truth, document.createTextNode(" True path"));
}

function showReadoutLegend(legend, tracks) {
  if (!legend) return;
  legend.replaceChildren();
  for (const track of tracks) {
    const swatch = document.createElement("i");
    swatch.className = "swatch-track";
    swatch.style.background = track.color;
    legend.append(swatch, document.createTextNode(` ${track.track_name} `));
  }
}

function writeOverlayCards() {
  const copy = {
    liftoff: ["Liftoff", "Not in this record", "Not detected from these tracks."],
    apogee: ["Highest in this record", "Per track", "Each track's maximum is in the notes. It is not an orbital apogee."],
    landing: ["Landing", "Not in this record", "The last row is not a landing."],
  };
  for (const name of ["liftoff", "apogee", "landing"]) {
    const card = document.querySelector(`.event[data-event="${name}"]`);
    const [title, time, alt] = copy[name];
    card.querySelector("h2").textContent = title;
    card.querySelector(".event-time").textContent = time;
    card.querySelector(".event-alt").textContent = alt;
    card.querySelector(".event-delta").textContent = "";
  }
}

function displayTrack(track) {
  const offset = Number(track.time_offset_s) || 0;
  const copy = { ...track, time_s: track.time_s.map((value) => value + offset) };
  if (offset !== 0) {
    copy.import_summary = [
      ...(track.import_summary || []),
      `Chart time adds your offset of ${offset} s. The file's mission time was not rewritten.`,
    ];
  }
  return copy;
}

function trackSummary(track) {
  const end = track.extrema || {};
  const speed = end.speed_max_kmh == null ? "Speed unavailable." : `Max displayed speed ${formatNumber(end.speed_max_kmh, 1)} km/h at ${formatNumber(end.speed_max_t_s, 2)} s.`;
  return `${track.track_name}: mission time ${formatNumber(end.t_first_s, 2)}–${formatNumber(end.t_last_s, 2)} s. Highest altitude in this track ${formatNumber(end.altitude_max_m, 1)} m. ${speed}`;
}

const markerFilter = document.getElementById("marker-filter");
if (markerFilter) markerFilter.addEventListener("change", () => renderSourceMarkers());

document.getElementById("marker-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const trackId = document.getElementById("marker-track").value;
  const time = Number(document.getElementById("marker-time").value);
  const label = document.getElementById("marker-label").value.trim();
  if (!trackId || !Number.isFinite(time) || !label) return;
  viewState.markers.push({ trackId, mission_time_s: time, event: label, kind: "user_marker" });
  document.getElementById("marker-label").value = "";
  renderSourceMarkers();
  draw();
});

async function adoptEventCsv(text) {
  if (!viewState.tracks.length) {
    showError("Open a flight before loading event markers. The file was not applied.");
    return;
  }
  const result = await requestJson("/api/import/events", { csv: text });
  const unmatched = [];
  const next = viewState.markers.filter((marker) => marker.kind === "user_marker");
  for (const marker of result.markers) {
    const named = viewState.tracks.find((track) => track.track_name === marker.vehicle);
    const track = named || (!marker.vehicle && viewState.tracks.length === 1 ? viewState.tracks[0] : null);
    if (!track) {
      unmatched.push(marker.vehicle || "(no vehicle)");
      continue;
    }
    next.push({ ...marker, trackId: track.id });
  }
  const added = next.filter((marker) => marker.kind === "source_marker").length;
  if (!added) {
    showError(
      "No event row matched a track on screen (" + [...new Set(unmatched)].join(", ") + "). The markers already shown were left as they are.",
    );
    return;
  }
  const replaced = viewState.markers.some((marker) => marker.kind === "source_marker");
  viewState.markers = next;
  renderSourceMarkers();
  draw();
  if (unmatched.length) {
    readout.textContent = "Some event rows did not match an open track (" + [...new Set(unmatched)].join(", ") + "). Those rows were not added.";
  } else if (replaced) {
    readout.textContent = "Replaced the previous event list. Markers you added yourself are still here.";
  }
}

document.getElementById("events-file").addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  try {
    await adoptEventCsv(await file.text());
  } catch (error) {
    showError(error.message);
  }
});

for (const button of document.querySelectorAll("[data-demo]")) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await fetch(button.dataset.demo);
      if (!response.ok) throw new Error("The practice file could not be loaded from this site.");
      const name = button.dataset.demo.split("/").pop();
      importState.pendingEvents = button.dataset.events || "";
      if (name.toLowerCase().endsWith(".xlsx")) {
        const file = new File([await response.arrayBuffer()], name);
        await openFile(file);
      } else {
        await openCsv(await response.text(), name);
      }
    } catch (error) {
      importState.pendingEvents = "";
      showError(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

function closeImport() {
  importDialog.hidden = true;
  importState.pendingEvents = "";
  showImportError("");
}

function showImportError(message) {
  const slot = document.getElementById("import-error");
  slot.hidden = !message;
  slot.textContent = message || "";
}

async function requestJson(url, body) {
  const { ok, payload } = await callApi(url, body);
  if (!ok) throw new Error(payload.error || "The file could not be imported.");
  return payload;
}
