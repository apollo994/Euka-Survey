"""Shared constants for the EukaSurvey app and db_builder pipeline.

Single source of truth for taxonomic IDs, ranks, and UI limits that were
previously duplicated across app.py, db_builder/precompute_taxa.py, and the
db_builder/build_db/* modules.
"""

EUKARYOTE_TXID: int = 2759

COMMON_CLADES: dict[int, str] = {
    2759: "Eukaryota",
    33208: "Animals",
    40674: "Mammalia",
    9443: "Primates",
    4751: "Fungi",
    33090: "Plants",
}

ALLOWED_RANKS: list[str] = [
    "phylum", "class", "order", "family", "genus", "species",
]

FULL_RANKS: list[str] = [
    "domain", "superkingdom", "kingdom",
    "superphylum", "phylum", "subphylum",
    "superclass", "class", "subclass",
    "superorder", "order", "suborder",
    "superfamily", "family", "subfamily",
    "genus", "subgenus", "species",
]

HARD_NODE_CAP: int = 500
STANDARD_BREAKPOINTS: list[int] = [10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500]

SQLITE_MAX_VARIABLES: int = 999

RENDER_SUBPROCESS_TIMEOUT_SECONDS: int = 120
