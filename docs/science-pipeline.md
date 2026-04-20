# Science Pipeline Reference

How Open-Motion turns raw 1024-bin histograms into BFI/BVI. Consult this when the user asks "why does X matter" or when implementing offline analysis that needs to match the live pipeline.

The canonical reference is `openmotion-sdk/docs/SciencePipeline.md` (~500 lines, exhaustive). This is the operator's cheat-sheet.

---

## One-paragraph summary

Each camera produces a 1024-bin photon-count histogram at 40 Hz. The pipeline drops 9 warmup frames, then classifies every 600th frame as a "dark frame" (laser off → ambient + dark-current baseline). On each bright frame it computes the first two moments of the histogram, emits an **uncorrected** sample immediately for live plotting, and buffers the moments. When a second consecutive dark frame arrives, it linearly interpolates the dark baseline across the interval, subtracts it from each buffered bright frame's moments, subtracts the predicted photon shot-noise variance, and emits a **corrected batch** of BFI/BVI values. BFI and BVI are linear remaps of speckle contrast `K = σ/μ` and mean intensity `μ` to the 0–10 scale.

---

## Key constants

| Constant | Value | Reason |
|---|---|---|
| `NUM_BINS` | 1024 | Histogram width (fixed by FPGA). |
| `EXPECTED_HISTOGRAM_SUM` | 2 457 606 | 1920×1280 sensor pixels + 6 firmware sentinel counts. Frames that don't sum to this are corrupt. |
| `PEDESTAL_HEIGHT` | 64 | ADC bias bin when no light reaches the sensor. |
| `NOISE_FLOOR` | 10 | Bins below this count are zeroed before moments are computed — suppresses low-level noise bias. |
| `DISCARD_COUNT` | 9 | Sensor warmup frames (AGC, PLL settling). |
| `DARK_INTERVAL` | 600 | Frames between dark measurements = 15 s at 40 Hz. |
| `ADC_GAIN` | (1024−64)/11000 ≈ 0.0873 DN/e⁻ | For shot-noise correction. |
| `CAMERA_GAIN_MAP` | `[16, 4, 2, 1, 1, 2, 4, 16]` | Per-position analog gain (indexed by camera position 0–7). Outer cameras run with higher gain because they're dimmer. |
| `FRAME_RATE_HZ` | 40 | Nominal. |

---

## Frame classification

For each frame, compute absolute frame index *n* by unwrapping the 8-bit counter. Then:

- **Discarded** if n ≤ 9 (silently dropped)
- **Dark frame** if n = 10 or (n > 10 and (n − 1) mod 600 = 0)
- **Bright frame** otherwise

Under default settings, darks occur at frames 10, 601, 1201, 1801, …

---

## Moments

For histogram **h** = (h₀, …, h₁₀₂₃) with total count *N* (after noise-floor decimation):

```
μ₁ = (1/N) Σ k · h_k
μ₂ = (1/N) Σ k² · h_k
σ² = μ₂ − μ₁²
```

In NumPy:

```python
import numpy as np
BINS = np.arange(1024, dtype=np.float64)
BINS_SQ = BINS ** 2

row_sum = hist.sum()
mu1 = (hist @ BINS) / row_sum
mu2 = (hist @ BINS_SQ) / row_sum
sigma2 = max(0.0, mu2 - mu1 ** 2)
```

---

## Uncorrected stream (live plot)

Every bright frame produces a `Sample` with:

```
mean     = max(0, μ₁ − 64)       # pedestal-subtracted
std_dev  = √σ²                    # σ (pedestal-invariant)
contrast = σ / mean               # K
bfi      = calibrate_bfi(K, mean, side, cam_pos)
bvi      = calibrate_bvi(mean, side, cam_pos)
```

**On dark frames**, the uncorrected stream re-emits the previous bright frame's values (with the dark frame's timestamp / frame_id). This is cosmetic — it hides the laser-off dip from the live plot. Don't do this for publication.

---

## Corrected batch (dark-frame correction)

Called when the second of two consecutive dark frames `D_next` arrives. Let `D_prev` be the previous dark.

### Step 1 — Baseline interpolation

For each bright frame *n* ∈ (D_prev, D_next):

```
t(n)   = (n − D_prev) / (D_next − D_prev)       ∈ (0, 1)
μ̄₁(n) = μ₁(D_prev) + t(n) · (μ₁(D_next) − μ₁(D_prev))
σ̄²(n) = σ²(D_prev) + t(n) · (σ²(D_next) − σ²(D_prev))
```

