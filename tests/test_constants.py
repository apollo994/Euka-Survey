"""Sanity checks on shared constants.

Cheap regression net — these run in milliseconds and would catch e.g.
a typo'd taxid, an `ALLOWED_RANKS` entry missing from `FULL_RANKS`,
or a chunk-size constant clobbering SQLite's host-variable cap.
"""

from src.constants import (
    ALLOWED_RANKS,
    COMMON_CLADES,
    EUKARYOTE_TXID,
    FULL_RANKS,
    HARD_NODE_CAP,
    RENDER_SUBPROCESS_TIMEOUT_SECONDS,
    SQLITE_MAX_VARIABLES,
    STANDARD_BREAKPOINTS,
)


def test_eukaryote_txid_is_2759():
    assert EUKARYOTE_TXID == 2759


def test_common_clades_well_formed():
    assert len(COMMON_CLADES) >= 1
    for taxid, name in COMMON_CLADES.items():
        assert isinstance(taxid, int) and taxid > 0
        assert isinstance(name, str) and name


def test_eukaryota_is_a_common_clade():
    """The pipeline + UI both root themselves at Eukaryota — losing it
    from COMMON_CLADES would break both."""
    assert EUKARYOTE_TXID in COMMON_CLADES


def test_allowed_ranks_subset_of_full_ranks():
    assert set(ALLOWED_RANKS).issubset(FULL_RANKS)


def test_allowed_ranks_in_canonical_order():
    """ALLOWED_RANKS must appear in the same coarse→fine order as
    FULL_RANKS, since `taxonomy.resolve_valid_ranks` uses index-based
    'strictly finer' comparisons."""
    idx = [FULL_RANKS.index(r) for r in ALLOWED_RANKS]
    assert idx == sorted(idx)


def test_full_ranks_unique():
    assert len(FULL_RANKS) == len(set(FULL_RANKS))


def test_hard_node_cap_positive():
    assert HARD_NODE_CAP > 0


def test_standard_breakpoints_sorted_and_capped():
    assert STANDARD_BREAKPOINTS == sorted(STANDARD_BREAKPOINTS)
    assert STANDARD_BREAKPOINTS[-1] <= HARD_NODE_CAP


def test_sqlite_max_variables_at_sqlite_default():
    """The chunking in database.py is keyed on this. Going above 999
    would risk `too many SQL variables` errors on older SQLite builds."""
    assert SQLITE_MAX_VARIABLES <= 999


def test_render_subprocess_timeout_sane():
    assert 10 <= RENDER_SUBPROCESS_TIMEOUT_SECONDS <= 600
