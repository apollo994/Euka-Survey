import logging
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from src.ete_utils import get_ncbi

log = logging.getLogger("euka.precompute_aggregations")


def precompute_clades(db_path: Path):
    """
    Reads the leaf-level 'taxid_features' table, calculates the aggregations
    for every ancestral clade, and creates a fast precomputed table.
    """
    log.info("Connecting to database: %s", db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        _precompute_clades_impl(conn)


_LINEAGE_CHUNK = 50_000


def _batched(seq: list, n: int):
    """Yield successive `n`-sized chunks from `seq`."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _precompute_clades_impl(conn: sqlite3.Connection) -> None:
    ncbi = get_ncbi()

    cursor = conn.cursor()
    cursor.execute(
        "SELECT taxid, short_read_count, long_read_count, assembly_count, annotation_count "
        "FROM taxid_features"
    )
    leaf_rows = cursor.fetchall()
    log.info("Loaded %d leaf rows with features.", len(leaf_rows))

    log.info("Filtering to only include 'species' rank (chunked)...")
    all_raw_taxids = [row[0] for row in leaf_rows]
    ranks: dict[int, str] = {}
    for chunk in _batched(all_raw_taxids, _LINEAGE_CHUNK):
        try:
            ranks.update(ncbi.get_rank(chunk))
        except Exception as e:
            log.warning("get_rank chunk failed (%d taxids): %s", len(chunk), e)

    leaf_rows = [row for row in leaf_rows if ranks.get(row[0]) == "species"]
    log.info("Kept %d species-rank rows after filtering.", len(leaf_rows))

    # Dictionary to hold the aggregations for each ancestor.
    # Structure: clade_taxid -> {'n_rows', 'c_ass', 'c_ann', 'c_rna', 'c_lng',
    #                            's_ass', 's_ann', 's_rna', 's_lng'}
    clade_aggs = defaultdict(lambda: {
        'n_rows': 0, 'c_ass': 0, 'c_ann': 0, 'c_rna': 0, 'c_lng': 0,
        's_ass': 0, 's_ann': 0, 's_rna': 0, 's_lng': 0,
    })

    log.info("Resolving lineages in %d-chunk batches...", _LINEAGE_CHUNK)
    all_taxids = [row[0] for row in leaf_rows]
    lineages: dict[int, list[int]] = {}
    for chunk in _batched(all_taxids, _LINEAGE_CHUNK):
        try:
            lineages.update(ncbi.get_lineage_translator(chunk))
        except KeyError as e:
            log.warning("get_lineage_translator chunk failed (%d taxids): %s", len(chunk), e)

    log.info("Rolling up %d species into ancestor aggregates...", len(leaf_rows))
    start_time = time.time()
    missing_lineages = 0

    for row in leaf_rows:
        taxid = row[0]
        s_short, s_long, s_ass, s_ann = row[1], row[2], row[3], row[4]

        lineage = lineages.get(taxid)
        if not lineage:
            # Audit C4: previously this row was attributed only to itself
            # (`lineage = [taxid]`), which silently under-counted every
            # ancestor above it. Skipping is correct: without a lineage
            # we cannot determine which ancestors this species belongs to.
            missing_lineages += 1
            continue

        has_ass = 1 if s_ass > 0 else 0
        has_ann = 1 if s_ann > 0 else 0
        has_rna = 1 if (s_short > 0 or s_long > 0) else 0
        has_lng = 1 if s_long > 0 else 0

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
            "%d species had no valid taxonomy lineage in ete3 and were SKIPPED "
            "(not counted against any ancestor). Investigate if this count is large.",
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
