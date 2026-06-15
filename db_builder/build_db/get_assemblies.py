"""
Retrieves assembly information for taxonomic IDs.
Uses the NCBI datasets CLI to identify which taxa have sequenced genome assemblies.
"""

import json
import logging
import os
import subprocess
import sys

# Allow direct `python db_builder/build_db/get_assemblies.py` invocation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.constants import EUKARYOTE_TXID

log = logging.getLogger("euka.get_assemblies")


class DatasetsCLIError(RuntimeError):
    """Raised when the NCBI datasets CLI is missing or fails."""


def get_assemblies(txid: int) -> dict[int, int]:
    """Get a dictionary of taxonomic IDs and their assembly counts using NCBI datasets CLI tool."""
    try:
        process = subprocess.Popen(
            [
                "datasets",
                "summary",
                "genome",
                "taxon",
                str(txid),
                "--as-json-lines",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        raise DatasetsCLIError(
            "NCBI datasets CLI not found. Install from: "
            "https://www.ncbi.nlm.nih.gov/datasets/docs/v2/command-line-tools/download-and-install/"
        ) from e

    taxids_count_assembly: dict[int, int] = {}

    for line in process.stdout:  # type: ignore
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            organism = record.get("organism") or {}
            tax_id = organism.get("tax_id")
            if tax_id is None:
                continue
            taxids_count_assembly[tax_id] = taxids_count_assembly.get(tax_id, 0) + 1
        except json.JSONDecodeError as e:
            log.warning("Skipping malformed record: %s", e)

    process.wait()

    if process.returncode != 0:
        stderr_output = process.stderr.read().strip()  # type: ignore
        raise DatasetsCLIError(
            f"datasets exited with code {process.returncode}: {stderr_output}"
        )

    return taxids_count_assembly


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    txid_assemblies = get_assemblies(EUKARYOTE_TXID)
    log.info("Total taxonomic IDs with assemblies: %d", len(txid_assemblies))
    log.info("First 10: %s", list(txid_assemblies.items())[:10])
