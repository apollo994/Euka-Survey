"""
Queries the EBI ENA portal API to fetch RNA-seq read metadata.
Separates runs into long-read (ONT/PacBio) and short-read taxa.
"""

import json
import logging
import os
import sys

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

# Allow direct `python db_builder/build_db/get_reads.py` invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.constants import EUKARYOTE_TXID

ENA_BASE = "https://www.ebi.ac.uk/ena/portal/api/search"
log = logging.getLogger("euka.get_reads")


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def fetch_ena_reads() -> tuple[dict[int, int], dict[int, int], int]:
    """Query ENA portal API (POST) for RNA-seq reads.

    Returns (long_reads_txids, short_reads_txids, total_record_count).
    `limit=0` fetches all records in one request.
    """
    payload = {
        "result": "read_run",
        "query": f'tax_tree({EUKARYOTE_TXID}) AND (library_source="transcriptomic" OR library_strategy="rna-seq")',
        "fields": "tax_id,instrument_platform",
        "format": "json",
        "limit": 0,
    }
    r = requests.post(
        ENA_BASE,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=120,
        stream=True,
    )
    r.raise_for_status()

    try:
        data = r.json()
    except requests.exceptions.JSONDecodeError as e:
        # Re-raise so tenacity retries; previously this silently returned empty
        # dicts and a zero count, which masked transient failures and left the
        # pipeline producing a degenerate DB.
        log.error("Failed to decode JSON from ENA: %s", e)
        raise

    txids_count_long_reads: dict[int, int] = {}
    txids_count_short_reads: dict[int, int] = {}

    for record in data:
        try:
            tax_id = int(record.get("tax_id"))
        except (ValueError, TypeError):
            continue

        platform = record.get("instrument_platform", "")
        if platform in ("OXFORD_NANOPORE", "PACBIO_SMRT"):
            txids_count_long_reads[tax_id] = txids_count_long_reads.get(tax_id, 0) + 1
        else:
            txids_count_short_reads[tax_id] = txids_count_short_reads.get(tax_id, 0) + 1

    return txids_count_long_reads, txids_count_short_reads, len(data)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    long_txids, short_txids, count = fetch_ena_reads()
    log.info(
        "Fetched %d runs (%d long-read taxa, %d short-read taxa).",
        count, len(long_txids), len(short_txids),
    )
    log.info("First 10 long-read: %s", list(long_txids.items())[:10])
    log.info("First 10 short-read: %s", list(short_txids.items())[:10])