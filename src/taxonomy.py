#!/usr/bin/env python3
"""Live ETE3 fallbacks for taxonomy queries the app can't get from
`precomputed_taxa` or the existing cached helpers in `src.ete_utils`.

These are slower paths invoked only when the precomputed lookup misses:
- `resolve_valid_ranks` powers the dynamic "Breakdown rank" dropdown
  (which ranks are *below* a given root).
- `get_taxa_at_rank` lists `(taxid, name)` pairs at a given rank under a
  root for non-canonical root taxa.
"""

from functools import lru_cache

from src.constants import ALLOWED_RANKS, FULL_RANKS
from src.ete_utils import get_ncbi


class UnknownTaxonError(ValueError):
    """Raised when a taxid is not present in the local ETE3 taxonomy DB."""


def get_taxa_at_rank(root_taxid: int, rank: str) -> list[tuple[int, str]]:
    """Return all (taxid, name) pairs at the given rank under root_taxid.

    Slow path — used only when (root_taxid, rank) is not in
    `precomputed_taxa`. Wrapped by `@st.cache_data` in app.py so the
    cost is paid at most once per (root_taxid, rank) per session.

    Implementation note: a recursive-CTE rewrite against ETE3's local
    SQLite was investigated and proved slower (3–30× depending on
    clade depth) because the `species` table has no index on `parent`.
    The `track`-column LIKE approach is a single full scan (~1.5 s) and
    is also slower than ETE3's internal path for narrow clades.
    `NCBITaxa.get_descendant_taxa` already uses ETE3's optimized
    traversal, so we delegate.
    """
    ncbi = get_ncbi()
    descendants = ncbi.get_descendant_taxa(root_taxid, intermediate_nodes=True)
    ranks = ncbi.get_rank(descendants)
    hits = [taxid for taxid, r in ranks.items() if r == rank]
    names = ncbi.get_taxid_translator(hits)
    return sorted(names.items(), key=lambda x: x[1])


@lru_cache(maxsize=512)
def resolve_valid_ranks(root_taxid: int) -> tuple[str, ...]:
    """Return the ranks (subset of ALLOWED_RANKS) strictly below `root_taxid`'s own rank.

    The web app's rank dropdown is restricted to ranks finer than the
    root taxon's own rank. This used to run live ETE3 on every Streamlit
    rerun; cached here so each unique root_taxid resolves at most once
    per process.

    Raises `UnknownTaxonError` if the taxid is not in the local taxonomy.
    """
    ncbi = get_ncbi()

    try:
        root_rank = ncbi.get_rank([root_taxid]).get(root_taxid, "no rank")
    except ValueError as e:
        raise UnknownTaxonError(str(root_taxid)) from e

    # Fallback: walk lineage to find the nearest canonical rank.
    if root_rank not in FULL_RANKS:
        try:
            lineage = ncbi.get_lineage(root_taxid)
        except ValueError as e:
            raise UnknownTaxonError(str(root_taxid)) from e
        if not lineage:
            raise UnknownTaxonError(str(root_taxid))
        lin_ranks = ncbi.get_rank(lineage)
        for ancestor in reversed(lineage):
            candidate = lin_ranks.get(ancestor, "no rank")
            if candidate in FULL_RANKS:
                root_rank = candidate
                break

    if root_rank not in FULL_RANKS:
        # Unranked or otherwise unresolvable — allow the full dropdown.
        return tuple(ALLOWED_RANKS)

    root_idx = FULL_RANKS.index(root_rank)
    return tuple(r for r in ALLOWED_RANKS if FULL_RANKS.index(r) > root_idx)
