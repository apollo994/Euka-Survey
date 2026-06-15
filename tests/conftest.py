"""Shared pytest fixtures.

The `fixture_db` connection provides a minimal in-memory SQLite with the
real schema and known data, so we can test the data layer (database.py)
without needing the full 300 MB `eukaryotes.db`.

Tests that need live ETE3 use `requires_ete3_db` markers; tests that hit
the internet use `network`. Both are skipped by default — opt in with
`-m`.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

# Make `from src import …` work from anywhere under tests/.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# --------------------------------------------------------------------- #
# Synthetic data shared by multiple tests
# --------------------------------------------------------------------- #

# (taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng)
# This is hand-crafted so we can assert exact totals from tests.
#
# Layout (a tiny "Mammalia + Family" universe):
#   100 ROOT             — pretend "Mammalia"-equivalent; rolled-up totals
#   101 HOMINIDAE        — has every kind of data
#   102 BOVIDAE          — assemblies + annotations, no RNA
#   103 PHOCIDAE         — assemblies only
#   104 SORICIDAE        — nothing (empty taxon)
#   105 LONG_TAILED      — only long-read RNA
#   106 SHORT_ONLY_RNA   — only short-read (c_rna=1, c_lng=0)
FIXTURE_CLADE_ROWS: list[tuple] = [
    # taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng
    (100, 600,    400,   300,   500,   100,   1500,   900,   8000,   500),  # root
    (101, 100,    80,    60,    90,    30,    250,    150,    2000,   200),  # has everything
    (102, 80,     40,    35,    0,     0,     120,    100,    0,      0),    # ass+ann, no rna
    (103, 50,     25,    0,     0,     0,     60,     0,      0,      0),    # ass only
    (104, 30,     0,     0,     0,     0,     0,      0,      0,      0),    # empty
    (105, 20,     5,     0,     8,     8,     8,      0,      40,     40),   # long-read only
    (106, 40,     10,    5,     30,    0,     12,     5,      300,    0),    # short-read only
]

# (root_taxid, target_rank, taxid, name) — pretend taxid 100 is a precomputed root,
# the other taxids are its families.
FIXTURE_PRECOMPUTED_TAXA: list[tuple] = [
    (100, "family", 101, "Hominidae"),
    (100, "family", 102, "Bovidae"),
    (100, "family", 103, "Phocidae"),
    (100, "family", 104, "Soricidae"),
    (100, "family", 105, "LongTailedFamily"),
    (100, "family", 106, "ShortOnlyFamily"),
]


@pytest.fixture
def fixture_db():
    """Return an open, populated in-memory sqlite3 connection.

    Schema mirrors the real `eukaryotes.db`. Closed on test teardown.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE precomputed_clade_features (
            taxid INTEGER PRIMARY KEY,
            n_rows INTEGER, c_ass INTEGER, c_ann INTEGER, c_rna INTEGER, c_lng INTEGER,
            s_ass INTEGER, s_ann INTEGER, s_rna INTEGER, s_lng INTEGER
        );
        CREATE TABLE precomputed_taxa (
            root_taxid INTEGER, target_rank TEXT, taxid INTEGER, name TEXT
        );
        CREATE INDEX idx_precomputed_taxa_cover
            ON precomputed_taxa(root_taxid, target_rank, taxid, name);
        """
    )
    conn.executemany(
        "INSERT INTO precomputed_clade_features VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        FIXTURE_CLADE_ROWS,
    )
    conn.executemany(
        "INSERT INTO precomputed_taxa VALUES (?, ?, ?, ?)",
        FIXTURE_PRECOMPUTED_TAXA,
    )
    conn.commit()
    yield conn
    conn.close()


# --------------------------------------------------------------------- #
# Markers / skip helpers
# --------------------------------------------------------------------- #

def pytest_collection_modifyitems(config, items):
    """Skip `network` and `slow` tests unless explicitly selected.

    `-m network` enables network tests; `-m slow` enables slow ones.
    `-m "network or slow"` enables both. No flag → both skipped.
    """
    selected_marks = config.getoption("-m") or ""
    for item in items:
        if "network" in item.keywords and "network" not in selected_marks:
            item.add_marker(pytest.mark.skip(reason="network test — pass `-m network` to enable"))
        if "slow" in item.keywords and "slow" not in selected_marks:
            item.add_marker(pytest.mark.skip(reason="slow test — pass `-m slow` to enable"))
