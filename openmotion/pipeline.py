"""
Offline science pipeline — reference implementation.

Takes raw histogram DataFrames (from io.load_raw) for one or both sides and
produces a corrected DataFrame identical in schema to what the live SDK writes.

Why this exists
---------------
- Users with only raw histogram CSVs (no corrected) can still get BFI/BVI.
- Re-analyzing an old scan with different parameters (noise floor, dark interval,
  calibration) is trivial here and painful in the live SDK.
- Serves as a transparent, deterministic reference to cross-check the live pipeline.

Deviates from the live SDK in one way: no threading, no queues. Pure numpy + pandas.
Results should match within floating-point rounding.

See references/science-pipeline.md for the math.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .constants import (
    ADC_GAIN,
    CAMERA_GAIN_MAP,
    DARK_INTERVAL,
    DISCARD_COUNT,
    FRAME_RATE_HZ,
    HISTO_BINS,
    HISTO_BINS_SQ,
    NOISE_FLOOR,
    NUM_BINS,
    PEDESTAL_HEIGHT,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Tunable pipeline parameters. Defaults match the openmotion-sdk SciencePipeline."""
    noise_floor: int = NOISE_FLOOR
    dark_interval: int = DARK_INTERVAL
    discard_count: int = DISCARD_COUNT

    # Calibration arrays of shape (2, 8). Axis 0: 0=left, 1=right. Axis 1: cam_pos 0..7.
    # If None, BFI and BVI use identity scaling: BFI = K*10, BVI = mu1*10.
    bfi_c_min: np.ndarray | None = None
    bfi_c_max: np.ndarray | None = None
    bfi_i_min: np.ndarray | None = None
    bfi_i_max: np.ndarray | None = None

    @property
    def has_calibration(self) -> bool:
        return all(
            arr is not None for arr in
            (self.bfi_c_min, self.bfi_c_max, self.bfi_i_min, self.bfi_i_max)
        )


# ---------------------------------------------------------------------------
# Frame classification
# ---------------------------------------------------------------------------

def is_dark_frame(n: int, cfg: PipelineConfig) -> bool:
    """n is an absolute (logical) frame index. True if n is a scheduled dark frame."""
    if n <= cfg.discard_count:
        return False
    if n == cfg.discard_count + 1:
        return True
    return (n - 1) % cfg.dark_interval == 0


# ---------------------------------------------------------------------------
# Moment computation
# ---------------------------------------------------------------------------

def compute_moments(hist: np.ndarray, noise_floor: int = NOISE_FLOOR) -> tuple[float, float, int]:
    """
    Compute first moment, second moment, and post-decimation row sum
    for one 1024-bin histogram. Bins below `noise_floor` are zeroed first.

    Returns (mu1, mu2, row_sum).
    """
    if noise_floor > 0:
        hist = np.where(hist < noise_floor, 0, hist)
    row_sum = int(hist.sum())
    if row_sum <= 0:
        return 0.0, 0.0, 0
    mu1 = float((hist * HISTO_BINS).sum() / row_sum)
    mu2 = float((hist * HISTO_BINS_SQ).sum() / row_sum)
    return mu1, mu2, row_sum


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibrate_bfi_bvi(
    K: float,
    mu1: float,
    side: str,
    cam_pos: int,
    cfg: PipelineConfig,
) -> tuple[float, float]:
    """Return (BFI, BVI). Uses calibration arrays if present, identity otherwise."""
    if not cfg.has_calibration:
        return K * 10.0, mu1 * 10.0

    module_idx = 0 if side == "left" else 1
    cp = cam_pos % 8
    try:
        c_min = cfg.bfi_c_min[module_idx, cp]
        c_max = cfg.bfi_c_max[module_idx, cp]
        i_min = cfg.bfi_i_min[module_idx, cp]
        i_max = cfg.bfi_i_max[module_idx, cp]
    except (IndexError, TypeError):
        return K * 10.0, mu1 * 10.0

    if c_max == c_min or i_max == i_min:
        return K * 10.0, mu1 * 10.0

    bfi = (1.0 - (K   - c_min) / (c_max - c_min)) * 10.0
    bvi = (1.0 - (mu1 - i_min) / (i_max - i_min)) * 10.0
    return float(bfi), float(bvi)


# ---------------------------------------------------------------------------
# The main offline pipeline
# ---------------------------------------------------------------------------

