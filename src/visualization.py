#!/usr/bin/env python3
"""ETE3 phylogenetic tree rendering with per-leaf divergent bar charts.

This module is imported and re-imported in spawned child processes (see
`app.py::generate_tree_svg_cached`). All matplotlib output is rendered
into a per-render temporary directory passed down through the helpers
— there are no module-level path globals or shared `.tmp_bars/`
directory, so concurrent renders cannot stomp on each other's files.

Two backend pins fire at module import time, BEFORE either the
matplotlib or ete3-treeview names are touched:

- `matplotlib.use("Agg")` — so the same import works in the headless
  render subprocess (which must NOT pick a Qt backend or it conflicts
  with ETE3's QApplication) and in the Streamlit parent process (which
  never uses pyplot directly).
- `QT_QPA_PLATFORM=offscreen` — so `from ete3 import ImgFace, ...` below
  succeeds even when no DISPLAY is set. ete3's __init__ does
  `try: from .treeview import (..., ImgFace, ...)` wrapped in a bare
  except; a failed PyQt5 platform-plugin probe silently drops those
  names from the ete3 top-level namespace, and the import on the next
  line then raises ImportError. Setting the env var here keeps Streamlit
  Cloud (no DISPLAY) working. Subprocesses re-import this module on
  spawn, so the same setting fires there too — no duplicate inside
  `render_tree_in_process` is needed.
"""

import logging
import os

# Pin matplotlib backend BEFORE pyplot is imported. Must remain above
# `import matplotlib.pyplot as plt`.
import matplotlib

matplotlib.use("Agg")

# Pin Qt platform BEFORE the ete3 treeview import below — see module
# docstring for the failure mode this guards.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from ete3 import ImgFace, TextFace, TreeStyle  # noqa: E402

from src.ete_utils import get_ncbi  # noqa: E402
from src.metrics import CladeMetadata, METRICS, Metric  # noqa: E402

log = logging.getLogger("euka.visualization")

# Per-side light/dark lookup so the legend can name the four corners of
# the divergent bar chart without re-hardcoding the metric keys.
_BY_SIDE_AND_OVERLAY: dict[tuple[str, bool], Metric] = {
    (m.side, m.overlay): m for m in METRICS
}

# Shared bar-chart geometry
BAR_FIG_W   = 4.0
BAR_FIG_H   = 0.2
BAR_DPI     = 100
BAR_HEIGHT  = 1.0
GRID_TICKS  = [25, 50, 75, 100]
GRID_COLOR  = "#d4d4d4"
SPINE_COLOR = "#555555"


# ── Bar-chart helpers ────────────────────────────────────────────────
def _apply_shared_axes(ax) -> None:
    """Grid lines, centre spine, and cosmetics shared by every bar row."""
    for x in GRID_TICKS:
        ax.axvline(x, color=GRID_COLOR, linewidth=0.6, zorder=0)
        ax.axvline(-x, color=GRID_COLOR, linewidth=0.6, zorder=0)
    ax.axvline(0, color=SPINE_COLOR, linewidth=0.6, linestyle="--", zorder=4)
    ax.set_xlim(-105, 105)
    ax.set_ylim(-0.5, 0.5)


def generate_bar_chart(taxid: int, meta: CladeMetadata, tmp_dir: str) -> str:
    """Horizontal divergent bar for a single taxon, saved as a PNG.

    Left half (negative x): the two `side="left"` metrics — light base
    bar with the overlay metric drawn on top. Right half mirrors it for
    the `side="right"` metrics. Light bars sit at zorder 2, dark overlays
    at zorder 3 so the darker metric stays visible when both are non-zero.
    """
    fig, ax = plt.subplots(figsize=(BAR_FIG_W, BAR_FIG_H), dpi=BAR_DPI)
    _apply_shared_axes(ax)

    kw = dict(height=BAR_HEIGHT, align="center", edgecolor="white", linewidth=0.4)
    for m in METRICS:
        direction = -1 if m.side == "left" else 1
        zorder = 3 if m.overlay else 2
        ax.barh(0, direction * meta.percent(m.key), color=m.color, zorder=zorder, **kw)

    ax.axis("off")
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    out_path = os.path.join(tmp_dir, f"{taxid}.png")
    fig.savefig(out_path, transparent=True, pad_inches=0)
    plt.close(fig)
    return out_path


