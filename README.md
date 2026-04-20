# openmotion-tools

> ## ⚠️ NOTICE OF EXPERIMENTAL STATUS — PLEASE READ ⚠️
>
> **Classification:** `ZERO-SHOT · UNTESTED · VIBES-ONLY`
> **Provenance:** emitted by a language model in one (1) pass, on a machine with no Open-Motion device attached, no scan CSVs on hand, and no humans in the loop to object.
> **Validation status:** none. Not a single line has been executed against real hardware or real data. The constants *should* be right; the code *should* import; the plots *should* render. These are aspirations, not guarantees.
>
> **Mandatory acceptance criteria:** this release is pending field validation by **Viktor**, who is hereby designated the sole qualified tester. Viktor, if you are reading this: please run it, break it, and file issues.
>
> **Tooling requirement:** Viktor MUST conduct testing using **[Claude Code](https://claude.com/claude-code)**. Use of Windsurf, Cursor-with-a-different-model, or any other surrogate harness will void the informal warranty and hurt the author's feelings. This is a load-bearing requirement. Do not negotiate with Windsurf.
>
> Everyone else: wait for the first green checkmark from Viktor before trusting any number this code produces.

### Can this repo crash the device?

**No.** This package is strictly offline post-processing:

- **Inputs:** CSV files that the SDK already wrote to disk (`scan_*_histogram.csv`, `*_corrected.csv`).
- **Outputs:** PNG plots, an HTML dashboard, a summary card.
- **Device I/O:** zero. No USB, no serial, no firmware calls. `openmotion/` does not import `pyusb`, `pyserial`, or the SDK. You can grep for it: `grep -r "usb\|serial\|openmotion_sdk" openmotion/` returns nothing.

The one thing that touches the OS is `linux/install.sh`, which (a) `apt`/`dnf`/`pacman`-installs `libusb-1.0` and (b) drops a udev rule that grants your user read/write on USB devices with vendor ID `0483`. That's a permissions change on `/dev/bus/usb/*`, not a firmware operation — the worst it can do is fail to grant permission, in which case you fall back to `sudo`. It cannot brick, flash, or reconfigure the console. If you're still nervous, skip the installer and just `pip install -e .`; you'll only lose the convenience of running capture scripts without `sudo`.

So: worst realistic failure mode of this repo is **producing a wrong-looking plot from a right-looking scan.** Which is exactly why Viktor needs to eyeball the first run.

---


Analysis + visualization helpers for the **[Openwater Open-Motion](https://github.com/OpenwaterHealth/openmotion-sdk)** cerebral blood-flow monitor — a wearable, open-source, near-infrared laser speckle contrast imager.

This repo is a companion to the upstream [`openmotion-sdk`](https://github.com/OpenwaterHealth/openmotion-sdk). The SDK handles device bring-up and scan capture; this repo handles everything after the CSVs hit disk:

- offline **dark-frame correction** for raw histograms (reference implementation of the SDK's science pipeline)
- the six stock matplotlib plots, plus an interactive Plotly dashboard
- a one-page **scan quality / summary card** for handing to a clinician
- canonical constants (`EXPECTED_HISTOGRAM_SUM`, pedestal, camera gain map, USB topology → left/right) baked in once, correctly

Tested on Linux (Ubuntu 22.04 / 24.04, Fedora 40, Arch). macOS should also work for the analysis code; device capture on macOS is not supported by the SDK.

---

## Quick start (Linux)

```bash
git clone https://github.com/k0ba/openmotion-tools.git
cd openmotion-tools
./linux/install.sh
```

The installer:
1. Installs `libusb-1.0` via your distro package manager.
2. Drops `linux/99-openmotion.rules` into `/etc/udev/rules.d/` so you can talk to the device without `sudo` (grants user access to USB VID `0483`).
3. Creates `.venv/` and installs this package editable (`pip install -e .`).

Unplug/replug the console and **wait ~10 seconds** for enumeration. Verify:

```bash
lsusb | grep 0483    # should show the sensor modules
```

Then clone and follow the [SDK](https://github.com/OpenwaterHealth/openmotion-sdk) to run `multicam_setup.py` and `capture_data.py`. You'll end up with a scan directory containing raw-histogram CSVs and/or a `*_corrected.csv`.

---

## Analyzing a scan

```python
from pathlib import Path
from openmotion import io, plot_static, summary

scan = Path("~/scans/2026-04-20_demo").expanduser()

# Load a corrected CSV (already dark-frame corrected by the SDK)
df = io.load_corrected(scan / "scan_corrected.csv")

# Six-panel grid of BFI (black, lw=2) + BVI (red, lw=1), mirrored to physical 4×2 layout
plot_static.grid_bfi_bvi(df, out=scan / "grid_bfi_bvi.png")

# One-page PNG + HTML summary card (per-camera mean BFI, cardiac-band PSD, L/R asymmetry)
summary.scan_card(df, out_png=scan / "summary.png", out_html=scan / "summary.html")
```

Working from raw histograms instead? `openmotion.pipeline.dark_correct(raw_df)` replicates the SDK's online pipeline offline, so you can re-process a scan with different constants.

See [`docs/`](docs/) for the full reference:
- [`data-formats.md`](docs/data-formats.md) — CSV column shapes
- [`science-pipeline.md`](docs/science-pipeline.md) — why each correction step exists
- [`visualization-patterns.md`](docs/visualization-patterns.md) — plot conventions (camera grid, colors, axes)
- [`setup-and-troubleshooting.md`](docs/setup-and-troubleshooting.md) — install / driver / enumeration issues

---

## Canonical constants

Do not re-derive these — getting one wrong silently produces plausible-but-wrong metrics.

| Constant | Value | Meaning |
|---|---|---|
| `EXPECTED_HISTOGRAM_SUM` | `2_457_606` | 1920 × 1280 sensor pixels + 6 firmware sentinel counts. Frames with any other sum are **dropped**. |
| `PEDESTAL_HEIGHT` | `64.0` | Subtracted from μ₁ before contrast. |
| `NUM_BINS` | `1024` | Bin 1023 is a sentinel — **zero it before analysis**. |
| `noise_floor` | `10` | Zero bins below this before computing moments. |
| `discard_count` | `9` | Warmup frames to drop. |
| `dark_interval` | `600` | Dark frame every 15 s at 40 Hz. |
| `FRAME_ID_MODULUS` | `256` | 8-bit firmware frame_id — **unwrap per `cam_id`** before time series. |
| `CAMERA_GAIN_MAP` | `[16, 4, 2, 1, 1, 2, 4, 16]` | Outer cams hotter. |
| `ADC_GAIN` | `≈ 0.0873` DN/e⁻ | Shot-noise correction of variance. |
| Left/right | USB `port_numbers[-1] == 2` → left, `== 3` → right | Physical side from USB topology. |

Camera indexing: `cam_id` in CSVs is **0–7**; camera numbers in docs/plots are **1–8** (`channel = cam − 1`).

All of the above live in [`openmotion/constants.py`](openmotion/constants.py).

---
## What's in the `openmotion` skill?

**SKILL.md** — aggressive triggers (any mention of openmotion / openwater / BFI / BVI / speckle contrast / LVO, plus filename and column-pattern triggers), routing logic, plotly-vs-static decision rules, canonical constants checklist.

### `references/` — 4 docs, ~1100 lines total

- **`setup-and-troubleshooting.md`** — full setup per OS, error decision tree, data-quality symptom table
- **`data-formats.md`** — CSV schemas for raw / corrected / telemetry with frame-ID unwrap
- **`science-pipeline.md`** — BFI/BVI derivation, dark-frame interpolation, shot-noise correction, edge cases
- **`visualization-patterns.md`** — physical layout rules, color conventions, 6 extension plots

### `scripts/` — 6 Python modules, ~1400 lines total

- **`constants.py`** — all canonical values (`NUM_BINS`, `PEDESTAL_HEIGHT`, `CAMERA_GAIN_MAP`, grid maps, style dict)
- **`io.py`** — CSV loaders with frame-ID unwrap, sentinel zeroing, warmup discard built in
- **`pipeline.py`** — offline reference implementation of the SDK's `SciencePipeline`
- **`plot_static.py`** — 8 matplotlib plot functions (histograms, moments grid, BFI/BVI grid, asymmetry, cardiac PSD, telemetry)
- **`plot_interactive.py`** — single-file Plotly dashboard builder with 4 tabs (Overview, Asymmetry, Spectral, Spatial heatmap)
- **`summary.py`** — one-PNG scan QC report with 6 panels

Plus **`_smoke_test.py`** — generates synthetic data and exercises every function. Useful if you ever modify the skill and want to verify it still works (`python _smoke_test.py` from the skill root).

### To install

Drop `openmotion.skill` into your Claude skills directory (or upload via the skills UI at claude.ai/settings/capabilities). It'll trigger automatically next time you or your friend mention Open-Motion, upload a scan CSV, or ask about BFI/BVI.
Quick qualitative test

### Realistic prompts examples:

1. _"I just plugged in my Open-Motion and I'm getting NoBackendError when I run test_connection.py — help"_
2. _"here's my scan_S001_20251217_corrected.csv — give me a plot"_ (with one of the sample CSVs)
3. _"what does contrast_l3 mean in my corrected output?"_

Alternatively, ship it and iterate when your friend actually uses it in the wild.
---

## Repo layout

```
openmotion/          # Python package — import openmotion
  constants.py       # canonical constants (above)
  io.py              # load raw-histogram and corrected CSVs
  pipeline.py        # offline dark-frame correction (reference impl)
  plot_static.py     # matplotlib plots (6 stock + extensions)
  plot_interactive.py# Plotly dashboard
  summary.py         # one-page QC / summary card
docs/                # reference docs (science, formats, viz, setup)
linux/               # install.sh + 99-openmotion.rules (udev)
examples/            # smoke_test.py — run after install to sanity-check
openwater-research.md# compiled research notes (scaffolding for this repo)
```

---

## Status

Alpha. The code is a port of the reference pipeline from the research notes — it matches the SDK's online numbers on the sample scans but has not been validated against a large corpus. File issues with a scan CSV attached if you see a discrepancy.

## License

MIT — see [`LICENSE`](LICENSE). The upstream SDK has its own license; check there before redistributing anything that includes SDK code.

## See also

- [OpenwaterHealth/openmotion-sdk](https://github.com/OpenwaterHealth/openmotion-sdk) — firmware, capture scripts, and the authoritative `docs/` folder (`SciencePipeline.md`, `Architecture.md`, `CameraArrangement.md`)
- [Openwater Health](https://www.openwater.health/) — the organization behind the device
