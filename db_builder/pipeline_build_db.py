#!/usr/bin/env python3
"""
pipeline_build_db.py — Build a SQLite database of taxIDs with assemblies, annotations, and reads.

Writes to `eukaryote_taxid_features_YYYY_MM_DD.db.partial` while in progress;
atomically renames to `eukaryote_taxid_features_YYYY_MM_DD.db` only on full
success. On any step failure, the `.partial` file is left on disk for
inspection and the workflow's `mv eukaryote_taxid_features_*.db` glob will
not pick it up.

Steps:
  [1/7] Local ETE3 SQLite     → all descendant species of Eukaryota
  [2/7] NCBI datasets CLI     → assemblies per taxid
  [3/7] Annotrieve API        → annotations per taxid
  [4/7] ENA portal API        → long-/short-read RNA-Seq runs per taxid
  [5/7] sqlite3               → taxid_features table
  [6/7] ete3 lineages         → precomputed_clade_features table
  [7/7] ete3 + sqlite3        → precomputed_taxa table (common clades)
"""

import datetime
import logging
import os
import sys
import time
from pathlib import Path

from src.constants import DB_SCHEMA_VERSION_CURRENT, EUKARYOTE_TXID
from src.ete_utils import get_all_descendant_taxids
from db_builder.build_db.get_assemblies import get_assemblies
from db_builder.build_db.get_annotations import fetch_annotrieve_annotations
from db_builder.build_db.get_reads import fetch_ena_reads
from db_builder.build_db.build_database import build_database


TOTAL_STEPS = 7
log = logging.getLogger("euka.pipeline")


class PipelineError(RuntimeError):
    """A pipeline step failed. The exception's `__cause__` carries the
    original failure."""


def _step(num: int, label: str):
    """Decorator-ish helper: log the step header and turn any exception
    into a PipelineError tagged with the step number, so the top-level
    handler can produce a clean error summary."""
    def decorator(fn):
        def wrapped(*args, **kwargs):
            log.info("[%d/%d] %s", num, TOTAL_STEPS, label)
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                raise PipelineError(f"step {num}/{TOTAL_STEPS} ({label}) failed: {e}") from e
        return wrapped
    return decorator


@_step(1, "Fetching all descendant species of Eukaryota")
def step_descendants():
    taxids = get_all_descendant_taxids(EUKARYOTE_TXID)
    log.info("  Found %d descendant species of Eukaryota (taxID %d)", len(taxids), EUKARYOTE_TXID)
    return taxids


@_step(2, "Fetching assemblies (NCBI datasets CLI)")
def step_assemblies():
    a = get_assemblies(EUKARYOTE_TXID)
    log.info("  Found assemblies for %d unique taxa", len(a))
    return a


@_step(3, "Fetching annotations (Annotrieve)")
def step_annotations():
    a = fetch_annotrieve_annotations()
    log.info("  Found annotations for %d taxa", len(a))
    return a


@_step(4, "Fetching RNA-Seq runs (ENA)")
def step_reads():
    long_reads, short_reads, count = fetch_ena_reads()
    log.info("  Fetched %d runs (%d long-read taxa, %d short-read taxa)",
             count, len(long_reads), len(short_reads))
    # Sanity check: humans/mice dominate transcriptomic ENA runs.
    if 9606 not in short_reads and 10090 not in short_reads:
        log.warning(
            "Neither humans (9606) nor mice (10090) found in short-read taxa — "
            "ENA response may have been truncated or the query may need review."
        )
    return long_reads, short_reads, count


@_step(5, "Writing taxid_features table")
def step_build_db(partial_path, all_taxids, assemblies, annotations, short_reads, long_reads):
    log.info("  Output: %s", partial_path.name)
    return build_database(
        all_taxids=all_taxids,
        assembly_taxids=assemblies,
        annotation_taxids=annotations,
        short_read_taxids=short_reads,
        long_read_taxids=long_reads,
        db_path=partial_path,
    )


@_step(6, "Precomputing clade aggregations")
def step_precompute_clades(partial_path):
    # Imported here so a missing optional dep doesn't crash earlier steps.
    from db_builder.precompute_aggregations import precompute_clades
    precompute_clades(partial_path)


@_step(7, "Baking common-clade UI shortcuts (precompute_taxa)")
def step_precompute_taxa(partial_path):
    from db_builder.precompute_taxa import precompute_common_clades
    precompute_common_clades(partial_path)


def _stamp_schema_version(path: Path) -> None:
    """Set PRAGMA user_version on the produced DB.

    The app reads this on startup to refuse incompatible DBs (see
    src/utils.py::ensure_database). Stamped after the final atomic
    rename so an interrupted build never produces a versioned-looking
    .partial file.
    """
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(path)) as conn:
        # SQLite's PRAGMA does not accept parametrized values.
        conn.execute(f"PRAGMA user_version = {int(DB_SCHEMA_VERSION_CURRENT)}")
        conn.commit()
    log.info("Stamped %s with schema version %d", path.name, DB_SCHEMA_VERSION_CURRENT)


def main():
    log.info("--- Starting Eukaryote Feature Pipeline ---")
    start_time = time.time()

    today_str = datetime.date.today().strftime("%Y_%m_%d")
    final_path = Path(f"eukaryote_taxid_features_{today_str}.db")
    partial_path = final_path.with_suffix(".db.partial")

    # If a stale .partial exists from a prior failed run, remove it so
    # this run starts clean.
    if partial_path.exists():
        log.info("Removing stale partial DB: %s", partial_path)
        partial_path.unlink()

    try:
        all_taxids = step_descendants()
        assemblies = step_assemblies()
        annotations = step_annotations()
        long_reads, short_reads, _ = step_reads()
        rows_written = step_build_db(
            partial_path, all_taxids, assemblies, annotations, short_reads, long_reads,
        )
        step_precompute_clades(partial_path)
        step_precompute_taxa(partial_path)

        # Atomic rename — only after every step has succeeded.
        os.replace(partial_path, final_path)

        # Stamp the schema version AFTER the atomic rename so an
        # interrupted build cannot leave a versioned-looking .partial.
        _stamp_schema_version(final_path)

        elapsed = time.time() - start_time
        log.info("Pipeline completed successfully in %.2f seconds.", elapsed)
        log.info("Wrote %d records to %s.", rows_written, final_path.name)
        return 0

    except PipelineError as e:
        log.error("PIPELINE FAILED: %s", e)
        if partial_path.exists():
            log.error("Partial output left at %s for inspection.", partial_path)
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sys.exit(main())
