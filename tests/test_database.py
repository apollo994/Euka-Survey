"""Tests on `src.database` against the synthetic in-memory fixture DB.

This is the main regression net for the unification refactor (audit C1).
If `get_filtered_taxa_metadata` (SQL) ever drifts from
`filter_sort_limit_metadata` (Python), parametrized parity tests
below will catch it.
"""

import pytest

from src import database
from src.database import FilterLogic
from tests.conftest import FIXTURE_CLADE_ROWS

ROOT_TAXID = 100  # the synthetic precomputed root in conftest
RANK = "family"
EXPECTED_TAXIDS = {101, 102, 103, 104, 105, 106}


# --------------------------------------------------------------------- #
# build_phylum_metadata
# --------------------------------------------------------------------- #

def test_build_phylum_metadata_returns_known_rows(fixture_db):
    meta = database.build_phylum_metadata(fixture_db, [101, 102, 103])
    assert set(meta) == {101, 102, 103}
    assert meta[101]["c_ass"] == 80
    assert meta[101]["s_rna"] == 2000


def test_build_phylum_metadata_zero_fills_unknown_taxids(fixture_db):
    """A taxid not in `precomputed_clade_features` should get a
    zero-filled record when exclude_empty=False (so callers can
    distinguish 'no data' from 'taxon missing entirely')."""
    meta = database.build_phylum_metadata(fixture_db, [101, 999999], exclude_empty=False)
    assert set(meta) == {101, 999999}
    assert meta[999999]["n_rows"] == 0
    assert meta[999999]["c_ass"] == 0


def test_build_phylum_metadata_exclude_empty_drops_zero_and_missing(fixture_db):
    meta = database.build_phylum_metadata(
        fixture_db, [101, 104, 999999], exclude_empty=True,
    )
    # 101 has data, 104 is empty (all c_* = 0), 999999 is missing entirely
    assert set(meta) == {101}


def test_build_phylum_metadata_handles_empty_input(fixture_db):
    assert database.build_phylum_metadata(fixture_db, []) == {}


def test_build_phylum_metadata_chunked_query_respects_sqlite_limit(fixture_db):
    """The IN-list query is chunked to stay under SQLite's host-variable
    cap. Passing many taxids should still return the known ones."""
    inputs = list(range(101, 107)) + list(range(200, 200 + 2000))
    meta = database.build_phylum_metadata(fixture_db, inputs, exclude_empty=True)
    assert set(meta) == {101, 102, 103, 105, 106}  # 104 dropped by exclude_empty


def test_build_phylum_metadata_percentages_match_counts(fixture_db):
    meta = database.build_phylum_metadata(fixture_db, [101])
    m = meta[101]
    assert m["p_ass"] == pytest.approx(80 / 100 * 100)  # 80.0
    assert m["p_ann"] == pytest.approx(60 / 100 * 100)  # 60.0


# --------------------------------------------------------------------- #
# get_filtered_taxa_metadata — basic SQL behavior
# --------------------------------------------------------------------- #

def test_get_filtered_returns_all_when_no_filters(fixture_db):
    meta, total = database.get_filtered_taxa_metadata(
        fixture_db, ROOT_TAXID, RANK, exclude_empty=False,
        filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", limit=100,
    )
    assert total == len(EXPECTED_TAXIDS)
    assert set(meta) == EXPECTED_TAXIDS


def test_get_filtered_exclude_empty_drops_104(fixture_db):
    """Taxid 104 has all c_* = 0 in the fixture."""
    meta, total = database.get_filtered_taxa_metadata(
        fixture_db, ROOT_TAXID, RANK, exclude_empty=True,
        filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", limit=100,
    )
    assert 104 not in meta
    assert total == len(EXPECTED_TAXIDS) - 1


def test_get_filtered_and_logic(fixture_db):
    """Three fixture taxa have BOTH c_ass>0 AND c_rna>0: 101, 105, 106.
    (102 has assemblies but no RNA; 103 has assemblies only; 104 is empty.)"""
    meta, total = database.get_filtered_taxa_metadata(
        fixture_db, ROOT_TAXID, RANK, exclude_empty=False,
        filter_keys=["c_ass", "c_rna"], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", limit=100,
    )
    assert set(meta) == {101, 105, 106}
    assert total == 3


