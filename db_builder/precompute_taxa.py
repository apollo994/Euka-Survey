import logging
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

# Add parent directory to sys.path to import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src import taxonomy
from src.constants import ALLOWED_RANKS, COMMON_CLADES

log = logging.getLogger("euka.precompute_taxa")


def precompute_common_clades(db_path: Path):
    log.info("Connecting to database: %s", db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        log.info("Setting up precomputed_taxa table...")
        conn.execute("DROP TABLE IF EXISTS precomputed_taxa")
        conn.execute("""
            CREATE TABLE precomputed_taxa (
                root_taxid INTEGER,
                target_rank TEXT,
                taxid INTEGER,
                name TEXT
            )
        """)

        # Covering index: WHERE root_taxid=? AND target_rank=? selects taxid, name;
        # including taxid+name in the index lets the planner serve the read from
        # the index alone without touching the table.
        conn.execute("""
            CREATE INDEX idx_precomputed_taxa_cover
            ON precomputed_taxa(root_taxid, target_rank, taxid, name)
        """)

        insert_rows = []
        for root in COMMON_CLADES:
            for rank in ALLOWED_RANKS:
                log.info("Fetching %s combinations for TaxID %d...", rank, root)
                taxa_pairs = taxonomy.get_taxa_at_rank(root, rank)
                for taxid, name in taxa_pairs:
                    insert_rows.append((root, rank, taxid, name))

        log.info("Inserting %d rows into precomputed_taxa...", len(insert_rows))
        conn.executemany("""
            INSERT INTO precomputed_taxa (root_taxid, target_rank, taxid, name)
            VALUES (?, ?, ?, ?)
        """, insert_rows)

        conn.commit()
    log.info("Done! Database is now optimized for UI rendering.")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Precompute taxa for common clades.")
    parser.add_argument("--db", required=True, help="Path to database.")
    args = parser.parse_args()
    precompute_common_clades(Path(args.db))
