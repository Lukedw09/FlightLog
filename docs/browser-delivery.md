# Sharing Flight log without installing Python

This is a research note from 8 November 2026. Nothing in it was deployed, posted, purchased, or signed up for. The Origin repository stays private. `http://127.0.0.1:47231/` is only the program on the machine that is running it. It is not a public link.

Paid hosting is not a requirement for a static page. A free direct upload can publish a folder of files without connecting this repository and without a GitHub mirror. What that upload cannot do is keep the shipped page private: the HTML, JavaScript, and Python that the browser runs are downloaded by every visitor.

## Two different kinds of privacy

The Origin repository can stay private. A direct-upload host does not need access to it, and no mirror is required.

The site that host serves is a public copy of the analyzer. Anyone can save `app.js`, `pyodide-boot.js`, and the `flightlog` Python modules and read them. That includes the import rules, the detector, and the ISA sketch. It does not include the git history, tests, or files that were left out of the upload. Flight CSVs a visitor opens are not uploaded to the host; they stay in that browser tab. The host still sees requests for the page itself, and jsDelivr sees the request for Pyodide.

## What was actually run in the browser engine

The prototype is the local page `/browser`. It loads Pyodide 0.28.3 and NumPy from `https://cdn.jsdelivr.net/pyodide/v0.28.3/full/`, installs `openpyxl` from PyPI with micropip, then reads the Python package from the local server. Chrome drove that page. A warm cache, with those libraries already downloaded, reported ready in about 2.9 seconds. A first visit still has to download them. Measured sizes from that CDN: `pyodide.asm.wasm` 8.6 MB, `python_stdlib.zip` 2.4 MB, the NumPy wheel 3.1 MB. openpyxl is an extra download at startup, including for a visit that only opens a CSV.

After that load, the same page imported the three supplied webcast files and the Transporter-18 workbook. This is the analyzer, not only the simulated apogee.

| File | Result in the Pyodide page |
| --- | --- |
| Starlink 15-18 `telemetry.csv` | Three tracks. Full span −508.474 s to 557.524 s. Banner: webcast readout, not independently authenticated. Temperature chart hidden. Import about 0.3 s after the engine was ready. |
| 2026-10-27 `telemetry.csv` | Three tracks. Full span −5.472 s to 558.525 s. Same banner. Import about 0.2 s. |
| 2026-10-23 `telemetry.csv` | Three tracks. Full span −5.472 s to 558.525 s. Same banner. Import about 0.2 s. |
| Each `events.csv` | 18, 19, and 20 markers. Graphic filter kept 3. Audio rows stayed “audio, ASR-assisted/provisional”. The list did not say detected. Landing card stayed “Not in this record”. |
| Booster only | Stats started with that track: 15-18 at 153.52–510.54 s and 114,000.0 m in the record; 27 October at 153.52–510.51 s and 114,000.0 m; 23 October at 152.52–510.51 s and 114,000.0 m. |
| Drag zoom | On each file the held band showed a “Selecting …” readout and release showed “Zoomed to …” on that interval. One checked interval on 15-18 was 248.12–419.25 s. |
| Chart notes | Each file showed the missing-readout sentence and the sentence that several-second sample spacing is not bridged. |
| `large-rocket-flight-sample.xlsx` | One track, 30 s through 110 s, highest altitude 33,100.0 m, max displayed speed 3,799.0 km/h at 110.00 s. Banner: imported file, not marked simulated. Landing: not in this record. Temperature hidden. The button stayed disabled until Unknown was chosen for altitude reference and speed frame. That is the same confirmation the local page requires. |

An earlier check of the simulated sketch on this same engine showed apogee 20.84 s and 626.4 m, with the window ending at 114.376 s, matching the local Python page at the displayed precision. That sketch check does not cover the importer. The table above is the importer check.

The local Python suite was 53 tests at the last run. Those tests do not make this page production-ready or certified, and they do not exercise a public host.

## Exact gaps versus the local Python build

The browser engine and the local page share `flightlog.session` for simulate, CSV mapping, workbook import, and event lists. These are the differences that were confirmed or that follow from how the prototype is built:

