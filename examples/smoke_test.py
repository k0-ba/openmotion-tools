"""
Smoke test for the openmotion skill.

Generates a synthetic corrected CSV + telemetry CSV + raw histogram CSV and runs
every plot function. Fails loud if anything throws. Doesn't verify the plots are
scientifically correct — that's the human-review step.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make the scripts package importable under a namespace.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.io import load_corrected, load_raw, load_telemetry
from scripts.pipeline import PipelineConfig, apply_science_pipeline
from scripts.plot_static import (
    plot_asymmetry,
    plot_camera_spectrogram,
    plot_cardiac_psd,
    plot_grid_bfi_bvi,
    plot_moments_grid,
    plot_single_histogram,
    plot_spectrogram_grid,
    plot_telemetry,
    save_figure,
)
from scripts.plot_interactive import build_dashboard
from scripts.summary import generate_scan_card

OUT_DIR = Path("/tmp/openmotion-smoke")
OUT_DIR.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Fixture: synthetic corrected CSV
# ---------------------------------------------------------------------------

def make_corrected_csv() -> Path:
    """Wide-format corrected CSV for 16 cameras x ~30 seconds."""
    n = 1200
    frame_ids = np.arange(1, n + 1)
    t_s = frame_ids / 40.0
    cardiac = 0.5 * np.sin(2 * np.pi * 1.2 * t_s)
    trend = np.linspace(0, 0.2, n)

    cols = {"frame_id": frame_ids, "timestamp_s": t_s}
    for side_char in ("l", "r"):
        for cam in range(1, 9):
            phase = rng.uniform(0, np.pi)
            noise = rng.normal(0, 0.08, n)
            # Left cameras a bit higher BFI than right for a fake asymmetry.
            offset = 4.0 if side_char == "l" else 3.7
            bfi = offset + cardiac * np.cos(phase) + trend + noise
            cols[f"bfi_{side_char}{cam}"] = bfi
            cols[f"bvi_{side_char}{cam}"] = 5.0 + 0.5 * np.cos(2 * np.pi * 0.25 * t_s + phase) + rng.normal(0, 0.1, n)
            cols[f"mean_{side_char}{cam}"] = 300 + 10 * cardiac + rng.normal(0, 2, n)
            cols[f"contrast_{side_char}{cam}"] = 0.15 + 0.01 * cardiac + rng.normal(0, 0.002, n)
            cols[f"std_{side_char}{cam}"] = 5 + 0.2 * cardiac + rng.normal(0, 0.1, n)
            cols[f"temp_{side_char}{cam}"] = 28 + 0.1 * np.sin(2 * np.pi * 0.02 * t_s) + rng.normal(0, 0.01, n)

    df = pd.DataFrame(cols)
    path = OUT_DIR / "scan_TEST_20260101_corrected.csv"
    df.to_csv(path, index=False)
    return path


def make_telemetry_csv() -> Path:
    n = 60
    t0 = 1_750_000_000.0
    df = pd.DataFrame({
        "timestamp": t0 + np.arange(n),
        "tcm": 25 + rng.normal(0, 0.1, n),
        "tcl": 22 + rng.normal(0, 0.1, n),
        "pdc": 1500 + rng.normal(0, 5, n),
        "tec_v_raw": 1000 + rng.normal(0, 10, n),
        "tec_set_raw": 1010,
        "tec_curr_raw": 500 + rng.normal(0, 5, n),
        "tec_volt_raw": 2000 + rng.normal(0, 20, n),
        **{f"pdu_raw_{i}": 1000 + 100 * i + rng.normal(0, 5, n) for i in range(16)},
        **{f"pdu_volt_{i}": (1000 + 100 * i + rng.normal(0, 5, n)) * 0.001 for i in range(16)},
        "tec_good": np.ones(n, dtype=int),
        "safety_se": np.ones(n, dtype=int),
        "safety_so": np.ones(n, dtype=int),
        "safety_ok": np.ones(n, dtype=int),
        "read_ok": np.ones(n, dtype=int),
    })
    path = OUT_DIR / "scan_TEST_20260101_telemetry.csv"
    df.to_csv(path, index=False)
    return path


def make_raw_csv() -> Path:
    """A small raw CSV with 8 cameras x a handful of frames of fake histograms."""
    rows = []
    for cam_id in range(8):
        for frame_id in range(1, 30):
            hist = np.zeros(1024, dtype=np.int64)
            # Narrow peak around bin 300.
            peak_pos = 300 + rng.integers(-5, 5)
            hist[peak_pos - 20:peak_pos + 20] = rng.integers(800, 1500, 40)
            # Sentinel bin first, THEN top-up so total lands on EXPECTED.
            hist[1023] = 999
            hist[100] = max(0, 2_457_606 - int(hist.sum()))
            row = {
                "frame_id": frame_id % 256,
                "cam_id": cam_id,
                "total": int(hist.sum()),
                "temperature": 28 + rng.normal(0, 0.1),
            }
            for i in range(1024):
                row[str(i)] = int(hist[i])
            rows.append(row)
    df = pd.DataFrame(rows)
    path = OUT_DIR / "scan_TEST_20260101_left_maskFF.csv"
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Run the suite
# ---------------------------------------------------------------------------

def main() -> None:
    print("1) Making fixtures ...")
    corr_path = make_corrected_csv()
    tel_path = make_telemetry_csv()
    raw_path = make_raw_csv()
    print(f"   corrected: {corr_path}")
    print(f"   telemetry: {tel_path}")
    print(f"   raw:       {raw_path}")

    print("\n2) Loading ...")
    corrected = load_corrected(corr_path)
    print(f"   corrected (long): {len(corrected)} rows, cols = {list(corrected.columns)}")
    telemetry = load_telemetry(tel_path)
    print(f"   telemetry: {len(telemetry)} rows")
    raw = load_raw(raw_path)
    print(f"   raw: {len(raw)} rows (dropped invalid={raw.attrs.get('dropped_invalid_sum', 0)}, "
          f"warmup={raw.attrs.get('dropped_warmup', 0)})")

    print("\n3) Static plots ...")
    save_figure(plot_grid_bfi_bvi(corrected), OUT_DIR / "grid_bfi_bvi.png")
    save_figure(plot_asymmetry(corrected), OUT_DIR / "asymmetry.png")
    psd_fig, bpms = plot_cardiac_psd(corrected)
    save_figure(psd_fig, OUT_DIR / "cardiac_psd.png")
    print(f"   estimated heart rates: {bpms}")

    save_figure(plot_telemetry(telemetry), OUT_DIR / "telemetry.png")
    save_figure(plot_moments_grid(raw, side_label="LEFT"), OUT_DIR / "moments_grid.png")
    save_figure(plot_spectrogram_grid(raw, side_label="LEFT"), OUT_DIR / "spectrogram_grid.png")
    save_figure(plot_single_histogram(raw, cam_id=0, row_idx=0, style="line"),
                OUT_DIR / "single_histogram.png")
    save_figure(plot_camera_spectrogram(raw, cam_id=0), OUT_DIR / "camera_spectrogram.png")

    print("\n4) Interactive dashboard ...")
    dash = build_dashboard(corrected, OUT_DIR / "dashboard.html",
                           title="Open-Motion scan — TEST subject")
    print(f"   wrote {dash}  ({dash.stat().st_size / 1024:.0f} KB)")

    print("\n5) Summary card ...")
    card = generate_scan_card(corrected, telemetry, output_png=OUT_DIR / "scan_card.png",
                               subject_id="TEST", scan_timestamp="2026-01-01 12:00")
    print(f"   wrote {card}")

    print("\n6) Offline science pipeline ...")
    corrected_offline = apply_science_pipeline(raw, None, cfg=PipelineConfig(dark_interval=10))
    print(f"   reproduced corrected DataFrame: {len(corrected_offline)} rows, "
          f"cols = {list(corrected_offline.columns)[:8]}...")

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
