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
   [1/7] ete3 SQLite ─────────▶  all descendant species of Eukaryota (2759)
   [2/7] NCBI datasets CLI ──▶  assembly_taxids: {taxid: count}
   [3/7] Annotrieve API ─────▶  annotation_taxids: {taxid: count}
   [4/7] ENA portal API ─────▶  long_read_taxids, short_read_taxids
   [5/7] sqlite3 ────────────▶  taxid_features table
   [6/7] ete3 lineages ──────▶  precomputed_clade_features table
   [7/7] ete3 + sqlite3 ─────▶  precomputed_taxa table (common clades)
```

### Step-by-step

| Step | Module                                       | Source                                       |
|------|----------------------------------------------|----------------------------------------------|
| 1    | `src.ete_utils.get_all_descendant_taxids`    | Local ETE3 SQLite taxonomy DB                |
| 2    | `db_builder.build_db.get_assemblies`         | `datasets summary genome taxon` CLI          |
| 3    | `db_builder.build_db.get_annotations`        | `https://genome.crg.es/annotrieve/api/v0`    |
| 4    | `db_builder.build_db.get_reads`              | `https://www.ebi.ac.uk/ena/portal/api/search`|
| 5    | `db_builder.build_db.build_database`         | (writes `taxid_features` to SQLite)          |
| 6    | `db_builder.precompute_aggregations`         | (rolls up to `precomputed_clade_features`)   |
| 7    | `db_builder.precompute_taxa`                 | (caches common-clade taxa → `precomputed_taxa`) |

### Atomic output

The pipeline writes to `eukaryote_taxid_features_YYYY_MM_DD.db.partial`
while in progress, then `os.replace`-renames to
`eukaryote_taxid_features_YYYY_MM_DD.db` on full success. If any step
fails, the `.partial` file is left on disk for inspection and the
workflow's `mv eukaryote_taxid_features_*.db` glob won't pick it up.

Each step is wrapped in a decorator that converts any exception into a
`PipelineError` tagged with the step number, so the top-level handler
logs a clean failure summary and exits non-zero.

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
# Install pipeline-specific Python deps (one-time)
uv sync --extra pipeline

# Install the NCBI datasets CLI (standalone binary)
curl -sSL -o ~/.local/bin/datasets \
  https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/v2/linux-amd64/datasets
chmod +x ~/.local/bin/datasets   # ensure ~/.local/bin is in PATH

# All 7 steps including precompute_taxa. Produces a dated DB in CWD.
uv run python db_builder/pipeline_build_db.py

# Rename to the static filename the app expects
mv eukaryote_taxid_features_*.db eukaryotes.db
```

You can also re-run just the precompute steps against an existing
DB (useful after schema tweaks in `precompute_taxa.py` /
`precompute_aggregations.py`):

```bash
uv run python db_builder/precompute_aggregations.py --db eukaryotes.db
uv run python db_builder/precompute_taxa.py --db eukaryotes.db
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

Beyond the standard `uv sync --extra pipeline`:

- **`datasets` CLI** — standalone binary from NCBI (curl recipe above).
  The pipeline shells out to `datasets summary genome taxon ...`.
- **Outbound network access** to NCBI, Annotrieve, and ENA.
- **Local ETE3 taxonomy DB** (`~/.etetoolkit/taxa.sqlite`). ETE3
  downloads this automatically on first use; you can also force a
  refresh with `uv run python -c "from ete3 import NCBITaxa; NCBITaxa().update_taxonomy_database()"`.

---

## GitHub Action

`.github/workflows/update_db.yml` runs the pipeline on the 1st of every
month and on manual `workflow_dispatch`.

Steps:

1. Checkout
2. Install `ncbi-datasets-cli` via `curl` (standalone binary, ~40 s)
3. Set up uv via `astral-sh/setup-uv@v6` (with cache)
4. `uv sync --extra pipeline --no-default-groups` installs the Python
   deps from `uv.lock` (~10 s with cache hit)
5. `uv run python db_builder/pipeline_build_db.py` — runs all 7 pipeline
   steps including `precompute_taxa`, with atomic `*.db.partial` →
   `*.db` rename on success
6. Verify exactly one dated DB was produced
7. **Smoke-test** the produced DB (size + per-table row counts; fails
   before publish if any check fails)
8. Publish to GitHub Release with a date-based tag (`db-YYYY.MM.DD.HHMM`)
   and `make_latest: true`. Past builds keep their dated tags for
   rollback; the app's `/releases/latest/download/eukaryotes.db` URL
   keeps resolving to the most recent build.

The web app's first-launch download targets that `latest` release.

---

## Known issues (tracked in the audit)

- **No incremental processing.** The whole DB is rebuilt monthly.
