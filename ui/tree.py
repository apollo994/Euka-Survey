"""Explore Results section: breakdown rank, filter/sort/limit form, then a
Tree + Table view. Owns the breakdown rank (it's a parameter of the
results, not a global selector — the summary doesn't need it)."""

import csv
import io
import os
import sqlite3
import tempfile

import streamlit as st

from src import database, ete_utils, taxonomy
from src.cache import (
    fetch_taxa_cached,
    generate_tree_svg_cached,
    get_filtered_taxa_metadata_cached,
    get_phylum_metadata_cached,
    get_taxa_count_cached,
)
from src.constants import HARD_NODE_CAP, STANDARD_BREAKPOINTS
from src.metrics import CladeMetadata, METRICS
from ui.state import QueryState, RootChoice

# Plurals for the canonical ranks, for the breakdown explainer line.
_RANK_PLURAL = {
    "phylum": "phyla", "class": "classes", "order": "orders",
    "family": "families", "genus": "genera", "species": "species",
}


def render_results(conn: sqlite3.Connection, root: RootChoice) -> QueryState:
    """Render the Explore Results section: breakdown rank + form, then the
    Tree + Table views on submit. Caller has verified `root.is_valid_root`.
    Returns the resolved `QueryState` so the caller can gate the export."""
    st.header("Explore Results", anchor=False)
    st.caption("Filter and sort the breakdown, then view it as an interactive tree or a sortable table.")

    # Step 2 — breakdown rank (reactive) + size readback. This is what the
    # rest of the section operates on.
    query = _render_rank_and_size(conn, root)

    if query.target_rank is None:
        st.warning(
            "This root taxon is at species level or lower — there's no finer "
            "rank to break it down by. Pick a higher-level clade to explore."
        )
        return query
    if query.num_nodes == 0:
        st.warning(f"No {query.target_rank}-level taxa found under TaxID {root.root_taxid}.")
        return query

    filter_options = {m.filter_label: m.coverage_key for m in METRICS}
    # Sort options derived from METRICS: count variants then total variants.
    sort_options = {
        "Unique Species": "n_rows",
        **{m.sort_count_label: m.coverage_key for m in METRICS},
        **{m.sort_total_label: m.total_key for m in METRICS},
    }

    with st.form("tree_settings_form", border=True):
        # One compact row: filter / sort / limit side by side (no lone
        # full-width widgets), then a toggles row, then the CTA.
        c_filter, c_sort, c_limit = st.columns(3, gap="large")

        with c_filter:
            selected_filters = st.multiselect(
                "Require data for",
                list(filter_options.keys()),
                placeholder="Any (no filter)",
                help="Keep only taxa that have the selected resource(s).",
            )
            filter_logic_label = "Match ALL (AND)"
            if len(selected_filters) > 1:
                filter_logic_label = st.segmented_control(
                    "Match", ["Match ALL (AND)", "Match ANY (OR)"], default="Match ALL (AND)",
                )
            filter_logic = (
                database.FilterLogic.AND
                if filter_logic_label == "Match ALL (AND)"
                else database.FilterLogic.OR
            )
            exclude_empty = st.toggle(
                "Exclude empty taxa (no data in any resource)", value=True
            )

        with c_sort:
            sort_by_label = st.selectbox(
                "Sort by", list(sort_options.keys()), key="sort_by_selection",
                help="Ranks the taxa; the top ones are kept up to the limit.",
            )
            sort_by_key = sort_options[sort_by_label]
            include_counts = st.toggle(
                "Show numeric details on the tree",
                value=True,
                help="Show per-resource counts next to each leaf in the tree (does not affect the table).",
            )

        with c_limit:
            # Dynamic taxa-limit options bounded by both the actual taxa
            # count and the hard performance/memory cap.
            effective_max = min(query.num_nodes, HARD_NODE_CAP)
            valid_options_limit = [str(b) for b in STANDARD_BREAKPOINTS if b < effective_max]
            valid_options_limit.append(f"All ({effective_max})")

            if "25" in valid_options_limit:
                default_idx = valid_options_limit.index("25")
            else:
                default_idx = len(valid_options_limit) - 1  # the "All (…)" option

            selected_limit = st.selectbox(
                "Max taxa to display",
                valid_options_limit,
                index=default_idx,
                key="limit_selection",
                help=f"Capped at {HARD_NODE_CAP} taxa to stay within memory limits.",
            )

            if selected_limit.startswith("All"):
                top_n = effective_max
            else:
                top_n = int(selected_limit)

        submitted = st.form_submit_button(
            "Generate Tree & Table", type="primary", icon=":material/analytics:",
        )

    if not submitted:
        return query

    with st.spinner("Aggregating and filtering taxa..."):
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

        taxa_excluded = query.num_nodes - total_matches
        if taxa_excluded > 0:
            st.info(
                f"**Showing {total_matches} of {query.num_nodes} taxa** "
                f"({taxa_excluded} hidden by your filters)"
            )

        if not phylum_metadata:
            st.warning("No taxa have data matching the criteria (or all were empty).")
            st.stop()

    tab_tree, tab_table = st.tabs(["🌳 Tree", "📊 Table"])
    with tab_tree:
        _render_tree_tab(phylum_metadata, include_counts, query)
    with tab_table:
        _render_table_tab(phylum_metadata, query)

    return query


