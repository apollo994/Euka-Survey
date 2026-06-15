"""Export Data section: TSV download of the current query."""

import sqlite3

import streamlit as st

from src import utils
from src.cache import fetch_taxa_cached
from ui.state import QueryState


def render_export(conn: sqlite3.Connection, query: QueryState) -> None:
    """Render the TSV download. Caller has already verified
    `query.has_results and query.target_rank`."""
    assert query.root_taxid is not None and query.target_rank is not None

    st.header("Export Data", anchor=False)
    st.write("Download the complete overview of the current query as a TSV file.")

    tsv_filename = f"{query.root_name.replace(' ', '_')}_{query.target_rank}_data.tsv"

    # `generate_tsv` is itself @st.cache_data. We pass the cacheable
    # `fetch_taxa_cached` through so the heavy taxa resolution happens
    # inside the cached bounds — the parent spinner stays responsive
    # instead of locking the whole UI.
    tsv_data = utils.generate_tsv(conn, query.root_taxid, query.target_rank, fetch_taxa_cached)

    st.download_button(
        label="Download TSV",
        data=tsv_data,
        file_name=tsv_filename,
        mime="text/tab-separated-values",
        icon=":material/download:",
        type="primary",
    )