### Step 2 — Dark subtraction

```
μ̃₁(n) = μ₁(n) − μ̄₁(n)
```

Note: pedestal is present in both raw μ₁(n) and μ̄₁(n), so **it cancels exactly**. No explicit pedestal subtraction in the corrected path.

### Step 3 — Shot-noise correction

Poisson: variance = mean. Convert to DN and account for camera gain:

```
σ²_shot(n) = ADC_GAIN · g_cam · max(0, μ̃₁(n))
           = 0.0873 · CAMERA_GAIN_MAP[cam_pos] · μ̃₁(n)
```

### Step 4 — Corrected variance and contrast

```
σ̃²(n) = max(0, raw_σ²(n) − σ̄²(n) − σ²_shot(n))
σ̃(n)  = √σ̃²(n)
K̃(n)  = σ̃(n) / μ̃₁(n)   if μ̃₁(n) > 0 else 0
```

### Step 5 — Calibration (same mapping as uncorrected)

```
module_idx = 0 if side == "left" else 1
cam_pos    = cam_id % 8

BFI = (1 − (K̃ − C_min[module, cam]) / (C_max[module, cam] − C_min[module, cam])) · 10
BVI = (1 − (μ̃₁ − I_min[module, cam]) / (I_max[module, cam] − I_min[module, cam])) · 10
```

`C_min`, `C_max`, `I_min`, `I_max` are per-device calibration arrays of shape `(2, 8)`. Without them the fallback is identity: `BFI = K̃ × 10`, `BVI = μ̃₁ × 10`.

### Step 6 — The dark frame's own corrected value

The dark frame `D_prev` gets a corrected value from a 4-point quadratic stencil across its four nearest bright neighbors (two before, two after). Fallback rules:

- All four neighbors available: full quadratic stencil.
- Only right side available (first interval): linear average of two right neighbors.
- Only one neighbor each side: simple average.
- No left neighbors: repeat the first right neighbor.

The current dark `D_next` is **not** in this batch — it becomes `D_prev` of the next batch.

---

## Why every step exists (the theory-of-mind version)

| Step | Without it, you'd see… |
|---|---|
| Warmup discard | First 9 frames have wildly wrong AGC — they'd skew your baseline. |
| Noise-floor zeroing | Dark-current leak into low bins inflates μ₁ and biases contrast. |
| Pedestal subtraction (uncorrected only) | Contrast would be "compressed" toward a non-zero denominator → underestimated BFI. |
| Dark-frame correction | Slow drifts in ambient light or laser power mix into your BFI trace. |
| Shot-noise correction | High-intensity frames appear to have artificially *lower* contrast (more light → smaller relative Poisson noise). |
| 4-point stencil on dark frame | The dark frame's own timestamp would have a visible dip in the BFI trace every 15 s. |
| BFI/BVI calibration | Without it, you're plotting dimensionless contrast and mean — still informative, but not comparable across devices. |

---

## Edge cases you'll hit

- **Scan shorter than 15 s** — the terminal-dark-flush kicks in, promoting the last pending moment to a synthetic dark. Correct values are produced but with only one true dark measurement, so baseline trend isn't captured.
- **μ̃₁ ≤ 0** — happens when laser is off or blocked. Contrast is set to 0 to avoid division-by-zero. BFI/BVI will clip at the calibration edge.
- **σ̃² clamped to 0** — shot-noise correction over-shot. Not usually a problem unless it's happening on most frames (then laser power is too low).
- **Histogram sum ≠ 2 457 606** — frame dropped, never reaches the pipeline. USB bandwidth issue.

---

## Reference implementation

`scripts/pipeline.py` contains a standalone implementation of this pipeline suitable for offline use — load raw histogram CSVs, produce a corrected DataFrame, skip the real-time threading. Use it when:

- You have raw CSVs but lost (or never had) the corrected CSV.
- You want to experiment with different `NOISE_FLOOR`, `DARK_INTERVAL`, or calibration values.
- You want a deterministic, transparent reference to diff against the SDK's output.

```python
from scripts.pipeline import apply_science_pipeline
from scripts.io import load_raw

raw_left = load_raw("scan_left.csv")
raw_right = load_raw("scan_right.csv")
corrected = apply_science_pipeline(raw_left, raw_right)
```
