"""ETE3-backed taxonomy lookups.

Thin helpers over `ete3.NCBITaxa` for name/rank lookups, plus a direct
recursive-CTE query against ETE3's underlying SQLite taxonomy database for
bulk descendant collection (used by the offline pipeline).
"""

import sqlite3
from contextlib import closing
from functools import lru_cache

from ete3 import NCBITaxa


@lru_cache(maxsize=4096)
def get_name_from_taxid(taxid: int) -> str:
    """Get the scientific name for a given taxonomic ID, or "Unknown"."""
    if not isinstance(taxid, int):
        return "Unknown"
    ncbi = NCBITaxa()
    return ncbi.get_taxid_translator([taxid]).get(taxid, "Unknown")


@lru_cache(maxsize=4096)
def get_rank_from_taxid(taxid: int) -> str:
    """Get the taxonomic rank for a given taxonomic ID, or "clade"."""
    if not isinstance(taxid, int):
        return "clade"
    ncbi = NCBITaxa()
    return ncbi.get_rank([taxid]).get(taxid, "clade")


def get_all_descendant_taxids(parent_taxid: int) -> set[int]:
    """Fetch all descendant taxIDs of `parent_taxid` directly from ETE3's SQLite db."""
    query = """
        WITH RECURSIVE subtree(taxid) AS (
            SELECT taxid FROM species WHERE taxid = ?
            UNION ALL
            SELECT s.taxid FROM species AS s
            JOIN subtree AS t ON s.parent = t.taxid
        )
        SELECT taxid FROM subtree
    """
    db_path = NCBITaxa().dbfile
    uri = f"file:{db_path}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        return {row[0] for row in conn.execute(query, [parent_taxid])}
