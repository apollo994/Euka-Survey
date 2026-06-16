"""Genomic Resource Summary: the four-card overview at the top of the page.

Each card is rendered from a `Metric` config row — the four cards that
used to be four hand-written render blocks (~80 lines of copy-pasted
markup) are now one `render_metric_card` call inside a loop.
"""

import sqlite3

import streamlit as st

from src import taxonomy
from src.cache import get_phylum_metadata_cached
from src.metrics import CladeMetadata, METRICS, Metric
from ui.state import QueryState


def render_summary(conn: sqlite3.Connection, query: QueryState) -> None:
    """Render the summary section. Caller has already verified
    `query.is_valid_root` (skip the section otherwise).

    Edge case: if the root taxid resolves to a *name* (`root_name !=
    "Unknown"`) but has no row in `precomputed_clade_features`, we
    fall through to a warning so the user sees something rather than
    a silent missing section.
    """
    assert query.root_taxid is not None  # gated by is_valid_root

    _render_breadcrumb(query.root_taxid)

    st.header("Genomic Resource Summary", anchor=False)
    st.markdown(
        f"Overview of available resources across the entire "
        f"_{query.root_name}_ {query.root_rank} (TaxID {query.root_taxid})."
    )

    root_metadata = get_phylum_metadata_cached(conn, (query.root_taxid,), exclude_empty=False)
    if not root_metadata or query.root_taxid not in root_metadata:
        st.warning("No data found for this Root Taxon.")
        return

    stats = root_metadata[query.root_taxid]

    # Prominent top-level metric.
    st.metric(
        label=f":material/groups: Total Species under {query.root_name}",
        value=f"{stats.n_rows:,}",
        help="Total number of unique species tracked in this clade",
        border=True,
    )

    # Four resource cards — one per Metric, same order.
    cols = st.columns(len(METRICS))
    for col, metric in zip(cols, METRICS):
        with col:
            _render_metric_card(metric, stats, query.root_taxid)


def _render_breadcrumb(root_taxid: int) -> None:
    """Show the root's lineage path (canonical ranks only) so the user is
    oriented within the tree of life. Skips only when the lineage can't be
    resolved at all — it's decorative, not load-bearing."""
    crumb = taxonomy.get_lineage_breadcrumb(root_taxid)
    if not crumb:
        return
    names = [name for _, name, _ in crumb]
    # Bold the current node; join ancestors with the breadcrumb separator.
    path = " › ".join(names[:-1] + [f"**{names[-1]}**"])
    st.markdown(f":material/account_tree: :gray[Lineage —] {path}")


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
