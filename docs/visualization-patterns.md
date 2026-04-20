# Visualization Patterns

How to turn Open-Motion data into useful plots. The rules in this file override generic plotting instincts — they exist because the data has specific structure (16 cameras in 2 physical grids, 40 Hz sampling, cardiac-band oscillations) that only reads well when you respect it.

---

## The physical layout (memorize this)

Every multi-panel plot must mirror the physical camera arrangement. Each sensor module has 8 cameras in a 4×2 grid:

```
┌───────────┐
│ Cam1  Cam8│  row 0 (top)
│ Cam2  Cam7│  row 1
│ Cam3  Cam6│  row 2
│ Cam4  Cam5│  row 3 (bottom)
└───────────┘
```

For a full two-sensor plot, use a 4×4 layout (left sensor in columns 0–1, right sensor in columns 2–3):

```
┌─────────────────────────────┐
│ L:1  L:8 │ R:1  R:8          │  row 0
│ L:2  L:7 │ R:2  R:7          │
│ L:3  L:6 │ R:3  R:6          │
│ L:4  L:5 │ R:4  R:5          │  row 3
└─────────────────────────────┘
```

`scripts/constants.py` has `CAMERA_GRID_POS` and helpers that do this automatically. Don't hand-roll subplot positions.

### Collapsing sparse layouts

If the user captured only 4 cameras (`--camera-mask 0x99`), don't draw an 8×2 grid full of blanks. Collapse to 2×2 while preserving the spatial ordering. `scripts/plot_static.py:_build_grid` handles this.

---

## Standard plot types

Six visualizations cover 95% of what users want. All six exist in the official SDK; `scripts/plot_static.py` re-implements them with consistent styling.

| Plot | Input | Use it for |
|---|---|---|
| Single histogram | raw CSV, one (cam, frame) | Debugging a single frame — is the distribution bimodal? Is bin 1023 blown up? |
| Histogram spectrogram | raw CSV, one cam, all frames | Watch one camera's histogram evolve over time. Dark frames appear as vertical stripes. |
| Moments grid (μ, σ, temp) | raw CSV, all cams | QC across all 8 cameras. First thing to look at for a new scan. |
| Spectrogram grid | raw CSV, all cams | Spatial × temporal view. Catches cameras where only one is misbehaving. |
| BFI/BVI grid | corrected CSV | **The main scientific plot.** Always render this if the user just asks for "plots". |
| Telemetry panels | telemetry CSV | Hardware health. Mostly useful during scan debugging. |

---

## Color conventions (non-negotiable)

Scientists looking at Open-Motion plots expect these. Breaking them forces them to re-read the legend every panel:

| Channel | Color | Line style | Axis |
|---|---|---|---|
| BFI | `black` | solid, linewidth 2 | left |
| BVI | `red` / `#c91f37` | solid, linewidth 1 | right (twin) |
| Temperature | `tab:red` | dashed, marker `d` | right twin |
| μ (mean intensity) | `tab:blue` | solid with circle markers | primary |
| σ (std dev) | `tab:orange` | dashed with square markers | primary |
| Contrast K | `tab:green` | solid | primary |
| Spectrograms | `viridis` colormap | — | — |
| Heatmaps of BFI across cameras | `RdBu_r` centered at midpoint | — | — |

---

## Preprocessing you must always do

1. **Unwrap the 8-bit frame counter** per `cam_id` before any time-series plot. Without this, your x-axis is a sawtooth.
2. **Zero bin 1023** before showing any raw histogram. It's a firmware sentinel and will dwarf every other bin.
3. **Drop invalid frames** (total ≠ 2 457 606) before plotting.
4. **Drop warmup frames** (logical_frame_id ≤ 9).
5. **Skip NaN rows** in corrected CSVs (pre-first-dark rows).

All of this is done for you by `scripts/io.py:load_raw` / `load_corrected`. Use the loaders.

---

## Extensions worth building (the SDK doesn't ship these)

These add real analytical value. They're implemented in `scripts/plot_static.py` and `scripts/plot_interactive.py`:

### 1. Spatial heatmap over time

A 4×4 grid of colored cells where the color is BFI value, animated across time. Lets the viewer see left/right asymmetry develop in real time. This is the most important extension for stroke-detection use.

### 2. Left/right asymmetry index

Per camera-row pair, plot:

```
AI(t) = (BFI_left(t) − BFI_right(t)) / (BFI_left(t) + BFI_right(t))
```

A sustained, non-zero AI(t) is the stroke signal. Plot all 4 row pairs on one axis.

### 3. Cardiac-band PSD

BFI at 40 Hz contains a clear ~1 Hz component from the cardiac cycle. Compute the power spectral density in 0–5 Hz and look for a peak. Heart-rate estimate:

```python
from scipy.signal import welch
f, P = welch(bfi, fs=40, nperseg=256)
hr_band = (f > 0.5) & (f < 3.0)   # 30-180 bpm
peak_freq_hz = f[hr_band][P[hr_band].argmax()]
heart_rate_bpm = peak_freq_hz * 60
```

### 4. Cross-camera coherence

All 8 cameras on the same sensor should see the same cardiac pulsation. Compute pairwise correlation of bandpass-filtered BFI. A camera whose correlation drops out is likely not in contact with skin.

### 5. Raw vs corrected overlay

Plot uncorrected BFI in light gray behind corrected BFI in black, with dark-frame positions marked as vertical dashes. Immediately shows whether dark correction did anything meaningful.

### 6. Scan summary card

One PNG with: subject ID, timestamp, scan duration, per-camera mean BFI ± std, asymmetry index, estimated heart rate, data-quality flags (dropped frame %). Generated by `scripts/summary.py`. This is the thing to produce automatically at the end of every scan.

---

## Interactive vs static — decision logic

The user asked for Plotly when appropriate, static when simpler. Rules:

| Situation | Pick |
|---|---|
| "Show me a plot" / "I want to see the data" / exploration | **Plotly** — `plot_interactive.build_dashboard()` |
| "Quick look" / "just a chart" / debugging a single camera | **Static matplotlib** — `plot_static.plot_grid_bfi_bvi()` |
| End-of-scan report / print / embed in PDF | **Static PNG** — `summary.generate_scan_card()` |
| Inside a Jupyter notebook | Both work; ask the user |
| File size matters (email attachment) | Static PNG (~200 KB vs Plotly HTML ~2 MB) |

When in doubt, default to Plotly — it's more useful and the user said so.

---

## Plotly dashboard structure

The interactive dashboard (`scripts/plot_interactive.py`) is a single self-contained HTML file with these tabs:

1. **Overview** — 4×4 grid of BFI/BVI time series, mirroring physical layout. Hover shows exact values. Zoom-synced across all panels.
2. **Asymmetry** — 4 rows of L−R asymmetry index. Clinical view.
3. **Spectral** — per-camera Welch PSD, with cardiac band highlighted.
4. **Spatial** — time-animated heatmap of BFI across the 16-camera grid.
5. **Quality** — dropped frames, calibration range warnings, telemetry flags.

The file drops in `/mnt/user-data/outputs/` and is emailable / shareable / opens in any browser. Plotly renders entirely client-side with the data embedded.

---

## Minimum viable plot

If the user just says "plot my data" with a corrected CSV attached, here's the one-liner to run:

```python
from scripts.io import load_corrected
from scripts.plot_interactive import build_dashboard

df = load_corrected("<their CSV>")
build_dashboard(df, output_html="/mnt/user-data/outputs/scan_dashboard.html")
```

And present the file. This is ~90% of what they need. For the remaining 10%, ask one clarifying question (which camera, which time window, static or interactive) rather than guess.
