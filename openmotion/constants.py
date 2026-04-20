"""
Canonical constants for Open-Motion data processing.

Every script in this skill imports from here. Do not duplicate these values inline
— getting one wrong silently produces plausible-but-wrong metrics.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Histogram geometry
# ---------------------------------------------------------------------------

NUM_BINS = 1024
"""Width of one histogram (fixed by FPGA)."""

EXPECTED_HISTOGRAM_SUM = 2_457_606
"""
Valid frame total: 1920 x 1280 sensor pixels + 6 firmware sentinel counts.
Frames with any other total are corrupt (USB dropouts or firmware mismatch)
and should be dropped.
"""

SENTINEL_BIN = 1023
"""The last bin is a firmware sentinel. Always zero it before analysis or plotting."""

# ---------------------------------------------------------------------------
# Pipeline constants (must match openmotion-sdk SciencePipeline)
# ---------------------------------------------------------------------------

PEDESTAL_HEIGHT = 64.0
"""
ADC bin index where the sensor settles when no photons reach it.
Subtract from mu1 in the uncorrected stream. Cancels automatically in the
dark-subtracted (corrected) stream since both bright and dark carry it.
"""

NOISE_FLOOR = 10
"""Bins below this count are zeroed before moment computation."""

DISCARD_COUNT = 9
"""Warmup frames dropped at the start of every scan."""

DARK_INTERVAL = 600
"""Frames between scheduled dark measurements. 15 seconds at 40 Hz."""

FRAME_RATE_HZ = 40
"""Nominal camera frame rate."""

FRAME_ID_MODULUS = 256
"""Firmware emits an 8-bit rolling counter. This is the rollover period."""

FRAME_ROLLOVER_THRESHOLD = 128
"""Max forward delta before a backwards-looking jump counts as a genuine rollover."""

# ---------------------------------------------------------------------------
# Sensor ADC model (used for shot-noise correction in the corrected stream)
# ---------------------------------------------------------------------------

ADC_GAIN = (NUM_BINS - PEDESTAL_HEIGHT) / 11000.0
"""Sensor ADC gain, in DN per electron. ≈ 0.0873."""

CAMERA_GAIN_MAP = np.array([16, 4, 2, 1, 1, 2, 4, 16], dtype=np.float64)
"""
Per-camera-position analog gain, indexed by camera position 0..7.
Outer cameras (positions 0 and 7) use higher gain because they're dimmer
at the array periphery. Central cameras run at unity gain.
"""

# ---------------------------------------------------------------------------
# Physical camera layout
# ---------------------------------------------------------------------------

CAMERA_GRID_POS = {
    # 1-indexed camera number -> (row, col) within a single sensor's 4x2 grid
    1: (0, 0),
    2: (1, 0),
    3: (2, 0),
    4: (3, 0),
    5: (3, 1),
    6: (2, 1),
    7: (1, 1),
    8: (0, 1),
}
"""
Physical layout:
    Cam 1 | Cam 8     row 0 (top)
    Cam 2 | Cam 7
    Cam 3 | Cam 6
    Cam 4 | Cam 5     row 3 (bottom)
The layout counts *down* the left column then *hooks back up* the right.
Every multi-panel plot should mirror this.
"""

CHANNEL_GRID_POS = {cam - 1: pos for cam, pos in CAMERA_GRID_POS.items()}
"""Same map but keyed by 0-indexed channel (= cam_id = cam - 1)."""

SENSOR_COL_OFFSET = {"left": 0, "right": 2}
"""
In a full two-sensor plot grid, the left sensor occupies plot columns 0 and 1,
the right sensor occupies plot columns 2 and 3.
"""

SIDES = ("left", "right")

CAMERAS_PER_SENSOR = 8
MAX_SENSORS = 2

# Named camera groups
CAMERA_GROUPS = {
    "outer": (1, 4, 5, 8),   # four corners — high gain
    "inner": (2, 3, 6, 7),   # middle rows — low gain
    "left_col": (1, 2, 3, 4),
    "right_col": (5, 6, 7, 8),
    "top_pair": (1, 8),
    "bottom_pair": (4, 5),
}

# ---------------------------------------------------------------------------
# Plot style conventions (keep consistent across static and interactive plots)
# ---------------------------------------------------------------------------

STYLE = {
    "bfi_color": "black",
    "bfi_linewidth": 2.0,
    "bvi_color": "#c91f37",       # warm red
    "bvi_linewidth": 1.0,
    "temp_color": "tab:red",
    "temp_linestyle": "-.",
    "temp_marker": "d",
    "mean_color": "tab:blue",
    "std_color": "tab:orange",
    "contrast_color": "tab:green",
    "spectrogram_cmap": "viridis",
    "asymmetry_cmap": "RdBu_r",
    "grid_alpha": 0.3,
}

# ---------------------------------------------------------------------------
# Precomputed NumPy helpers
# ---------------------------------------------------------------------------

HISTO_BINS = np.arange(NUM_BINS, dtype=np.float64)
HISTO_BINS_SQ = HISTO_BINS ** 2


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------

def camera_gain(cam_pos: int) -> float:
    """Analog gain for a camera at position 0..7."""
    return float(CAMERA_GAIN_MAP[cam_pos % CAMERAS_PER_SENSOR])


def grid_position(side: str, cam: int) -> tuple[int, int]:
    """
    Return (row, col) for camera `cam` (1-indexed) on sensor `side`
    in the full 4x4 plot grid.
    """
    grid_row, sensor_col = CAMERA_GRID_POS[cam]
    plot_col = sensor_col + SENSOR_COL_OFFSET[side]
    return grid_row, plot_col
