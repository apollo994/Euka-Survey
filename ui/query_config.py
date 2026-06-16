"""Root-taxon control — the single global "which clade?" question.

Rendered prominently at the top of the sidebar (the most important
control in the app), with the selected clade's lineage right beneath it.
Produces a `RootChoice`; the breakdown rank now lives with the results it
drives (see `render_results`).
"""

import sqlite3

import streamlit as st

from src import ete_utils, taxonomy
from src.constants import COMMON_CLADES
from ui.state import RootChoice

# Best-effort font bump for the sidebar's main controls. Scoped to the
# sidebar via the stable `stSidebar` testid; if Streamlit's internal
# BaseWeb markup changes, these rules simply no-op (no crash).
_SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] div[data-baseweb="select"] { font-size: 1.05rem; }
section[data-testid="stSidebar"] div[data-baseweb="input"] input { font-size: 1.05rem; }
</style>
"""


def render_root_control(conn: sqlite3.Connection) -> RootChoice:
    """Render the root-taxon picker in the sidebar. Returns the choice."""
    with st.sidebar:
        st.markdown(_SIDEBAR_CSS, unsafe_allow_html=True)
        st.markdown("## :material/arrow_forward: Start here")
        st.markdown(
            "**Choose a clade to explore.** You'll see the genomic data available "
            "across every species it contains."
        )

        common_taxa_labels = [f"{name} ({tid})" for tid, name in COMMON_CLADES.items()]
        label_to_taxid = {f"{name} ({tid})": tid for tid, name in COMMON_CLADES.items()}

        st.markdown("### Root taxon")
        choice = st.selectbox(
            "Root taxon",
            ["Enter your own"] + common_taxa_labels,
            index=1,
            placeholder="Choose a valid NCBI Taxon ID",
            key="root_taxon_selection",
            label_visibility="collapsed",
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

        root_name = ete_utils.get_name_from_taxid(root_taxid) if root_taxid else "Error"
        root_rank = ete_utils.get_rank_from_taxid(root_taxid) if root_taxid else "clade"

        # Where the chosen clade sits in the tree of life — orientation right
        # at the point of selection.
        if root_taxid and root_name != "Unknown":
            crumb = taxonomy.get_lineage_breadcrumb(root_taxid)
            if crumb:
                names = [name for _, name, _ in crumb]
                path = " › ".join(names[:-1] + [f"**{names[-1]}**"])
                st.caption(f":material/account_tree: {path}")

    return RootChoice(root_taxid=root_taxid, root_name=root_name, root_rank=root_rank)
