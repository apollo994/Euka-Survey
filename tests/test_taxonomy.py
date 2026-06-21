"""Tests for `src.taxonomy.resolve_valid_ranks` and related helpers.

These hit live ETE3 (the local `~/.etetoolkit/taxa.sqlite`), so they're
marked `requires_ete3_db`. The lookup itself is local + fast, but if
ETE3's DB isn't available we skip rather than fail.
"""

import os

import pytest

from src.constants import COMMON_CLADES


def _ete3_db_available() -> bool:
    try:
        from ete3 import NCBITaxa
        return os.path.exists(NCBITaxa().dbfile)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ete3_db_available(),
    reason="ETE3 taxonomy DB not available (~/.etetoolkit/taxa.sqlite)",
)


def test_resolve_valid_ranks_for_common_clades():
    """Every COMMON_CLADES root resolves to a non-empty rank tuple
    (except species — but no common clade is species-rank)."""
    from src.taxonomy import resolve_valid_ranks

    for taxid, name in COMMON_CLADES.items():
        ranks = resolve_valid_ranks(taxid)
        assert ranks, f"empty rank tuple for {name} ({taxid})"
        # Every returned rank must be one of ALLOWED_RANKS.
        from src.constants import ALLOWED_RANKS
        assert all(r in ALLOWED_RANKS for r in ranks)


def test_resolve_valid_ranks_mammalia_omits_higher_ranks():
    """Mammalia is at class rank; the dropdown must offer only ranks
    *below* class."""
    from src.taxonomy import resolve_valid_ranks
    ranks = set(resolve_valid_ranks(40674))
    assert "class" not in ranks
    assert "phylum" not in ranks
    # And does include the obviously-below ones:
    assert "family" in ranks
    assert "genus" in ranks
    assert "species" in ranks


def test_resolve_valid_ranks_species_root_returns_empty():
    """A species-rank root (Homo sapiens) has no finer rank — UI shows
    'no further breakdown'."""
    from src.taxonomy import resolve_valid_ranks
    assert resolve_valid_ranks(9606) == ()


def test_resolve_valid_ranks_unknown_taxid_raises():
    from src.taxonomy import resolve_valid_ranks, UnknownTaxonError
    with pytest.raises(UnknownTaxonError):
        resolve_valid_ranks(999_999_999)


def test_resolve_valid_ranks_unranked_falls_back_to_lineage():
    """Vertebrata (7742) is 'no rank' in NCBI taxonomy; we should
    walk the lineage to find the nearest canonical rank above it and
    return ranks below that."""
    from src.taxonomy import resolve_valid_ranks
    ranks = resolve_valid_ranks(7742)
    assert ranks, "lineage fallback should have produced ranks"
    # The nearest canonical ancestor of Vertebrata is Craniata (subphylum)
    # or thereabouts — anything finer than phylum should appear.
    assert "family" in ranks
    assert "species" in ranks


def test_resolve_valid_ranks_is_cached():
    """Repeated calls on the same root must hit the lru_cache (no new
    ETE3 lookup). We can't observe the call directly, but we can
    confirm the cache_info exposes the entry."""
    from src.taxonomy import resolve_valid_ranks
    resolve_valid_ranks.cache_clear()
    resolve_valid_ranks(40674)
    resolve_valid_ranks(40674)
    info = resolve_valid_ranks.cache_info()
    assert info.hits >= 1, f"expected at least one cache hit, got {info}"
