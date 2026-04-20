"""
I/O helpers for Open-Motion CSV files.

Every plotting/analysis script should go through these loaders rather than
pandas.read_csv directly — they handle the frame-ID unwrap, sentinel zeroing,
warmup discard, and sum-check filtering that must happen before any analysis.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .constants import (
    DISCARD_COUNT,
    EXPECTED_HISTOGRAM_SUM,
    FRAME_ID_MODULUS,
    NUM_BINS,
    SENTINEL_BIN,
    SIDES,
)


# ---------------------------------------------------------------------------
# Frame ID unwrapping
# ---------------------------------------------------------------------------

def unwrap_frame_id(series: pd.Series) -> pd.Series:
    """
    Turn a series of raw 0..255 frame IDs into a monotonic logical frame index.

    Must be applied per camera (the firmware counter is per-camera and rolls
    over independently).

    Example
    -------
    >>> df["logical_frame_id"] = (
    ...     df.groupby("cam_id")["frame_id"].transform(unwrap_frame_id)
    ... )
    """
    rollovers = (series.diff() < 0).cumsum().fillna(0).astype(int)
    return rollovers * FRAME_ID_MODULUS + series.astype(int)


# ---------------------------------------------------------------------------
# Raw histogram CSV
# ---------------------------------------------------------------------------

def load_raw(
    path: str | Path,
    *,
    validate_sums: bool = True,
    drop_warmup: bool = True,
    zero_sentinel: bool = True,
) -> pd.DataFrame:
    """
    Load a raw histogram CSV (one per side).

    Returns a pandas DataFrame with:
      - logical_frame_id (int64, monotonic, unwrapped per cam)
      - cam_id (0..7)
      - total (histogram sum, should equal EXPECTED_HISTOGRAM_SUM)
      - timestamp, temperature (if present in source)
      - bin columns "0".."1023" as ints (bin 1023 zeroed)

    Parameters
    ----------
    validate_sums : drop rows whose total != EXPECTED_HISTOGRAM_SUM (default True)
    drop_warmup   : drop logical_frame_id <= DISCARD_COUNT (default True)
    zero_sentinel : zero bin 1023 in place (default True)
    """
    path = Path(path)
    df = pd.read_csv(path)

    # Some dumps use "id" instead of "frame_id" for the raw counter.
    if "frame_id" not in df.columns and "id" in df.columns:
        df = df.rename(columns={"id": "frame_id"})

    if "frame_id" not in df.columns or "cam_id" not in df.columns:
        raise ValueError(
            f"{path} does not look like a raw histogram CSV "
            f"(expected columns frame_id, cam_id, total, 0..1023; got {list(df.columns)[:8]}...)"
        )

    # Ensure bin columns are named as strings "0".."1023". Some writers use ints.
    bin_str_cols = [str(i) for i in range(NUM_BINS)]
    bin_int_cols = list(range(NUM_BINS))
    have_str = all(c in df.columns for c in bin_str_cols[:3])
    have_int = all(c in df.columns for c in bin_int_cols[:3])
    if not have_str and have_int:
        df = df.rename(columns={i: str(i) for i in bin_int_cols})
    elif not have_str and not have_int:
        # Bin columns may appear as "bin_0", "bin_1", etc.
        named = [c for c in df.columns if c.startswith("bin_")]
        if len(named) >= NUM_BINS:
            rename = {f"bin_{i}": str(i) for i in range(NUM_BINS)}
            df = df.rename(columns=rename)

    # Zero the sentinel bin.
    if zero_sentinel:
        sentinel = str(SENTINEL_BIN)
        if sentinel in df.columns:
            df[sentinel] = 0

    # Defragment after the rename/zero operations (cosmetic: silences PerformanceWarning).
    df = df.copy()

    # Unwrap frame_id per camera.
    df["logical_frame_id"] = (
        df.groupby("cam_id", sort=False)["frame_id"].transform(unwrap_frame_id)
    )

    # Sum check.
    if validate_sums and "total" in df.columns:
        before = len(df)
        df = df[df["total"] == EXPECTED_HISTOGRAM_SUM].copy()
        dropped = before - len(df)
        if dropped:
            df.attrs["dropped_invalid_sum"] = dropped

    # Warmup discard.
    if drop_warmup:
        before = len(df)
        df = df[df["logical_frame_id"] > DISCARD_COUNT].copy()
        df.attrs["dropped_warmup"] = before - len(df)

    df = df.sort_values(["cam_id", "logical_frame_id"]).reset_index(drop=True)
    return df


def histogram_matrix(raw_df: pd.DataFrame, cam_id: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Extract the (n_frames, 1024) histogram matrix for one camera from a raw DataFrame.

    Returns
    -------
    (frame_ids, histograms) : tuple of np.ndarray
        frame_ids : shape (n_frames,) — logical (unwrapped) frame indices
        histograms : shape (n_frames, 1024) — bin counts
    """
    cam_df = raw_df[raw_df["cam_id"] == cam_id].sort_values("logical_frame_id")
    if cam_df.empty:
        return np.array([], dtype=int), np.empty((0, NUM_BINS), dtype=int)

    frame_ids = cam_df["logical_frame_id"].to_numpy()
    bin_cols = [str(i) for i in range(NUM_BINS)]
    hist = cam_df[bin_cols].to_numpy(dtype=np.int64)
    return frame_ids, hist


