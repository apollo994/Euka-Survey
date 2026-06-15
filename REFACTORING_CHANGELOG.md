# Refactoring Changelog

Tracks all changes made on `refactor/improve-codebase` against the items in
`REFACTORING_AUDIT.md`. Each entry: which audit item, files touched, behavior
change (if any), and why.

## 2026-06-15 — Batch 1: Phase 1 quick wins

### Foundation

**Audit cross-cutting #2 — `src/constants.py`** *(new file)*
- Single source for `EUKARYOTE_TXID`, `COMMON_CLADES`, `FULL_RANKS`,
  `ALLOWED_RANKS`, `HARD_NODE_CAP`, `STANDARD_BREAKPOINTS`,
  `SQLITE_MAX_VARIABLES`, `RENDER_SUBPROCESS_TIMEOUT_SECONDS`.
- Eliminates duplicate literals across `app.py`, `db_builder/pipeline_build_db.py`,
  `db_builder/precompute_taxa.py`, and the `db_builder/build_db/*` modules.
- No behavior change.

### app.py

**Audit L1 / Roadmap Phase 1 #1 — Dead import removed**
- Removed module-level `from ete3 import NCBITaxa` (was shadowed by a local
  re-import inside the rank-resolution block).

**Audit C2 / Roadmap Phase 1 #4 — Subprocess timeout + atomic temp SVG**
- `generate_tree_svg_cached` now:
  - Uses `tempfile.mkstemp` instead of CWD-relative `temp_tree_<uuid>.svg`.
  - Calls `p.join(timeout=RENDER_SUBPROCESS_TIMEOUT_SECONDS)` (120s default).
  - Terminates → kills a stuck child rather than hanging the Streamlit thread.
  - Verifies non-empty output before reading.
  - Cleans up via `try/finally`.
- Post-render display path also switched from CWD `temp_tree_<session>.svg`
  to `tempfile.mkstemp` with `try/finally` cleanup.
- `import uuid` removed (no longer used).
- Reliability fix; user-visible only if a render previously hung.

**Audit M5 / Roadmap Phase 1 #6 — Centralized common-taxa + ranks**
- Replaced inline `common_taxa` list, `taxid_map` dict, `FULL_RANKS`,
  `ALLOWED_RANKS`, `HARD_CAP`, `standard_breakpoints` with imports from
  `src.constants`.
- Labels (`"Eukaryota (2759)"`) are derived from `COMMON_CLADES` dict at runtime,
  removing the drift risk between the display list and the label→taxid map.
- No behavior change.

### src/utils.py

**Audit H1 / Roadmap Phase 1 #5 — Atomic database download**
- `ensure_database` now downloads to `{db_path}.tmp` and `os.replace`s on
  success. A network drop mid-download no longer leaves a half-written file
  that future runs would treat as valid.
