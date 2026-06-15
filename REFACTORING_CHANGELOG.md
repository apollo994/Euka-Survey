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

## Items still intentionally deferred

- **Phase 2 #18 (NCBITaxa singleton)** — blocked by Streamlit thread-affinity;
  needs a thread-local accessor, not a naive module global. The
  `lru_cache`-on-lookups gives most of the wins safely in the interim.
