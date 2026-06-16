"""EukaSurvey Streamlit app — thin controller.

The page is composed of five independent sections, each rendered by
its own `ui/` module. The cache wrappers and DB constants live in
`src/cache.py` and `src/constants.py` respectively.
"""

import streamlit as st

from src.cache import get_db_connection, get_db_ready
from ui.export import render_export
from ui.query_config import render_query_config
from ui.sidebar import render_sidebar
from ui.summary import render_summary
from ui.tree import render_tree_section

st.set_page_config(
    page_title="EukaSurvey Platform",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    st.title("🧬 EukaSurvey", anchor=False)
    st.subheader("The Genomic Resource Explorer for Eukaryotes", divider="blue", anchor=False)
    st.caption("Visualize genomic data availability across the Eukaryotic Tree of Life.")

    try:
        get_db_ready()
    except RuntimeError:
        st.error("Could not download the database. Please refresh the page to try again.")
        st.stop()

    conn = get_db_connection()

    # Sidebar = persistent control panel: query controls first, help below.
    query = render_query_config(conn)
    render_sidebar()

    if query.is_valid_root:
        render_summary(conn, query)
    elif query.root_taxid is not None:
        # User typed a taxid that doesn't resolve in NCBI's taxonomy.
        st.error(f"TaxID {query.root_taxid} does not exist in the NCBI taxonomy database.")

    st.space("xsmall")
    if query.has_results:
        render_tree_section(conn, query)

    st.space("xsmall")
    if query.has_results and query.target_rank:
        render_export(conn, query)


if __name__ == "__main__":
    main()
