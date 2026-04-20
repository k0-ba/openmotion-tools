# Openwater **Open-Motion** — Setup & Data Visualization Research

> Research notes compiled from the OpenwaterHealth GitHub org, the Openwater wiki, and clinical publications. The goal is to give you (and your friend) an orientation that the official docs currently don't — and to set up a later Claude skill.

---

## 1. What the device actually is

Open-Motion 3.0 is a **wearable, non-invasive cerebral blood-flow monitor** built by [Openwater Health](https://www.openwater.health) (founded by Mary Lou Jepsen, ex-Oculus, ex-Google X). It uses **near-infrared laser speckle contrast imaging (LSCI)** to measure, through the skull:

- **Blood flow** (BFI — Blood Flow Index)
- **Blood volume** (BVI — Blood Volume Index)
- **Micro-motion** deep in tissue

Clinical headline use-case: rapid pre-hospital detection of **large vessel occlusion (LVO) stroke**, by comparing left-vs-right hemispheric blood flow. A 2025 study showed 79% sensitivity / 84% specificity, beating standard prehospital stroke scales.

Status: **research / investigational** device. Not FDA cleared. AGPL-3.0 licensed end-to-end — hardware designs, firmware, SDK.

### How the sensing works (one paragraph)

A short (100 µs), highly coherent infrared laser pulse (<60 MHz linewidth, up to 400 µJ) is injected into tissue through an optical fiber. Backscattered light interferes with itself to form a **speckle pattern** on a camera sensor. Moving scatterers (= red blood cells) blur the speckle; the **speckle contrast** `K = σ/μ` of the intensity distribution is the fundamental measurement. The firmware doesn't ship pixels — it ships a **1024-bin histogram of pixel intensities** per frame. Every downstream metric (BFI, BVI) is derived from the moments of that histogram.

---

## 2. Hardware architecture

One Open-Motion system has three USB devices plugged into your PC:

```
PC ──USB─► Console module       (USB Virtual COM Port — pyserial)
   ──USB─► Sensor module LEFT   (USB bulk transfer — libusb)
   ──USB─► Sensor module RIGHT  (USB bulk transfer — libusb)
```

- **Console** — STM32H7 MCU that drives the laser, TEC (thermoelectric cooler for laser), fans, PDU, generates the frame sync. Optional **safety FPGA** supervises. Talks 921 600 baud VCP.
- **Sensor modules** — up to two, labelled `left` / `right`. Each contains **8 × OmniVision OV2312 cameras** (1920×1280) arranged in a **4×2 grid**, driven by an iCE40 FPGA for histogramming, read out over USB bulk endpoints at 40 Hz.

### Camera grid layout (memorize this — every plot mirrors it)

```
┌───────────────────┐
│  Cam 1  │  Cam 8  │  ← top
│  Cam 2  │  Cam 7  │
│  Cam 3  │  Cam 6  │
│  Cam 4  │  Cam 5  │  ← bottom
└───────────────────┘
   left col   right col
```

Left/right assignment is determined by USB port topology: `port_numbers[-1] == 2` → left sensor, `== 3` → right sensor. If your left/right are swapped, it's a cabling issue.

Named groups used throughout the codebase:

| Group | 1-indexed cams | Purpose |
|---|---|---|
| Outer | 1, 4, 5, 8 | Four corners; higher analog gain (16×) |
| Inner | 2, 3, 6, 7 | Middle rows; unity-to-4× gain |

---

## 3. The relevant repos (this is the part the Wiki hides)

All under [github.com/OpenwaterHealth](https://github.com/OpenwaterHealth), all **AGPL-3.0**:

| Repo | What it is | Use it if… |
|---|---|---|
| **[openmotion-sdk](https://github.com/OpenwaterHealth/openmotion-sdk)** | Python SDK — primary entry point. Includes `omotion/` library, capture scripts, plotting scripts, drivers, tests. | Always. Start here. |
| [motion-sensor-fw](https://github.com/OpenwaterHealth/motion-sensor-fw) | Sensor module STM32H7 firmware (C). | Flashing / rebuilding sensor firmware. |
| [motion-console-fw](https://github.com/OpenwaterHealth/motion-console-fw) | Console STM32 firmware (C). | Console firmware work. |
| [openmotion-console-v2](https://github.com/OpenwaterHealth/openmotion-console-v2) | Newer console firmware variant. | Newer hardware revs. |
| [motion-safety-fpga](https://github.com/OpenwaterHealth/motion-safety-fpga) | Safety FPGA (Verilog). | FPGA work only. |
| [ow-bloodflow-app](https://github.com/OpenwaterHealth/ow-bloodflow-app) | PyQt / QML desktop app — the "official" operator UI. | End-user GUI. |
| [openwater-docs](https://github.com/OpenwaterHealth/openwater-docs) | Consolidated docs (still being populated, as of Jan 2026). | Future reference. |
| [opw_bloodflow_gen1_sw](https://github.com/OpenwaterHealth/opw_bloodflow_gen1_sw) | Gen-1 prototype software (legacy). | Historical context. |
| [opw_bloodflow_gen2_sw](https://github.com/OpenwaterHealth/opw_bloodflow_gen2_sw) | Gen-2 prototype software (legacy). | Historical context. |

**The `openmotion-sdk` `docs/` folder** is your actual manual — it has `Architecture.md`, `CameraArrangement.md`, `SciencePipeline.md`, `MOTION_Interface_API.md`, `MOTION_Console_API.md`, `MOTION_Sensor_API.md`, `ConsoleTelemetry.md`, `scan-sequencing.md`, `PipelineComparison.md`, `TestPlan.md`. This is the gold.

**Wiki:** [wiki.openwater.health](https://wiki.openwater.health) — older but has the hardware design articles.

**Community:** Discord (request invite at `community@openwater.health`).

---

## 4. Setup from zero — the steps that actually work

### 4.1 Prereqs

- Python 3.10+ (the SDK uses `numpy 2.2.5`, `matplotlib 3.10.1`, `pyserial`, `pyusb`, `libusb1`)
- On **Windows**: Visual C++ redistributables; a way to bind USB devices to `WinUSB` or `libusbK` (Zadig is the normal tool)
- On **Linux**: a udev rule granting your user access to the `0483:` VID devices, so you don't need `sudo`

### 4.2 Install the SDK

```bash
git clone https://github.com/OpenwaterHealth/openmotion-sdk.git
cd openmotion-sdk
pip install -r requirements.txt
# optional: build and install as a wheel so 'omotion' is importable anywhere
python -m pip install --upgrade build
python -m build
python -m pip install --force-reinstall dist/openmotion_sdk-*-py3-none-any.whl
```

### 4.3 Install libusb (the single biggest setup gotcha)

- **Windows:** download the matching `libusb-1.0.dll` from [libusb releases](https://github.com/libusb/libusb/releases) and drop it in `C:\Windows\System32`. Then in Zadig, re-bind each sensor module to **WinUSB** (or libusbK). The console stays as a COM port.
- **Linux:** `sudo apt install libusb-1.0-0` and a udev rule like

  ```
  SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", MODE="0666"
  ```

  into `/etc/udev/rules.d/99-openmotion.rules`, then `sudo udevadm control --reload-rules && sudo udevadm trigger`.

- **macOS:** `brew install libusb`. USB bulk is fine; VCP device appears under `/dev/tty.usbmodem*`.

Verify:

```bash
python -c "import usb, omotion.usb_backend as ub; print(ub.get_libusb1_backend())"
```

Should print a backend object, not raise.

### 4.4 First connection

1. Plug in console + both sensor modules.
2. **Wait ≥10 seconds** for the aggregators to fully boot before running anything. This is not negotiable — the SDK expects it.
3. Sanity check:
   ```bash
   python scripts/test_connection.py
   ```

### 4.5 Flash / configure the camera sensors (one-time per boot)

Each camera needs its iCE40 FPGA loaded with a bitstream and its OV2312 registers programmed. There's a script for that:

```bash
python scripts/multicam_setup.py             # flashes all 8 cameras
# or
python scripts/flash_camera.py 1             # just camera 1
```

Cameras are numbered 1–8, matching physical connectors J1–J8 on the aggregator board.

### 4.6 Capture a scan

The minimal, supported entry point is:

```bash
python scripts/capture_data.py --subject-id S001 --duration 60 --camera-mask 0xFF
# cameras are a bitmask, 0xFF = all 8
# max duration is 120s in the current script; patch MAX_DURATION if you need longer
```

This produces, in `scan_data/`:

- `scan_<subject>_<timestamp>_left_mask<hex>.csv` — raw histogram CSV, left
- `scan_<subject>_<timestamp>_right_mask<hex>.csv` — raw histogram CSV, right
- `scan_<subject>_<timestamp>_corrected.csv` — dark-frame-corrected BFI/BVI/etc
- `scan_<subject>_<timestamp>_telemetry.csv` — console health log

For single-camera debugging you want `scripts/monitor.py <cam>` which also exercises the camera config flow.

### 4.7 Common first-run failures

| Symptom | Fix |
|---|---|
| `libusb not found` | Copy `libusb-1.0.dll` to `System32` (Windows) or install the system package (Linux/Mac). |
| Device enumerates but I/O fails | On Windows, Zadig-bind the sensor modules to **WinUSB** or **libusbK**. The driver matters. |
| Left/right swapped | It's physical — swap the USB cables. `port_numbers[-1] == 2` is left. |
| Histogram rows are dropped with `WARNING` | Packet integrity check failed. Expected sum per frame = **2 457 606** (1920 × 1280 + 6 sentinel). A bad sum means USB corruption or firmware mismatch. |
| First frame rejected as "stale" | Unplug/replug the sensor. The SDK drops any frame whose raw `frame_id` isn't `1` on start. |
| `Scan empty` / corrected CSV empty | Scan ended before the second dark frame (default dark interval = 600 frames = 15 s). Run longer, or rely on the terminal-dark flush (it's implemented, but scans shorter than ~15 s won't have great data). |

---

## 5. The data you get out

### 5.1 Raw histogram CSV (per side)

Columns: `frame_id, cam_id, total, bin_0, bin_1, …, bin_1023` (+ optional `timestamp`, `temperature`).

- `frame_id` is the **raw 8-bit firmware counter** (0–255, rolls over). You must unwrap it before plotting time series.
- `cam_id` is 0–7 (channel), not 1–8 (camera number). `channel = cam - 1`.
- `total` should equal 2 457 606 for valid frames.
- **Bin 1023 is a sentinel** — zero it out before analysis/plotting or it will dominate.

### 5.2 Corrected CSV (both sides combined)

Columns (shortened):

```
frame_id, timestamp_s,
bfi_l1..bfi_l8, bfi_r1..bfi_r8,          # BFI per camera, 0–10 scale
bvi_l1..bvi_l8, bvi_r1..bvi_r8,          # BVI per camera, 0–10 scale
mean_l1..mean_r8,                        # μ₁ (intensity)
contrast_l1..contrast_r8,                # K
temp_l1..temp_r8                         # per-camera temperature
```

Naming: `l`/`r` is side, `1..8` is camera number (1-indexed). `timestamp_s` is normalized to zero at the first corrected frame.

### 5.3 Telemetry CSV

Console health: `timestamp, tcm, tcl, pdc, tec_*, pdu_raw_0..15, pdu_volt_0..15, tec_good, safety_se, safety_so, safety_ok, read_ok`. Useful for debugging laser/TEC/PDU issues.

---

## 6. The science pipeline in 90 seconds

This is the distilled `docs/SciencePipeline.md`. You want to know it before visualizing, because every plot is built on top of it.

1. **Discard the first 9 frames** (sensor warm-up). No data is produced.
2. **Dark-frame schedule**: every 600 frames (15 s at 40 Hz) the laser is cut for one frame — this is the ambient + dark-current baseline. The schedule is deterministic; the pipeline doesn't have to detect darks.
3. **Zero histogram bins below noise floor (10)** before computing moments.
4. Compute first/second moments: `μ₁ = Σ k·h_k / N`, `μ₂ = Σ k²·h_k / N`, variance `σ² = μ₂ − μ₁²`.
5. **Uncorrected stream** (real-time, every frame):
   - `mean = max(0, μ₁ − 64)` — subtract ADC pedestal
   - `K = σ / mean` — speckle contrast
   - BFI, BVI via per-camera calibration (see below)
   - On dark frames: re-emit the previous non-dark frame's values so the live plot doesn't flicker.
6. **Corrected batch** (emitted once per dark interval, used for publication):
   - Linear interpolation of the dark baseline across the interval
   - Subtract dark baseline from both μ₁ and σ²
   - **Shot-noise correction**: subtract `ADC_GAIN · g_cam · μ̃₁` from the variance (Poisson)
   - Per-camera analog gain: `[16, 4, 2, 1, 1, 2, 4, 16]` — outer cameras run hotter
   - Recompute contrast K̃ from corrected moments
   - The dark frame itself gets a corrected value from a **4-point quadratic stencil** across its neighbors.
7. **BFI/BVI calibration** is a linear mapping per (side, camera_position):
   ```
   BFI = (1 − (K − C_min)/(C_max − C_min)) × 10
   BVI = (1 − (μ₁ − I_min)/(I_max − I_min)) × 10
   ```
   Calibration arrays are stored as shape `(2, 8)` NumPy tables. You can extract them from the SDK config or, if absent, fall back to identity scaling (BFI = K×10, BVI = μ₁×10).

### Constants you'll type repeatedly

| Constant | Value | Meaning |
|---|---|---|
| `PEDESTAL_HEIGHT` | 64.0 | ADC zero-light bias |
| `EXPECTED_HISTOGRAM_SUM` | 2 457 606 | 1920×1280 + 6 sentinel; frames with any other sum are dropped |
| `discard_count` | 9 | Warmup frames |
| `dark_interval` | 600 | 15 s at 40 Hz |
| `noise_floor` | 10 | Bin-count threshold for noise decimation |
| `NUM_BINS` | 1024 | Histogram width |
| `FRAME_ID_MODULUS` | 256 | 8-bit counter |
| `CAMERA_GAIN_MAP` | `[16,4,2,1,1,2,4,16]` | Per-position analog gain |
| `ADC_GAIN` | `(1024−64)/11000 ≈ 0.0873` DN/e⁻ | Sensor ADC gain |

---

## 7. Visualization — what the SDK ships, and what's actually good

### 7.1 The six scripts that come in the box

All live under `scripts/` or `data-processing/` of `openmotion-sdk`:

| Script | Input | Output | When to use |
|---|---|---|---|
| `data-processing/plot_single_histogram.py` | raw histogram CSV, `--cam N --row R --style {line,bar,spectro}` | one 1024-bin plot | Inspect a single frame |
| `data-processing/plot_single_spectrogram.py` | raw CSV (hardcoded file / cam) | frames × bins heatmap (imshow, viridis) | See how one camera's histogram evolves over a scan |
| `data-processing/plot_all_histo_average.py` | raw CSV | 4×2 grid of μ & σ time series per camera, with temperature on twin axis | Quick quality check across all 8 cameras |
| `data-processing/plot_all_spectrogram.py` | raw CSV | 4×2 grid of spectrograms | Spatial + temporal overview |
| `data-processing/plot_corrected_scan.py` | corrected CSV | 4×4 grid (both sides) of BFI (black, left axis) + BVI (red, right axis) | **The main scientific plot.** |
| `scripts/plot_telemetry.py` | telemetry CSV | Multi-panel: temps, TEC, PDU, flags | Debugging hardware issues |

### 7.2 The conventions they all follow (adopt these!)

1. **Subplot grid mirrors physical layout.** Row 0 is the top of the sensor array; column ordering follows the physical 4×2 grid. Both sides side-by-side for a 4×4 master layout:

   ```
   L:C1  L:C8 | R:C1  R:C8     row 0
   L:C2  L:C7 | R:C2  R:C7
   L:C3  L:C6 | R:C3  R:C6
   L:C4  L:C5 | R:C4  R:C5     row 3
   ```

2. **Collapse empty rows/columns.** If only outer cameras (1, 4, 5, 8) are active, the grid collapses to 2×4. Don't waste whitespace — it makes sparse-camera scans unreadable.

3. **BFI / BVI dual y-axis**, always in the same colors:
   - BFI: solid black, linewidth 2, left axis
   - BVI: solid red, linewidth 1, right axis

4. **Spectrograms** use `imshow` with `cmap="viridis"`, `aspect="auto"`, `origin="lower"`, and always zero bin 1023.

5. **Frame-ID unwrapping** before any time-series plot:
   ```python
   def logical_frame_index(series):
       rollovers = (series.diff() < 0).cumsum()
       return rollovers * 256 + series
   ```
   `pd.diff() < 0` detects the 255→0 wrap. Apply per `cam_id`.

6. **Temperature overlay** on per-camera μ/σ plots uses a third color (`tab:red`, dashed, marker `d`) on a twin y-axis.

### 7.3 What's missing / what I'd add (good skill targets)

The shipped scripts stop at *multi-line time-series plots*. These are good for QC but not great for interpretation. Higher-value views:

1. **Spatial heatmap at a given timepoint** — 4×2 (or 4×4 both sides) grid of colored cells showing BFI value, animated over time. Much easier to see left/right asymmetry — the actual clinical signal.
2. **Left/right asymmetry index** — per camera row, plot `(BFI_left − BFI_right) / (BFI_left + BFI_right)` vs time. One number per pair, immediately flags LVO-side.
3. **Cardiac pulse extraction** — BFI at 40 Hz contains a clear ~1 Hz oscillation from the cardiac cycle. A bandpass (0.5–3 Hz) + peak-pick gives a heart-rate trace. PSD (power spectral density) of BFI in the 0–5 Hz band is a publication-ready view.
4. **Respiratory band (~0.2 Hz)** — same approach on the 0.1–0.5 Hz band.
5. **Cross-camera coherence** — correlate each pair of cameras' BFI series. Shows whether all 8 channels are seeing the same pulsatility (they should).
6. **Raw vs corrected overlay** — plot the uncorrected BFI in light gray behind the corrected BFI in black, with dark-frame positions marked. Immediately shows whether dark correction is doing anything useful.
7. **Summary "scan card"** — one PNG with: patient ID, timestamp, scan length, per-camera mean BFI ± std, asymmetry index, cardiac rate estimate, data-quality flags (fraction of frames dropped, frames failing sum check). This is the thing to generate automatically at the end of every scan.
8. **Interactive plot** via Plotly or Bokeh — the matplotlib plots are static PNGs, which is fine for archival but terrible for exploration. A single-file HTML with zoom + camera-toggle is 80% of the clinical value.

### 7.4 Plotting dependencies — what's already in the stack

The SDK already installs `matplotlib 3.10`, `numpy 2.2`, `pandas` (implicit), `pyserial`, `pyusb`, `libusb1`, `crcmod`, `requests`, `keyboard`. You have everything you need for `matplotlib` plots out of the box. For the extensions above you'd add:

- `scipy` — for `signal.welch`, `signal.butter`, peak-finding
- `plotly` or `bokeh` — for interactive HTML
- `mne` (optional) — if you want to treat BFI as quasi-EEG for spectral analysis

---

## 8. Related / background projects

Not Open-Motion itself, but useful for context or code-lifting:

| Project | Relevance |
|---|---|
| [PyLSCI](https://pypi.org/project/pylsci/) | Generic Python LSCI package (`pip install pylsci`). Works on 2D/3D speckle image arrays, not histograms — different data model, but the math is the same. |
| Dunn et al., *"Laser Speckle Contrast Imaging in Biomedical Optics"* | The canonical LSCI review paper. |
| Senarathna, Rege, Li, Thakor 2013 — *IEEE Reviews in Biomedical Engineering* | LSCI theory / instrumentation reference. |
| Vaz, Humeau-Heurtier et al. 2016 — *IEEE Reviews in Biomedical Engineering* | LSCI for microvascular blood flow, review. |
| Openwater Healio Q&A (May 2025) | Clinical framing of the LVO stroke study. |

---

## 9. Notes for the Claude skill we're about to build

**Target use-cases for the skill:**

1. **Onboarding helper** — walk a new user through the steps in §4, troubleshoot at each step. The skill should know which error message means which fix (see table §4.7).
2. **Analysis runner** — given a corrected CSV (or a raw histogram CSV), produce the standard 6 plots plus the extensions in §7.3 as a set of PNGs + an HTML summary card.
3. **Canonical constants** — bake in `EXPECTED_HISTOGRAM_SUM = 2_457_606`, `PEDESTAL_HEIGHT = 64`, the camera grid map, the physical-layout column offsets. These shouldn't be re-derived per conversation.
4. **Reference implementation** — a ready-to-drop `science_pipeline.py` that does dark-frame correction offline, for users who only have raw histograms.
5. **Data-quality report** — parse a scan directory, check frame-sum integrity, warmup discards, dark-frame positions, and output a one-page diagnostic.

**Suggested skill file layout:**

```
openmotion/
├── SKILL.md                         # when to trigger, what it does
├── constants.py                     # EXPECTED_HISTOGRAM_SUM, layout maps, etc.
├── io.py                            # read raw-histogram CSV, read corrected CSV
├── pipeline.py                      # offline dark-frame correction reference
├── plots/
│   ├── histogram_single.py
│   ├── spectrogram_single.py
│   ├── grid_moments.py              # plot_all_histo_average.py rewrite
│   ├── grid_spectrograms.py
│   ├── grid_bfi_bvi.py              # plot_corrected_scan.py rewrite
│   └── telemetry.py
├── analysis/
│   ├── asymmetry.py                 # left/right asymmetry index
│   ├── cardiac.py                   # 0.5–3 Hz bandpass + peak pick
│   ├── coherence.py                 # pairwise cross-camera
│   └── summary_card.py              # one-PNG scan summary
└── setup/
    ├── troubleshoot.md              # decision tree from §4.7
    └── install_*.md                 # per-OS install notes
```

The `SKILL.md` should trigger on mentions of: *openmotion*, *open-motion*, *openwater*, *BFI*, *BVI*, *speckle contrast*, *blood flow monitor*, *cerebral blood flow*, *histogram CSV* + terms like *openwater*, or when the user uploads a file matching `*_corrected.csv` or `histogram*.csv` with 1024 bin columns.

---

## 10. TL;DR

- **What** — Open-Motion 3.0, open-source wearable cerebral blood-flow monitor (laser speckle contrast, NIR).
- **Repos** — start with `openmotion-sdk`; its `docs/` folder is the real manual.
- **Setup** — Python 3.10+, `pip install -r requirements.txt`, drop `libusb-1.0.dll` in `System32` (Win), Zadig-bind sensors to WinUSB, wait 10 s after plug-in, run `multicam_setup.py`, then `capture_data.py`.
- **Data** — raw histogram CSVs (1024 bins × frames × cameras) + a corrected BFI/BVI CSV.
- **Viz** — six stock matplotlib scripts; all mirror the 4×2 physical camera layout. The really useful additions are spatial heatmaps, left/right asymmetry, and cardiac-band PSD.
- **Gotchas** — zero bin 1023; unwrap the 8-bit frame counter; subtract pedestal 64; expect histogram sum = 2 457 606; wait 10 s after USB plug-in.