- Matplotlib plots and `python -m flightlog plot` are not in the browser. The PNG path stays on the local install.
- The command-line tools are not in the browser.
- The prototype installs openpyxl from PyPI before any file is chosen. The local app uses the copy already installed in its environment and does not contact PyPI on each launch.
- Pyodide and NumPy come from jsDelivr on every cold visit. With an empty cache the page cannot draw a flight until those downloads finish. A warm load here was about 2.9 s; a cold load is the multi-megabyte download plus startup, and that cold timing was not measured separately.
- Opening the HTML from disk (`file://`) does not work. The engine needs HTTP.
- With no network and no cached Pyodide, the page does not start. The local launcher works offline after its one-time install.
- The Python modules are fetched as ordinary text files. On a public host they are public source. The Origin repository is not.
- The upload folder is `flightlog-pages.zip`. `index.html` is at its root. Python modules are `pkg/*.py`, loaded by relative URL, not by the Python web server. openpyxl is downloaded only when a workbook is opened. A failed CDN load shows a retry button. Those checks were run by serving that folder with a generic static file server.
- A hostile workbook can still use CPU inside the 20 MB cap. The cap is not a sandbox. That limit is the same idea as the local page.

CSV mapping, three-track split, event provenance, missing-readout notes, unbridged sparse spacing, drag zoom, and one workbook import did run in Pyodide and matched the expected spans and summaries above.

## Hosting without linking the repository

Official direct-upload options, read from vendor docs on 8 November 2026. None of these were used.

### Cloudflare Pages direct upload

Docs: [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/) and [Limits](https://developers.cloudflare.com/pages/platform/limits/).

- No Git repository. Drag a folder or zip in the dashboard, or run `npx wrangler pages deploy <folder>` after `wrangler login`.
- A Cloudflare account is required. The Free plan documents static asset requests as free and unlimited ([Functions pricing](https://developers.cloudflare.com/pages/functions/pricing/): a request that does not invoke Functions is static).
- This app does not need Pages Functions. Leaving them out keeps the site on that static allowance.
- Per file: 25 MiB. Drag-and-drop: 1,000 files. Wrangler: 20,000 files. The HTML, JavaScript, and Python sources fit. A vendored Pyodide tree might include a file over 25 MiB; the CDN approach does not upload those files.
- A direct-upload project cannot later be switched to Git integration. That is acceptable if the Origin repo must stay unconnected.
- The site name becomes `<project>.pages.dev` unless a custom domain is added. No domain is required.
- Account action: create a free Cloudflare account, create a Pages project by drag-and-drop or Wrangler, upload only the static folder, and set the project to public. Approval is the owner’s, because the upload publishes the client-side source.

### Vercel Drop

Docs: [Deploying with Vercel Drop](https://vercel.com/docs/drop).

- No Git and no CLI. Drag a folder or zip to `https://vercel.com/drop`.
- A static site can be deployed without an account. The URL is temporary and the success page shows a countdown. Keeping it requires claiming the project with a free Vercel account.
- This is not the Origin Git connection. That connection is a separate product, in beta, and Vercel says private Origin repositories cannot be deployed from a Hobby team. Direct upload does not use it, so the paid Origin integration is not required for this static page.
- Anonymous limits stated on that page: static sites, up to 100 MB per file and 1 GB for the drop.

### Netlify Drop

Docs: [Netlify Drop quickstart](https://docs.netlify.com/start/quickstarts/netlify-drop-quickstart/) and the Netlify CLI note on [anonymous deploy](https://www.netlify.com/knowledge-base/publish-and-update-sites-with-the-netlify-cli/).

- No Git. Drag a folder or zip to `https://app.netlify.com/drop`.
- Without signing in, Netlify says the URL is protected with a temporary password until the site is claimed. The CLI document says an unclaimed anonymous site is removed after one hour.
- After a claim, the site belongs to a Netlify account. Current Netlify accounts use credit-based plans; the free tier can pause a site when the included credits are used. That is a reason a busy X post could take the site offline even though the upload itself is free. Cloudflare’s documented static allowance does not meter those requests the same way.
- Dropping while logged out publishes the files as-is. Dropping a project that still needs a build only builds if you are logged in.

## What a later approval would actually be

1. Decide that the Python and JavaScript of the analyzer may be downloaded by the public. The Origin repo can remain private either way.
2. Pack a static folder: the page, its CSS and JavaScript, the boot script, and the `flightlog` modules it imports. Do not upload `.git`, the virtualenv, or secrets. The sample CSVs may be omitted; visitors open their own files.
3. Point the boot script at those static module URLs. Today it still calls `/pkg/` on the local Python server.
4. Create a free Cloudflare account and use Pages direct upload, or claim a Vercel Drop or Netlify Drop. No Git connection, no GitHub mirror, and no Origin app install.
5. Re-run the three webcast files, their event lists, one zoom, and the workbook on the resulting `pages.dev` (or equivalent) URL before anyone shares it. The checks in this note were against the local `/browser` prototype, not against a host.
6. Expect each cold visitor to download Pyodide and NumPy from jsDelivr, and openpyxl from PyPI, unless those files are later copied onto the same host. Copying them is optional and must stay under that host’s per-file size limit.

No account was created for this research. No project was uploaded.