# ---------------------------------------------------------------------------
# Corrected CSV
# ---------------------------------------------------------------------------

_METRIC_PREFIXES = ("bfi", "bvi", "mean", "std", "contrast", "temp")


def load_corrected(
    path: str | Path,
    *,
    long_format: bool = True,
    drop_nan_rows: bool = True,
) -> pd.DataFrame:
    """
    Load a corrected CSV from a scan.

    If long_format=True (default), returns a tidy long-format DataFrame with columns:
      logical_frame_id, timestamp_s, side, cam, bfi, bvi, mean, contrast, std, temp
    Wide-format pass-through (long_format=False) returns the raw wide file with
    NaN rows dropped by default.

    The long format makes `for (side, cam), g in df.groupby(["side", "cam"])`
    trivial, which is what every plotting routine wants.
    """
    path = Path(path)
    wide = pd.read_csv(path)

    # Normalize column names in case of minor variations.
    if "logical_frame_id" not in wide.columns and "frame_id" in wide.columns:
        wide = wide.rename(columns={"frame_id": "logical_frame_id"})

    if drop_nan_rows:
        metric_cols = [
            c for c in wide.columns if any(c.startswith(p + "_") for p in _METRIC_PREFIXES)
        ]
        if metric_cols:
            wide = wide.dropna(subset=metric_cols, how="all").reset_index(drop=True)

    if not long_format:
        return wide

    # Melt to long format. Column pattern: <metric>_<l|r><1..8>
    id_vars = [c for c in ("logical_frame_id", "timestamp_s") if c in wide.columns]

    rows = []
    for metric in _METRIC_PREFIXES:
        prefix = metric + "_"
        metric_cols = [c for c in wide.columns if c.startswith(prefix)]
        for col in metric_cols:
            suffix = col[len(prefix):]
            if len(suffix) < 2:
                continue
            side_char, cam_str = suffix[0], suffix[1:]
            if side_char not in ("l", "r") or not cam_str.isdigit():
                continue
            side = "left" if side_char == "l" else "right"
            cam = int(cam_str)
            sub = wide[id_vars + [col]].rename(columns={col: metric})
            sub["side"] = side
            sub["cam"] = cam
            rows.append(sub)

    if not rows:
        return wide  # fall back

    # Pivot back together by (frame, side, cam). Start from the first metric,
    # merge subsequent metrics.
    long_parts: dict[str, pd.DataFrame] = {}
    for part in rows:
        metric = [c for c in part.columns if c not in id_vars + ["side", "cam"]][0]
        if metric not in long_parts:
            long_parts[metric] = part
        else:
            long_parts[metric] = pd.concat([long_parts[metric], part], ignore_index=True)

    long_parts_list = list(long_parts.values())
    merged = long_parts_list[0]
    for other in long_parts_list[1:]:
        merged = merged.merge(other, on=id_vars + ["side", "cam"], how="outer")

    return merged.sort_values(id_vars + ["side", "cam"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Telemetry CSV
# ---------------------------------------------------------------------------

def load_telemetry(path: str | Path) -> pd.DataFrame:
    """
    Load a telemetry CSV. Adds a `t` column (seconds since first sample)
    for convenient plotting.
    """
    df = pd.read_csv(path)
    if "timestamp" in df.columns:
        t0 = df["timestamp"].iloc[0]
        df["t"] = df["timestamp"] - t0
    else:
        df["t"] = np.arange(len(df), dtype=float)
    return df


# ---------------------------------------------------------------------------
# File auto-discovery
# ---------------------------------------------------------------------------

def discover_scan_files(scan_dir: str | Path) -> dict[str, Path | None]:
    """
    Given a scan data directory, return a dict locating the raw/corrected/telemetry files
    for the most recent scan. Keys: 'left_raw', 'right_raw', 'corrected', 'telemetry'.
    Missing files come back as None.
    """
    scan_dir = Path(scan_dir)

    def _newest(pattern: str) -> Path | None:
        matches = sorted(scan_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
        return matches[-1] if matches else None

    return {
        "left_raw":   _newest("scan_*_left_mask*.csv"),
        "right_raw":  _newest("scan_*_right_mask*.csv"),
        "corrected":  _newest("scan_*_corrected.csv"),
        "telemetry":  _newest("scan_*_telemetry.csv"),
    }


def active_cameras(df: pd.DataFrame) -> dict[str, list[int]]:
    """
    Given a corrected DataFrame (long or wide format), return
    {'left': [1, 2, ...], 'right': [...]} of cameras that actually have data.
    """
    out: dict[str, list[int]] = {"left": [], "right": []}
    if "side" in df.columns and "cam" in df.columns and "bfi" in df.columns:
        # Long format
        live = df.dropna(subset=["bfi"])
        for side in SIDES:
            cams = sorted(live[live["side"] == side]["cam"].unique().tolist())
            out[side] = [int(c) for c in cams]
    else:
        # Wide format
        for side in SIDES:
            side_char = side[0]
            for cam in range(1, 9):
                col = f"bfi_{side_char}{cam}"
                if col in df.columns and df[col].notna().any():
                    out[side].append(cam)
    return out
