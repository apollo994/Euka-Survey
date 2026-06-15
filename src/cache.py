"""All `@st.cache_*` wrappers for the Streamlit app.

Closes Phase 2 #28 of the refactor audit. These wrappers are the only
place where Streamlit caching policy (max_entries, show_spinner) is
applied to the underlying `src/` data functions. Keeping them in one
module means:

- The data layer (`src/database.py`, `src/visualization.py`, etc.) has
  no Streamlit imports — easier to test in isolation.
- Cache tuning lives in one file rather than scattered across the UI.
- The UI modules under `ui/` just call these wrappers and don't see
  the cache decorators at all.

Two layers of caching are in use:

- `@st.cache_resource`: process-lifetime singletons. Used for the DB
  download check and the read-only SQLite connection.
- `@st.cache_data`: keyed cache. Used for the query results that the
  UI re-requests on every rerun (taxa counts, metadata, rendered SVG).
"""

import multiprocessing as mp
import os
import sqlite3
import tempfile

import streamlit as st

from src import database, taxonomy, utils, visualization
from src.constants import (
    DB_DOWNLOAD_URL,
    DB_PATH,
    RENDER_SUBPROCESS_TIMEOUT_SECONDS,
)


@st.cache_resource(show_spinner="Downloading Database (this happens once)...")
def get_db_ready() -> bool:
    """Ensure the SQLite DB exists and is at a compatible schema version.

    On first run downloads from `DB_DOWNLOAD_URL` to `DB_PATH`
    atomically; on subsequent runs just validates `PRAGMA user_version`.
    """
    if utils.ensure_database(DB_PATH, DB_DOWNLOAD_URL):
        return True
    raise RuntimeError("Database download failed. Restart the app to retry.")


@st.cache_resource
def get_db_connection() -> sqlite3.Connection:
    """Open a read-only, thread-safe connection to the precomputed DB.

    `check_same_thread=False` is required because Streamlit runs
    callbacks on worker threads. The connection is read-only so this
    is safe.
    """
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)


@st.cache_data(max_entries=200, show_spinner=False)
def get_taxa_count_cached(_conn: sqlite3.Connection, root_taxid: int, target_rank: str) -> int:
    """Fast SQL count of `precomputed_taxa` rows for the chosen
    (root, rank) pair — feeds the "Tree size: N nodes" indicator
    without loading the rows themselves."""
    if not root_taxid or not target_rank:
        return 0
    try:
        cursor = _conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM precomputed_taxa WHERE root_taxid = ? AND target_rank = ?",
            (int(root_taxid), target_rank),
        )
        result = cursor.fetchone()
        return result[0] if result else 0
    except sqlite3.OperationalError:
        return 0


@st.cache_data(max_entries=200, show_spinner=False)
def fetch_taxa_cached(_conn: sqlite3.Connection, root_taxid: int, target_rank: str):
    """Resolve a (root, rank) pair to a list of `(taxid, name)` tuples.

    Tries `precomputed_taxa` first (fast SQL); falls back to live ETE3
    traversal via `taxonomy.get_taxa_at_rank` for non-canonical roots.
    """
    if root_taxid is None or target_rank is None:
        return None
    try:
        cursor = _conn.cursor()
        cursor.execute(
            "SELECT taxid, name FROM precomputed_taxa WHERE root_taxid = ? AND target_rank = ?",
            (int(root_taxid), target_rank),
        )
        rows = cursor.fetchall()
        if rows:
            return [(row[0], row[1]) for row in rows]
    except sqlite3.OperationalError:
        pass  # table may not exist yet

    return taxonomy.get_taxa_at_rank(root_taxid, target_rank)


@st.cache_data(max_entries=100, show_spinner=False)
def get_phylum_metadata_cached(_conn: sqlite3.Connection, taxids: tuple, exclude_empty: bool) -> dict:
    """Bulk per-taxid metadata fetch. Wrap `database.build_phylum_metadata`."""
    return database.build_phylum_metadata(_conn, list(taxids), exclude_empty)


@st.cache_data(max_entries=50, show_spinner=False)
def get_filtered_taxa_metadata_cached(
    _conn: sqlite3.Connection,
    root_taxid: int,
    target_rank: str,
    exclude_empty: bool,
    filter_keys_tuple: tuple,
    filter_logic: database.FilterLogic,
    sort_by_key: str,
    top_n: int,
):
    """SQL-pushdown filter/sort/limit when the root/rank pair is
    precomputed. Wraps `database.get_filtered_taxa_metadata`."""
    return database.get_filtered_taxa_metadata(
        _conn, root_taxid, target_rank, exclude_empty,
        list(filter_keys_tuple), filter_logic, sort_by_key, top_n,
    )


@st.cache_data(max_entries=50, show_spinner=False)
def generate_tree_svg_cached(phylum_metadata: dict, include_counts: bool) -> bytes | None:
    """Render the phylogenetic tree SVG in a spawned subprocess.

    PyQt5 requires its QApplication on the main thread of a process;
    Streamlit runs callbacks on worker threads, hence the subprocess.
    A timeout (`RENDER_SUBPROCESS_TIMEOUT_SECONDS`) guards against a
    stuck Qt child hanging the Streamlit thread indefinitely.
    """
    tmp_fd, tmp_svg = tempfile.mkstemp(prefix="euka_tree_", suffix=".svg")
    os.close(tmp_fd)

    ctx = mp.get_context("spawn")
    p = ctx.Process(
        target=visualization.render_tree_in_process,
        args=(phylum_metadata, include_counts, tmp_svg),
    )
    p.start()
    p.join(timeout=RENDER_SUBPROCESS_TIMEOUT_SECONDS)

    try:
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
            if p.is_alive():
                p.kill()
            return None

        if p.exitcode != 0 or not os.path.exists(tmp_svg) or os.path.getsize(tmp_svg) == 0:
            return None

        with open(tmp_svg, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_svg):
            os.remove(tmp_svg)
