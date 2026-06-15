#!/usr/bin/env python3
"""
pipeline_build_db.py — Build a SQLite database of taxIDs with assemblies, annotations, and reads.
"""

import sys
import time
import datetime
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


def main():
    print("--- Starting Eukaryote Feature Pipeline ---")
    start_time = time.time()

    # 1. Get all species' taxIDs
    print(f"\n[1/{TOTAL_STEPS}] Getting all descendant species...")
    all_taxids = get_all_descendant_taxids(EUKARYOTE_TXID)
    print(f"  Found {len(all_taxids)} descendant species of Eukaryota (taxID {EUKARYOTE_TXID})")

    # 2. Get assemblies
    print(f"\n[2/{TOTAL_STEPS}] Getting assembly taxids...")
    print("Fetching assemblies using NCBI datasets CLI...")
    assembly_taxids = get_assemblies(EUKARYOTE_TXID)
    print(f"  Found assemblies for {len(assembly_taxids)} unique taxa")

    # 3. Get annotations
    print(f"\n[3/{TOTAL_STEPS}] Getting annotation taxids...")
    print("Fetching annotations from Annotrieve...")
    annotation_taxids = fetch_annotrieve_annotations()
    print(f"  Found annotations for {len(annotation_taxids)} taxa")

    # 4. Get reads
    print(f"\n[4/{TOTAL_STEPS}] Getting short and long read taxids...")
    print("Fetching ENA RNA-seq reads...")
    long_read_taxids, short_read_taxids, count = fetch_ena_reads()
    print(f"  Fetched {count} runs")
    print(f"  Long-read unique taxa: {len(long_read_taxids)}")
    print(f"  Short-read unique taxa: {len(short_read_taxids)}")
    # Sanity check: humans/mice dominate transcriptomic ENA runs. Their absence
    # signals a likely truncated or malformed ENA response, not an intentional
    # exclusion (the query in get_reads.py does not exclude them).
    if 9606 not in short_read_taxids and 10090 not in short_read_taxids:
        print(
            "  [WARNING] Neither humans (9606) nor mice (10090) found in short-read taxa — "
            "ENA response may have been truncated or the query may need review."
        )

    # 5. Build database
    print(f"\n[5/{TOTAL_STEPS}] Building SQLite database...")
    today_str = datetime.date.today().strftime("%Y_%m_%d")
    output_db = Path(f"eukaryote_taxid_features_{today_str}.db")
    print(f"Saving records to {output_db.name}...")

    rows_written = build_database(
        all_taxids=all_taxids,
        assembly_taxids=assembly_taxids,
        annotation_taxids=annotation_taxids,
        short_read_taxids=short_read_taxids,
        long_read_taxids=long_read_taxids,
        db_path=output_db
    )

    # 6. Precompute aggregations
    print(f"\n[6/{TOTAL_STEPS}] Precomputing clade aggregations for web app...")
    from db_builder.precompute_aggregations import precompute_clades
    precompute_clades(output_db)

    elapsed = time.time() - start_time
    print(f"\nPipeline completed successfully in {elapsed:.2f} seconds.")
    print(f"Wrote {rows_written} records to {output_db.name}.")


if __name__ == "__main__":
    main()
