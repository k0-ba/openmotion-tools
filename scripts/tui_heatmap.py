#!/usr/bin/env python3
"""
tui_heatmap.py — live terminal heatmap for Open-Motion scans.

No AI. No agent. No network. No dependencies beyond the Python 3.10+ stdlib.
Just read the corrected CSV the SDK is writing and paint per-camera BFI as
ANSI blocks in a 4x2 grid that mirrors the physical sensor layout.

Usage:
    python3 scripts/tui_heatmap.py path/to/scan_corrected.csv
    python3 scripts/tui_heatmap.py path/to/scan_corrected.csv --watch
    python3 scripts/tui_heatmap.py path/to/scan_corrected.csv --window 40  # last N frames

Controls (in --watch mode):
    Ctrl-C   quit.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

# Physical camera grid: 4 rows x 2 cols per hemisphere, 1-indexed (cam 1..8).
# Row 0 is forehead, row 3 is back (see openwater-research.md §6 / CameraArrangement.md).
GRID_ROWS, GRID_COLS = 4, 2
CAM_ORDER = [1, 2, 3, 4, 5, 6, 7, 8]  # top-to-bottom, inner-to-outer

# Viridis-ish 24-bit ANSI ramp, dark -> bright.
RAMP = [
    (68, 1, 84), (72, 35, 116), (64, 67, 135), (52, 94, 141),
    (41, 120, 142), (32, 144, 140), (34, 167, 132), (68, 190, 112),
    (121, 209, 81), (189, 222, 38), (253, 231, 36),
]
BLOCK = "██"  # two chars wide so each cell is visually square-ish in most terminals
RESET = "\x1b[0m"
CLEAR = "\x1b[2J\x1b[H"


def shade(v: float, lo: float, hi: float) -> str:
    """Return an ANSI-colored 2-char block for v in [lo, hi]."""
    if hi <= lo or v != v:  # NaN-safe
        r, g, b = 40, 40, 40
    else:
        t = max(0.0, min(1.0, (v - lo) / (hi - lo)))
        idx = min(len(RAMP) - 1, int(t * (len(RAMP) - 1) + 0.5))
        r, g, b = RAMP[idx]
    return f"\x1b[38;2;{r};{g};{b}m{BLOCK}{RESET}"


def load_bfi(path: Path, window: int) -> tuple[dict, dict, float, float]:
    """Read CSV, return (left_cam -> mean_bfi, right_cam -> mean_bfi, lo, hi)."""
    left: dict[int, list[float]] = {c: [] for c in CAM_ORDER}
    right: dict[int, list[float]] = {c: [] for c in CAM_ORDER}
    with path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    rows = rows[-window:] if window > 0 else rows
    for row in rows:
        for c in CAM_ORDER:
            for side, bucket in (("l", left), ("r", right)):
                key = f"bfi_{side}{c}"
                if key in row and row[key]:
                    try:
                        bucket[c].append(float(row[key]))
                    except ValueError:
                        pass
    lmean = {c: (sum(v) / len(v)) if v else float("nan") for c, v in left.items()}
    rmean = {c: (sum(v) / len(v)) if v else float("nan") for c, v in right.items()}
    all_vals = [v for v in list(lmean.values()) + list(rmean.values()) if v == v]
    lo, hi = (min(all_vals), max(all_vals)) if all_vals else (0.0, 1.0)
    return lmean, rmean, lo, hi


def render(path: Path, window: int) -> str:
    left, right, lo, hi = load_bfi(path, window)
    out = []
    out.append(f"Open-Motion live heatmap  —  {path.name}  "
               f"(BFI, last {window} frames)   range [{lo:.3f}, {hi:.3f}]")
    out.append("")
    out.append("           LEFT              RIGHT")
    for row in range(GRID_ROWS):
        line_l, line_r = [], []
        for col in range(GRID_COLS):
            cam = CAM_ORDER[row * GRID_COLS + col]
            line_l.append(shade(left[cam], lo, hi))
            line_r.append(shade(right[cam], lo, hi))
        out.append(f"  row {row}:  " + " ".join(line_l) + "     " + " ".join(line_r))
    out.append("")
    out.append("  low " + "".join(shade(lo + (hi - lo) * i / 10, lo, hi) for i in range(11)) + " high")
    out.append("")
    out.append("  no ai. no agent. no network. just ansi blocks and numpy-free arithmetic.")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", type=Path, help="scan_corrected.csv written by the SDK")
    p.add_argument("--watch", action="store_true", help="redraw every second until Ctrl-C")
    p.add_argument("--window", type=int, default=40, help="average over last N frames (default: 40 ≈ 1 s at 40 Hz)")
    args = p.parse_args()
    if not args.csv.exists():
        print(f"not found: {args.csv}", file=sys.stderr)
        return 1
    try:
        while True:
            frame = render(args.csv, args.window)
            if args.watch:
                sys.stdout.write(CLEAR)
            sys.stdout.write(frame + "\n")
            sys.stdout.flush()
            if not args.watch:
                return 0
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
