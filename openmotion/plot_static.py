"""
Static matplotlib plots for Open-Motion scans.

These mirror the official SDK's `data-processing/plot_*` scripts but with
consistent styling, robust handling of sparse layouts, and clean interfaces
(pass a DataFrame, get a Figure).

Functions
---------
plot_single_histogram     : one 1024-bin row (line / bar / spectro strip)
plot_camera_spectrogram   : all frames x 1024 bins for one camera as heatmap
plot_moments_grid         : 4x2 grid of mu/sigma per camera, from raw data
plot_spectrogram_grid     : 4x2 grid of spectrograms from raw data
plot_grid_bfi_bvi         : 4x4 grid of BFI/BVI time series from corrected data
plot_asymmetry            : left-minus-right asymmetry index, per row pair
plot_cardiac_psd          : Welch PSD of BFI, cardiac band highlighted
plot_telemetry            : 5-panel telemetry visualization
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import welch

from .constants import (
    CAMERA_GRID_POS,
    FRAME_RATE_HZ,
    NUM_BINS,
    SENSOR_COL_OFFSET,
    SIDES,
    STYLE,
)
from .io import active_cameras, histogram_matrix


# ---------------------------------------------------------------------------
# Grid geometry — collapse empty rows/columns
# ---------------------------------------------------------------------------

def _active_cells(corrected_long: pd.DataFrame) -> list[tuple[int, int, str, int]]:
    """
    Return a list of (grid_row, plot_col, side, cam) tuples for every camera
    that has non-NaN BFI data.
    """
    cells: list[tuple[int, int, str, int]] = []
    alive = corrected_long.dropna(subset=["bfi"])
    for side in SIDES:
        for cam in range(1, 9):
            sub = alive[(alive["side"] == side) & (alive["cam"] == cam)]
            if sub.empty:
                continue
            grid_row, sensor_col = CAMERA_GRID_POS[cam]
            plot_col = sensor_col + SENSOR_COL_OFFSET[side]
            cells.append((grid_row, plot_col, side, cam))
    return cells


def _collapse_grid(cells: list[tuple[int, int, str, int]]):
    """Return (row_map, col_map, n_rows, n_cols) that map logical to packed indices."""
    if not cells:
        return {}, {}, 0, 0
    active_rows = sorted({c[0] for c in cells})
    active_cols = sorted({c[1] for c in cells})
    row_map = {r: i for i, r in enumerate(active_rows)}
    col_map = {c: i for i, c in enumerate(active_cols)}
    return row_map, col_map, len(active_rows), len(active_cols)


# ---------------------------------------------------------------------------
# Single histogram
# ---------------------------------------------------------------------------

def plot_single_histogram(
    raw_df: pd.DataFrame,
    cam_id: int,
    row_idx: int = 0,
    *,
    style: str = "line",   # "line" | "bar" | "spectro"
    ax: plt.Axes | None = None,
) -> plt.Figure:
    """
    Plot one 1024-bin histogram (bin 1023 already zeroed by io.load_raw).

    Parameters
    ----------
    raw_df : DataFrame from io.load_raw
    cam_id : 0..7
    row_idx : which frame of that camera to plot (0 = first)
    style : "line", "bar", or "spectro" (1xN imshow strip)
    """
    frames, hists = histogram_matrix(raw_df, cam_id)
    if hists.size == 0:
        raise ValueError(f"No data for cam_id={cam_id}")
    if not (0 <= row_idx < len(hists)):
        raise ValueError(f"row_idx {row_idx} out of range (0..{len(hists) - 1})")

    bins = hists[row_idx]
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 4))
    else:
        fig = ax.figure

    if style == "bar":
        ax.bar(range(NUM_BINS), bins, width=1.0)
        ax.set_xlabel("Bin")
        ax.set_ylabel("Count")
    elif style == "line":
        ax.plot(range(NUM_BINS), bins)
        ax.set_xlabel("Bin")
        ax.set_ylabel("Count")
    elif style == "spectro":
        im = ax.imshow(
            np.expand_dims(bins, 0),
            aspect="auto",
            cmap=STYLE["spectrogram_cmap"],
            origin="lower",
        )
        ax.set_yticks([])
        ax.set_xlabel("Bin")
        fig.colorbar(im, ax=ax, pad=0.02, label="Count")
    else:
        raise ValueError(f"Unknown style: {style}")

    total = int(bins.sum())
    ax.set_title(f"Cam {cam_id} • Frame {int(frames[row_idx])} • Total = {total:,}")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Per-camera spectrogram
# ---------------------------------------------------------------------------

def plot_camera_spectrogram(
    raw_df: pd.DataFrame,
    cam_id: int,
    *,
    ax: plt.Axes | None = None,
) -> plt.Figure:
    """Plot frames x bins heatmap for one camera."""
    frames, hists = histogram_matrix(raw_df, cam_id)
    if hists.size == 0:
        raise ValueError(f"No data for cam_id={cam_id}")

    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 6))
    else:
        fig = ax.figure

    im = ax.imshow(
        hists,
        aspect="auto",
        interpolation="nearest",
        origin="lower",
        cmap=STYLE["spectrogram_cmap"],
        extent=(0, NUM_BINS, int(frames[0]), int(frames[-1])),
    )
    fig.colorbar(im, ax=ax, label="Bin count")
    ax.set_xlabel("Bin index")
    ax.set_ylabel("Frame index")
    ax.set_title(f"Camera {cam_id} histogram spectrogram")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Moments grid (4x2 per side)
# ---------------------------------------------------------------------------

def plot_moments_grid(
    raw_df: pd.DataFrame,
    *,
    side_label: str = "",
    show_sigma: bool = True,
    show_temp: bool = True,
) -> plt.Figure:
    """
    4x2 grid mirroring physical layout — mu and sigma per camera with optional temperature.
    One figure per sensor side (call twice for both).
    """
    fig, axes = plt.subplots(nrows=4, ncols=2, figsize=(12, 10), sharex=False)
    title = f"Moments per camera" + (f" — {side_label}" if side_label else "")
    fig.suptitle(title, fontsize=12, y=0.995)

    for cam_num, (grid_row, grid_col) in CAMERA_GRID_POS.items():
        ax = axes[grid_row, grid_col]
        cam_id = cam_num - 1
        ax.set_title(f"Cam {cam_num}", fontsize=10)
        ax.grid(True, alpha=STYLE["grid_alpha"])

        frames, hists = histogram_matrix(raw_df, cam_id)
        if hists.size == 0:
            ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
            ax.set_xticks([]); ax.set_yticks([])
            continue

        sums = hists.sum(axis=1).astype(np.float64)
        bins = np.arange(NUM_BINS)
        mu = np.divide(hists @ bins, sums, out=np.zeros_like(sums), where=sums > 0)
        mu2 = np.divide(hists @ (bins ** 2), sums, out=np.zeros_like(sums), where=sums > 0)
        sigma = np.sqrt(np.clip(mu2 - mu ** 2, 0.0, None))

        ax.plot(frames, mu, "o-", markersize=2.5, color=STYLE["mean_color"], label="μ")
        if show_sigma:
            ax.plot(frames, sigma, "s--", markersize=2.5, color=STYLE["std_color"], label="σ")

        if show_temp and "temperature" in raw_df.columns:
            cam_df = raw_df[raw_df["cam_id"] == cam_id].sort_values("logical_frame_id")
            temps = cam_df["temperature"].to_numpy()
            if temps.size == frames.size:
                ax2 = ax.twinx()
                ax2.plot(
                    frames, temps, ":", color=STYLE["temp_color"],
                    marker=STYLE["temp_marker"], markersize=2.5, label="Temp",
                )
                ax2.set_ylabel("°C", color=STYLE["temp_color"], fontsize=8)
                ax2.tick_params(axis="y", labelsize=8, colors=STYLE["temp_color"])

        ax.set_ylabel("Bin index", fontsize=8)
        ax.tick_params(labelsize=8)
        if (grid_row, grid_col) == (0, 0):
            ax.legend(fontsize=7, loc="best")

    for ax in axes[-1, :]:
        ax.set_xlabel("Logical frame index", fontsize=8)
    fig.tight_layout()
    return fig


def plot_spectrogram_grid(raw_df: pd.DataFrame, *, side_label: str = "") -> plt.Figure:
    """4x2 grid of spectrograms, one per camera."""
    fig, axes = plt.subplots(nrows=4, ncols=2, figsize=(14, 11))
    title = "Histogram spectrograms" + (f" — {side_label}" if side_label else "")
    fig.suptitle(title, fontsize=12, y=0.995)

    for cam_num, (grid_row, grid_col) in CAMERA_GRID_POS.items():
        ax = axes[grid_row, grid_col]
        cam_id = cam_num - 1
        frames, hists = histogram_matrix(raw_df, cam_id)
        if hists.size == 0:
            ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
            ax.set_xticks([]); ax.set_yticks([])
            continue

        ax.imshow(
            hists, aspect="auto", interpolation="nearest", origin="lower",
            cmap=STYLE["spectrogram_cmap"],
            extent=(0, NUM_BINS, int(frames[0]), int(frames[-1])),
        )
        ax.set_title(f"Cam {cam_num}", fontsize=10)
        ax.tick_params(labelsize=8)

    for ax in axes[-1, :]:
        ax.set_xlabel("Bin", fontsize=8)
    for ax in axes[:, 0]:
        ax.set_ylabel("Frame", fontsize=8)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# BFI/BVI 4x4 grid (the main scientific plot)
# ---------------------------------------------------------------------------

def plot_grid_bfi_bvi(
    corrected: pd.DataFrame,
    *,
    show_bvi: bool = True,
    title: str = "BFI (black) and BVI (red) per camera — physical layout",
) -> plt.Figure:
    """
    The canonical 4x4 plot. Left sensor in columns 0-1, right in columns 2-3.
    BFI on left y-axis (black), BVI on twin right y-axis (red).
    Empty rows/columns are collapsed for sparse camera sets.

    Accepts either wide- or long-format corrected DataFrame.
    """
    # Normalize to long format.
    df = corrected
    if "side" not in df.columns or "cam" not in df.columns:
        # Wide -> minimal long for plotting.
        rows = []
        for side in SIDES:
            sc = side[0]
            for cam in range(1, 9):
                bfi_col = f"bfi_{sc}{cam}"
                bvi_col = f"bvi_{sc}{cam}"
                if bfi_col not in df.columns:
                    continue
                sub = pd.DataFrame({
                    "logical_frame_id": df.get("logical_frame_id", df.get("frame_id")),
                    "timestamp_s": df.get("timestamp_s", np.arange(len(df)) / FRAME_RATE_HZ),
                    "side": side, "cam": cam,
                    "bfi": df[bfi_col],
                    "bvi": df[bvi_col] if bvi_col in df.columns else np.nan,
                })
                rows.append(sub)
        df = pd.concat(rows, ignore_index=True) if rows else df

    cells = _active_cells(df)
    if not cells:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No active cameras", ha="center", va="center")
        ax.axis("off")
        return fig

    row_map, col_map, n_rows, n_cols = _collapse_grid(cells)
    fig, axes = plt.subplots(
        nrows=n_rows, ncols=n_cols,
        figsize=(3 * n_cols + 1, 2 * n_rows + 1),
        sharex=True, squeeze=False,
    )
    fig.suptitle(title, fontsize=11, y=0.995)

    x_col = "timestamp_s" if "timestamp_s" in df.columns else "logical_frame_id"
    x_label = "Time (s)" if x_col == "timestamp_s" else "Frame"

    for (grid_row, plot_col, side, cam) in cells:
        r, c = row_map[grid_row], col_map[plot_col]
        ax = axes[r, c]
        sub = df[(df["side"] == side) & (df["cam"] == cam)].dropna(subset=["bfi"])
        if sub.empty:
            continue

        ax.plot(
            sub[x_col], sub["bfi"],
            color=STYLE["bfi_color"], linewidth=STYLE["bfi_linewidth"], label="BFI",
        )
        ax.set_title(f"{side[0].upper()} cam {cam}", fontsize=9)
        ax.grid(True, alpha=STYLE["grid_alpha"])
        ax.tick_params(labelsize=8)

        if show_bvi and "bvi" in sub.columns and sub["bvi"].notna().any():
            ax2 = ax.twinx()
            ax2.plot(
                sub[x_col], sub["bvi"],
                color=STYLE["bvi_color"], linewidth=STYLE["bvi_linewidth"], label="BVI",
            )
            ax2.tick_params(labelsize=7, colors=STYLE["bvi_color"])
            if c == n_cols - 1:
                ax2.set_ylabel("BVI", color=STYLE["bvi_color"], fontsize=8)

        if c == 0:
            ax.set_ylabel("BFI", fontsize=8)
        if r == n_rows - 1:
            ax.set_xlabel(x_label, fontsize=8)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Asymmetry
# ---------------------------------------------------------------------------

def plot_asymmetry(corrected_long: pd.DataFrame) -> plt.Figure:
    """
    Plot left-right asymmetry index per row-pair:
        AI = (BFI_L - BFI_R) / (BFI_L + BFI_R)
    The 4 physical rows (top to bottom) give 4 left/right pairs:
        row 0: L1-R1 vs L8-R8   (top pair, outer)
        row 1: L2-R2 vs L7-R7
        row 2: L3-R3 vs L6-R6
        row 3: L4-R4 vs L5-R5   (bottom pair)

    Drawn as 4 traces on a single axis.
    """
    df = corrected_long
    x_col = "timestamp_s" if "timestamp_s" in df.columns else "logical_frame_id"
    x_label = "Time (s)" if x_col == "timestamp_s" else "Frame"

    fig, ax = plt.subplots(figsize=(12, 5))
    row_pairs = [
        ("Row 0 (top, C1/C8)", [(1, 1), (8, 8)]),
        ("Row 1 (C2/C7)",       [(2, 2), (7, 7)]),
        ("Row 2 (C3/C6)",       [(3, 3), (6, 6)]),
        ("Row 3 (bottom, C4/C5)", [(4, 4), (5, 5)]),
    ]

    for label, pairs in row_pairs:
        # Average AI across all left/right pairings in this row.
        ai_traces = []
        for cam_l, cam_r in pairs:
            l = df[(df["side"] == "left") & (df["cam"] == cam_l)].set_index(x_col)["bfi"]
            r = df[(df["side"] == "right") & (df["cam"] == cam_r)].set_index(x_col)["bfi"]
            if l.empty or r.empty:
                continue
            joined = pd.concat([l.rename("l"), r.rename("r")], axis=1).dropna()
            ai = (joined["l"] - joined["r"]) / (joined["l"] + joined["r"])
            ai_traces.append(ai)
        if not ai_traces:
            continue
        avg = pd.concat(ai_traces, axis=1).mean(axis=1)
        ax.plot(avg.index, avg.values, label=label, linewidth=1.5)

    ax.axhline(0.0, color="gray", linewidth=0.5)
    ax.set_xlabel(x_label)
    ax.set_ylabel("Asymmetry (L − R) / (L + R)")
    ax.set_title("Left/right BFI asymmetry — sustained non-zero is the stroke signal")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, alpha=STYLE["grid_alpha"])
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Cardiac-band PSD
# ---------------------------------------------------------------------------

def plot_cardiac_psd(
    corrected_long: pd.DataFrame,
    *,
    fs: float = FRAME_RATE_HZ,
    band_hz: tuple[float, float] = (0.5, 3.0),
) -> tuple[plt.Figure, dict[str, float]]:
    """
    Welch PSD of each camera's BFI trace, with cardiac band highlighted.
    Returns (figure, heart_rate_estimates_bpm_per_camera).
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    bpm_estimates: dict[str, float] = {}

    for (side, cam), g in corrected_long.groupby(["side", "cam"]):
        bfi = g.dropna(subset=["bfi"])["bfi"].to_numpy()
        if bfi.size < 128:
            continue
        # Detrend.
        bfi = bfi - np.mean(bfi)
        nperseg = min(256, len(bfi))
        f, P = welch(bfi, fs=fs, nperseg=nperseg)
        ax.semilogy(f, P, label=f"{side[0].upper()}{cam}", alpha=0.7, linewidth=0.8)

        band_mask = (f >= band_hz[0]) & (f <= band_hz[1])
        if band_mask.any() and P[band_mask].size > 0:
            peak_f = float(f[band_mask][P[band_mask].argmax()])
            bpm_estimates[f"{side[0].upper()}{cam}"] = peak_f * 60.0

    ax.axvspan(band_hz[0], band_hz[1], color="red", alpha=0.1, label="cardiac band")
    ax.set_xlim(0, 5)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD of BFI")
    ax.set_title("Cardiac-band spectrum of BFI (~1 Hz ≈ 60 bpm)")
    ax.grid(True, alpha=STYLE["grid_alpha"])
    ax.legend(fontsize=7, loc="upper right", ncol=2)
    fig.tight_layout()
    return fig, bpm_estimates


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

