"""Results section: filter/sort/limit form, then a Tree + Table view."""

import csv
import io
import os
import sqlite3
import tempfile

import streamlit as st

from src import database, ete_utils
from src.cache import (
    generate_tree_svg_cached,
    get_filtered_taxa_metadata_cached,
    get_phylum_metadata_cached,
)
from src.constants import HARD_NODE_CAP, STANDARD_BREAKPOINTS
from src.metrics import CladeMetadata, METRICS
from ui.state import QueryState


def render_tree_section(conn: sqlite3.Connection, query: QueryState) -> None:
    """Render the form, then the Tree + Table views on submit. Caller has
    already verified `query.has_results`."""
    st.header("Explore Results", anchor=False)

    with st.form("tree_settings_form", border=True):
        st.subheader("Filter Nodes", anchor=False)

        # Filter options derived from METRICS: label -> coverage_key.
        filter_options = {m.filter_label: m.coverage_key for m in METRICS}
        selected_filters = st.multiselect(
            "Require data for (leaves node out if it lacks data)",
            list(filter_options.keys()),
            placeholder="Select features...",
        )

        filter_logic_label = "Match ALL (AND)"
        if len(selected_filters) > 1:
            filter_logic_label = st.segmented_control(
                "Condition", ["Match ALL (AND)", "Match ANY (OR)"], default="Match ALL (AND)",
            )
        filter_logic = (
            database.FilterLogic.AND
            if filter_logic_label == "Match ALL (AND)"
            else database.FilterLogic.OR
        )

        st.subheader("Sorting & Limits", anchor=False)
        # Sort options derived from METRICS: count variants then total variants.
        sort_options = {
            "Unique Species": "n_rows",
            **{m.sort_count_label: m.coverage_key for m in METRICS},
            **{m.sort_total_label: m.total_key for m in METRICS},
        }
        cols = st.columns(2)

        with cols[0]:
            sort_by_label = st.selectbox(
                "Sort top nodes by number of ", list(sort_options.keys()), key="sort_by_selection",
            )
            sort_by_key = sort_options[sort_by_label]

            exclude_empty = st.toggle("Exclude Empty Taxa (Zero data across all fields)", value=True)

        with cols[1]:
            # Dynamic node-limit options bounded by both the actual node
            # count and the hard performance cap.
            effective_max = min(query.num_nodes, HARD_NODE_CAP)
            valid_options_limit = [str(b) for b in STANDARD_BREAKPOINTS if b < effective_max]
            valid_options_limit.append(f"All ({effective_max})")
            valid_options_limit.append("Custom")

            if "25" in valid_options_limit:
                default_idx = valid_options_limit.index("25")
            else:
                default_idx = max(0, len(valid_options_limit) - 2)

            selected_limit = st.selectbox(
                "Max nodes to display",
                valid_options_limit,
                index=default_idx,
                key="limit_selection",
                help=f"Hard cap set to {HARD_NODE_CAP} nodes for performance.",
            )

            if selected_limit == "Custom":
                top_n = st.number_input(
                    "Enter custom max nodes",
                    min_value=2,
                    max_value=effective_max,
                    value=min(25, effective_max),
                    step=1,
                )
            elif selected_limit.startswith("All"):
                top_n = effective_max
            else:
                top_n = int(selected_limit)

            include_counts = st.toggle(
                "Show Numeric Details in Tree",
                value=True,
                help="Toggle display of per-feature resource counts in the tree visualization.",
            )

        submitted = st.form_submit_button(
            "Generate Visualization", type="primary", icon=":material/account_tree:",
        )

    if not submitted:
        return

    if not query.target_rank:
        st.error("Cannot generate tree: Root taxon is at species level or lower, no further taxonomic breakdown is possible.")
        st.stop()
    if query.num_nodes == 0:
        st.error(f"Cannot generate tree. No {query.target_rank}s found or invalid TaxID {query.root_taxid}.")
        st.stop()

    with st.spinner("Aggregating data and filtering clades..."):
        filter_keys = [filter_options[f] for f in selected_filters] if selected_filters else []

        if query.is_precomputed:
            # SQL pushes filter/sort/limit down to SQLite.
            phylum_metadata, total_matches = get_filtered_taxa_metadata_cached(
                conn,
                query.root_taxid,
                query.target_rank,
                exclude_empty,
                tuple(filter_keys),
                filter_logic,
                sort_by_key,
                top_n,
            )
        else:
            # Non-precomputed root: fetch unfiltered metadata (cache key
            # independent of filter knobs) then apply the same
            # filter/sort/limit semantics as the SQL path in pure Python.
            raw_metadata = get_phylum_metadata_cached(conn, tuple(query.query_taxids), exclude_empty=False)
            phylum_metadata, total_matches = database.filter_sort_limit_metadata(
                raw_metadata,
                filter_keys=filter_keys,
                filter_logic=filter_logic,
                sort_by_key=sort_by_key,
                top_n=top_n,
                exclude_empty=exclude_empty,
            )

        nodes_excluded = query.num_nodes - total_matches
        if nodes_excluded > 0:
            st.info(
                f"**Nodes included:** {total_matches}/{query.num_nodes} "
                f"({nodes_excluded} excluded due to filtering criteria)"
            )

        if not phylum_metadata:
            st.warning("No clades have data matching the criteria (or all were empty).")
            st.stop()

    tab_tree, tab_table = st.tabs(["🌳 Tree", "📊 Table"])
    with tab_tree:
        _render_tree_tab(phylum_metadata, include_counts, query)
    with tab_table:
        _render_table_tab(phylum_metadata, query)


