/* Loads the same flightlog package in Pyodide from static files next to this page.
   The runtime comes from the jsDelivr CDN. This file does not deploy anything. */

const PYODIDE_INDEX = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";

window.flightlogEngine = {
  ready: null,
  async request(url, body) {
    const pyodide = await this.ready;
    if (body && body.xlsx_base64) await ensureOpenpyxl(pyodide);
    const raw = JSON.stringify(body || {});
    const result = pyodide.runPython(
      `dispatch(${JSON.stringify(url)}, ${JSON.stringify(raw)})`
    );
    return JSON.parse(result);
  },
};

let openpyxlReady = null;

function ensurePyodideScript() {
  if (typeof loadPyodide === "function") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PYODIDE_INDEX + "pyodide.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("The runtime script did not load from the CDN."));
    document.head.appendChild(script);
  });
}

async function ensureOpenpyxl(pyodide) {
  if (!openpyxlReady) {
    openpyxlReady = (async () => {
      await pyodide.loadPackage("micropip");
      const micropip = pyodide.pyimport("micropip");
      await micropip.install("openpyxl");
    })();
  }
  try {
    await openpyxlReady;
  } catch (error) {
    openpyxlReady = null;
    throw new Error("The workbook library did not load. Check the network, then try the workbook again. " + error.message);
  }
}

window.flightlogEngine.ready = bootPyodide();

async function bootPyodide() {
  const strip = document.getElementById("origin-strip");
  const retry = document.getElementById("runtime-retry");
  document.body.dataset.runtime = "loading";
  if (retry) retry.hidden = true;
  if (strip) {
    strip.classList.add("idle");
    strip.textContent = "Loading the flight log runtime. The first visit downloads it. This tab does not upload your files.";
  }
  try {
    await ensurePyodideScript();
    const pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX });
    await pyodide.loadPackage("numpy");
    const manifestUrl = new URL("pkg/manifest.json", document.baseURI);
    const manifest = await fetch(manifestUrl).then((response) => {
      if (!response.ok) throw new Error("The flight log modules were not found next to this page.");
      return response.json();
    });
    pyodide.FS.mkdirTree("/flightlog");
    for (const name of manifest.files) {
      const fileUrl = new URL("pkg/" + name, document.baseURI);
      const text = await fetch(fileUrl).then((response) => {
        if (!response.ok) throw new Error("Missing module " + name);
        return response.text();
      });
      pyodide.FS.writeFile("/flightlog/" + name, text);
    }
    pyodide.runPython(DISPATCH);
    document.body.dataset.runtime = "ready";
    if (strip && !strip.textContent.startsWith("SIMULATED") && !strip.textContent.startsWith("WEBCAST") && !strip.textContent.startsWith("IMPORTED")) {
      strip.textContent = "Runtime ready. Files you open stay in this tab.";
    }
    return pyodide;
  } catch (error) {
    document.body.dataset.runtime = "error";
    if (strip) {
      strip.classList.add("idle");
      strip.textContent = "The runtime did not load. " + (error && error.message ? error.message : "The network request failed.");
    }
    if (retry) retry.hidden = false;
    throw error;
  }
}

const DISPATCH = `
import json, sys
sys.path.insert(0, "/")
from flightlog.session import (
    FormError,
    import_event_file,
    import_mapped_csv,
    preview_import,
    replay_csv,
    simulate_form,
)

def dispatch(path, raw_text):
    raw = json.loads(raw_text)
    try:
        if path == "/api/simulate":
            payload = simulate_form(raw)
        elif path == "/api/replay":
            payload = replay_csv(raw.get("csv") or "", raw)
        elif path == "/api/import/preview":
            payload = preview_import(raw.get("csv") or "", raw)
        elif path == "/api/import/apply":
            payload = import_mapped_csv(raw.get("csv") or "", raw)
        elif path == "/api/import/events":
            payload = import_event_file(raw.get("csv") or "")
        else:
            payload = {"ok": False, "error": "That request is not available in the browser page."}
    except FormError as exc:
        payload = {"ok": False, "error": str(exc), "field": exc.field}
    return json.dumps(payload)
`;

document.addEventListener("DOMContentLoaded", () => {
  const retry = document.getElementById("runtime-retry");
  if (!retry) return;
  retry.addEventListener("click", () => {
    retry.disabled = true;
    window.flightlogEngine.ready = bootPyodide().finally(() => {
      retry.disabled = false;
    });
  });
});