def test_get_filtered_or_logic(fixture_db):
    """Anyone with c_ass>0 OR c_rna>0 → 101, 102, 103, 105, 106."""
    meta, total = database.get_filtered_taxa_metadata(
        fixture_db, ROOT_TAXID, RANK, exclude_empty=False,
        filter_keys=["c_ass", "c_rna"], filter_logic=FilterLogic.OR,
        sort_by_key="n_rows", limit=100,
    )
    assert set(meta) == {101, 102, 103, 105, 106}
    assert total == 5


def test_get_filtered_limit_caps_results(fixture_db):
    meta, total = database.get_filtered_taxa_metadata(
        fixture_db, ROOT_TAXID, RANK, exclude_empty=False,
        filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", limit=2,
    )
    assert len(meta) == 2
    # total still reflects pre-limit match count
    assert total == len(EXPECTED_TAXIDS)


def test_get_filtered_sort_order_descending(fixture_db):
    """Highest n_rows first. From fixture: 101=100, 102=80, 103=50,
    106=40, 104=30, 105=20."""
    meta, _ = database.get_filtered_taxa_metadata(
        fixture_db, ROOT_TAXID, RANK, exclude_empty=False,
        filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", limit=100,
    )
    assert list(meta) == [101, 102, 103, 106, 104, 105]


def test_get_filtered_no_matches_returns_empty(fixture_db):
    """Unknown root_taxid: zero matches."""
    meta, total = database.get_filtered_taxa_metadata(
        fixture_db, 999999, RANK, exclude_empty=False,
        filter_keys=[], filter_logic=FilterLogic.AND,
        sort_by_key="n_rows", limit=100,
    )
    assert meta == {}
    assert total == 0


# --------------------------------------------------------------------- #
# Parity: SQL path == Python helper, across a matrix of scenarios
# --------------------------------------------------------------------- #

PARITY_SCENARIOS = [
    # (exclude_empty, filter_keys, filter_logic, sort_by_key, top_n)
    (False, [],                    FilterLogic.AND, "n_rows", 100),
    (True,  [],                    FilterLogic.AND, "c_ass",  100),
    (True,  ["c_ass"],             FilterLogic.AND, "s_ass",  100),
    (True,  ["c_ass", "c_lng"],    FilterLogic.AND, "s_ann",  100),
    (False, ["c_ass", "c_lng"],    FilterLogic.OR,  "c_rna",  100),
    (False, ["c_ann"],             FilterLogic.AND, "s_rna",  100),
    # limit edge cases
    (False, [],                    FilterLogic.AND, "n_rows", 2),
    (False, [],                    FilterLogic.AND, "n_rows", 1),
    # sort by every defined metric
    (False, [],                    FilterLogic.AND, "c_ass",  100),
    (False, [],                    FilterLogic.AND, "c_ann",  100),
    (False, [],                    FilterLogic.AND, "c_rna",  100),
    (False, [],                    FilterLogic.AND, "c_lng",  100),
    (False, [],                    FilterLogic.AND, "s_ass",  100),
    (False, [],                    FilterLogic.AND, "s_ann",  100),
    (False, [],                    FilterLogic.AND, "s_rna",  100),
    (False, [],                    FilterLogic.AND, "s_lng",  100),
]


@pytest.mark.parametrize(
    "exclude_empty,filter_keys,filter_logic,sort_by_key,top_n", PARITY_SCENARIOS
)
def test_sql_path_matches_python_path(
    fixture_db, exclude_empty, filter_keys, filter_logic, sort_by_key, top_n,
):
    """The SQL pushdown path and the Python helper must return
    byte-identical totals, taxid sets, ordering, and metadata."""
    # SQL path
    sql_meta, sql_total = database.get_filtered_taxa_metadata(
        fixture_db, ROOT_TAXID, RANK, exclude_empty,
        filter_keys, filter_logic, sort_by_key, top_n,
    )

    # Python path: fetch unfiltered metadata first (this is what the
    # non-precomputed fallback in app.py does), then run the helper.
    raw = database.build_phylum_metadata(
        fixture_db, list(EXPECTED_TAXIDS), exclude_empty=False,
    )
    py_meta, py_total = database.filter_sort_limit_metadata(
        raw,
        filter_keys=filter_keys,
        filter_logic=filter_logic,
        sort_by_key=sort_by_key,
        top_n=top_n,
        exclude_empty=exclude_empty,
    )

    assert sql_total == py_total, "total_matches differ"
    assert set(sql_meta) == set(py_meta), "key sets differ"
    assert list(sql_meta) == list(py_meta), "ordering differs"
    for tid in sql_meta:
        assert sql_meta[tid] == py_meta[tid], f"values differ at taxid {tid}"