def _render_rank_and_size(conn: sqlite3.Connection, root: RootChoice) -> QueryState:
    """Render the breakdown-rank picker (the section's primary control) as a
    prominent segmented control + a dynamic explainer of what to expect, and
    resolve how many taxa sit at that rank. Reactive (outside the form) so the
    explainer and the form's limit options update the moment the rank changes."""
    try:
        valid_options = list(taxonomy.resolve_valid_ranks(root.root_taxid))
    except taxonomy.UnknownTaxonError:
        valid_options = []

    target_rank: str | None = None
    if valid_options:
        # Keep a valid selection in session_state *before* the widget renders,
        # so switching root (which changes the available ranks) never leaves a
        # stale value that segmented_control would reject.
        if st.session_state.get("rank_selection") not in valid_options:
            st.session_state["rank_selection"] = valid_options[0]

        st.markdown("##### :material/account_tree: Break down by rank")
        selected = st.segmented_control(
            "Break down by rank",
            valid_options,
            key="rank_selection",
            label_visibility="collapsed",
            help="Split the clade at this taxonomic rank — each resulting group becomes one row in the tree/table.",
        )
        # segmented_control can return None if the user deselects; keep a rank.
        target_rank = selected if selected is not None else valid_options[0]

    num_nodes = 0
    is_precomputed = False
    query_taxids: list[int] = []
    if target_rank:
        try:
            num_nodes = get_taxa_count_cached(conn, root.root_taxid, target_rank)
            if num_nodes > 0:
                is_precomputed = True
            else:
                query_taxa = fetch_taxa_cached(conn, root.root_taxid, target_rank)
                if query_taxa:
                    query_taxids = [t[0] for t in query_taxa]
                    num_nodes = len(query_taxids)
        except ValueError:
            st.error("Invalid TaxID: Not found in database.")

    if target_rank and num_nodes > 0:
        plural = _RANK_PLURAL.get(target_rank, f"{target_rank}s")
        note = (
            f"Splitting **{root.root_name}** into its **{num_nodes:,} {plural}** — "
            f"each row is one {target_rank}; the bars show what share of its "
            "species have each genomic resource."
        )
        if num_nodes > 100:
            note += " :gray[· larger selections take longer to render.]"
        st.caption(note)

    return QueryState(
        root_taxid=root.root_taxid,
        target_rank=target_rank,
        root_name=root.root_name,
        root_rank=root.root_rank,
        num_nodes=num_nodes,
        is_precomputed=is_precomputed,
        query_taxids=query_taxids,
    )


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
    st.toast("Tree & table ready", icon="✅")


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
        type="primary",
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