_TEMP_COLS = ("tcm", "tcl", "pdc")
_TEC_COLS = ("tec_v_raw", "tec_set_raw", "tec_curr_raw", "tec_volt_raw")
_FLAG_COLS = ("tec_good", "safety_se", "safety_so", "safety_ok", "read_ok")


def plot_telemetry(telemetry: pd.DataFrame, *, title: str = "Console telemetry") -> plt.Figure:
    """Five-panel view of console health."""
    fig = plt.figure(figsize=(14, 16))
    fig.suptitle(title, fontsize=12, y=0.995)
    gs = gridspec.GridSpec(5, 1, figure=fig, hspace=0.4, top=0.96, bottom=0.04)

    t = telemetry["t"]

    # 1. Temperatures
    ax1 = fig.add_subplot(gs[0])
    for col in _TEMP_COLS:
        if col in telemetry:
            ax1.plot(t, telemetry[col], label=col, linewidth=1.5)
    ax1.set_title("Temperatures")
    ax1.set_ylabel("Raw / °C")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=STYLE["grid_alpha"])

    # 2. TEC
    ax2 = fig.add_subplot(gs[1])
    for col in _TEC_COLS:
        if col in telemetry:
            ax2.plot(t, telemetry[col], label=col, linewidth=1.2)
    ax2.set_title("TEC (laser cooler)")
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=STYLE["grid_alpha"])

    # 3. PDU voltages
    ax3 = fig.add_subplot(gs[2])
    for i in range(16):
        col = f"pdu_volt_{i}"
        if col in telemetry:
            ax3.plot(t, telemetry[col], linewidth=0.7)
    ax3.set_title("Power Distribution Unit — 16 channel voltages")
    ax3.set_ylabel("Volts")
    ax3.grid(True, alpha=STYLE["grid_alpha"])

    # 4. PDU raw
    ax4 = fig.add_subplot(gs[3])
    for i in range(16):
        col = f"pdu_raw_{i}"
        if col in telemetry:
            ax4.plot(t, telemetry[col], linewidth=0.7)
    ax4.set_title("PDU raw ADC counts")
    ax4.set_ylabel("Counts")
    ax4.grid(True, alpha=STYLE["grid_alpha"])

    # 5. Flags
    ax5 = fig.add_subplot(gs[4])
    for col in _FLAG_COLS:
        if col in telemetry:
            ax5.plot(t, telemetry[col], label=col, marker=".", linestyle="-", linewidth=0.8)
    ax5.set_title("Safety and health flags (1 = healthy)")
    ax5.set_xlabel("Time (s)")
    ax5.set_ylabel("Flag")
    ax5.set_ylim(-0.1, 1.1)
    ax5.legend(loc="upper right", fontsize=8)
    ax5.grid(True, alpha=STYLE["grid_alpha"])

    return fig


# ---------------------------------------------------------------------------
# Convenience writers
# ---------------------------------------------------------------------------

def save_figure(fig: plt.Figure, output_path: str | Path, *, dpi: int = 140) -> Path:
    """Save a figure with consistent DPI. Returns the absolute path."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out.resolve()
