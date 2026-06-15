import csv
import io
import logging
import os
import shutil
import sqlite3
import urllib.request
from contextlib import closing

import streamlit as st

from src import database
from src.constants import (
    DB_SCHEMA_VERSION_CURRENT,
    DB_SCHEMA_VERSION_LEGACY,
    DB_SCHEMA_VERSION_MIN_COMPATIBLE,
)
from src.metrics import METRICS

_DOWNLOAD_TIMEOUT_SECONDS = 300
log = logging.getLogger("euka.utils")


class IncompatibleDatabaseError(RuntimeError):
    """Raised when `eukaryotes.db` exists but is at an incompatible
    schema version. Carries the read version and the compatible range."""

    def __init__(self, found: int, min_compat: int, current: int):
        self.found = found
        self.min_compat = min_compat
        self.current = current
        if found > current:
            msg = (
                f"eukaryotes.db schema version {found} is newer than this app supports "
                f"(max {current}). Update the app or delete eukaryotes.db to re-download."
            )
        else:
            msg = (
                f"eukaryotes.db schema version {found} is older than the minimum "
                f"this app supports ({min_compat}). Delete eukaryotes.db to re-download "
                f"the latest release."
            )
        super().__init__(msg)


def _read_schema_version(db_path: str) -> int:
    """Return the `PRAGMA user_version` of `db_path`. Returns 0 on a
    legacy (pre-stamping) DB; SQLite's default for unstamped DBs is 0."""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    return int(version)


def _check_schema_version(db_path: str) -> None:
    """Validate that `db_path` is at a schema version this app can serve.

    Treats `DB_SCHEMA_VERSION_LEGACY` (0) as equivalent to the current
    minimum-compatible version, so DBs built before the gate existed
    keep working without a forced rebuild.
    """
    found = _read_schema_version(db_path)
    if found == DB_SCHEMA_VERSION_LEGACY:
        log.info(
            "eukaryotes.db has no schema version stamp (legacy build) — "
            "treating as compatible with v%d.", DB_SCHEMA_VERSION_MIN_COMPATIBLE,
        )
        return
    if found < DB_SCHEMA_VERSION_MIN_COMPATIBLE or found > DB_SCHEMA_VERSION_CURRENT:
        raise IncompatibleDatabaseError(
            found, DB_SCHEMA_VERSION_MIN_COMPATIBLE, DB_SCHEMA_VERSION_CURRENT,
        )
    log.info("eukaryotes.db schema version %d — OK.", found)


def ensure_database(db_path, download_url):
    """Ensure the SQLite DB exists and is at a compatible schema version.

    Downloads atomically (`{db_path}.tmp` → `os.replace`) if missing, so
    a network drop never leaves a half-written file. Then validates
    `PRAGMA user_version` against the range the app supports.
    """
    if not os.path.exists(db_path):
        tmp_path = f"{db_path}.tmp"
        try:
            with urllib.request.urlopen(download_url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response, \
                 open(tmp_path, "wb") as out:
                shutil.copyfileobj(response, out)
            os.replace(tmp_path, db_path)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            st.error(f"Could not download database: {e}")
            return False

    try:
        _check_schema_version(db_path)
    except IncompatibleDatabaseError as e:
        st.error(str(e))
        return False

    return True

@st.cache_data(show_spinner="Preparing data for download...")
def generate_tsv(_conn, root_taxid, target_rank, _fetch_func):
    """
    Generate a TSV string for the given query limit dynamically.
    """
    
    # We resolve the actual taxa inside the cached function to avoid hashing huge lists
    query_taxa = _fetch_func(_conn, root_taxid, target_rank)

    if not query_taxa:
        return ""
    
    query_taxids = [t[0] for t in query_taxa]
    taxa_names = {t[0]: t[1] for t in query_taxa}
    
    metadata = database.build_phylum_metadata(_conn, query_taxids, exclude_empty=False)

    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')

    # Single source of truth for the TSV column schema: each entry is
    # (column_name, value_fn). Header row is `[name for name, _ in cols]`
    # and each data row is `[fn(tid, stats) for _, fn in cols]` — so the
    # header cannot drift from the row. Fixed prefix, then per-metric
    # species-covered count, then per-metric total-runs count, all in
    # METRICS order.
    columns: list[tuple[str, callable]] = [
        ("taxon_id", lambda tid, stats: tid),
        ("name", lambda tid, stats: taxa_names.get(tid, "Unknown")),
        ("total_species", lambda tid, stats: int(stats.get("n_rows", 0))),
    ]
    for m in METRICS:
        columns.append((m.tsv_count_column, lambda tid, stats, k=m.coverage_key: int(stats.get(k, 0))))
    for m in METRICS:
        columns.append((m.tsv_total_column, lambda tid, stats, k=m.total_key: int(stats.get(k, 0))))

    writer.writerow([name for name, _ in columns])
    for taxid in query_taxids:
        stats = metadata.get(taxid, {})
        writer.writerow([fn(taxid, stats) for _, fn in columns])

    return output.getvalue()
