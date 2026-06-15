#!/usr/bin/env python3
"""SQL layer over the precomputed feature tables.

Two read paths exist:

1. `build_phylum_metadata(conn, taxids, …)` — bulk fetch by taxid list.
   Used by the non-precomputed (live-ETE3) fallback in app.py and by the
   TSV export.

2. `get_filtered_taxa_metadata(conn, root_taxid, target_rank, …)` —
   SQL-pushed-down JOIN + WHERE + ORDER + LIMIT, only available when
   `precomputed_taxa` contains rows for the given root/rank pair.

Both paths must produce identical output for identical inputs. To keep
them in sync:

- The row → metadata-dict conversion is shared (`_row_to_metadata`).
- Filter / sort / limit semantics are encoded once in
  `filter_sort_limit_metadata` (used by the fallback path). The SQL path
  pushes the same predicates down to SQLite and uses
  `_secondary_sort_key` so the ORDER BY columns match.
- The string label "Match ALL (AND)" / "Match ANY (OR)" no longer
  leaks into the data layer — callers pass a `FilterLogic` enum.
"""

import sqlite3
from enum import Enum
from typing import Iterable

from src.constants import SQLITE_MAX_VARIABLES
from src.metrics import COVERAGE_KEYS, METRICS, PERCENT_KEYS, TOTAL_KEYS


class FilterLogic(str, Enum):
    """How multiple resource-presence filters combine."""
    AND = "AND"
    OR = "OR"


# Column groups derived from src.metrics.METRICS — single source of truth.
_COUNT_KEYS: tuple[str, ...] = ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS
_COVERAGE_KEYS: tuple[str, ...] = COVERAGE_KEYS  # exclude_empty + percentage math
_SQL_COLUMNS: str = ", ".join(("taxid", "n_rows") + COVERAGE_KEYS + TOTAL_KEYS)

# Chunk size for IN-list queries — SQLite has a hard cap of 999 host params
# by default; leave headroom for the other bound parameters in the query.
_IN_CHUNK = SQLITE_MAX_VARIABLES - 99


def _row_to_metadata(row: tuple) -> dict:
    """Build the per-taxid metadata dict from a result row.

    Row order matches `_SQL_COLUMNS`: taxid first, then n_rows, then the
    coverage columns (c_<key> for each metric), then the total columns
    (s_<key> for each metric) — all in METRICS order.
    """
    _, n, *rest = row
    n_metrics = len(METRICS)
    coverage_values = rest[:n_metrics]
    total_values = rest[n_metrics:]
    out: dict = {"n_rows": n}
    out.update(dict(zip(COVERAGE_KEYS, coverage_values)))
    out.update(dict(zip(TOTAL_KEYS, total_values)))
    for c_key, p_key in zip(COVERAGE_KEYS, PERCENT_KEYS):
        out[p_key] = (out[c_key] / n * 100) if n else 0.0
    return out


def _empty_metadata() -> dict:
    """Zero-filled metadata for taxa absent from precomputed_clade_features."""
    return {k: 0 for k in _COUNT_KEYS} | {k: 0.0 for k in PERCENT_KEYS}


def _secondary_sort_key(sort_by_key: str) -> str:
    """Return the tiebreaker column for a given primary sort column.

    When sorting by a `c_*` (covered-species) metric, tie-break by the
    matching `s_*` (total-runs) metric. Otherwise tie-break by `c_ass`.
    Used identically by SQL and Python sort paths.
    """
    if sort_by_key.startswith("c_"):
        return sort_by_key.replace("c_", "s_", 1)
    return "c_ass"


