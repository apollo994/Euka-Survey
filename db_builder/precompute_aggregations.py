import logging
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from ete3 import NCBITaxa

log = logging.getLogger("euka.precompute_aggregations")


def precompute_clades(db_path: Path):
    """
    Reads the leaf-level 'taxid_features' table, calculates the aggregations
    for every ancestral clade, and creates a fast precomputed table.
    """
    log.info("Connecting to database: %s", db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        _precompute_clades_impl(conn)


def _precompute_clades_impl(conn: sqlite3.Connection) -> None:
    ncbi = NCBITaxa()

    cursor = conn.cursor()
    cursor.execute(
        "SELECT taxid, short_read_count, long_read_count, assembly_count, annotation_count "
        "FROM taxid_features"
    )
    leaf_rows = cursor.fetchall()
    log.info("Loaded %d leaf rows with features.", len(leaf_rows))

    log.info("Filtering to only include 'species' rank...")
    all_raw_taxids = [row[0] for row in leaf_rows]
    try:
        ranks = ncbi.get_rank(all_raw_taxids)
    except Exception:
        ranks = {}

    leaf_rows = [row for row in leaf_rows if ranks.get(row[0]) == "species"]
    log.info("Kept %d species-rank rows after filtering.", len(leaf_rows))

    # Dictionary to hold the aggregations for each ancestor
    # Structure: clade_taxid -> {'n_rows', 'c_ass', 'c_ann', 'c_rna', 'c_lng', 's_ass', 's_ann', 's_rna', 's_lng'}
    clade_aggs = defaultdict(lambda: {
        'n_rows': 0, 'c_ass': 0, 'c_ann': 0, 'c_rna': 0, 'c_lng': 0,
        's_ass': 0, 's_ann': 0, 's_rna': 0, 's_lng': 0,
    })

    log.info("Rolling up lineages (this will take a moment)...")
    start_time = time.time()

    all_taxids = [row[0] for row in leaf_rows]

    # ETE3 generates warnings for taxids not found, we handle gracefully.
    try:
        lineages = ncbi.get_lineage_translator(all_taxids)
    except KeyError:
        lineages = {}

    missing_lineages = 0

    for row in leaf_rows:
        taxid = row[0]
        s_short, s_long, s_ass, s_ann = row[1], row[2], row[3], row[4]

        has_ass = 1 if s_ass > 0 else 0
        has_ann = 1 if s_ann > 0 else 0
        has_rna = 1 if (s_short > 0 or s_long > 0) else 0
        has_lng = 1 if s_long > 0 else 0

        lineage = lineages.get(taxid, [])
        if not lineage:
            missing_lineages += 1
            lineage = [taxid]  # fallback to just itself

        for ancestor in lineage:
            agg = clade_aggs[ancestor]
            agg['n_rows'] += 1
            agg['c_ass'] += has_ass
            agg['c_ann'] += has_ann
            agg['c_rna'] += has_rna
            agg['c_lng'] += has_lng
            agg['s_ass'] += s_ass
            agg['s_ann'] += s_ann
            agg['s_rna'] += s_short + s_long
            agg['s_lng'] += s_long

    if missing_lineages > 0:
        log.warning(
            "%d taxids had no valid taxonomy lineage in ete3 and contributed only to themselves.",
            missing_lineages,
        )

    log.info(
        "Precomputed %d distinct clade nodes in %.2f seconds.",
        len(clade_aggs), time.time() - start_time,
    )

    log.info("Writing to precomputed_clade_features table...")
    conn.execute("DROP TABLE IF EXISTS precomputed_clade_features")
    conn.execute("""
        CREATE TABLE precomputed_clade_features (
            taxid INTEGER PRIMARY KEY,
            n_rows INTEGER,
            c_ass INTEGER,
            c_ann INTEGER,
            c_rna INTEGER,
            c_lng INTEGER,
            s_ass INTEGER,
            s_ann INTEGER,
            s_rna INTEGER,
            s_lng INTEGER
        )
    """)

    insert_rows = [
        (tid, a['n_rows'], a['c_ass'], a['c_ann'], a['c_rna'], a['c_lng'],
         a['s_ass'], a['s_ann'], a['s_rna'], a['s_lng'])
        for tid, a in clade_aggs.items()
    ]

    conn.executemany("""
        INSERT INTO precomputed_clade_features
        (taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, insert_rows)

    conn.commit()
    log.info("Done! Database is now optimized for the web.")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Precompute clade feature aggregations.")
    parser.add_argument("--db", required=True, help="Path to your eukaryotes.db file.")
    args = parser.parse_args()
    precompute_clades(Path(args.db))
