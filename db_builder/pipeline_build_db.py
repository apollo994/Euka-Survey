#!/usr/bin/env python3
"""
pipeline_build_db.py — Build a SQLite database of taxIDs with assemblies, annotations, and reads.
"""

import datetime
import logging
import sys
import time
from pathlib import Path

# Add project root to path so we can import src and db_builder modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.constants import EUKARYOTE_TXID
from src.ete_utils import get_all_descendant_taxids
from db_builder.build_db.get_assemblies import get_assemblies
from db_builder.build_db.get_annotations import fetch_annotrieve_annotations
from db_builder.build_db.get_reads import fetch_ena_reads
from db_builder.build_db.build_database import build_database


TOTAL_STEPS = 6
log = logging.getLogger("euka.pipeline")


def main():
    log.info("--- Starting Eukaryote Feature Pipeline ---")
    start_time = time.time()

    log.info("[1/%d] Getting all descendant species...", TOTAL_STEPS)
    all_taxids = get_all_descendant_taxids(EUKARYOTE_TXID)
    log.info("  Found %d descendant species of Eukaryota (taxID %d)", len(all_taxids), EUKARYOTE_TXID)

    log.info("[2/%d] Getting assembly taxids (NCBI datasets CLI)...", TOTAL_STEPS)
    assembly_taxids = get_assemblies(EUKARYOTE_TXID)
    log.info("  Found assemblies for %d unique taxa", len(assembly_taxids))

    log.info("[3/%d] Getting annotation taxids (Annotrieve)...", TOTAL_STEPS)
    annotation_taxids = fetch_annotrieve_annotations()
    log.info("  Found annotations for %d taxa", len(annotation_taxids))

    log.info("[4/%d] Getting short and long read taxids (ENA)...", TOTAL_STEPS)
    long_read_taxids, short_read_taxids, count = fetch_ena_reads()
    log.info("  Fetched %d runs", count)
    log.info("  Long-read unique taxa: %d", len(long_read_taxids))
    log.info("  Short-read unique taxa: %d", len(short_read_taxids))
    # Sanity check: humans/mice dominate transcriptomic ENA runs. Their absence
    # signals a likely truncated or malformed ENA response, not an intentional
    # exclusion (the query in get_reads.py does not exclude them).
    if 9606 not in short_read_taxids and 10090 not in short_read_taxids:
        log.warning(
            "Neither humans (9606) nor mice (10090) found in short-read taxa — "
            "ENA response may have been truncated or the query may need review."
        )

    log.info("[5/%d] Building SQLite database...", TOTAL_STEPS)
    today_str = datetime.date.today().strftime("%Y_%m_%d")
    output_db = Path(f"eukaryote_taxid_features_{today_str}.db")
    log.info("Saving records to %s...", output_db.name)

    rows_written = build_database(
        all_taxids=all_taxids,
        assembly_taxids=assembly_taxids,
        annotation_taxids=annotation_taxids,
        short_read_taxids=short_read_taxids,
        long_read_taxids=long_read_taxids,
        db_path=output_db,
    )

    log.info("[6/%d] Precomputing clade aggregations for web app...", TOTAL_STEPS)
    from db_builder.precompute_aggregations import precompute_clades
    precompute_clades(output_db)

    elapsed = time.time() - start_time
    log.info("Pipeline completed successfully in %.2f seconds.", elapsed)
    log.info("Wrote %d records to %s.", rows_written, output_db.name)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    main()
