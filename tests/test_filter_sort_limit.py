"""Unit tests on the pure `filter_sort_limit_metadata` helper.

This function is the single source of truth for filter / sort / limit
semantics (audit C1 was closed by unifying the SQL and Python paths
behind it — so testing it well is the cheapest insurance against the
two-paths-out-of-sync class of bug returning).
"""

import pytest

from src.database import FilterLogic, filter_sort_limit_metadata


def _meta(n_rows=10, c_ass=5, c_ann=4, c_rna=3, c_lng=1, s_ass=20, s_ann=15, s_rna=12, s_lng=2):
    """Build a metadata dict with sensible defaults; override what you need."""
    return {
        "n_rows": n_rows,
        "c_ass": c_ass, "c_ann": c_ann, "c_rna": c_rna, "c_lng": c_lng,
        "s_ass": s_ass, "s_ann": s_ann, "s_rna": s_rna, "s_lng": s_lng,
        "p_ass": 0.0, "p_ann": 0.0, "p_rna": 0.0, "p_lng": 0.0,
    }


# --------------------------------------------------------------------- #
# exclude_empty
# --------------------------------------------------------------------- #

def test_exclude_empty_drops_taxa_with_no_coverage():
    metadata = {
        1: _meta(c_ass=0, c_ann=0, c_rna=0, c_lng=0),
        2: _meta(c_ass=1),
    }
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", top_n=10, exclude_empty=True,
    )
    assert 1 not in result
    assert 2 in result
    assert total == 1


def test_exclude_empty_false_keeps_all():
    metadata = {
        1: _meta(c_ass=0, c_ann=0, c_rna=0, c_lng=0),
        2: _meta(c_ass=1),
    }
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", top_n=10, exclude_empty=False,
    )
    assert set(result) == {1, 2}
    assert total == 2


# --------------------------------------------------------------------- #
# filter_keys + filter_logic
# --------------------------------------------------------------------- #

def test_filter_keys_and_requires_all():
    metadata = {
        1: _meta(c_ass=1, c_lng=0),  # has ass, no lng
        2: _meta(c_ass=0, c_lng=1),  # no ass, has lng
        3: _meta(c_ass=1, c_lng=1),  # both
    }
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=["c_ass", "c_lng"],
        filter_logic=FilterLogic.AND, sort_by_key="n_rows",
        top_n=10, exclude_empty=False,
    )
    assert set(result) == {3}
    assert total == 1


def test_filter_keys_or_requires_any():
    metadata = {
        1: _meta(c_ass=1, c_lng=0),
        2: _meta(c_ass=0, c_lng=1),
        3: _meta(c_ass=0, c_lng=0),
    }
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=["c_ass", "c_lng"],
        filter_logic=FilterLogic.OR, sort_by_key="n_rows",
        top_n=10, exclude_empty=False,
    )
    assert set(result) == {1, 2}
    assert total == 2


def test_no_filter_keys_returns_everything():
    metadata = {i: _meta() for i in range(1, 4)}
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", top_n=10, exclude_empty=False,
    )
    assert len(result) == 3
    assert total == 3


# --------------------------------------------------------------------- #
# sort + top_n
# --------------------------------------------------------------------- #

def test_sort_primary_descending():
    metadata = {
        1: _meta(n_rows=5),
        2: _meta(n_rows=30),
        3: _meta(n_rows=10),
    }
    result, _ = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", top_n=10, exclude_empty=False,
    )
    assert list(result) == [2, 3, 1]


def test_top_n_caps_returned_items():
    metadata = {i: _meta(n_rows=100 - i) for i in range(1, 11)}
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", top_n=3, exclude_empty=False,
    )
    assert len(result) == 3
    # total reflects pre-limit match count
    assert total == 10
    assert list(result) == [1, 2, 3]  # highest n_rows are taxids 1..3


def test_secondary_sort_c_to_s():
    """When primary sort is on c_*, tiebreaker is the matching s_*."""
    metadata = {
        1: _meta(c_ass=5, s_ass=100),
        2: _meta(c_ass=5, s_ass=200),  # same c_ass as 1, more s_ass → first
        3: _meta(c_ass=5, s_ass=50),
    }
    result, _ = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="c_ass", top_n=10, exclude_empty=False,
    )
    assert list(result) == [2, 1, 3]


def test_secondary_sort_default_c_ass():
    """When primary sort is on a non-c_* metric, tiebreaker is c_ass."""
    metadata = {
        1: _meta(s_ann=100, c_ass=10),
        2: _meta(s_ann=100, c_ass=20),  # same s_ann, more c_ass → first
        3: _meta(s_ann=100, c_ass=5),
    }
    result, _ = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="s_ann", top_n=10, exclude_empty=False,
    )
    assert list(result) == [2, 1, 3]


# --------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------- #

def test_empty_input_short_circuits():
    result, total = filter_sort_limit_metadata(
        {}, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", top_n=10, exclude_empty=False,
    )
    assert result == {}
    assert total == 0


def test_all_filtered_out_returns_empty():
    metadata = {1: _meta(c_lng=0), 2: _meta(c_lng=0)}
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=["c_lng"],
        filter_logic=FilterLogic.AND, sort_by_key="n_rows",
        top_n=10, exclude_empty=False,
    )
    assert result == {}
    assert total == 0


def test_top_n_zero_returns_empty_but_keeps_total():
    """A user-facing edge case: top_n=0 should never be requested by the
    UI (HARD_NODE_CAP > 0), but the function should not crash."""
    metadata = {1: _meta(), 2: _meta()}
    result, total = filter_sort_limit_metadata(
        metadata, filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", top_n=0, exclude_empty=False,
    )
    assert result == {}
    assert total == 2


@pytest.mark.parametrize("logic", [FilterLogic.AND, FilterLogic.OR])
def test_filter_logic_enum_accepted(logic):
    """Both enum members must be honored — guards against a string
    compare creeping back in."""
    metadata = {1: _meta(c_ass=1)}
    result, _ = filter_sort_limit_metadata(
        metadata, filter_keys=["c_ass"], filter_logic=logic,
        sort_by_key="n_rows", top_n=10, exclude_empty=False,
    )
    assert 1 in result