def generate_axis_img(tmp_dir: str) -> str:
    """Axis ruler — drawn once per render into `tmp_dir`."""
    fig, ax = plt.subplots(figsize=(BAR_FIG_W, 0.30), dpi=BAR_DPI)
    ax.set_xlim(-105, 105)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.plot([-100, 100], [0.95, 0.95], color=SPINE_COLOR, linewidth=0.8)

    def _tick(x, major=False):
        h = 0.55 if major else 0.35
        ax.plot([x, x], [0.95, 0.95 - h], color=SPINE_COLOR,
                linewidth=(1.0 if major else 0.6))

    labeled = {-100: "1", -50: "0.5", 0: "0", 50: "0.5", 100: "1"}
    for x in [-100, -75, -50, -25, 0, 25, 50, 75, 100]:
        _tick(x, major=(x in labeled))
        if x in labeled:
            ax.text(x, 0.25, labeled[x], va="top", ha="center",
                    fontsize=8, fontfamily="sans-serif", color="#333333")

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    out_path = os.path.join(tmp_dir, "axis.png")
    fig.savefig(out_path, transparent=True, pad_inches=0)
    plt.close(fig)
    return out_path


def generate_legend_img(tmp_dir: str) -> str:
    """Compact two-row legend — drawn once per render into `tmp_dir`."""
    fig, ax = plt.subplots(figsize=(BAR_FIG_W, 0.55), dpi=BAR_DPI)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    swatch_w, swatch_h = 0.06, 0.28
    gap = 0.02
    label_kw = dict(va="center", fontsize=9, fontfamily="sans-serif", color="#222222")

    def _row(y_center, c_light, c_dark, label_left, label_right):
        y0 = y_center - swatch_h / 2
        x0_l = 0.5 - swatch_w - gap / 2
        ax.add_patch(mpatches.FancyBboxPatch(
            (x0_l, y0), swatch_w, swatch_h, boxstyle="round,pad=0.01",
            facecolor=c_light, edgecolor="white", linewidth=0.5))
        ax.text(x0_l - gap, y_center, label_left, ha="right", **label_kw)
        x0_d = 0.5 + gap / 2
        ax.add_patch(mpatches.FancyBboxPatch(
            (x0_d, y0), swatch_w, swatch_h, boxstyle="round,pad=0.01",
            facecolor=c_dark, edgecolor="white", linewidth=0.5))
        ax.text(x0_d + swatch_w + gap, y_center, label_right, ha="left", **label_kw)

    # Top row pairs the two light (non-overlay) metrics; bottom row pairs
    # the two dark (overlay) metrics. Both rows go left-side → right-side.
    light_left  = _BY_SIDE_AND_OVERLAY[("left", False)]
    light_right = _BY_SIDE_AND_OVERLAY[("right", False)]
    dark_left   = _BY_SIDE_AND_OVERLAY[("left", True)]
    dark_right  = _BY_SIDE_AND_OVERLAY[("right", True)]
    _row(0.72, light_left.color, light_right.color, light_left.legend_label, light_right.legend_label)
    _row(0.25, dark_left.color,  dark_right.color,  dark_left.legend_label,  dark_right.legend_label)

    ax.axvline(0.5, ymin=0.05, ymax=0.95, color=SPINE_COLOR, linewidth=0.8, linestyle="--")

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    out_path = os.path.join(tmp_dir, "legend.png")
    fig.savefig(out_path, transparent=True, pad_inches=0)
    plt.close(fig)
    return out_path


def _color_square_factory(tmp_dir: str):
    """Return a function `(color) -> path` that lazily renders + memoizes
    a small colored swatch per render. Memoization is local to the
    factory's closure (no module globals)."""
    cache: dict[str, str] = {}

    def make(color: str) -> str:
        if color in cache:
            return cache[color]
        fig, ax = plt.subplots(figsize=(0.12, 0.12), dpi=BAR_DPI)
        ax.add_patch(mpatches.Rectangle((0, 0), 1, 1, facecolor=color, edgecolor="white", linewidth=0.5))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
        out_path = os.path.join(tmp_dir, f"square_{color.replace('#', '')}.png")
        fig.savefig(out_path, transparent=True, pad_inches=0)
        plt.close(fig)
        cache[color] = out_path
        return out_path

    return make


