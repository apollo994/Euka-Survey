"""
Queries the EBI ENA portal API to fetch RNA-seq read metadata.
Separates runs into long-read (ONT/PacBio) and short-read taxa.
"""

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


_LONG_READ_PLATFORMS = {"OXFORD_NANOPORE", "PACBIO_SMRT"}


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def fetch_ena_reads() -> tuple[dict[int, int], dict[int, int], int]:
    """Query ENA portal API for RNA-seq runs and count by taxon × platform.

    Streams the response line-by-line as TSV. Previously the entire JSON
    array was loaded into memory via `r.json()`, which is a memory bomb
    for multi-million-row responses.

    Returns (long_reads_txids, short_reads_txids, total_record_count).
    """
    payload = {
        "result": "read_run",
        "query": (
            f'tax_tree({EUKARYOTE_TXID}) AND '
            f'(library_source="transcriptomic" OR library_strategy="rna-seq")'
        ),
        "fields": "tax_id,instrument_platform",
        "format": "tsv",
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

    txids_count_long_reads: dict[int, int] = {}
    txids_count_short_reads: dict[int, int] = {}
    total = 0
    header: list[str] | None = None

    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        fields = raw.split("\t")
        if header is None:
            header = fields
            try:
                tax_idx = header.index("tax_id")
                platform_idx = header.index("instrument_platform")
            except ValueError as e:
                # ENA returned an unexpected header; bail so tenacity retries.
                log.error("Unexpected ENA TSV header: %r", header)
                raise RuntimeError("unexpected ENA TSV header") from e
            continue

        if len(fields) <= max(tax_idx, platform_idx):
            continue
        try:
            tax_id = int(fields[tax_idx])
        except ValueError:
            continue

        platform = fields[platform_idx]
        if platform in _LONG_READ_PLATFORMS:
            txids_count_long_reads[tax_id] = txids_count_long_reads.get(tax_id, 0) + 1
        else:
            txids_count_short_reads[tax_id] = txids_count_short_reads.get(tax_id, 0) + 1
        total += 1

    if header is None:
        # No data at all — should not happen for a healthy ENA response.
        log.error("ENA returned no rows (not even a header).")
        raise RuntimeError("empty ENA response")

    return txids_count_long_reads, txids_count_short_reads, total


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