def build_phylum_metadata(conn: sqlite3.Connection, taxids: Iterable[int], exclude_empty: bool = False) -> dict:
    """Fetch per-taxid metadata for a list of taxids.

    Bulk-queries `precomputed_clade_features` in chunks (SQLite host-param
    cap). Taxa absent from the table receive a zero-filled record unless
    `exclude_empty=True`.
    """
    taxids = list(taxids)
    if not taxids:
        return {}

    cursor = conn.cursor()
    phylum_metadata: dict[int, dict] = {}

    for i in range(0, len(taxids), _IN_CHUNK):
        chunk = taxids[i:i + _IN_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        cursor.execute(
            f"SELECT {_SQL_COLUMNS} FROM precomputed_clade_features "
            f"WHERE taxid IN ({placeholders})",
            chunk,
        )
        present = {row[0]: row for row in cursor.fetchall()}

        for taxid in chunk:
            row = present.get(int(taxid))
            if row is None:
                if exclude_empty:
                    continue
                phylum_metadata[taxid] = _empty_metadata()
                continue
            meta = _row_to_metadata(row)
            if exclude_empty and all(meta[k] == 0 for k in _COVERAGE_KEYS):
                continue
            phylum_metadata[taxid] = meta

    return phylum_metadata


def filter_sort_limit_metadata(
    metadata: dict[int, dict],
    *,
    filter_keys: list[str],
    filter_logic: FilterLogic,
    sort_by_key: str,
    top_n: int,
    exclude_empty: bool,
) -> tuple[dict[int, dict], int]:
    """Apply exclude_empty → filter → sort → limit to a metadata dict.

    Pure Python; the canonical implementation of the filter/sort/limit
    semantics. The SQL path (`get_filtered_taxa_metadata`) pushes the
    same predicates down to SQLite and produces equivalent output.

    Returns:
        (limited_metadata, total_matches_before_limit)
    """
    if exclude_empty:
        metadata = {
            tid: m for tid, m in metadata.items()
            if any(m.get(k, 0) > 0 for k in _COVERAGE_KEYS)
        }

    if filter_keys:
        predicate = all if filter_logic == FilterLogic.AND else any
        metadata = {
            tid: m for tid, m in metadata.items()
            if predicate(m.get(k, 0) > 0 for k in filter_keys)
        }

    total_matches = len(metadata)
    if total_matches == 0:
        return {}, 0

    secondary = _secondary_sort_key(sort_by_key)
    sorted_items = sorted(
        metadata.items(),
        key=lambda kv: (kv[1][sort_by_key], kv[1][secondary]),
        reverse=True,
    )
    return dict(sorted_items[:top_n]), total_matches


def get_filtered_taxa_metadata(
    conn: sqlite3.Connection,
    root_taxid: int,
    target_rank: str,
    exclude_empty: bool,
    filter_keys: list[str],
    filter_logic: FilterLogic,
    sort_by_key: str,
    limit: int,
) -> tuple[dict, int]:
    """SQL-pushed-down filter/sort/limit. Only valid when `precomputed_taxa`
    has rows for (root_taxid, target_rank).

    Mirrors `filter_sort_limit_metadata` semantics — the two are kept in
    sync by sharing `_row_to_metadata`, `_secondary_sort_key`, and the
    `FilterLogic` enum.
    """
    cursor = conn.cursor()

    base_query = """
        FROM precomputed_taxa t
        INNER JOIN precomputed_clade_features f ON t.taxid = f.taxid
        WHERE t.root_taxid = ? AND t.target_rank = ?
    """
    params: list = [root_taxid, target_rank]

    where_clauses: list[str] = []
    if exclude_empty:
        where_clauses.append(
            "(" + " OR ".join(f"f.{k} > 0" for k in _COVERAGE_KEYS) + ")"
        )
    if filter_keys:
        joiner = " AND " if filter_logic == FilterLogic.AND else " OR "
        where_clauses.append(
            "(" + joiner.join(f"f.{k} > 0" for k in filter_keys) + ")"
        )

    if where_clauses:
        base_query += " AND " + " AND ".join(where_clauses)

    cursor.execute(f"SELECT COUNT(*) {base_query}", params)
    total_matches = cursor.fetchone()[0]
    if total_matches == 0:
        return {}, 0

    secondary = _secondary_sort_key(sort_by_key)
    select_query = (
        f"SELECT t.taxid, f.n_rows, f.c_ass, f.c_ann, f.c_rna, f.c_lng, "
        f"f.s_ass, f.s_ann, f.s_rna, f.s_lng "
        f"{base_query} "
        f"ORDER BY f.{sort_by_key} DESC, f.{secondary} DESC LIMIT ?"
    )
    cursor.execute(select_query, params + [limit])

    return {row[0]: _row_to_metadata(row) for row in cursor.fetchall()}, total_matches
