"""Export Data section: a clear explanation, a short preview, and the TSV
download of the current query's full breakdown."""

import csv
import io
import sqlite3

import streamlit as st

from src import utils
from src.cache import fetch_taxa_cached
from src.metrics import METRICS
from ui.state import QueryState

# How many rows to show in the preview (the file itself is unlimited).
_PREVIEW_ROWS = 10

# Readable labels for the public TSV columns, built from the same METRICS
# schema generate_tsv writes — so the preview headers can't drift from it.
_TSV_LABELS: dict[str, str] = {
    "taxon_id": "TaxID",
    "name": "Taxon",
    "total_species": "Species",
}
for _m in METRICS:
    _TSV_LABELS[_m.tsv_count_column] = f"{_m.card_title} (species)"
    _TSV_LABELS[_m.tsv_total_column] = f"{_m.card_title} (total)"


def render_export(conn: sqlite3.Connection, query: QueryState) -> None:
    """Render the TSV explanation + preview + download. Caller has already
    verified `query.has_results and query.target_rank`."""
    assert query.root_taxid is not None and query.target_rank is not None

    st.header("Export Data", anchor=False)

    # `generate_tsv` is @st.cache_data; this is the same string the download
    # button serves, so the preview reuses it (no extra computation/memory).
    tsv_data = utils.generate_tsv(conn, query.root_taxid, query.target_rank, fetch_taxa_cached)
    total_rows = max(tsv_data.count("\n") - 1, 0)  # rows minus the header

    st.markdown(
        f"Download the **complete breakdown** of _{query.root_name}_ by "
        f"**{query.target_rank}** as a tab-separated file (TSV) — **all "
        f"{total_rows:,} {query.target_rank}-level taxa**, one row each, with its "
        "species count and, for every genomic resource, the number of species "
        "covered and the total count. Unlike the table in *Explore Results*, "
        "this file is **never filtered, sorted, or limited**."
    )

    if total_rows:
        _render_preview(tsv_data, total_rows)

    tsv_filename = f"{query.root_name.replace(' ', '_')}_{query.target_rank}_data.tsv"
    st.download_button(
        label="Download TSV",
        data=tsv_data,
        file_name=tsv_filename,
        mime="text/tab-separated-values",
        icon=":material/download:",
        type="primary",
    )


def _render_preview(tsv_data: str, total_rows: int) -> None:
    """Show the first `_PREVIEW_ROWS` rows of the TSV as a clean table.

    Reads only the head of the (already in-memory) TSV string via a
    StringIO reader, so the preview never materializes the whole file again.
    """
    reader = csv.reader(io.StringIO(tsv_data), delimiter="\t")
    header = next(reader, [])
    records: list[dict] = []
    for i, row in enumerate(reader):
        if i >= _PREVIEW_ROWS:
            break
        records.append(
            {col: (val if col == "name" else _as_int(val)) for col, val in zip(header, row)}
        )

    col_cfg: dict = {"name": st.column_config.TextColumn(_TSV_LABELS["name"])}
    for col in header:
        if col == "name":
            continue
        col_cfg[col] = st.column_config.NumberColumn(
            _TSV_LABELS.get(col, col),
            format="%d" if col == "taxon_id" else "localized",
        )

    shown = min(_PREVIEW_ROWS, total_rows)
    st.caption(f"Preview — first {shown} of {total_rows:,} rows")
    st.dataframe(records, column_config=col_cfg, hide_index=True, width="stretch")


def _as_int(val: str):
    try:
        return int(val)
    except (TypeError, ValueError):
        return val
