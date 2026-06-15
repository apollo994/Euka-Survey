"""Network smoke test for the ENA portal API integration.

Skipped by default. Enable with: `pytest -m network`.

The test runs a SMALL query (against Homo sapiens only, not all of
Eukaryota) so we don't pull millions of rows just to validate the
shape of the response. The goal is to catch:

- An API endpoint change (new column names, dropped columns).
- A `format=json` row count of zero (the swallowed-error class of bug
  that bit us when reverting the TSV streaming attempt — audit C3).
- A mismatch between what we claim to fetch and what we actually get.

It does NOT validate exact counts — those can change daily as new
runs are deposited.
"""

import pytest

pytestmark = pytest.mark.network


def _patched_query():
    """Build a tiny ENA query so the network round-trip stays cheap."""
    return (
        'tax_tree(9606) AND '
        '(library_source="transcriptomic" OR library_strategy="rna-seq")'
    )


@pytest.fixture
def small_query(monkeypatch):
    """Swap the module-level EUKARYOTE_TXID inside get_reads for the
    duration of this test so we hit Homo sapiens (9606) instead of
    Eukaryota (2759). Restored on teardown."""
    from db_builder.build_db import get_reads
    monkeypatch.setattr(get_reads, "EUKARYOTE_TXID", 9606)


def test_ena_response_shape(small_query):
    """Hit ENA with a small query, verify the response is well-formed
    and at least one row was returned."""
    from db_builder.build_db.get_reads import fetch_ena_reads

    long_reads, short_reads, total = fetch_ena_reads()

    assert total > 0, "ENA returned zero rows for Homo sapiens RNA-Seq"
    assert isinstance(long_reads, dict)
    assert isinstance(short_reads, dict)
    # The keys should be ints (taxids) and the values positive counts.
    for d in (long_reads, short_reads):
        for taxid, count in d.items():
            assert isinstance(taxid, int)
            assert count > 0
    # Total should equal long + short summed counts.
    assert total == sum(long_reads.values()) + sum(short_reads.values())


def test_ena_short_reads_dominate_for_human(small_query):
    """Most human RNA-Seq runs are Illumina; the short-read bucket
    should outnumber the long-read bucket by at least an order of
    magnitude. Sanity check against accidentally swapping the
    long/short categorization."""
    from db_builder.build_db.get_reads import fetch_ena_reads

    long_reads, short_reads, _ = fetch_ena_reads()
    short_total = sum(short_reads.values())
    long_total = sum(long_reads.values())

    assert short_total > 0
    # Loosely: short ≫ long. Even a 5× ratio would be surprising
    # for human RNA-Seq.
    assert short_total > 5 * long_total, (
        f"Suspicious: short={short_total} long={long_total} "
        "— check the long-/short-read categorization in get_reads.py."
    )