# ── ETE3 layout & tree style ─────────────────────────────────────────
def create_layout_fn(ncbi, phylum_metadata, include_counts, tmp_dir):
    """Build the per-leaf layout function. Closes over the per-render
    `tmp_dir` so all generated bar-chart / swatch images go there."""
    make_swatch = _color_square_factory(tmp_dir)

    def my_layout(node):
        if not node.is_leaf():
            return

        try:
            taxid = int(node.name)
        except (TypeError, ValueError):
            return
        taxon_name = ncbi.get_taxid_translator([taxid]).get(taxid, str(taxid))

        name_face = TextFace(f" {taxon_name} ({taxid})", fsize=10,
                             ftype="times new roman", fstyle="italic")
        name_face.margin_right = 0
        node.add_face(name_face, column=0, position="aligned")

        if taxid not in phylum_metadata:
            return

        meta = phylum_metadata[taxid]

        img_face = ImgFace(generate_bar_chart(taxid, meta, tmp_dir))
        img_face.margin_left = 5
        img_face.margin_right = 15
        node.add_face(img_face, column=1, position="aligned")

        n_face = TextFace(f"{meta.n_rows:,}", fsize=10, bold=True,
                          ftype="times new roman", tight_text=True)
        n_face.margin_right = 20
        node.add_face(n_face, column=2, position="aligned")

        if include_counts:
            def _add_count_col(entries, organisms, color, col_idx_sq, col_idx_txt):
                sq_face = ImgFace(make_swatch(color))
                sq_face.margin_left = 0
                sq_face.margin_right = 3
                node.add_face(sq_face, column=col_idx_sq, position="aligned")
                txt_face = TextFace(f"{entries:,} ({organisms:,})", fsize=10,
                                    ftype="times new roman", tight_text=True)
                txt_face.margin_right = 0
                node.add_face(txt_face, column=col_idx_txt, position="aligned")

            # Column layout: (swatch, "{entries:,} ({organisms:,})") pair
            # per metric, starting at column 3 — so metric i lives in
            # columns 3+2i (swatch) and 4+2i (text).
            for i, m in enumerate(METRICS):
                _add_count_col(
                    getattr(meta, m.total_key), getattr(meta, m.coverage_key),
                    m.color, 3 + 2 * i, 4 + 2 * i,
                )

    return my_layout


def configure_tree_style(my_layout, include_counts, tmp_dir):
    ts = TreeStyle()
    ts.layout_fn = my_layout
    ts.show_leaf_name = False
    ts.force_topology = True
    ts.draw_guiding_lines = True
    ts.guiding_lines_type = 2
    ts.guiding_lines_color = "#c7c7c7"

    legend_face = ImgFace(generate_legend_img(tmp_dir))
    legend_face.margin_left = 5
    legend_face.margin_right = 15
    legend_face.margin_bottom = 8
    ts.aligned_header.add_face(legend_face, column=1)

    axis_face = ImgFace(generate_axis_img(tmp_dir))
    axis_face.margin_left = 5
    axis_face.margin_right = 15
    ts.aligned_foot.add_face(axis_face, column=1)

    org_header = TextFace("Number of\nspecies", fsize=10, bold=True,
                          ftype="times new roman", tight_text=True)
    org_header.margin_right = 20
    org_header.margin_bottom = 10
    ts.aligned_header.add_face(org_header, column=2)

    if include_counts:
        counts_header = TextFace("Entries (Unique Species)", fsize=10, bold=True,
                                 ftype="times new roman", tight_text=True)
        counts_header.margin_right = -100
        counts_header.margin_left = 0
        counts_header.margin_bottom = 0
        ts.aligned_header.add_face(counts_header, column=6)

    return ts


# ── Subprocess entry point ───────────────────────────────────────────
def render_tree_in_process(phylum_metadata, include_counts, out_svg):
    """Spawn-subprocess entry point that builds the ETE3 topology and
    writes the rendered SVG to `out_svg`.

    PyQt5 requires QApplication on the main thread; Streamlit runs
    callbacks on worker threads, so this is invoked via
    `multiprocessing.get_context('spawn').Process(...)` (see
    `app.py::generate_tree_svg_cached`).

    Uses Qt5's built-in `offscreen` platform plugin so we don't need an
    X server (Xvfb / pyvirtualdisplay) anywhere — Streamlit Cloud, CI,
    or local. The plugin is part of the PyQt5 wheel; no extra apt
    packages are required beyond the Qt5 system libs declared in
    packages.txt. The `QT_QPA_PLATFORM=offscreen` env var is pinned at
    module-import time (see this module's docstring), and a spawn-mode
    child re-runs the module, so the setting is in place before any Qt
    code runs here.
    """
    import tempfile

    ncbi = get_ncbi()

    # Batched lineage lookup (replaces an N+1 ncbi.get_lineage(tid) loop).
    # get_lineage_translator returns {taxid: [lineage]} only for taxids
    # present in the local taxonomy DB; missing taxids are silently dropped.
    candidate_taxids = list(phylum_metadata.keys())
    lineages = ncbi.get_lineage_translator(candidate_taxids)
    valid_taxids = [t for t in candidate_taxids if t in lineages]
    if not valid_taxids:
        log.warning("No valid taxids in phylum_metadata; nothing to render.")
        return

    with tempfile.TemporaryDirectory(prefix="euka_bars_") as tmp_dir:
        layout_fn = create_layout_fn(ncbi, phylum_metadata, include_counts, tmp_dir)
        ts = configure_tree_style(layout_fn, include_counts, tmp_dir)
        tree = ncbi.get_topology(valid_taxids)
        tree.render(out_svg, w=1200, units="px", tree_style=ts)
