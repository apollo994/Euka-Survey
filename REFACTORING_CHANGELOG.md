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

## Items intentionally deferred from this batch

- **Phase 1 #11 (pin env.yml + drop pandas/scipy)** — confirmed `pandas`/`scipy`
  unused via grep, but env-file changes deserve their own commit + smoke run.
- **Phase 1 #12 (`print` → `logging` in `db_builder/`)** — touches every script,
  prefer to do it once standalone.
- **Phase 1 #14 (workflow smoke-test step)** — workflow change, separate concern.
- **Phase 2 #18 (NCBITaxa singleton)** — blocked by Streamlit thread-affinity;
  needs a thread-local accessor, not a naive module global. The
  `lru_cache`-on-lookups above gives most of the wins safely in the interim.
