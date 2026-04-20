# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

Public companion tooling for Openwater Health's **Open-Motion 3.0** wearable cerebral blood-flow monitor (NIR laser speckle contrast imaging). The upstream [`openmotion-sdk`](https://github.com/OpenwaterHealth/openmotion-sdk) handles device bring-up and capture; this repo handles everything downstream: offline dark-frame correction, the stock matplotlib plots, a Plotly dashboard, and a one-page QC summary card.

Target OS is **Linux** (Ubuntu 22.04/24.04, Fedora 40, Arch). Device capture is not supported on macOS by the SDK, but the analysis code runs anywhere.

### Layout

- `openmotion/` — Python package (`constants.py`, `io.py`, `pipeline.py`, `plot_static.py`, `plot_interactive.py`, `summary.py`). Ported from the research notes §9 skill spec; canonical constants live in `constants.py`.
- `docs/` — reference docs (science, data formats, viz patterns, setup/troubleshooting).
- `linux/` — `install.sh` + `99-openmotion.rules` (udev rule for VID `0483`).
- `examples/smoke_test.py` — post-install sanity check.
- `openwater-research.md` — compiled research notes that scaffolded this repo.
- A built copy of the Claude skill version lives at `~/.claude/skills/openmotion/` (outside the repo) and mirrors this package structure — keep them aligned when changing canonical constants or plot conventions.

### Build / test

```bash
pip install -e .               # or ./linux/install.sh for full Linux setup
python examples/smoke_test.py  # synthesizes fake frames and runs the pipeline end-to-end
```

No test suite yet. When adding code, keep imports relative within `openmotion/` and do not duplicate constants — always import from `openmotion.constants`.

## Canonical domain facts (use these verbatim; don't re-derive)

When generating code or answering questions about Open-Motion data, treat these as authoritative — they come from `openwater-research.md` §5–§6 and must be consistent across any skill code produced here:

- `EXPECTED_HISTOGRAM_SUM = 2_457_606` (1920×1280 + 6 sentinel). Frames with any other sum are **dropped**.
- `PEDESTAL_HEIGHT = 64.0` — subtracted from μ₁ before contrast.
- `NUM_BINS = 1024`; **bin 1023 is a sentinel — zero it before any analysis/plot.**
- `noise_floor = 10` — zero bins below this before computing moments.
- `discard_count = 9` warmup frames; `dark_interval = 600` (every 15 s at 40 Hz).
- `FRAME_ID_MODULUS = 256` — firmware frame_id is 8-bit; **unwrap before time series** (per `cam_id`).
- `CAMERA_GAIN_MAP = [16, 4, 2, 1, 1, 2, 4, 16]` (outer cams hotter).
- `ADC_GAIN ≈ 0.0873` DN/e⁻, used in shot-noise correction of variance.
- Left/right assignment is USB topology: `port_numbers[-1] == 2` → left, `== 3` → right.
- Physical camera grid is 4×2; `cam_id` in CSVs is 0–7 (channel), camera numbers in docs/plots are 1–8 (`channel = cam - 1`).
- Plot convention: subplot grid mirrors physical layout; BFI = solid black (left y-axis, lw=2), BVI = solid red (right y-axis, lw=1); spectrograms use `imshow`, `cmap="viridis"`, `aspect="auto"`, `origin="lower"`.

## Data file shapes

- Raw histogram CSV (per side): `frame_id, cam_id, total, bin_0..bin_1023` (+ optional `timestamp`, `temperature`).
- Corrected CSV (both sides combined): `frame_id, timestamp_s, bfi_l1..bfi_r8, bvi_l1..bvi_r8, mean_*, contrast_*, temp_*`. Naming is `{metric}_{l|r}{1..8}` (1-indexed camera).
- Telemetry CSV: console health (TEC, PDU, safety flags).

## External ground truth

The SDK itself lives at `github.com/OpenwaterHealth/openmotion-sdk`; its `docs/` folder (`SciencePipeline.md`, `Architecture.md`, `CameraArrangement.md`, etc.) is the authoritative manual. Prefer fetching from there over guessing when the research notes don't cover a detail.
