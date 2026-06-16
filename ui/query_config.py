"""Query controls — root taxon + breakdown rank + size readback.

Rendered into the sidebar as a persistent control panel (A2). Producer
of the shared `QueryState` consumed by the summary, results, and export
sections in the main area.
"""

import sqlite3

import streamlit as st

from src import ete_utils, taxonomy
from src.cache import fetch_taxa_cached, get_taxa_count_cached
from src.constants import ALLOWED_RANKS, COMMON_CLADES
from ui.state import QueryState


def render_query_config(conn: sqlite3.Connection) -> QueryState:
    """Render the query controls in the sidebar. Returns the resolved state."""
    with st.sidebar:
        st.header("Query", anchor=False)

        common_taxa_labels = [f"{name} ({tid})" for tid, name in COMMON_CLADES.items()]
        label_to_taxid = {f"{name} ({tid})": tid for tid, name in COMMON_CLADES.items()}

        choice = st.selectbox(
            "Root taxon",
            ["Enter your own"] + common_taxa_labels,
            index=1,
            placeholder="Choose a valid NCBI Taxon ID",
            key="root_taxon_selection",
            help="Pick a commonly surveyed clade, or enter any valid NCBI Taxon ID to define the root of your query.",
        )

        if choice == "Enter your own":
            root_taxid_input = st.text_input(
                "NCBI Taxon ID",
                value="2759",
                placeholder="e.g. 2759 for Eukaryota",
            )
            if root_taxid_input and str(root_taxid_input).strip().isdigit():
                root_taxid: int | None = int(str(root_taxid_input).strip())
            else:
                if root_taxid_input:
                    st.warning("Please enter a valid numeric Taxon ID.")
                root_taxid = None
        else:
            root_taxid = label_to_taxid[choice]

        # Resolve which ranks are strictly finer than the root's own rank.
        # `resolve_valid_ranks` is @lru_cache'd, so the ETE3 lookup is
        # paid at most once per root_taxid per process.
        valid_options = list(ALLOWED_RANKS)
        if root_taxid:
            try:
                valid_options = list(taxonomy.resolve_valid_ranks(root_taxid))
            except taxonomy.UnknownTaxonError:
                st.error(
                    "The selected TaxID could not be found. Please enter a valid "
                    "TaxID or select from the common clades."
                )
                root_taxid = None

        if "rank_selection" not in st.session_state:
            st.session_state.rank_selection = valid_options[0] if valid_options else "phylum"

        if valid_options:
            # Auto-fall back to the highest available rank when the
            # previously-selected rank is no longer valid for this root.
            if st.session_state.rank_selection not in valid_options:
                st.session_state.rank_selection = valid_options[0]

            target_rank: str | None = st.selectbox(
                "Break down by rank",
                valid_options,
                placeholder=None,
                key="rank_selection",
                help="The taxonomic rank to break the clade into. Only ranks below the root taxon are available.",
            )
        else:
            st.warning("This root taxon is at species level or lower — no further breakdown is available.")
            target_rank = None

        root_name = ete_utils.get_name_from_taxid(root_taxid) if root_taxid else "Error"
        root_rank = ete_utils.get_rank_from_taxid(root_taxid) if root_taxid else "clade"

        # Reactive readback on selection size.
        query_taxids: list[int] = []
        num_nodes = 0
        is_precomputed = False
        if root_taxid and target_rank and root_name != "Unknown":
            try:
                num_nodes = get_taxa_count_cached(conn, root_taxid, target_rank)
                if num_nodes > 0:
                    is_precomputed = True
                else:
                    query_taxa = fetch_taxa_cached(conn, root_taxid, target_rank)
                    if query_taxa:
                        query_taxids = [t[0] for t in query_taxa]
                        num_nodes = len(query_taxids)

                if num_nodes > 0:
                    st.info(
                        f"**{num_nodes}** {target_rank}-level taxa in this selection",
                        icon=":material/category:",
                    )
                    if num_nodes > 100:
                        st.caption("Large selections may take longer to compute and render.")
                else:
                    st.warning(f"No {target_rank}-level taxa found under TaxID {root_taxid}.")
            except ValueError:
                st.error("Invalid TaxID: Not found in database.")

    return QueryState(
        root_taxid=root_taxid,
        target_rank=target_rank,
        root_name=root_name,
        root_rank=root_rank,
        num_nodes=num_nodes,
        is_precomputed=is_precomputed,
        query_taxids=query_taxids,
    )
