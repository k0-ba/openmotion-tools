"""
One-PNG scan summary card for Open-Motion scans.

Combines the key at-a-glance metrics into a single shareable image:
- Subject, timestamp, duration
- Per-camera mean BFI and BVI (bar chart in physical layout)
- Left/right asymmetry index over time (one trace per row pair)
- Cardiac-band heart-rate estimates (histogram across cameras)
- Data quality badges (frames dropped, calibration status, telemetry flags)

Usage
-----
    from scripts.io import load_corrected, load_telemetry
    from scripts.summary import generate_scan_card

    corrected = load_corrected("scan_S001_corrected.csv")
    telemetry = load_telemetry("scan_S001_telemetry.csv")
    generate_scan_card(corrected, telemetry, output_png="/mnt/user-data/outputs/card.png",
                        subject_id="S001", scan_timestamp="2025-12-17 16:09")
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
    SENSOR_COL_OFFSET,
    SIDES,
    STYLE,
)


def _estimate_heart_rate(bfi: np.ndarray, fs: float = FRAME_RATE_HZ) -> float | None:
    """Return cardiac-band peak in bpm, or None if series is too short."""
    bfi = bfi[~np.isnan(bfi)]
    if bfi.size < 128:
        return None
    bfi = bfi - bfi.mean()
    nperseg = min(256, len(bfi))
    f, P = welch(bfi, fs=fs, nperseg=nperseg)
    band = (f >= 0.5) & (f <= 3.0)
    if not band.any() or P[band].size == 0:
        return None
    peak_f = float(f[band][P[band].argmax()])
    return peak_f * 60.0


def generate_scan_card(
    corrected_long: pd.DataFrame,
    telemetry: pd.DataFrame | None = None,
    *,
    output_png: str | Path,
    subject_id: str = "(unknown)",
    scan_timestamp: str = "",
    dpi: int = 150,
) -> Path:
    """
    Generate a one-page PNG summary card.

    Parameters
    ----------
    corrected_long : long-format corrected DataFrame (from io.load_corrected)
    telemetry      : optional telemetry DataFrame (from io.load_telemetry)
    output_png     : where to write the PNG
    subject_id     : will be shown in the header
    scan_timestamp : free-form date/time string for the header
    """
    output = Path(output_png)
    output.parent.mkdir(parents=True, exist_ok=True)

    x_col = "timestamp_s" if "timestamp_s" in corrected_long.columns else "logical_frame_id"
    x_label = "Time (s)" if x_col == "timestamp_s" else "Frame"

    fig = plt.figure(figsize=(13, 10))
    gs = gridspec.GridSpec(
        4, 3, figure=fig, hspace=0.55, wspace=0.35,
        top=0.92, bottom=0.06, left=0.07, right=0.97,
    )

    # ------------------ Header ------------------
    duration = _scan_duration(corrected_long, x_col)
    header_text = (
        f"Open-Motion scan summary  —  Subject: {subject_id}  "
        f"{'•  ' + scan_timestamp if scan_timestamp else ''}"
        f"  •  Duration: {duration:.1f} s"
    )
    fig.suptitle(header_text, fontsize=12, fontweight="bold", y=0.97)

    # ------------------ Panel 1: Per-camera mean BFI bar chart ------------------
    ax1 = fig.add_subplot(gs[0, :])
    _panel_bar_means(ax1, corrected_long)

    # ------------------ Panel 2: Asymmetry over time ------------------
    ax2 = fig.add_subplot(gs[1, :])
    _panel_asymmetry(ax2, corrected_long, x_col, x_label)

    # ------------------ Panel 3: Heart-rate estimates ------------------
    ax3 = fig.add_subplot(gs[2, 0])
    _panel_heart_rates(ax3, corrected_long)

    # ------------------ Panel 4: Spatial BFI heatmap (mean over scan) ------------------
    ax4 = fig.add_subplot(gs[2, 1])
    _panel_spatial_heatmap(ax4, corrected_long)

    # ------------------ Panel 5: Quality badges ------------------
    ax5 = fig.add_subplot(gs[2, 2])
    _panel_quality(ax5, corrected_long, telemetry)

    # ------------------ Panel 6: Spaghetti BFI ------------------
    ax6 = fig.add_subplot(gs[3, :])
    _panel_spaghetti(ax6, corrected_long, x_col, x_label)

    fig.savefig(output, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output.resolve()


# ---------------------------------------------------------------------------
# Panel helpers
# ---------------------------------------------------------------------------

def _scan_duration(df: pd.DataFrame, x_col: str) -> float:
    alive = df.dropna(subset=["bfi"])
    if alive.empty:
        return 0.0
    span = alive[x_col].max() - alive[x_col].min()
    if x_col == "logical_frame_id":
        span = span / FRAME_RATE_HZ
    return float(span)


def _panel_bar_means(ax: plt.Axes, df: pd.DataFrame) -> None:
    ax.set_title("Mean BFI (black) and BVI (red) per camera", fontsize=10)
    alive = df.dropna(subset=["bfi"])
    means = (
        alive.groupby(["side", "cam"])[["bfi", "bvi"]]
        .mean()
        .reset_index()
    )
    if means.empty:
        ax.text(0.5, 0.5, "no data", ha="center", va="center")
        ax.axis("off"); return

    means["label"] = means["side"].str[0].str.upper() + means["cam"].astype(str)
    # Sort by physical position for readability.
    means["row"] = means["cam"].map(lambda c: CAMERA_GRID_POS[c][0])
    means["col"] = means.apply(
        lambda r: CAMERA_GRID_POS[int(r["cam"])][1] + SENSOR_COL_OFFSET[r["side"]],
        axis=1,
    )
    means = means.sort_values(["col", "row"]).reset_index(drop=True)

    x = np.arange(len(means))
    w = 0.35
    ax.bar(x - w / 2, means["bfi"], width=w, color=STYLE["bfi_color"], label="BFI")

    if "bvi" in means.columns and means["bvi"].notna().any():
        ax2 = ax.twinx()
        ax2.bar(x + w / 2, means["bvi"], width=w, color=STYLE["bvi_color"], alpha=0.9, label="BVI")
        ax2.set_ylabel("BVI", color=STYLE["bvi_color"])
        ax2.tick_params(axis="y", colors=STYLE["bvi_color"])

    ax.set_xticks(x)
    ax.set_xticklabels(means["label"], fontsize=8)
    ax.set_ylabel("BFI")
    ax.grid(True, alpha=STYLE["grid_alpha"], axis="y")


def _panel_asymmetry(ax: plt.Axes, df: pd.DataFrame, x_col: str, x_label: str) -> None:
    ax.set_title("Left / right BFI asymmetry index  ((L − R) / (L + R))", fontsize=10)
    ax.axhline(0.0, color="gray", linewidth=0.5)
    ax.grid(True, alpha=STYLE["grid_alpha"])

    row_pairs = [
        ("Row 0", [(1, 1), (8, 8)]),
        ("Row 1", [(2, 2), (7, 7)]),
        ("Row 2", [(3, 3), (6, 6)]),
        ("Row 3", [(4, 4), (5, 5)]),
    ]
    any_drawn = False
    for label, pairs in row_pairs:
        traces = []
        for cam_l, cam_r in pairs:
            l = df[(df["side"] == "left") & (df["cam"] == cam_l)].set_index(x_col)["bfi"]
            r = df[(df["side"] == "right") & (df["cam"] == cam_r)].set_index(x_col)["bfi"]
            if l.empty or r.empty:
                continue
            j = pd.concat([l.rename("l"), r.rename("r")], axis=1).dropna()
            ai = (j["l"] - j["r"]) / (j["l"] + j["r"])
            traces.append(ai)
        if not traces:
            continue
        avg = pd.concat(traces, axis=1).mean(axis=1)
        ax.plot(avg.index, avg.values, label=label, linewidth=1.4)
        any_drawn = True

    if not any_drawn:
        ax.text(0.5, 0.5, "no L/R pairs with data", ha="center", va="center", transform=ax.transAxes)
        return

    ax.set_xlabel(x_label)
    ax.set_ylabel("AI")
    ax.legend(fontsize=8, loc="best")


def _panel_heart_rates(ax: plt.Axes, df: pd.DataFrame) -> None:
    ax.set_title("Cardiac rate estimates across cameras", fontsize=10)
    bpms = []
    for (_, _), g in df.groupby(["side", "cam"]):
        bfi = g.dropna(subset=["bfi"])["bfi"].to_numpy()
        bpm = _estimate_heart_rate(bfi)
        if bpm is not None:
            bpms.append(bpm)

    if not bpms:
        ax.text(0.5, 0.5, "scan too short\nfor cardiac extraction",
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
        ax.axis("off"); return

    bpms = np.array(bpms)
    ax.hist(bpms, bins=np.arange(30, 180, 5), color=STYLE["bfi_color"], alpha=0.8)
    ax.axvline(np.median(bpms), color=STYLE["bvi_color"], linestyle="--",
               label=f"median {np.median(bpms):.1f} bpm")
    ax.set_xlabel("bpm")
    ax.set_ylabel("cameras")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=STYLE["grid_alpha"], axis="y")


def _panel_spatial_heatmap(ax: plt.Axes, df: pd.DataFrame) -> None:
    ax.set_title("Mean BFI heatmap (physical layout)", fontsize=10)
    means = (
        df.dropna(subset=["bfi"])
        .groupby(["side", "cam"])["bfi"].mean()
        .reset_index()
    )
    mat = np.full((4, 4), np.nan)
    labels = np.full((4, 4), "", dtype=object)
    for _, row in means.iterrows():
        r, sensor_col = CAMERA_GRID_POS[int(row["cam"])]
        c = sensor_col + SENSOR_COL_OFFSET[row["side"]]
        mat[r, c] = row["bfi"]
        labels[r, c] = f"{row['side'][0].upper()}{int(row['cam'])}"

    if np.isnan(mat).all():
        ax.text(0.5, 0.5, "no data", ha="center", va="center")
        ax.axis("off"); return

    vmin, vmax = np.nanpercentile(mat, [5, 95])
    if vmin == vmax:
        vmin, vmax = 0, 10
    im = ax.imshow(mat, cmap="viridis", vmin=vmin, vmax=vmax, aspect="auto")

    for r in range(4):
        for c in range(4):
            if labels[r, c]:
                ax.text(c, r, f"{labels[r, c]}\n{mat[r, c]:.2f}",
                        ha="center", va="center", fontsize=8, color="white",
                        fontweight="bold")

    ax.set_xticks([0.5, 2.5])
    ax.set_xticklabels(["LEFT", "RIGHT"], fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks([])
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="BFI")


def _panel_quality(ax: plt.Axes, corrected: pd.DataFrame, telemetry: pd.DataFrame | None) -> None:
    ax.set_title("Quality flags", fontsize=10)
    ax.axis("off")

    flags: list[tuple[str, str, str]] = []

    # Active camera count
    active = corrected.dropna(subset=["bfi"]).groupby(["side", "cam"]).size().reset_index()
    n_active = len(active)
    flags.append((
        f"{n_active}/16 cameras active",
        "green" if n_active >= 14 else "orange" if n_active >= 8 else "red",
        "",
    ))

    # Scan has enough darks?
    if "logical_frame_id" in corrected.columns:
        n_frames = corrected["logical_frame_id"].nunique()
        flags.append((
            f"{n_frames} corrected frames",
            "green" if n_frames > 600 else "orange",
            f"~{n_frames / FRAME_RATE_HZ:.0f}s scan",
        ))

    # Telemetry flags
    if telemetry is not None and not telemetry.empty:
        tflags = ("tec_good", "safety_ok", "read_ok")
        for fn in tflags:
            if fn in telemetry.columns:
                ok_frac = (telemetry[fn] >= 0.5).mean()
                color = "green" if ok_frac > 0.99 else "orange" if ok_frac > 0.9 else "red"
                flags.append((f"{fn}: {ok_frac * 100:.1f}%", color, ""))

    # Render.
    y = 0.95
    for text, color, sub in flags:
        ax.text(0.02, y, "●", color=color, fontsize=14, transform=ax.transAxes, va="top")
        ax.text(0.10, y, text, fontsize=10, transform=ax.transAxes, va="top")
        if sub:
            ax.text(0.10, y - 0.05, sub, fontsize=8, color="gray", transform=ax.transAxes, va="top")
            y -= 0.14
        else:
            y -= 0.09


def _panel_spaghetti(ax: plt.Axes, df: pd.DataFrame, x_col: str, x_label: str) -> None:
    ax.set_title("All BFI traces (spaghetti view, black=left • red=right)", fontsize=10)
    ax.grid(True, alpha=STYLE["grid_alpha"])

    for (side, cam), g in df.groupby(["side", "cam"]):
        color = STYLE["bfi_color"] if side == "left" else STYLE["bvi_color"]
        sub = g.dropna(subset=["bfi"])
        if sub.empty:
            continue
        ax.plot(sub[x_col], sub["bfi"], color=color, alpha=0.4, linewidth=0.7)

    ax.set_xlabel(x_label)
    ax.set_ylabel("BFI")
