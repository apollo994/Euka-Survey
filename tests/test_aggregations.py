"""Tests for `db_builder.precompute_aggregations._precompute_clades_impl`.

These exercise the rollup that produces `precomputed_clade_features`.
Includes the **audit C4 regression test**: a species with no ETE3
lineage must be SKIPPED, not silently attributed only to itself (which
would under-count every ancestor).

The tests use four real NCBI species taxids whose lineages we know
(human, chimp, mouse, zebrafish), build an in-memory `taxid_features`
table by hand, run the rollup, and check the aggregates at known
ancestor taxids (Mammalia, Primates, Eukaryota, etc.).
"""

import os
import sqlite3
from contextlib import closing

import pytest

# All four species share Eukaryota → Bilateria → … common ancestors.
HUMAN     = 9606    # Homo sapiens
CHIMP     = 9598    # Pan troglodytes
MOUSE     = 10090   # Mus musculus
ZEBRAFISH = 7955    # Danio rerio

EUKARYOTA = 2759
ANIMALS   = 33208   # Metazoa
MAMMALIA  = 40674
PRIMATES  = 9443
HOMINIDAE = 9604


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


def _build_taxid_features(rows: list[tuple]) -> sqlite3.Connection:
    """Return an in-memory SQLite with a populated `taxid_features` table.

    rows: (taxid, short_read_count, long_read_count, assembly_count, annotation_count)
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE taxid_features (
            taxid INTEGER PRIMARY KEY,
            short_read_count INTEGER, long_read_count INTEGER,
            assembly_count INTEGER, annotation_count INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO taxid_features VALUES (?, ?, ?, ?, ?)", rows,
    )
    conn.commit()
    return conn


def _read_precomputed(conn: sqlite3.Connection) -> dict[int, dict]:
    """Read the produced `precomputed_clade_features` into a dict."""
    cur = conn.execute(
        "SELECT taxid, n_rows, c_ass, c_ann, c_rna, c_lng, "
        "       s_ass, s_ann, s_rna, s_lng "
        "FROM precomputed_clade_features"
    )
    out = {}
    for row in cur:
        out[row[0]] = {
            "n_rows": row[1], "c_ass": row[2], "c_ann": row[3],
            "c_rna": row[4], "c_lng": row[5], "s_ass": row[6],
            "s_ann": row[7], "s_rna": row[8], "s_lng": row[9],
        }
    return out


# --------------------------------------------------------------------- #
# Rollup correctness
# --------------------------------------------------------------------- #

def test_rollup_credits_every_ancestor():
    """4 species, each with 1 of each resource. Mammalia should aggregate
    3 of them (human, chimp, mouse — not zebrafish); Primates should
    aggregate 2 (human + chimp); Eukaryota should aggregate all 4."""
    from db_builder.precompute_aggregations import _precompute_clades_impl

    rows = [
        # taxid, short, long, ass, ann
        (HUMAN,     5, 1, 2, 3),
        (CHIMP,     2, 0, 1, 1),
        (MOUSE,     4, 2, 3, 2),
        (ZEBRAFISH, 1, 0, 1, 1),
    ]
    with closing(_build_taxid_features(rows)) as conn:
        _precompute_clades_impl(conn)
        agg = _read_precomputed(conn)

    # All four species are in Eukaryota
    assert EUKARYOTA in agg
    assert agg[EUKARYOTA]["n_rows"] == 4
    # Every species had assemblies + annotations + some RNA, so coverage is 4 each
    assert agg[EUKARYOTA]["c_ass"] == 4
    assert agg[EUKARYOTA]["c_ann"] == 4
    assert agg[EUKARYOTA]["c_rna"] == 4
    # Long-read RNA only present in human + mouse (long_read_count > 0)
    assert agg[EUKARYOTA]["c_lng"] == 2
    # Summed runs: 5+2+4+1 (short) + 1+0+2+0 (long) = 15
    assert agg[EUKARYOTA]["s_rna"] == 15
    assert agg[EUKARYOTA]["s_lng"] == 3
    assert agg[EUKARYOTA]["s_ass"] == 7
    assert agg[EUKARYOTA]["s_ann"] == 7

    # Mammalia: human + chimp + mouse (NOT zebrafish)
    assert agg[MAMMALIA]["n_rows"] == 3
    assert agg[MAMMALIA]["s_ass"] == 6   # 2 + 1 + 3
    assert agg[MAMMALIA]["s_rna"] == 14  # 6+2+6
    assert agg[MAMMALIA]["c_lng"] == 2   # human + mouse

    # Primates: human + chimp
    assert agg[PRIMATES]["n_rows"] == 2
    assert agg[PRIMATES]["s_ass"] == 3   # 2 + 1
    assert agg[PRIMATES]["c_lng"] == 1   # only human

    # Hominidae: human + chimp (chimp is in Hominidae too)
    assert agg[HOMINIDAE]["n_rows"] == 2


def test_rollup_filters_non_species_input():
    """A non-species row (e.g. a genus by mistake in taxid_features)
    must be dropped by the species-rank filter, not rolled up."""
    from db_builder.precompute_aggregations import _precompute_clades_impl

    rows = [
        (HUMAN, 5, 1, 2, 3),  # species — kept
        (9605,  1, 0, 1, 0),  # genus Homo — filtered out
    ]
    with closing(_build_taxid_features(rows)) as conn:
        _precompute_clades_impl(conn)
        agg = _read_precomputed(conn)
    # Only the human row should be rolled up into Eukaryota.
    assert agg[EUKARYOTA]["n_rows"] == 1
    assert agg[EUKARYOTA]["s_ass"] == 2  # not 2+1


def test_coverage_versus_count_distinguishes_zero_count_species():
    """c_* is a species-presence count; s_* is the summed runs.
    A species with assembly_count=0 must contribute to n_rows but not c_ass."""
    from db_builder.precompute_aggregations import _precompute_clades_impl

    rows = [
        (HUMAN, 5, 1, 0, 0),  # has RNA but NO assemblies / annotations
        (CHIMP, 0, 0, 1, 1),  # has ass/ann but NO RNA
    ]
    with closing(_build_taxid_features(rows)) as conn:
        _precompute_clades_impl(conn)
        agg = _read_precomputed(conn)

    e = agg[EUKARYOTA]
    assert e["n_rows"] == 2
    assert e["c_ass"] == 1   # chimp only
    assert e["c_ann"] == 1   # chimp only
    assert e["c_rna"] == 1   # human only
    assert e["c_lng"] == 1   # human only
    assert e["s_ass"] == 1
    assert e["s_rna"] == 6   # 5+1


# --------------------------------------------------------------------- #
# Audit C4 regression test — the bug that prompted this test suite
# --------------------------------------------------------------------- #

def test_missing_lineage_taxid_is_skipped_not_self_attributed(monkeypatch):
    """A species with no ETE3 lineage must NOT be self-attributed.

    The pre-fix code had `lineage = [taxid]` as a fallback, which
    silently:

      1. Inflated coverage at the leaf taxid (treating it as a clade
         that "covers itself").
      2. Caused every real ancestor (Mammalia, etc.) to miss this
         species' contribution.

    The bug only fires when a row passes the species-rank filter but
    fails the lineage lookup — a narrow but real case (corrupted
    entries, or taxa whose rank metadata is out of sync with the
    lineage graph). We construct that exact case here by
    monkeypatching ETE3 to claim a synthetic taxid IS a species but
    has NO lineage.

    Verifies:
      - The synthetic taxid does not appear in the output.
      - Eukaryota's rollup contains only HUMAN's contribution.
    """
    from ete3 import NCBITaxa

    from db_builder.precompute_aggregations import _precompute_clades_impl

    SYNTHETIC = 88_888_888

    real_get_rank = NCBITaxa.get_rank
    real_get_lineage_translator = NCBITaxa.get_lineage_translator

    def fake_get_rank(self, taxids):
        result = real_get_rank(self, [t for t in taxids if t != SYNTHETIC])
        if SYNTHETIC in taxids:
            result[SYNTHETIC] = "species"  # pretend it's a species
        return result

    def fake_get_lineage_translator(self, taxids):
        # SYNTHETIC has no lineage — get_lineage_translator omits unknowns
        return real_get_lineage_translator(
            self, [t for t in taxids if t != SYNTHETIC],
        )

    monkeypatch.setattr(NCBITaxa, "get_rank", fake_get_rank)
    monkeypatch.setattr(NCBITaxa, "get_lineage_translator", fake_get_lineage_translator)

    rows = [
        (HUMAN,     5, 1, 2, 3),
        (SYNTHETIC, 9, 9, 9, 9),  # has counts; would be silently miscounted under the bug
    ]
    with closing(_build_taxid_features(rows)) as conn:
        _precompute_clades_impl(conn)
        agg = _read_precomputed(conn)

    # The synthetic taxid must not appear as its own row in the precomputed table.
    assert SYNTHETIC not in agg, "synthetic was self-attributed (audit C4 bug)"

    # And Eukaryota's rollup must contain only HUMAN's contribution.
    e = agg[EUKARYOTA]
    assert e["n_rows"] == 1, f"expected only HUMAN at Eukaryota (n_rows=1), got {e['n_rows']}"
    assert e["s_ass"] == 2, "synthetic should not inflate s_ass (was 2+9=11 under the bug)"
    assert e["s_rna"] == 6, "synthetic should not inflate s_rna"
    assert e["c_lng"] == 1, "only HUMAN has long-read; synthetic should not appear"