- Switched from `urllib.request.urlretrieve` to `urlopen` + `shutil.copyfileobj`
  to add a `timeout=300` parameter (urlretrieve doesn't accept one).
- Failure path now cleans up the `.tmp` file.
- Behavior change: a previously-failed half-download will now be retried on
  next launch instead of being treated as the real DB.

### src/ete_utils.py

**Audit H4 / M-perf / Roadmap Phase 1 #8 — `lru_cache` on lookups**
- `get_name_from_taxid` and `get_rank_from_taxid` are now
  `@functools.lru_cache(maxsize=4096)`.
- They still each instantiate `NCBITaxa()` on cache miss (the full singleton
  is Phase 2 #18 because of Streamlit's thread-affinity constraint), but each
  unique taxid is now resolved at most once per process.

**Audit H4 / Roadmap Phase 1 #9 — Read-only ETE3 SQLite connection**
- `get_all_descendant_taxids` now opens the ETE3 SQLite db via
  `file:{path}?mode=ro` URI and wraps the connection in `contextlib.closing`
  (the previous code relied on GC to close).

### src/visualization.py

**Audit L1 / Roadmap Phase 1 #1 — Dead import removed**
- Removed unused `import re`.

### db_builder/pipeline_build_db.py

**Audit C3-adjacent / Roadmap Phase 1 #2 — Inverted warning fixed**
- The previous warning fired when humans/mice were *missing* from the result
  set but said they "were excluded from the query" — misleading: the query
  in `get_reads.py` does not exclude them.
- New message clearly states the sanity-check intent: absence signals a
  truncated/malformed ENA response.
- Also: `9606 not in short_read_taxids.keys()` → `9606 not in short_read_taxids`
  (idiomatic), and `or` → `and` so the warning fires only when *both* are
  missing (a single missing one is plausible noise; both missing is a real
  red flag).

**Audit L7 / Roadmap Phase 1 #3 — Step counter fixed**
- `[1/5]`–`[5/5]` plus an unnumbered "Precomputing clade aggregations" step
  → `[1/6]`–`[6/6]` with all six steps explicitly enumerated.

**Audit L1 — Dead import removed**
- `from ete3 import NCBITaxa` was never used in this file.

**Audit M5 / Roadmap Phase 1 #6 — `EUKARYOTE_TXID` from constants**

### db_builder/precompute_taxa.py

**Roadmap Phase 1 #13 — `closing()` context manager**
- Connection now wrapped in `contextlib.closing` for explicit cleanup on
  any exception.

**Roadmap Phase 1 #7 — Covering index added to schema**
- Schema now creates `idx_precomputed_taxa_cover` on
  `(root_taxid, target_rank, taxid, name)`. The app's hot read
  `SELECT taxid, name FROM precomputed_taxa WHERE root_taxid=? AND target_rank=?`
  can now be served from the index without a table lookup.
- **Takes effect on the next DB regen**; the bundled `eukaryotes.db` keeps
  its existing single-column index until the next monthly build.

**Audit M5 / Roadmap Phase 1 #6 — `COMMON_CLADES` + `ALLOWED_RANKS` from constants**
- Hard-coded `common_taxids = [2759, 33208, 40674, 9443, 4751, 33090]` and the
  inline ranks list both removed.

### db_builder/precompute_aggregations.py

**Roadmap Phase 1 #13 — `closing()` context manager**
- Connection lifetime now owned by `precompute_clades` via
  `contextlib.closing`; the inner body was extracted to
  `_precompute_clades_impl(conn)` so existing tests/callers using a passed
  connection remain straightforward.
- Removed the manual `conn.close()` (it was already missing on the
  exception path).

### db_builder/build_db/get_assemblies.py + get_reads.py

**Audit M5 / Roadmap Phase 1 #6 — `EUKARYOTE_TXID` from constants**
- Removed per-file `EUKARYOTE_TXID = 2759` definitions.
- Added a small `sys.path.insert` so these files still work when invoked
  directly (`python db_builder/build_db/get_reads.py`), keeping the smoke-test
  `__main__` blocks functional. The Phase 3 `pyproject.toml` migration will
  retire the `sys.path` hack across the board.

### README.md

**Audit L4 / Roadmap Phase 1 #10 — Stale line removed**
- "patch missing zero-count taxonomic entries" referred to a step deleted in
  commit `bfbf5fe`. Removed from the offline-pipeline description.

## 2026-06-15 — Batch 2: Remaining Phase 1 items

### environment.yml

**Roadmap Phase 1 #11**
- Removed `scipy` and `pandas` (confirmed unused via repo-wide grep).
- Added missing `tenacity` (was being imported by `get_annotations.py` and
  `get_reads.py` but never declared — relied on a transitive install).
- Added a comment explaining the `numpy<2.0.0` pin (ete3/matplotlib ABI).

### db_builder/ — `print` → `logging`

**Roadmap Phase 1 #12**
- All 43 `print()` calls in `pipeline_build_db.py`, `precompute_aggregations.py`,
  `precompute_taxa.py`, `get_assemblies.py`, `get_reads.py`, and
  `get_annotations.py` converted to module-level `logging.getLogger("euka.…")`.
- Entry-point scripts (`__main__` blocks) configure `logging.basicConfig` with
  a timestamped format.
- `[WARNING]` prefix in pipeline_build_db.py → proper `log.warning()` (the
  message no longer requires the manual prefix).

### db_builder/build_db/get_assemblies.py

**Audit M8 / Roadmap Phase 2 #27 — `sys.exit(1)` → `raise`**
- Introduced `DatasetsCLIError(RuntimeError)`.
- Both error paths (CLI not installed; non-zero exit from `datasets`) now
  raise instead of `sys.exit(1)`. Library hygiene fix — the pipeline can now
  catch and decide how to handle the failure rather than the process dying
  inside a library call.
- Pulled forward from Phase 2 because the lines were already being touched
  by the print→logging conversion.

### db_builder/build_db/get_reads.py

**Audit C3 — Swallowed JSON decode error fixed**
- `r.json()` failure used to log to stdout and return empty dicts +
  `count=0`. This is a Critical-rank audit finding: it would silently produce
  a degenerate DB on a transient ENA outage.
- Now re-raises so `@tenacity.retry` can take over; if all 5 retries are
  exhausted, the failure propagates and the pipeline aborts loudly instead of
  publishing a broken DB.
- Also collapsed the redundant `_ena_search` + `fetch_ena_reads` no-op
  wrapper (Audit M.6 cleanup).

### .github/workflows/update_db.yml

**Audit H6 / Roadmap Phase 1 #14 — DB smoke test added**
- Inserted a "Smoke-test produced DB" step between the build and the publish
  steps. The test:
  - Checks `eukaryotes.db` is at least 50 MB (full DB is ~300 MB).
  - Opens the DB read-only.
  - Verifies each of the three expected tables (`taxid_features`,
    `precomputed_clade_features`, `precomputed_taxa`) has at least a sane
    minimum row count.
  - Workflow fails before publishing if any check fails — no more stale or
    broken releases overwriting `latest`.
- Also hardened the `mv eukaryote_taxid_features_*.db eukaryotes.db` step to
  fail if multiple matches exist (could happen if a prior run left an
  artifact).

### src/ete_utils.py

**Audit L3 — Lookup-function error contracts aligned**
- `get_name_from_taxid` used to raise `ValueError` on non-int input while the
  sibling `get_rank_from_taxid` silently returned `"clade"`.
- Both now return their respective sentinel (`"Unknown"` / `"clade"`) on
  non-int input. The only caller (`app.py`) already treats `"Unknown"` as the
  error sentinel.

## 2026-06-15 — Batch 3: Phase 2 — filter/sort/limit unification + rank-resolution caching

### src/database.py

**Audit C1 / Roadmap Phase 2 #15 + #16 + #17 — Filter/sort/limit unified**

The single highest-priority refactor in the audit. CLAUDE.md explicitly
warned about keeping the SQL path (`database.get_filtered_taxa_metadata`)
and the Python fallback path (inline in `app.py`) in sync. They are no
longer separate code:

- New `FilterLogic` enum (`AND` / `OR`) replaces the bare string compare
  `"Match ALL (AND)"` that was leaking through three layers (UI label →
  `@st.cache_data` key → SQL WHERE-clause builder). The UI now converts
  the segmented-control label to a `FilterLogic` value once, at the
  boundary; the data layer never sees the string.
- New `_row_to_metadata(row)` helper consumes the 10-column row from
  `precomputed_clade_features` and produces the standard metadata
  dict (`n_rows`, `c_*`, `s_*`, `p_*`). Used by both
  `build_phylum_metadata` and `get_filtered_taxa_metadata` — no more
  copy-pasted column unpacking and percentage math.
- New `_secondary_sort_key(sort_by_key)` returns the tiebreaker column,
  used identically in the SQL `ORDER BY` and in the Python `sorted`
  key. (Sorting by a `c_*` metric ties by the matching `s_*`; otherwise
  ties by `c_ass`.)
- New `filter_sort_limit_metadata(metadata, *, …) -> (dict, int)` is
  the canonical Python implementation of `exclude_empty` →
  `filter_keys`/`filter_logic` → `sort` → `limit`. The non-precomputed
  fallback in `app.py` now calls this single function instead of
  carrying its own copy of the logic.
- Magic `chunk_size = 900` → `_IN_CHUNK = SQLITE_MAX_VARIABLES - 99`
  (named constant; defined in `src/constants.py`).
- The `_COVERAGE_KEYS` tuple (`c_ass, c_ann, c_rna, c_lng`) is the
  single source of truth for the "exclude empty" predicate — used by
  both the SQL `WHERE` builder and the Python helper.

**Parity verified** against the real `eukaryotes.db` across five
scenarios (no filter, exclude_empty, AND-filter, OR-filter,
sort-by-`c_*`/`s_*`/`n_*`); SQL and Python paths produce identical
totals, key sets, ordering, and metadata values.

### app.py

**Reuses the unified data layer**

- UI segmented-control label converted to `FilterLogic` enum at the
  widget boundary.
- Non-precomputed fallback path now fetches `raw_metadata` with
  `exclude_empty=False` and pipes it through
  `database.filter_sort_limit_metadata`. This also means the cached
  `get_phylum_metadata_cached` result is now independent of filter
  knobs — toggling `exclude_empty` or changing filter selections
  reuses the cached fetch instead of busting it.

**Audit H3 — Rank resolution caching**

- The inline ETE3 lineage walk that computed the dropdown's valid ranks
  on every Streamlit rerun is gone (~25 lines removed from `app.py`).
- Replaced with `taxonomy.resolve_valid_ranks(root_taxid)` — a small
  `@lru_cache`'d helper that returns the tuple of `ALLOWED_RANKS`
  strictly below the root's own rank. Raises `UnknownTaxonError` (not
  the generic `ValueError`) for unknown taxids, so the UI's
  `except` clause is now type-safe.
- Verified on the six common roots + Vertebrata (no-rank fallback to
  lineage walk) + a species-rank root (empty list — UI shows "no
  further breakdown") + an unknown taxid.
- `FULL_RANKS` is no longer imported at the `app.py` level — all rank
  logic now lives in `src/taxonomy.py`.

### src/taxonomy.py

**Audit M6 — Investigated, rejected**

The audit suggested rewriting `get_taxa_at_rank` using the recursive
CTE pattern from `ete_utils`. Investigation showed this is **slower**:
the ETE3 SQLite has no index on `parent`, so the recursion builds an
automatic covering index per level. Measured 3–30× slowdown depending
on clade depth. A `track`-column LIKE approach (single full scan,
~1.5 s) was also slower than ETE3's internal traversal for narrow
clades. The original implementation has been retained with an
explanatory comment so the next reader doesn't re-investigate.

## 2026-06-15 — Batch 4: Phase 2 — visualization rewrite

### src/visualization.py

**Audit H2 / Roadmap Phase 2 #21 — Per-render tempdir, no module globals**

The biggest reliability finding remaining on the rendering path. The
old code wrote per-leaf bar charts, the axis ruler, the legend, and
color swatches into a project-relative `.tmp_bars/` directory, and
cached image paths in module-level globals (`_AXIS_IMG_PATH`,
`_LEGEND_IMG_PATH`, `_COLOR_SQUARES`). On entry, `render_tree_in_process`
`shutil.rmtree`'d the directory and recreated it — racy with concurrent
renders on Streamlit Cloud and broken-by-design (the path globals
pointed at files that were about to be deleted).

Now:
- All helpers (`generate_bar_chart`, `generate_axis_img`,
  `generate_legend_img`, color swatches) take `tmp_dir` as a parameter.
- `_color_square_factory(tmp_dir)` returns a closure with a local
  memoization cache (no module global).
- `render_tree_in_process` creates a `tempfile.TemporaryDirectory(
  prefix="euka_bars_")` and passes its path down. On exit (success or
  exception) the tempdir is removed automatically.
- `TMP_DIR`, `_AXIS_IMG_PATH`, `_LEGEND_IMG_PATH`, `_COLOR_SQUARES`
  are all gone from module scope.

**Roadmap Phase 2 #22 — matplotlib backend pinned to Agg**

`matplotlib.use("Agg")` is called at import time, before
`import matplotlib.pyplot`. This:
- Prevents matplotlib from auto-picking a Qt backend in the child
  process and colliding with ETE3's QApplication.
- Has no observable effect on the Streamlit parent (it never uses
  pyplot directly).

**Roadmap Phase 2 #23 — Batched lineage validation**

The old loop:
```python
for tid in phylum_metadata.keys():
    try:
        ncbi.get_lineage(tid)
        valid_taxids.append(tid)
    except ValueError:
        pass
```
was an N+1 ETE3 lookup. Now:
```python
lineages = ncbi.get_lineage_translator(candidate_taxids)
valid_taxids = [t for t in candidate_taxids if t in lineages]
```
— one SQLite query through ETE3 instead of up to 500.

**Audit M9 / pulled forward — Graceful display fallback**

`pyvirtualdisplay` was caught only on `ImportError`. If the package
was installed but `Xvfb` wasn't (common in dev WSL without
`packages.txt` installed), the subprocess crashed with a confusing
`FileNotFoundError`. Now the broader case is caught and we fall back
to Qt's built-in offscreen platform plugin (`QT_QPA_PLATFORM=offscreen`),
which lets ETE3 render in the absence of any X server. Verified
end-to-end against `eukaryotes.db`: a Mammalia+Family render of 10
taxa now produces a valid 97 KB SVG in 1.6 s with no Xvfb installed.

**Cleanup**
- Dead `NodeStyle` import removed.
- Module-level `import shutil` removed (no more `rmtree`).
- Inner re-imports of `os`/`shutil`/`NCBITaxa` inside the subprocess
  function removed (redundant — spawn already re-imports the module).
- `int(node.name)` is now wrapped in `try/except` so that internal
  nodes ETE3 may surface as leaves don't crash the layout function
  (defensive — addresses an edge case flagged in the audit findings).

## 2026-06-15 — Batch 5: Phase 2 — db_builder reliability

### db_builder/precompute_aggregations.py

**Audit C4 / Roadmap Phase 2 #24 — Fix silent under-counting + chunk lineage lookups**

Two Critical-rank issues closed:

1. **The silent under-counting bug**: when ETE3 had no lineage for a
   leaf species, the code used `lineage = [taxid]` as a fallback. That
   attributed the species' counts only to itself, silently *omitting*
   it from every ancestor's roll-up. Aggregates at order/class/phylum
   level were therefore systematically under-counted by the missing-
   lineage population.
   Now: missing-lineage rows are SKIPPED (not faked) and a warning is
   logged with the count. Roll-up arithmetic is internally consistent
   even if we cannot place a species in the tree.

2. **Memory bound on lineage lookups**: previously a single
   `ncbi.get_lineage_translator(all_taxids)` call on ~1.8 M species
   built a dict-of-lists in RAM. Now chunked at 50 000 taxids per
   call; the same chunking is applied to `ncbi.get_rank` (also called
   on the full taxid list previously).

### db_builder/build_db/get_reads.py

**Roadmap Phase 2 #25 — Stream ENA reads via TSV + iter_lines**

The ENA query used `format=json` with `limit=0`, then loaded the
entire response with `r.json()` — a memory bomb for multi-million-row
responses. The `stream=True` flag was set on the request but had no
effect because `json()` materializes everything anyway.

- Switched to `format=tsv` so the response is line-oriented.
- Parse incrementally via `requests.iter_lines(decode_unicode=True)`.
  Header parsed once; subsequent rows are split + counted directly
  into the long-read / short-read taxid dicts. No intermediate
  list-of-records held in memory.
- Header validation: if ENA returns an unexpected column order we
  raise (and tenacity retries).
- Empty response is now a hard failure (was previously an empty
  dict + count=0 — same class of degenerate-output bug as the
  swallowed JSON error fixed in Batch 2).

### db_builder/pipeline_build_db.py

**Audit H5 / Roadmap Phase 2 #26 — Per-step error handling + atomic output + bake precompute_taxa**

Top-level pipeline is now structured:

- Each step is a `@_step(num, label)`-decorated function. The decorator
  logs the header and wraps any exception in `PipelineError(...)` with
  the step number, so the top-level handler can produce a clean error
  summary instead of an opaque stack trace mid-pipeline.
- Output is written to `eukaryote_taxid_features_YYYY_MM_DD.db.partial`
  while in progress. On full success the file is `os.replace`-renamed
  to `eukaryote_taxid_features_YYYY_MM_DD.db` (atomic on POSIX). On
  any step failure, the `.partial` file is left on disk for inspection
  and the workflow's `mv eukaryote_taxid_features_*.db` glob won't
  pick it up. Stale `.partial` files from prior failed runs are
  removed at the top of `main()`.
- `precompute_common_clades` is now invoked as step 7 of the pipeline
  (was previously only called from the GitHub workflow as a separate
  script). The pipeline now produces a complete, ready-to-serve DB.
- `main()` returns an exit code; the script exits with `sys.exit(main())`
  so CI sees a non-zero exit on partial failure.
- Step count updated to `[1/7]`–`[7/7]`.

### .github/workflows/update_db.yml

- Dropped the separate `python db_builder/precompute_taxa.py --db eukaryotes.db`
  step now that the pipeline does it. The smoke test added in Batch 2
  already validates the `precomputed_taxa` table.

## 2026-06-15 — Hotfix: revert ENA TSV streaming

### db_builder/build_db/get_reads.py

Batch 5's streaming change (`format=tsv` + `iter_lines()`) produced a
silent data-loss regression: the user ran the new pipeline manually
and the resulting DB had ~28 % of the previous RNA-Seq run count and
~17 % of the long-read count, with species coverage at 43 % / 40 %.
The drop ratio (runs collapse faster than species) matches a
"stream truncated partway" pattern — long-tail species that have only
one or two runs are over-represented in what survived.

Likely root cause: the ENA `format=tsv` endpoint applies an
undocumented row cap, OR the streaming connection is being severed
mid-response (TLS read timeout? server-side idle disconnect?) and
`requests.iter_lines()` treats the truncated response as a clean EOF.
The `format=json` path uses `r.json()` which reads `r.content` to EOF
and would raise on incomplete data.

**Action**: reverted to `format=json` + `r.json()`. We accept the
in-memory cost (~few hundred MB for the current ~8 M-row response) as
the price of correctness for an offline monthly pipeline. The other
Batch 2 fixes are preserved (JSON-decode error now re-raises so
tenacity retries instead of silently returning empty dicts; empty
response is a hard failure).

**Phase 2 #25 is reopened** until the TSV discrepancy is diagnosed.
Future investigation:
- Try `format=json` + `iter_content`-based incremental JSON parsing
  via `ijson` (true streaming without the TSV cap).
- Try `format=tsv` with pagination (offset+limit, e.g. 100 k rows
  per request) instead of `limit=0`.
- Reproduce the row-count difference outside the pipeline with a
  side-by-side curl of both endpoints.

## 2026-06-15 — Batch 6: Phase 3 — test suite

### Closes audit H7 + roadmap Phase 3 #34.

Eight days after the ENA TSV-streaming regression escaped to the user,
the test suite that should have caught it. 63 tests + 2 network tests
+ a fixture-based test harness.

### Infrastructure

- `pytest.ini` — `testpaths = tests`, `markers` declared (`network`,
  `slow`, `requires_ete3_db`), `--strict-markers`.
- `environment.yml` — `pytest` added under pip deps.
- `tests/conftest.py` — `fixture_db` fixture (in-memory SQLite with
  the real schema + a hand-crafted dataset of 6 taxa), plus a
  `pytest_collection_modifyitems` hook that skips `network` / `slow`
  tests unless explicitly selected via `-m`.

### Tests written

| File | What it covers |
|---|---|
| `test_constants.py` | `COMMON_CLADES` well-formed, `ALLOWED_RANKS ⊆ FULL_RANKS`, canonical rank ordering, no chunk-size > SQLite cap. 10 tests. |
| `test_filter_sort_limit.py` | The canonical filter/sort/limit helper. `exclude_empty`, AND vs OR, secondary-sort tiebreakers, top_n edges, empty inputs, FilterLogic enum parametrization. 14 tests. |
| `test_database.py` | `build_phylum_metadata` zero-fill + chunking; `get_filtered_taxa_metadata` SQL behavior; **SQL/Python parity across a 16-scenario matrix** (audit C1 regression net). 29 tests. |
| `test_taxonomy.py` | `resolve_valid_ranks` for each common clade + Vertebrata (unranked lineage walk) + species-rank root (empty) + unknown taxid (raises) + cache verification. 6 tests. Auto-skipped if ETE3 DB absent. |
| `test_aggregations.py` | `_precompute_clades_impl` rollup correctness: ancestor crediting (human/chimp/mouse/zebrafish ↔ Mammalia/Primates/Eukaryota), species-rank filter, coverage vs count distinction, **the C4 regression test** (synthesized species with no ETE3 lineage must be SKIPPED, not self-attributed). 4 tests. |
| `test_ena_smoke.py` | Hits real ENA with a tiny `tax_tree(9606)` query. Verifies response shape and that short reads dominate for Homo sapiens. 2 tests, `@pytest.mark.network`. |

### Hostile-tested

The C4 regression test was deliberately exercised against a manually-
reintroduced version of the original bug to confirm it actually catches
what it claims to. First version of the test passed silently against
both the fixed and the buggy code (the species-rank filter was hiding
the bug from the test). Rewrote with monkeypatched
`NCBITaxa.get_rank` + `get_lineage_translator` to construct a taxid
that's classified as a species but has no lineage — the exact narrow
case the C4 fix addresses. Re-ran the hostile check: test fails on
the bug, passes on the fix.

### What's deliberately not covered

- The Streamlit UI rendering — no headless Streamlit test harness in
  place. Manual checklist in `docs/DEVELOPMENT.md`.
- The ETE3 tree render subprocess — would need a full multiprocessing
  + Qt fixture; deferred.
- The full pipeline end-to-end — too slow (~30–60 minutes) and
  network-dependent.

## 2026-06-15 — Batch 7: dependency cleanup (drop conda, adopt uv)

The repo had three overlapping dependency files (`environment.yml`,
`packages.txt`, and an implicit `.venv` created from conda). The only
real reason for conda was `ncbi-datasets-cli` and historical PyQt5
wheel reliability — neither problem applies anymore.

### New layout

| File | Purpose |
|---|---|
| `pyproject.toml` | Single source of truth for Python deps. Main `dependencies` = web-app shape; `[project.optional-dependencies] pipeline` = `tenacity`; `[dependency-groups] dev` = `pytest`. |
| `uv.lock` | Generated by `uv lock`, committed. **Streamlit Cloud's highest-priority dependency file** — it picks this and installs via uv, not pip. |
| `.python-version` | `3.11` — pins Python for uv + Streamlit Cloud agreement. |
| `packages.txt` | Trimmed from 5 entries to 3 — just the Qt5 system libs the PyQt5 wheel links against. |

### Deleted

- `environment.yml` — gone. Conda is no longer involved anywhere.
- `pyvirtualdisplay` Python dep — gone. We switched to Qt5's built-in
  `QT_QPA_PLATFORM=offscreen` plugin (the Batch 4 fallback path is now
  the only path). Verified end-to-end against `eukaryotes.db`:
  Mammalia+Family render produces a valid 99 KB SVG in 1.0 s with no
  Xvfb installed.
- `xvfb`, `x11-utils` apt deps — gone with pyvirtualdisplay.

### Render path simplification

`src/visualization.py::render_tree_in_process` previously had a
three-branch `try/except` around `pyvirtualdisplay.Display`:

```python
try:
    from pyvirtualdisplay import Display
    display = Display(visible=False, size=(1200, 1000))
    display.start()
except ImportError: ...
except (FileNotFoundError, OSError) as e:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
...
finally:
    if display is not None:
        display.stop()
```

Now collapsed to:

```python
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

No display object, no cleanup, no failure modes to handle.

### GitHub Actions workflow

- `conda-incubator/setup-miniconda@v3` → `astral-sh/setup-uv@v6`.
- `ncbi-datasets-cli` now installed via `curl` to `/usr/local/bin/datasets`
  (~40 s, no env solve).
- Python deps via `uv sync --extra pipeline --no-default-groups`
  (~10 s with cache).
- All Python invocations use `uv run …` instead of bare `python …`.

### Streamlit Community Cloud

Per Streamlit Cloud's documentation (fetched 2026-06-15), `uv.lock` is
the first-priority dependency file. With our `uv.lock` present, Cloud
will detect it, install Python deps with uv, and apply `packages.txt`
for apt. No further configuration on the Cloud side.

### Files touched

| File | Change |
|---|---|
| `pyproject.toml` (new) | Project metadata + deps |
| `.python-version` (new) | `3.11` |
| `uv.lock` (new) | Generated by `uv lock`, ~150 KB |
| `environment.yml` | **Deleted** |
| `packages.txt` | 5 → 3 lines |
| `src/visualization.py` | Render path collapsed to offscreen-only |
| `.github/workflows/update_db.yml` | uv-based, curl for datasets CLI |
| `README.md` | Quickstart uses `uv sync` + `uv run` |
| `docs/DEVELOPMENT.md` | Env section rewritten |
| `docs/PIPELINE.md` | Local-run + workflow steps updated |

## Items still intentionally deferred

- **Phase 2 #18 (NCBITaxa singleton)** — blocked by Streamlit thread-affinity;
  needs a thread-local accessor, not a naive module global. The
  `lru_cache`-on-lookups gives most of the wins safely in the interim.
- **Phase 2 #25 (ENA streaming)** — investigated and parked. The
  streaming attempt is reverted; the working `format=json` path is in
  place. No outstanding bug. Optimization itself won't be retried
  unless the TSV row-count discrepancy is diagnosed (suspected
  undocumented server-side cap).
- **Phase 2 #28 (caches → src/cache.py)** — straightforward but
  depends on the app.py UI split planned in Phase 3, so deferred
  there to avoid churn.
