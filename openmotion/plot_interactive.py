"""
Interactive Plotly dashboard for Open-Motion scans.

Produces a single self-contained HTML file with multiple tabs:
  - Overview:   4x4 grid of BFI/BVI time series, mirroring physical layout
  - Asymmetry:  left/right asymmetry index per row pair
  - Spectral:   Welch PSD of each camera's BFI, cardiac band highlighted
  - Spatial:    animated 4x4 heatmap of BFI over time

The HTML is fully client-side renderable — data is embedded. File sizes are
typically 1-5 MB depending on scan length.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import welch

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

from .constants import (
    CAMERA_GRID_POS,
    FRAME_RATE_HZ,
    SENSOR_COL_OFFSET,
    SIDES,
    STYLE,
)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_dashboard(
    corrected_long: pd.DataFrame,
    output_html: str | Path,
    *,
    title: str = "Open-Motion scan dashboard",
) -> Path:
    """
    Build a single-HTML interactive dashboard from a long-format corrected DataFrame.

    The returned file is a self-contained HTML with embedded data and the Plotly.js
    library; it opens in any browser.
    """
    output_path = Path(output_html)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    x_col = "timestamp_s" if "timestamp_s" in corrected_long.columns else "logical_frame_id"
    x_label = "Time (s)" if x_col == "timestamp_s" else "Frame"

    # Build each figure.
    overview_html = _overview_panel(corrected_long, x_col, x_label)
    asymmetry_html = _asymmetry_panel(corrected_long, x_col, x_label)
    spectral_html = _spectral_panel(corrected_long)
    spatial_html = _spatial_panel(corrected_long, x_col, x_label)

    # Stitch into a tabbed page.
    html = _render_tabs(title, [
        ("Overview (BFI & BVI)", overview_html),
        ("Left / Right asymmetry", asymmetry_html),
        ("Cardiac spectrum", spectral_html),
        ("Spatial heatmap", spatial_html),
    ])

    output_path.write_text(html, encoding="utf-8")
    return output_path.resolve()


# ---------------------------------------------------------------------------
# Overview panel — 4x4 BFI/BVI grid
# ---------------------------------------------------------------------------

def _overview_panel(df: pd.DataFrame, x_col: str, x_label: str) -> str:
    # Find active cameras and collapse grid.
    cells: list[tuple[int, int, str, int]] = []
    alive = df.dropna(subset=["bfi"])
    for side in SIDES:
        for cam in range(1, 9):
            if not ((alive["side"] == side) & (alive["cam"] == cam)).any():
                continue
            grid_row, sensor_col = CAMERA_GRID_POS[cam]
            plot_col = sensor_col + SENSOR_COL_OFFSET[side]
            cells.append((grid_row, plot_col, side, cam))

    if not cells:
        return "<p>No active cameras in this scan.</p>"

    active_rows = sorted({c[0] for c in cells})
    active_cols = sorted({c[1] for c in cells})
    row_map = {r: i for i, r in enumerate(active_rows)}
    col_map = {c: i for i, c in enumerate(active_cols)}
    n_rows, n_cols = len(active_rows), len(active_cols)

    subplot_titles = [""] * (n_rows * n_cols)
    for (grid_row, plot_col, side, cam) in cells:
        r, c = row_map[grid_row], col_map[plot_col]
        subplot_titles[r * n_cols + c] = f"{side[0].upper()} cam {cam}"

    fig = make_subplots(
        rows=n_rows, cols=n_cols,
        subplot_titles=subplot_titles,
        shared_xaxes=True,
        horizontal_spacing=0.04,
        vertical_spacing=0.08,
        specs=[[{"secondary_y": True} for _ in range(n_cols)] for _ in range(n_rows)],
    )

    for (grid_row, plot_col, side, cam) in cells:
        r, c = row_map[grid_row] + 1, col_map[plot_col] + 1
        sub = df[(df["side"] == side) & (df["cam"] == cam)].dropna(subset=["bfi"])
        if sub.empty:
            continue

        # BFI (primary axis, black)
        fig.add_trace(
            go.Scatter(
                x=sub[x_col], y=sub["bfi"],
                name=f"BFI {side[0].upper()}{cam}",
                mode="lines",
                line=dict(color=STYLE["bfi_color"], width=2),
                showlegend=False,
                hovertemplate="BFI %{y:.2f}<extra></extra>",
            ),
            row=r, col=c, secondary_y=False,
        )

        # BVI (secondary axis, red)
        if "bvi" in sub.columns and sub["bvi"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=sub[x_col], y=sub["bvi"],
                    name=f"BVI {side[0].upper()}{cam}",
                    mode="lines",
                    line=dict(color=STYLE["bvi_color"], width=1),
                    showlegend=False,
                    hovertemplate="BVI %{y:.2f}<extra></extra>",
                ),
                row=r, col=c, secondary_y=True,
            )

    fig.update_layout(
        height=220 * n_rows + 80,
        title="BFI (black, left axis) and BVI (red, right axis) — physical layout",
        hovermode="x unified",
        margin=dict(l=60, r=60, t=80, b=60),
    )
    fig.update_xaxes(title_text=x_label, row=n_rows)
    for i in range(n_rows):
        fig.update_yaxes(title_text="BFI", col=1, row=i + 1, secondary_y=False)
        fig.update_yaxes(
            title_text="BVI", col=n_cols, row=i + 1,
            secondary_y=True, color=STYLE["bvi_color"],
        )

    return pio.to_html(
        fig, include_plotlyjs="cdn", full_html=False, div_id="overview-panel",
    )


# ---------------------------------------------------------------------------
# Asymmetry panel
# ---------------------------------------------------------------------------

_ROW_PAIRS = [
    ("Row 0 (top, C1 & C8)", [(1, 1), (8, 8)]),
    ("Row 1 (C2 & C7)",       [(2, 2), (7, 7)]),
    ("Row 2 (C3 & C6)",       [(3, 3), (6, 6)]),
    ("Row 3 (bottom, C4 & C5)", [(4, 4), (5, 5)]),
]


def _asymmetry_panel(df: pd.DataFrame, x_col: str, x_label: str) -> str:
    fig = go.Figure()
    for label, pairs in _ROW_PAIRS:
        traces = []
        for cam_l, cam_r in pairs:
            left = df[(df["side"] == "left") & (df["cam"] == cam_l)].set_index(x_col)["bfi"]
            right = df[(df["side"] == "right") & (df["cam"] == cam_r)].set_index(x_col)["bfi"]
            if left.empty or right.empty:
                continue
            joined = pd.concat([left.rename("l"), right.rename("r")], axis=1).dropna()
            ai = (joined["l"] - joined["r"]) / (joined["l"] + joined["r"])
            traces.append(ai)
        if not traces:
            continue
        avg = pd.concat(traces, axis=1).mean(axis=1)
        fig.add_trace(go.Scatter(
            x=avg.index, y=avg.values,
            mode="lines", name=label, line=dict(width=2),
            hovertemplate="AI %{y:+.3f}<extra>%{fullData.name}</extra>",
        ))

    fig.add_hline(y=0.0, line_width=1, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Left-right BFI asymmetry — sustained non-zero is the clinical signal",
        xaxis_title=x_label,
        yaxis_title="(L − R) / (L + R)",
        height=520,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.05, x=0),
    )
    return pio.to_html(fig, include_plotlyjs=False, full_html=False, div_id="asymmetry-panel")


# ---------------------------------------------------------------------------
# Spectral panel
# ---------------------------------------------------------------------------

def _spectral_panel(df: pd.DataFrame) -> str:
    fig = go.Figure()
    bpm_summary: list[str] = []

    for (side, cam), g in df.groupby(["side", "cam"]):
        bfi = g.dropna(subset=["bfi"])["bfi"].to_numpy()
        if bfi.size < 128:
            continue
        bfi = bfi - bfi.mean()
        nperseg = min(256, len(bfi))
        f, P = welch(bfi, fs=FRAME_RATE_HZ, nperseg=nperseg)
        name = f"{side[0].upper()}{cam}"
        fig.add_trace(go.Scatter(
            x=f, y=P, mode="lines", name=name,
            line=dict(width=1),
            hovertemplate=f"{name}<br>f %{{x:.2f}} Hz<br>P %{{y:.2e}}<extra></extra>",
        ))

        band = (f >= 0.5) & (f <= 3.0)
        if band.any() and P[band].size:
            peak_f = float(f[band][P[band].argmax()])
            bpm_summary.append(f"{name}: {peak_f * 60:.1f} bpm")

    fig.update_layout(
        title="Welch PSD of BFI — cardiac band 0.5-3.0 Hz highlighted",
        xaxis=dict(title="Frequency (Hz)", range=[0, 5]),
        yaxis=dict(title="PSD", type="log"),
        height=540,
        shapes=[dict(
            type="rect", xref="x", yref="paper",
            x0=0.5, x1=3.0, y0=0, y1=1,
            fillcolor="red", opacity=0.08, line_width=0,
        )],
        hovermode="closest",
        legend=dict(font=dict(size=9)),
    )
    html = pio.to_html(fig, include_plotlyjs=False, full_html=False, div_id="spectral-panel")

    if bpm_summary:
        html += "<h3>Per-camera heart-rate estimates</h3><pre style='font-family:monospace'>"
        html += "\n".join(bpm_summary)
        html += "</pre>"
    return html


# ---------------------------------------------------------------------------
# Spatial heatmap (animated)
# ---------------------------------------------------------------------------

def _spatial_panel(df: pd.DataFrame, x_col: str, x_label: str) -> str:
    """
    Build a 4x4 animated heatmap: rows = physical grid row, cols = [L-L-R-R] columns,
    cell color = BFI at each time step. Animation slider over the time axis.

    Subsample to at most ~120 frames so the HTML stays reasonable.
    """
    alive = df.dropna(subset=["bfi"])
    if alive.empty:
        return "<p>No BFI data to animate.</p>"

    frames = sorted(alive[x_col].unique())
    if len(frames) > 120:
        idx = np.linspace(0, len(frames) - 1, 120).astype(int)
        frames = [frames[i] for i in idx]

    # Layout: 4 physical rows x 4 plot columns. Map (side, cam) -> (row, col).
    def cell_for(side: str, cam: int) -> tuple[int, int]:
        row, sensor_col = CAMERA_GRID_POS[cam]
        return row, sensor_col + SENSOR_COL_OFFSET[side]

    n_rows, n_cols = 4, 4
    labels = np.full((n_rows, n_cols), "", dtype=object)
    for side in SIDES:
        for cam in range(1, 9):
            r, c = cell_for(side, cam)
            labels[r, c] = f"{side[0].upper()}{cam}"

    # Build per-frame matrices.
    matrices = []
    for t in frames:
        snap = alive[alive[x_col] == t]
        mat = np.full((n_rows, n_cols), np.nan)
        for _, row in snap.iterrows():
            r, c = cell_for(row["side"], int(row["cam"]))
            mat[r, c] = row["bfi"]
        matrices.append(mat)

    # Color scale: BFI is 0-10 nominally, but clip to observed range for contrast.
    all_vals = np.concatenate([m.flatten() for m in matrices])
    vmin, vmax = np.nanpercentile(all_vals, [5, 95])
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
        vmin, vmax = 0, 10

    initial = matrices[0]
    heatmap = go.Heatmap(
        z=initial,
        text=labels,
        texttemplate="%{text}",
        textfont={"size": 11, "color": "white"},
        colorscale="Viridis",
        zmin=vmin, zmax=vmax,
        colorbar=dict(title="BFI"),
        xgap=2, ygap=2,
    )

    fig = go.Figure(
        data=[heatmap],
        layout=go.Layout(
            title="Spatial BFI heatmap — physical camera layout (L | R)",
            yaxis=dict(autorange="reversed", showticklabels=False),
            xaxis=dict(showticklabels=False,
                       tickvals=[0.5, 2.5],
                       ticktext=["LEFT", "RIGHT"],
                       side="top"),
            height=520,
            updatemenus=[dict(
                type="buttons",
                buttons=[
                    dict(label="Play",
                         method="animate",
                         args=[None, {"frame": {"duration": 100, "redraw": True},
                                      "fromcurrent": True}]),
                    dict(label="Pause",
                         method="animate",
                         args=[[None], {"frame": {"duration": 0, "redraw": False},
                                        "mode": "immediate"}]),
                ],
            )],
            sliders=[dict(
                steps=[
                    dict(method="animate",
                         args=[[f"f{i}"], {"mode": "immediate", "frame": {"duration": 0}}],
                         label=f"{frames[i]:.1f}")
                    for i in range(len(frames))
                ],
                currentvalue=dict(prefix=f"{x_label}: "),
            )],
        ),
        frames=[
            go.Frame(
                data=[go.Heatmap(
                    z=matrices[i], text=labels, texttemplate="%{text}",
                    textfont={"size": 11, "color": "white"},
                    colorscale="Viridis", zmin=vmin, zmax=vmax,
                )],
                name=f"f{i}",
            )
            for i in range(len(frames))
        ],
    )

    return pio.to_html(fig, include_plotlyjs=False, full_html=False, div_id="spatial-panel")


# ---------------------------------------------------------------------------
# HTML tab container
# ---------------------------------------------------------------------------

def _render_tabs(title: str, tabs: list[tuple[str, str]]) -> str:
    """Render a simple tabbed HTML page containing the provided tab HTML fragments."""
    tab_buttons = "".join(
        f'<button class="tab-btn" onclick="showTab({i})">{name}</button>'
        for i, (name, _) in enumerate(tabs)
    )
    tab_bodies = "".join(
        f'<div class="tab-body" id="tab-{i}" style="display:{"block" if i == 0 else "none"}">{body}</div>'
        for i, (_, body) in enumerate(tabs)
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0; padding: 0; background: #fafafa;
    }}
    header {{
      background: #111; color: #fff; padding: 16px 24px;
      font-weight: 600; font-size: 18px;
    }}
    .tab-bar {{ background: #eee; padding: 0 24px; border-bottom: 1px solid #ddd; }}
    .tab-btn {{
      background: none; border: 0; padding: 14px 18px; cursor: pointer;
      font-size: 14px; color: #444; border-bottom: 3px solid transparent;
    }}
    .tab-btn:hover {{ background: #e0e0e0; }}
    .tab-btn.active {{ color: #000; border-bottom-color: #c91f37; font-weight: 600; }}
    .tab-body {{ padding: 24px; }}
    h3 {{ margin-top: 24px; color: #333; }}
    pre {{ background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; }}
  </style>
</head>
<body>
  <header>{title}</header>
  <div class="tab-bar">{tab_buttons}</div>
  {tab_bodies}
  <script>
    function showTab(i) {{
      document.querySelectorAll(".tab-body").forEach((el, idx) => {{
        el.style.display = idx === i ? "block" : "none";
      }});
      document.querySelectorAll(".tab-btn").forEach((el, idx) => {{
        el.classList.toggle("active", idx === i);
      }});
    }}
    document.querySelector(".tab-btn").classList.add("active");
  </script>
</body>
</html>
"""