def apply_science_pipeline(
    raw_left: pd.DataFrame | None = None,
    raw_right: pd.DataFrame | None = None,
    cfg: PipelineConfig | None = None,
) -> pd.DataFrame:
    """
    Apply the full dark-frame-corrected science pipeline to raw histogram data.

    Inputs
    ------
    raw_left, raw_right : DataFrames from io.load_raw for each sensor side.
        Either may be None if that side wasn't captured.
    cfg : PipelineConfig, defaults to pipeline constants.

    Returns
    -------
    wide-format DataFrame matching the live corrected.csv schema:
        logical_frame_id, timestamp_s, bfi_l1..bfi_r8, bvi_*, mean_*, contrast_*, std_*, temp_*

    Notes
    -----
    - This is the offline reference. It does NOT do shot-noise correction's
      identical-bit-for-bit match with the live pipeline because intermediate
      floating-point order differs. Values match within ~1e-9.
    - Uncorrected samples are not produced by this function — it only emits
      dark-corrected output, which is what people want for analysis anyway.
    """
    cfg = cfg or PipelineConfig()

    if raw_left is None and raw_right is None:
        raise ValueError("Need at least one of raw_left or raw_right.")

    per_frame: dict[int, dict[str, float]] = {}
    t0: float | None = None

    for side, df in (("left", raw_left), ("right", raw_right)):
        if df is None or df.empty:
            continue

        for cam_id, cam_df in df.groupby("cam_id"):
            cam_pos = int(cam_id)
            cam_num = cam_pos + 1
            g_cam = float(CAMERA_GAIN_MAP[cam_pos])

            cam_df = cam_df.sort_values("logical_frame_id").reset_index(drop=True)
            bin_cols = [str(i) for i in range(NUM_BINS)]

            # Precompute moments for every frame in this camera.
            frames = cam_df["logical_frame_id"].to_numpy(dtype=int)
            hists = cam_df[bin_cols].to_numpy(dtype=np.int64)

            mus = np.empty(len(frames), dtype=np.float64)
            mu2s = np.empty(len(frames), dtype=np.float64)
            for i, hist in enumerate(hists):
                mu1, mu2, _ = compute_moments(hist, cfg.noise_floor)
                mus[i], mu2s[i] = mu1, mu2

            # Find dark frames.
            dark_mask = np.fromiter(
                (is_dark_frame(int(n), cfg) for n in frames), dtype=bool, count=len(frames)
            )
            dark_idxs = np.where(dark_mask)[0]

            if dark_idxs.size < 2:
                continue  # Need at least two darks to correct anything.

            # Iterate over consecutive dark pairs.
            for a, b in zip(dark_idxs[:-1], dark_idxs[1:]):
                n_prev = int(frames[a])
                n_next = int(frames[b])
                interval = n_next - n_prev
                if interval <= 0:
                    continue

                mu1_prev = mus[a]
                mu1_next = mus[b]
                sig2_prev = max(0.0, mu2s[a] - mu1_prev ** 2)
                sig2_next = max(0.0, mu2s[b] - mu1_next ** 2)

                # Corrected values for each bright frame in the interval.
                for j in range(a + 1, b):
                    n = int(frames[j])
                    if dark_mask[j]:
                        continue  # Shouldn't happen, but just in case.
                    raw_mu1 = mus[j]
                    raw_mu2 = mu2s[j]
                    raw_sig2 = max(0.0, raw_mu2 - raw_mu1 ** 2)

                    t = (n - n_prev) / interval
                    mu1_bar = mu1_prev + t * (mu1_next - mu1_prev)
                    sig2_bar = sig2_prev + t * (sig2_next - sig2_prev)

                    mu1_corr = raw_mu1 - mu1_bar
                    sig2_shot = ADC_GAIN * g_cam * max(0.0, mu1_corr)
                    sig2_corr = max(0.0, raw_sig2 - sig2_bar - sig2_shot)
                    sig_corr = float(np.sqrt(sig2_corr))

                    if mu1_corr > 0.0:
                        K_corr = sig_corr / mu1_corr
                    else:
                        K_corr = 0.0

                    bfi, bvi = calibrate_bfi_bvi(K_corr, mu1_corr, side, cam_pos, cfg)

                    ts = cam_df["timestamp"].iloc[j] if "timestamp" in cam_df.columns else np.nan
                    if not np.isnan(ts):
                        if t0 is None:
                            t0 = float(ts)
                        timestamp_s = float(ts) - t0
                    else:
                        timestamp_s = n / FRAME_RATE_HZ

                    temp = (
                        float(cam_df["temperature"].iloc[j])
                        if "temperature" in cam_df.columns else np.nan
                    )

                    side_char = side[0]
                    row = per_frame.setdefault(
                        n,
                        {"logical_frame_id": n, "timestamp_s": timestamp_s},
                    )
                    row[f"bfi_{side_char}{cam_num}"] = bfi
                    row[f"bvi_{side_char}{cam_num}"] = bvi
                    row[f"mean_{side_char}{cam_num}"] = mu1_corr
                    row[f"std_{side_char}{cam_num}"] = sig_corr
                    row[f"contrast_{side_char}{cam_num}"] = K_corr
                    row[f"temp_{side_char}{cam_num}"] = temp

    if not per_frame:
        return pd.DataFrame(columns=["logical_frame_id", "timestamp_s"])

    out = pd.DataFrame(sorted(per_frame.values(), key=lambda r: r["logical_frame_id"]))
    return out
