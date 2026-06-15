"""Query Configuration section: root taxon + rank + tree-size readback.

Producer of the shared `QueryState` consumed by the summary, tree, and
export sections.
"""

import sqlite3

import streamlit as st

from src import ete_utils, taxonomy
from src.cache import fetch_taxa_cached, get_taxa_count_cached
from src.constants import ALLOWED_RANKS, COMMON_CLADES
from ui.state import QueryState


def render_query_config(conn: sqlite3.Connection) -> QueryState:
    """Render the Query Configuration box. Returns the resolved state."""
    with st.container(border=True):
        st.header("Query Configuration", anchor=False)

        common_taxa_labels = [f"{name} ({tid})" for tid, name in COMMON_CLADES.items()]
        label_to_taxid = {f"{name} ({tid})": tid for tid, name in COMMON_CLADES.items()}

        q_cols = st.columns([1.5, 1, 1], gap="large")

        with q_cols[0]:
            choice = st.selectbox(
                "Root Taxon ID",
                ["Enter your own"] + common_taxa_labels,
                index=1,
                placeholder="Choose a valid NCBI Taxon ID",
                key="root_taxon_selection",
                help="Choose from a selection of commonly surveyed clades or enter any valid NCBI Taxon ID to define the root of your tree query."
            )

            if choice == "Enter your own":
                root_taxid_input = st.text_input(
                    "Enter NCBI Taxon ID:",
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

        with q_cols[1]:
            if valid_options:
                # Auto-fall back to the highest available rank when the
                # previously-selected rank is no longer valid for this root.
                if st.session_state.rank_selection not in valid_options:
                    st.session_state.rank_selection = valid_options[0]

                target_rank: str | None = st.selectbox(
                    "Breakdown by Rank",
                    valid_options,
                    placeholder=None,
                    key="rank_selection",
                    help="Select the taxonomic rank to slice the tree. Only ranks below the selected root taxon are available."
                )
            else:
                st.warning("Selected root taxon is at the species level or lower. No further breakdown available.")
                target_rank = None

        root_name = ete_utils.get_name_from_taxid(root_taxid) if root_taxid else "Error"
        root_rank = ete_utils.get_rank_from_taxid(root_taxid) if root_taxid else "clade"

        # Reactive readback on tree size.
        query_taxids: list[int] = []
        num_nodes = 0
        is_precomputed = False
        with q_cols[2]:
            st.write("")  # alignment spacing
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
                        st.info(f"Tree size: **{num_nodes}** {target_rank} nodes", icon="🌲")
                        if num_nodes > 100:
                            st.caption("High node counts may take longer to compute and render.")
                    else:
                        st.warning(f"No {target_rank}s found under TaxID {root_taxid}.")
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