def _render_tree_tab(phylum_metadata, include_counts, query: QueryState) -> None:
    """Render the ETE3 SVG figure + its download button."""
    with st.spinner("Rendering phylogenetic tree..."):
        svg_bytes = generate_tree_svg_cached(phylum_metadata, include_counts)

    if svg_bytes is None:
        # No st.stop() — let the Table tab still render below.
        st.error("Failed to render the tree. This is usually due to Qt/X11 rendering restrictions.")
        return

    # `st.image` rejects raw SVG bytes (PIL.UnidentifiedImageError);
    # writing to a temp file lets it dispatch via extension.
    tmp_fd, tmp_svg = tempfile.mkstemp(prefix="euka_display_", suffix=".svg")
    os.close(tmp_fd)
    try:
        with open(tmp_svg, "wb") as f:
            f.write(svg_bytes)
        st.image(tmp_svg, width="stretch")
    finally:
        if os.path.exists(tmp_svg):
            os.remove(tmp_svg)

    st.download_button(
        label="Download SVG Figure",
        data=svg_bytes,
        file_name=f"tree_{query.root_taxid}_{query.target_rank}.svg",
        mime="image/svg+xml",
        icon=":material/download:",
        type="primary",
    )
    st.session_state.rendered_taxid = query.root_taxid


def _render_table_tab(phylum_metadata: dict[int, CladeMetadata], query: QueryState) -> None:
    """Sortable in-app table of the same filtered/sorted/limited rows the
    tree shows. Coverage is a ProgressColumn bar; totals are formatted
    numbers. Users can re-sort/search client-side without re-running."""
    rows: list[dict] = []
    for taxid, meta in phylum_metadata.items():
        row: dict = {
            "taxon": ete_utils.get_name_from_taxid(taxid),
            "taxid": taxid,
            "species": meta.n_rows,
        }
        for m in METRICS:  # coverage bars grouped first …
            row[m.percent_key] = round(meta.percent(m.key), 1)
        for m in METRICS:  # … then totals
            row[m.total_key] = getattr(meta, m.total_key)
        rows.append(row)

    col_cfg: dict = {
        "taxon": st.column_config.TextColumn("Taxon"),
        "taxid": st.column_config.NumberColumn("TaxID", format="%d"),
        "species": st.column_config.NumberColumn(
            "Species", format="localized", help="Unique species tracked in this clade"
        ),
    }
    for m in METRICS:
        col_cfg[m.percent_key] = st.column_config.ProgressColumn(
            m.card_title,
            help=f"% of species with {m.card_title.lower()}",
            min_value=0,
            max_value=100,
            format="%.0f%%",
        )
    for m in METRICS:
        # `m.total_label` is "Total Runs" for both RNA metrics, which would
        # collide as two identical columns — use the resource title instead.
        col_cfg[m.total_key] = st.column_config.NumberColumn(
            f"{m.card_title} (total)", format="localized", help=m.total_help
        )

    st.dataframe(rows, column_config=col_cfg, hide_index=True, width="stretch")
    st.caption(
        "Click a column header to sort. Coverage bars show the % of species "
        "in each clade with that resource."
    )

    st.download_button(
        label="Download table (TSV)",
        data=_rows_to_tsv(rows),
        file_name=f"table_{query.root_taxid}_{query.target_rank}.tsv",
        mime="text/tab-separated-values",
        icon=":material/download:",
        help="Exactly the rows shown above (current filters, sort, and limit).",
    )


def _rows_to_tsv(rows: list[dict]) -> str:
    """Serialize the displayed table rows to TSV with readable headers."""
    labels = {"taxon": "Taxon", "taxid": "TaxID", "species": "Species"}
    for m in METRICS:
        labels[m.percent_key] = f"{m.card_title} coverage %"
    for m in METRICS:
        labels[m.total_key] = f"{m.card_title} (total)"

    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t")
    keys = list(rows[0].keys())
    writer.writerow([labels[k] for k in keys])
    for r in rows:
        writer.writerow([r[k] for k in keys])
    return out.getvalue()
