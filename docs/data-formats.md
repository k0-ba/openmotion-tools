# Data Formats

Open-Motion scans produce four file types. Know the schema before you write analysis code — getting the column layout wrong produces plausible-looking garbage.

---

## Raw histogram CSV

**Filename pattern:** `scan_<subject>_<timestamp>_<side>_mask<hex>.csv`

One file per side (left + right). Every row is one frame from one camera.

### Columns

| Column | Type | Description |
|---|---|---|
| `frame_id` | int 0–255 | Raw 8-bit firmware counter. **Wraps.** Must be unwrapped before plotting. |
| `cam_id` | int 0–7 | Channel index (= camera number − 1). |
| `total` | int | Should equal `EXPECTED_HISTOGRAM_SUM = 2_457_606`. Frames with other values were dropped by the pipeline but may survive in raw dumps. |
| `0`, `1`, …, `1023` | int | Bin counts. **Bin 1023 is a firmware sentinel — always zero it before analysis.** |
| `timestamp` | float, optional | Seconds since scan start, if the firmware version emits it. |
| `temperature` | float, optional | Per-camera temperature in °C, if the firmware emits it. |

### Frame-ID unwrapping

Must be done per `cam_id`:

```python
import pandas as pd

FRAME_ID_MODULUS = 256

def unwrap_frame_id(series: pd.Series) -> pd.Series:
    """Turn a series of raw 0-255 frame IDs into a monotonic logical frame index."""
    rollovers = (series.diff() < 0).cumsum()
    return rollovers * FRAME_ID_MODULUS + series
```

For multi-camera data:

```python
df["logical_frame_id"] = (
    df.groupby("cam_id")["frame_id"].transform(unwrap_frame_id)
)
```

### Validity checks

Drop rows where `total != 2_457_606` — these are corrupt frames. Drop rows where `logical_frame_id ≤ 9` — these are warmup frames and shouldn't be analyzed.

---

## Corrected CSV

**Filename pattern:** `scan_<subject>_<timestamp>_corrected.csv`

One row per logical frame (both sides combined). This is the science output — dark-frame-corrected, shot-noise-corrected, calibrated.

### Columns

| Column pattern | Count | Description |
|---|---|---|
| `frame_id` | 1 | Logical (unwrapped) frame ID. |
| `timestamp_s` | 1 | Seconds since the **first corrected frame**. Not the start of the scan. |
| `bfi_l1`, `bfi_l2`, …, `bfi_l8` | 8 | Left sensor BFI, scaled 0–10. |
| `bfi_r1`, `bfi_r2`, …, `bfi_r8` | 8 | Right sensor BFI, scaled 0–10. |
| `bvi_l1..bvi_l8`, `bvi_r1..bvi_r8` | 16 | BVI, scaled 0–10. |
| `mean_l1..mean_l8`, `mean_r1..mean_r8` | 16 | First moment μ̃₁ (dark-subtracted intensity, bin-index units). |
| `contrast_l1..contrast_l8`, `contrast_r1..contrast_r8` | 16 | Speckle contrast K̃ = σ̃ / μ̃₁. |
| `std_l1..std_r8` | 16 | σ̃ (corrected standard deviation). Not in all firmware versions. |
| `temp_l1..temp_l8`, `temp_r1..temp_r8` | 16 | Per-camera temperature in °C. |

**Naming:** `l` / `r` prefix is the side, suffix `1..8` is the 1-indexed camera number (NOT `cam_id`).

### Missing columns

A missing `bfi_l3` column means camera 3 on the left sensor was masked out during the scan. Never assume all 16 cameras are present — always check column existence before plotting.

### NaN values

Rows in early frames (before the first dark frame at frame 10) will be NaN for all corrected metrics. This is expected — drop them or mark them explicitly on plots.

---

## Telemetry CSV

**Filename pattern:** `scan_<subject>_<timestamp>_telemetry.csv`

Console health log. Sampled at ~1 Hz by the `ConsoleTelemetryPoller`.

### Columns

| Column | Description |
|---|---|
| `timestamp` | Unix timestamp of the sample. |
| `tcm`, `tcl`, `pdc` | Temperature sensors — Module (°C), Laser (°C), Photodiode (raw counts). |
| `tec_v_raw`, `tec_set_raw`, `tec_curr_raw`, `tec_volt_raw` | TEC (laser cooler) control values, raw ADC counts. |
| `pdu_raw_0..15` | Power Distribution Unit ADC raw counts (16 channels). |
| `pdu_volt_0..15` | Same, scaled to volts. |
| `tec_good`, `safety_se`, `safety_so`, `safety_ok`, `read_ok` | Binary flags. `1` = healthy. Any `0` during a scan is suspect. |

### When telemetry matters

- **TEC not good during scan** → laser was out of temperature spec, BFI values are likely bad.
- **Safety flags dropping** → the Safety FPGA detected an out-of-bounds condition. Investigate before trusting the scan.
- **PDU voltages unstable** → power rail issue, scan is probably unusable.

Use `scripts/plot_telemetry.py` from the official SDK for the canonical visualization. The `plot_static.py` module in this skill also has `plot_telemetry()`.

---

## Loading CSVs in Python

`scripts/io.py` provides three loaders that handle all the above:

```python
from scripts.io import load_raw, load_corrected, load_telemetry

raw = load_raw("scan_S001_20251217_left_maskFF.csv")
# raw is a pandas DataFrame with logical_frame_id already computed,
# bin 1023 zeroed, invalid-sum rows dropped, warmup discarded.

corrected = load_corrected("scan_S001_20251217_corrected.csv")
# Long-format: columns [logical_frame_id, timestamp_s, side, cam, bfi, bvi, mean, contrast, ...].
# Long format makes plotting loops trivial.

telemetry = load_telemetry("scan_S001_20251217_telemetry.csv")
# t column added (seconds since first sample).
```

Prefer the long-format corrected DataFrame — iterating over (side, cam) pairs is one `groupby` call. Wide-format access (`corrected["bfi_l3"]`) is also supported because sometimes it's more readable.
