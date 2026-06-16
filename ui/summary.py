"""Genomic Resource Summary: the four-card overview at the top of the page.

Each card is rendered from a `Metric` config row — the four cards that
used to be four hand-written render blocks (~80 lines of copy-pasted
markup) are now one `render_metric_card` call inside a loop.
"""

import sqlite3

import streamlit as st

from src.cache import get_phylum_metadata_cached
from src.metrics import CladeMetadata, METRICS, Metric
from src.wikipedia import get_taxon_summary
from ui.state import RootChoice

# Shared fixed height for the top row so the metric + "About" card stay the
# same size and the layout doesn't jump when the root (and its image/blurb)
# changes. Overflow scrolls inside the card rather than resizing it.
_TOP_ROW_HEIGHT = 240
# Trim the Wikipedia extract so the blurb fits the fixed card height.
_EXTRACT_MAX_CHARS = 300
# Fixed thumbnail box — object-fit:cover crops any aspect ratio to this size,
# so a portrait vs. landscape image never changes the card's height.
_THUMB_PX = 110


def render_summary(conn: sqlite3.Connection, root: RootChoice) -> None:
    """Render the summary section. Caller has already verified
    `root.is_valid_root` (skip the section otherwise). Depends only on
    the root taxon — the breakdown rank doesn't affect these clade-wide
    rollups.

    Edge case: if the root taxid resolves to a *name* (`root_name !=
    "Unknown"`) but has no row in `precomputed_clade_features`, we
    fall through to a warning so the user sees something rather than
    a silent missing section.
    """
    assert root.root_taxid is not None  # gated by is_valid_root

    st.header("Genomic Resource Summary", anchor=False)
    st.markdown(
        f"Overview of available resources across the entire "
        f"_{root.root_name}_ {root.root_rank} (TaxID {root.root_taxid})."
    )

    root_metadata = get_phylum_metadata_cached(conn, (root.root_taxid,), exclude_empty=False)
    if not root_metadata or root.root_taxid not in root_metadata:
        st.warning("No data found for this Root Taxon.")
        return

    stats = root_metadata[root.root_taxid]

    # Top row: prominent species count paired with a Wikipedia "About" card
    # so the headline number doesn't sit alone across the full width. If
    # there's no usable Wikipedia summary, the metric falls back to full width.
    summary = get_taxon_summary(root.root_name)
    if summary:
        metric_col, about_col = st.columns([1, 2], gap="large")
        with metric_col:
            _render_total_species(stats, root)
        with about_col:
            _render_about_card(summary)
    else:
        _render_total_species(stats, root)

    # Four resource cards — one per Metric, same order.
    cols = st.columns(len(METRICS))
    for col, metric in zip(cols, METRICS):
        with col:
            _render_metric_card(metric, stats, root.root_taxid)


def _render_total_species(stats: CladeMetadata, root: RootChoice) -> None:
    """The headline species count for the whole clade. Vertically centered
    in a fixed-height card so it sits level with the About card beside it."""
    with st.container(border=True, height=_TOP_ROW_HEIGHT, vertical_alignment="center"):
        st.metric(
            label=":material/groups: Total Species",
            value=f"{stats.n_rows:,}",
            help="Total number of unique species tracked in this clade",
        )
        st.caption(f"in **{root.root_name}** · {root.root_rank}")


def _render_about_card(summary: dict) -> None:
    """Wikipedia snippet for the root taxon — thumbnail + blurb + link, in a
    fixed-height card (a fixed object-fit thumbnail keeps it from resizing)."""
    with st.container(border=True, height=_TOP_ROW_HEIGHT):
        title = f"##### :material/menu_book: {summary['title']}"
        if summary["description"]:
            title += f" :gray[· {summary['description']}]"
        st.markdown(title)

        extract = summary["extract"]
        if len(extract) > _EXTRACT_MAX_CHARS:
            extract = extract[:_EXTRACT_MAX_CHARS].rsplit(" ", 1)[0] + "…"

        if summary["thumbnail"]:
            img_col, text_col = st.columns([1, 4], vertical_alignment="top")
            with img_col:
                st.markdown(
                    f'<img src="{summary["thumbnail"]}" '
                    f'style="width:{_THUMB_PX}px;height:{_THUMB_PX}px;'
                    'object-fit:cover;border-radius:8px;" '
                    f'alt="{summary["title"]}">',
                    unsafe_allow_html=True,
                )
            with text_col:
                st.markdown(extract)
        else:
            st.markdown(extract)

        st.markdown(f"[Read more on Wikipedia :material/open_in_new:]({summary['url']})")


def _render_metric_card(metric: Metric, stats: CladeMetadata, root_taxid: int) -> None:
    """Render one of the four summary cards."""
    with st.container(border=True):
        title_markdown = f"##### :material/{metric.card_icon}: :{metric.card_color}[{metric.card_title}]"
        if metric.card_title_help:
            st.markdown(title_markdown, help=metric.card_title_help)
        else:
            st.markdown(title_markdown)

        covered = getattr(stats, metric.coverage_key)
        pct = stats.percent(metric.key)
        st.metric(
            label="Species Covered",
            value=f"{covered:,}",
            help=metric.species_help,
        )
        # Coverage as a visual: the headline "how well-sampled is this
        # clade?" signal, not just a raw count.
        st.progress(min(pct / 100.0, 1.0), text=f"{pct:.0f}% of species")

        st.metric(
            label=metric.total_label,
            value=f"{getattr(stats, metric.total_key):,}",
            help=metric.total_help,
        )
        st.link_button(
            f"View on {metric.external_source_name}",
            metric.external_url(root_taxid),
            icon=":material/open_in_new:",
            width="stretch",
        )
