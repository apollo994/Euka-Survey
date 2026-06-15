# Offline DB-build pipeline

The web app reads a precomputed SQLite file, `eukaryotes.db`. This
document covers how that file is produced.

The pipeline lives in `db_builder/` and is not invoked at runtime by
the web app. It runs either:

- **Automatically**, on the 1st of every month, via
  `.github/workflows/update_db.yml`. The output is published as the
  `latest` GitHub Release asset that `src/utils.ensure_database`
  downloads on first launch.
- **Manually**, by running it locally — see
  [Running the pipeline locally](#running-the-pipeline-locally).

---

## What the pipeline does

```
                ┌─────────────────────────────────────────┐
                │  db_builder/pipeline_build_db.py        │
                └──────────────────┬──────────────────────┘
                                   │
   [1/6] ete3 SQLite ─────────▶  all descendant species of Eukaryota (2759)
   [2/6] NCBI datasets CLI ──▶  assembly_taxids: {taxid: count}
   [3/6] Annotrieve API ─────▶  annotation_taxids: {taxid: count}
   [4/6] ENA portal API ─────▶  long_read_taxids, short_read_taxids
   [5/6] sqlite3 ────────────▶  taxid_features table
   [6/6] ete3 lineages ──────▶  precomputed_clade_features table

                                + (separately:)
                                  precompute_taxa.py
                                  → precomputed_taxa table
```

### Step-by-step

| Step | Module                                     | Source                                       |
|------|--------------------------------------------|----------------------------------------------|
| 1    | `src.ete_utils.get_all_descendant_taxids`  | Local ETE3 SQLite taxonomy DB                |
| 2    | `db_builder.build_db.get_assemblies`       | `datasets summary genome taxon` CLI          |
| 3    | `db_builder.build_db.get_annotations`      | `https://genome.crg.es/annotrieve/api/v0`    |
| 4    | `db_builder.build_db.get_reads`            | `https://www.ebi.ac.uk/ena/portal/api/search`|
| 5    | `db_builder.build_db.build_database`       | (writes `taxid_features` to SQLite)          |
| 6    | `db_builder.precompute_aggregations`       | (rolls up to `precomputed_clade_features`)   |

The pipeline writes a dated file: `eukaryote_taxid_features_YYYY_MM_DD.db`.
The workflow renames it to `eukaryotes.db`, then runs the separate
`precompute_taxa.py` step to add the `precomputed_taxa` table.

---

## Tables produced

See [ARCHITECTURE.md § Database schema](ARCHITECTURE.md#database-schema)
for the column-by-column reference.

| Table                          | Written by                            | Indexes                                                 |
|--------------------------------|---------------------------------------|---------------------------------------------------------|
| `taxid_features`               | step 5                                | PK on `taxid`                                           |
| `precomputed_clade_features`   | step 6                                | PK on `taxid`                                           |
| `precomputed_taxa`             | `precompute_taxa.py` (separate)       | `idx_precomputed_taxa_cover(root_taxid, target_rank, taxid, name)` |

---

## Running the pipeline locally

```bash
conda activate euka_refactored

# Step 1–6: produces a dated DB file in CWD
python db_builder/pipeline_build_db.py

# Rename to the static filename the app expects
mv eukaryote_taxid_features_*.db eukaryotes.db

# Bake the UI common-clade lookup table
python db_builder/precompute_taxa.py --db eukaryotes.db
```

The full run takes ~30–60 minutes depending on network latency to NCBI
and ENA. ENA fetches the most data and is the slowest step.

You can also run individual fetch steps in isolation, e.g. for
debugging:

```bash
python db_builder/build_db/get_assemblies.py
python db_builder/build_db/get_reads.py
python db_builder/build_db/get_annotations.py
```

Each module has a small `__main__` block that runs the fetch and logs
counts.

### Logging

All pipeline scripts use Python's `logging` module. The default level
when invoked as `__main__` is `INFO` with timestamps. Override by
setting up logging yourself, or by editing the `basicConfig` call in
the script.

### Environment requirements

Beyond the standard `environment.yml`:

- **`datasets` CLI** (`ncbi-datasets-cli` conda package). The pipeline
  shells out to `datasets summary genome taxon ...`.
- **Outbound network access** to NCBI, Annotrieve, and ENA.
- **Local ETE3 taxonomy DB** (`~/.etetoolkit/taxa.sqlite`). ETE3
  downloads this automatically on first use; you can also force a
  refresh with `python -c "from ete3 import NCBITaxa; NCBITaxa().update_taxonomy_database()"`.

---

## GitHub Action

`.github/workflows/update_db.yml` runs the pipeline on the 1st of every
month and on manual `workflow_dispatch`.

Steps:

1. Checkout
2. Set up conda env via `conda-incubator/setup-miniconda@v3`
3. Run `pipeline_build_db.py`
4. Verify exactly one dated DB was produced (catches leftover
   artifacts from prior failed runs)
5. Run `precompute_taxa.py`
6. **Smoke-test** the produced DB:
   - File size ≥ 50 MB (full DB is ~300 MB)
   - Each of the three tables has at least a sane minimum row count
   - Workflow fails before publish if any check fails
7. Publish to GitHub Release tag `latest` via
   `softprops/action-gh-release@v2`

The web app's first-launch download targets that `latest` release.

---

## Known issues (tracked in the audit)

- **No per-step error handling.** A failing fetch silently produces a
  degenerate DB; the smoke test added in step 6 above catches *some*
  but not all degenerate outputs. Tracked as **H5** in
  [REFACTORING_AUDIT.md](../REFACTORING_AUDIT.md).
- **`precompute_aggregations` silently under-counts ancestors** when an
  ETE3 lineage lookup fails. Tracked as **C4**.
- **ENA `limit=0` loads the entire result set into memory.** For multi-
  million-row responses this is a memory risk. Tracked as audit
  Findings under `get_reads.py`.
- **No incremental processing.** The whole DB is rebuilt monthly.
