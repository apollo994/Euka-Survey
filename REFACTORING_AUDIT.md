# EukaSurvey — Refactoring Audit

Reference document for the in-progress refactor on branch `refactor/improve-codebase`.
Source-of-truth for findings; update as items are completed.

---

## Executive Summary

### Top 10 highest-value refactors

| # | Refactor | Impact | Difficulty | Status |
|---|---|---|---|---|
| 1 | Eliminate the duplicated filter/sort/limit logic between `app.py` (Python fallback) and `src/database.py::get_filtered_taxa_metadata` (SQL path) by routing both through a single helper that accepts pre-resolved taxids | High — biggest correctness risk in the repo; CLAUDE.md explicitly warns about keeping the paths in sync | Medium | **DONE** (2026-06-15) — parity verified |
| 2 | Extract a single `NCBITaxa` module-level singleton/accessor (with thread-safe lazy init) and reuse it across `src/taxonomy.py`, `src/ete_utils.py`, `src/visualization.py`, `app.py`, and `db_builder/` | High — currently 5+ instantiations per Streamlit rerun, opens many SQLite handles, slows hot path | Low | **PARTIAL / BLOCKED** — `@lru_cache` on lookup helpers in place; full module-level singleton blocked by Streamlit thread-affinity (Qt/SQLite handles must stay on the worker thread). Needs thread-local accessor. |
| 3 | Split `app.py` (530 lines) into `ui/sidebar.py`, `ui/query_config.py`, `ui/summary.py`, `ui/tree.py`, `ui/export.py` + a thin `app.py` controller | High — current file is the biggest maintainability liability | Medium | **DONE** (2026-06-15) — app.py now 57 lines |
| 4 | De-duplicate the `phylum_metadata` row→dict construction in `database.py` (identical in `build_phylum_metadata` and `get_filtered_taxa_metadata`) | Medium | Low | **DONE** (2026-06-15) — shared `_row_to_metadata` in `src/database.py:50`, used by both paths |
| 5 | Add a render-subprocess timeout and proper error/cleanup in `app.py::generate_tree_svg_cached` (no `p.join(timeout=...)`, no `try/finally` cleanup, temp files written to CWD instead of `tempfile.NamedTemporaryFile`) | High — current code can hang the app indefinitely on a stuck child process | Low | **DONE** (2026-06-15) |
| 6 | Move the live ETE3 rank-resolution block (lines 178–202 of `app.py`) into a memoized helper in `src/taxonomy.py` and cache by `root_taxid` | Medium-High — runs on every Streamlit rerun | Low | **DONE** (2026-06-15) — `taxonomy.resolve_valid_ranks(root_taxid)` with `@lru_cache(maxsize=512)` |
| 7 | Replace the `globals + cached path` pattern in `src/visualization.py` (`_AXIS_IMG_PATH`, `_LEGEND_IMG_PATH`, `_COLOR_SQUARES`) with `functools.lru_cache`-decorated generators returning paths inside a per-render `tempfile.TemporaryDirectory` (so the shared `.tmp_bars/` race goes away) | Medium-High | Medium | **DONE** (2026-06-15) — per-render `tempfile.TemporaryDirectory(prefix="euka_bars_")`; module globals removed |
| 8 | Make the `db_builder` pipeline incremental, idempotent, and resilient: each step writes to a staging file/table, exceptions are caught per step, and `precompute_taxa.py` is called from `pipeline_build_db.main()` instead of only from the GitHub workflow | High | Medium | **DONE** (2026-06-15) — resilience via `@_step` + `PipelineError` + `.partial` → `os.replace`; `precompute_taxa` invoked as step 7; per-step pickle snapshots for steps 1–4 mean failed builds resume from the last successful step instead of re-fetching from NCBI/Annotrieve/ENA. Snapshots auto-cleanup on success; `--from-step N` forces re-fetch. (Roadmap #32) |
| 9 | Centralize the "common taxa" set (`{2759, 33208, 40674, 9443, 4751, 33090}`) and the rank/filter/sort label maps into `src/constants.py`. Currently duplicated across `app.py`, `precompute_taxa.py`, `pipeline_build_db.py` | Medium | Low | **DONE** (2026-06-15) |
| 10 | Add a covering index `CREATE INDEX idx_precomputed_taxa_cover ON precomputed_taxa(root_taxid, target_rank, taxid, name)` so the count + fetch can be served from the index alone | Medium | Low | **DONE** (2026-06-15) — index present in shipped DB; `EXPLAIN QUERY PLAN` confirms `USING COVERING INDEX idx_precomputed_taxa_cover` |

---

## Findings by File

### `app.py` (529 lines)

**Issues**

1. God file. UI, query orchestration, caching wrappers, multiprocessing for SVG rendering, ad-hoc filter logic, ETE3 rank resolution, TSV download wiring — all in one module. `main()` body ~430 lines.
2. Duplicated filter/sort/limit logic (lines 432–462) reimplements the SQL path in `database.get_filtered_taxa_metadata`. Python fallback uses `stats.get(k, 0)` while SQL uses raw `f.{k} > 0`; secondary sort key differs subtly.
3. Dead import: `from ete3 import NCBITaxa` on line 6 — shadowed by re-import on line 181.
4. Repeated `NCBITaxa()` instantiation: line 182 + `ete_utils.get_name_from_taxid` (225) + `ete_utils.get_rank_from_taxid` (226). Three new SQLite connections per Streamlit rerun.
5. Rank-resolution block (lines 178–202) not cached. Runs on every rerun.
6. Magic numbers: `HARD_CAP = 500`, `standard_breakpoints`, cache `max_entries`, render size — move to constants.
7. `taxid_map` (lines 163–170) duplicates `common_taxa` (line 139). Drift risk.
8. Race-prone temp file naming. `temp_tree_{session_id}.svg` written into CWD twice (line 79, line 485) with two different UUIDs. Should be `tempfile.NamedTemporaryFile(suffix=".svg")`.
9. `generate_tree_svg_cached` does not pass timeout to `p.join()` (line 84). Stuck child = hung UI thread.
10. No cleanup on subprocess crash mid-write.
11. Filter logic strings compared by literal value (`"Match ALL (AND)"`). Any UI relabel silently breaks SQL path.
12. `st.cache_data` over `tuple(query_taxids)` (line 441) hashes hundreds–thousands of ints per click.
13. `st.cache_data` on `generate_tree_svg_cached` hashes dict-of-dicts (~500 dict hashings per lookup at top_n=500).
14. `query_taxids` is populated inside one block and read in a different block — hidden state coupling.

**Recommended refactor**: caches to `src/cache.py`; rank-resolution to `taxonomy.resolve_valid_ranks(root_taxid)`; generic `filter_sort_limit` helper for both paths; `tempfile.NamedTemporaryFile` + `try/finally`; explicit `p.join(timeout=60)` + terminate.

---

### `src/database.py`

**Issues**

1. Two near-identical row→dict transformations in `build_phylum_metadata` (lines 47–64) and `get_filtered_taxa_metadata` (lines 130–145). Extract `_row_to_metadata(row)`.
2. Filter-string coupling: `filter_logic == "Match ALL (AND)"` (line 96). Use enum.
3. Magic chunk size `900` inline. Move to module-level constant.
4. `exclude_empty` semantics diverge between functions: `build_phylum_metadata` inserts zero rows when `exclude_empty=False`; `get_filtered_taxa_metadata` never returns rows missing from `precomputed_clade_features` (INNER JOIN). Same param, different result shape.
5. No connection ownership/row factory.
6. No `LIMIT` bounds checking.
7. Repeated `p_xxx = c_xxx / n * 100 if n else 0` in both functions.

---

### `src/taxonomy.py`

**Issues**

1. `get_taxa_at_rank` instantiates `NCBITaxa()` on every call.
2. `get_descendant_taxa(intermediate_nodes=True)` then filters by rank in Python — slow for deep clades. The CTE pattern in `ete_utils` is faster.
3. Return type not aliased (`TaxaPair = tuple[int, str]`).
4. No docstring example, no edge case handling for unknown taxid.

---

### `src/ete_utils.py`

**Issues**

1. Misleading module docstring — claims it only fetches descendants.
2. `get_name_from_taxid` raises on non-int; `get_rank_from_taxid` silently returns `"clade"`. Inconsistent error contracts.
3. Hidden connection leak: `NCBITaxa().dbfile` constructs and abandons a `NCBITaxa` instance.
4. No caching on `get_name_from_taxid` / `get_rank_from_taxid` despite being on the render hot path.
5. `sqlite3.connect(NCBITaxa().dbfile)` opens RW; should use `mode=ro` URI.

---

### `src/utils.py`

**Issues**

1. `generate_tsv` re-resolves taxa and re-runs `build_phylum_metadata` on every download instead of reusing computed metadata.
2. `urllib.request.urlretrieve` without Content-Length / hash check — partial downloads marked "present". Use `eukaryotes.db.tmp` + `os.replace`.
3. `ensure_database` calls `st.error` — couples utils to Streamlit. Should raise, let caller report.
4. TSV header text is the only place the public column schema is defined. Hardcoded column ordering repeated twice (header + writerow).

---

### `src/visualization.py`

**Issues**

1. Mixed concerns: subprocess entry, bar chart, axis/legend, ETE3 layout, ETE3 tree style — five responsibilities in one module.
2. Dead import: `import re` (line 3).
3. Mutable module globals (`_AXIS_IMG_PATH`, etc.) persist across renders, but `TMP_DIR` is `rmtree`'d at the start of every render → stale paths in subsequent calls. Masked only because the subprocess re-imports.
4. `TMP_DIR = ".tmp_bars"` is project-relative, racy across concurrent renders. Use `tempfile.mkdtemp()` per render.
5. Per-leaf PNG write (500 files at top_n=500).
6. N+1 ETE3 lookup: `for tid in phylum_metadata.keys(): ncbi.get_lineage(tid)` (line 38–43). Use `get_lineage_translator` once.
7. No matplotlib backend pinned. Should `matplotlib.use("Agg")` before `import pyplot` in subprocess.
8. `pyvirtualdisplay` ImportError silently swallowed — confusing failure mode locally.
9. Redundant re-imports inside `render_tree_in_process` — `spawn` already re-imports the module.
10. `int(node.name)` will crash on internal nodes if ETE3 collapses single-child branches.
11. `generate_color_square` writes 12×12 px files per color — could be in-memory.

---

### `db_builder/pipeline_build_db.py`

**Issues**

1. No per-step error handling. Failing fetch silently produces a degenerate DB.
2. No staging / atomic rename. Output goes straight to dated `.db`.
3. Inconsistent step counting: `[1/5]`–`[5/5]` but there are actually 6 logical steps; `precompute_taxa` is never called.
4. `precompute_taxa.py` not invoked. Local pipeline produces an incomplete DB.
5. Line 53: `9606 not in short_read_taxids.keys()` — `.keys()` unnecessary; message inverted (says "excluded" when in fact missing).
6. `from db_builder.precompute_aggregations import precompute_clades` imported inside `main` asymmetrically.
7. `sys.path.insert(0, ...)` hack — needs proper package config.

---

### `db_builder/precompute_aggregations.py`

**Issues**

1. `ncbi.get_lineage_translator(all_taxids)` for ~1.8M species in one call. Memory blowup risk; chunk.
2. Fallback `lineage = [taxid]` (line 65) silently under-counts ancestors when lineage lookup fails. **Correctness bug.**
3. `ncbi.get_rank(all_raw_taxids)` for all taxids in one call. Same risk.
4. No secondary indexes on `precomputed_clade_features` (PK only — adequate today).
5. Single-function does fetch, filter, roll-up, write.
6. No schema-version check.
7. Defaultdict-of-dicts holds 600k–1M entries; could stream into SQLite.
8. Manual `conn.close()`; no context manager.

---

### `db_builder/precompute_taxa.py`

**Issues**

1. Naming inconsistency: `precompute_common_clades` here vs `precompute_clades` in `precompute_aggregations.py`.
2. Hardcoded common taxids + ranks duplicated with `app.py`.
3. No covering index on `(root_taxid, target_rank, taxid, name)`.
4. No PK on `precomputed_taxa`.
5. No connection context manager.
6. `sys.path` hack.
7. Per-pair `print`; no progress bar.

---

### `db_builder/build_db/build_database.py`

**Issues**

1. `with sqlite3.connect(...) as conn:` commits but does not close (Python sqlite3 context manager semantics).
2. No explicit `BEGIN`/`COMMIT` grouping.
3. `INSERT OR REPLACE` silently overwrites; consider truncate-and-rewrite.
4. No indexes on `taxid_features`.

---

### `db_builder/build_db/get_assemblies.py`

**Issues**

1. `subprocess.Popen` without context manager / `process.kill()`. Leak on consumer error.
2. `process.stdout` never explicitly closed.
3. No timeout.
4. `sys.exit(1)` from library function. Should `raise`.
5. `stderr=PIPE` but only read on error — pipe buffer can fill and block the child.
6. Hardcoded `EUKARYOTE_TXID` (also in `pipeline_build_db.py` and `get_reads.py`).

---

### `db_builder/build_db/get_annotations.py`

**Issues**

1. Timeout 120s — consider tuple `(connect, read)`.
2. No structured logging on retry attempts (tenacity `before_sleep`).

---

### `db_builder/build_db/get_reads.py`

**Issues**

1. `limit=0` POST loads entire ENA result into memory. *Investigated 2026-06-15: a streaming switch to `format=tsv` + `iter_lines()` returned only ~28% of rows (suspected undocumented server-side cap on TSV streaming). Reverted; `format=json` + `r.json()` retained as the correct-and-working path. Memory cost (a few hundred MB) is acceptable for an offline monthly pipeline.*
2. ✅ *(2026-06-15)* JSON decode failure returns empty dicts + `count=0` silently — now re-raises so tenacity retries (audit C3).
3. `int(record.get("tax_id"))` on missing key raises `TypeError` caught by `except`. Explicit check is clearer.
4. ✅ *(2026-06-15)* `fetch_ena_reads` wrapper is a no-op around `_ena_search` — collapsed.
5. `__main__` block claims "Verification complete" — doesn't verify. ✅ *(2026-06-15)* rewritten to log counts via `logging`.

---

### `db_builder/build_db/__init__.py`

Empty package marker — no issues.

---

### `.github/workflows/update_db.yml`

**Issues**

1. No failure notifications.
2. `mv eukaryote_taxid_features_*.db eukaryotes.db` assumes exactly one match.
3. No conda env caching.
4. No DB-validation step before publish.
5. `make_latest: true` overwrites previous release — no rollback path.
6. No artifact retention of intermediate logs.
7. No DB-size sanity check.

---

### `environment.yml`, `packages.txt`, `.streamlit/config.toml`

**Issues**

1. `pyvirtualdisplay` (pip) ↔ `xvfb` (apt) coupling implicit.
2. `numpy<2.0.0` pin reason undocumented.
3. No pins on `streamlit`, `requests`, `matplotlib`, `pandas`.
4. `pandas` / `scipy` listed but appear unused.
5. `tenacity` used by `db_builder/build_db/` but not declared in `environment.yml`.

---

### `README.md`

**Issues**

1. "Patch missing zero-count taxonomic entries" line is stale (patch step deleted in `bfbf5fe`).
2. Documents `precompute_taxa.py` as a follow-up step inconsistent with the workflow.

---

## Cross-Cutting Refactors

1. **One `NCBITaxa` singleton** in `src/ete_utils.py::_get_ncbi()`. Used everywhere. Drops 5+ instantiations per rerun.
2. **`src/constants.py`** with `EUKARYOTE_TXID`, `COMMON_CLADES`, `ALLOWED_RANKS`, `FULL_RANKS`, `HARD_NODE_CAP`, `STANDARD_BREAKPOINTS`.
3. **Single filter/sort/limit pipeline** operating on metadata dict. Both SQL and Python paths feed it.
4. **Typed metadata** via `@dataclass(frozen=True, slots=True)` instead of dict-of-dicts.
5. **Unified subprocess/render abstraction** in `src/render.py` owning spawn + temp-file + timeout.
6. **Logging instead of `print`** in all `db_builder/` modules.
7. **Atomic DB writes** for both live download and pipeline output.
8. **Connection context managers** (`closing(...)`) throughout `db_builder/`.
9. **Drop `sys.path.insert` hacks** via `pyproject.toml`.
10. **Tests** — at minimum, fixture-based comparison ensuring SQL and Python paths produce identical results.

---

## Architectural Improvements

**A. Layered architecture**

```
src/
  core/        # pure domain (typed metadata, enums)
  data/        # database.py, utils.ensure_database
  taxonomy/    # ete_utils.py, taxonomy.py, lookups
  visualization/  # bars.py, layout.py, render.py, subprocess.py
  cache.py     # all @st.cache_* wrappers
ui/
  sidebar.py
  query_config.py
  summary.py
  tree.py
  export.py
app.py         # thin orchestrator
```

**B. `@dataclass` metadata** replaces dict-of-dicts.
**C. Schema versioning** via `PRAGMA user_version`; app refuses stale DB.
**D. Pipeline as state machine** — fetch steps produce snapshot files; build step is pure.
**E. Long-lived Qt render worker** — retire spawn-per-render dance.
**F.** ✅ *(2026-06-15)* Config-driven metric definition — single `METRICS: tuple[Metric, ...]` in `src/metrics.py` replaces all hardcoded `ass/ann/rna/lng` references across `database.py`, `visualization.py`, `app.py`, and `utils.py` (Batch 11).

---

## Technical Debt Ranking

### Critical
- **C1.** ✅ *(2026-06-15)* Duplicated filter/sort/limit logic in `app.py` vs `database.py` — unified via `FilterLogic` enum + `filter_sort_limit_metadata` helper; parity verified.
- **C2.** ✅ *(2026-06-15)* `app.py::generate_tree_svg_cached` calls `p.join()` without timeout. [`app.py:84`]
- **C3.** ✅ *(2026-06-15)* `get_reads.py::_ena_search` swallows JSON decode errors → degenerate DB. [`get_reads.py:32-36`]
- **C4.** ✅ *(2026-06-15)* `precompute_aggregations.py` silently under-counts ancestors when lineage lookups fail — missing-lineage rows are now SKIPPED instead of fake-attributed to self; warning logged with count.

### High
- **H1.** ✅ *(2026-06-15)* No atomic write in `utils.ensure_database`. [`utils.py:8-16`]
- **H2.** ✅ *(2026-06-15)* Race in `.tmp_bars` between concurrent users on Cloud — replaced with per-render `tempfile.TemporaryDirectory`; module globals dropped.
- **H3.** ✅ *(2026-06-15)* `app.py` rank-resolution runs ETE3 on every rerun — moved to `taxonomy.resolve_valid_ranks` with `@lru_cache`.
- **H4.** ⚠️ *Partial (2026-06-15)* — lookup `lru_cache` in place; full singleton blocked by Streamlit thread-affinity.
- **H5.** ✅ *(2026-06-15)* Pipeline lacks per-step error handling and atomic output — `@_step` decorator + `PipelineError` + `.partial` → `os.replace` rename on success.
- **H6.** ✅ *(2026-06-15)* Workflow has no DB-validation gate before publishing.
- **H7.** ✅ *(2026-06-15)* No tests at all — pytest suite added (63 tests + 2 network); covers constants, filter/sort/limit, SQL/Python parity (audit C1 regression net), rank resolution, aggregation rollup correctness with explicit C4 regression test (hostile-tested).

### Medium
- **M1.** ✅ *(2026-06-15)* `app.py` 530 lines in one function — now 57 lines (Batch 12).
- **M2.** ✅ *(2026-06-15)* Duplicate row→dict construction in `database.py` — shared `_row_to_metadata` helper used by both `build_phylum_metadata` and `get_filtered_taxa_metadata`.
- **M3.** ✅ *(2026-06-15)* Dict-of-dicts metadata stringly-typed — replaced end-to-end with `@dataclass(frozen=True, slots=True) CladeMetadata` in `src/metrics.py`; all data/UI/test paths read via attribute access (or `getattr` for dynamic keys driven by `Metric` config). Percentages computed on demand via `m.percent(key)`.
- **M4.** Magic numbers scattered.
- **M5.** ✅ *(2026-06-15)* Common-taxa list duplicated.
- **M6.** ⊘ *(2026-06-15)* `get_taxa_at_rank` slow for large clades — investigated, rejected: CTE rewrite is slower (no parent index in ETE3 SQLite); original retained with explanatory comment.
- **M7.** ✅ *(2026-06-15)* `precompute_aggregations` loads 1.8M lineages in one call — chunked at 50k.
- **M8.** ✅ *(2026-06-15)* `get_assemblies` uses `sys.exit(1)` instead of raising.
- **M9.** ✅ *(2026-06-15)* `pyvirtualdisplay` ImportError silently swallowed — broader `(FileNotFoundError, OSError)` catch + fallback to `QT_QPA_PLATFORM=offscreen`.
- **M10.** ✅ *(2026-06-15)* No structured logging in `db_builder/`.

### Low
- **L1.** ✅ *(2026-06-15)* Dead imports (`from ete3 import NCBITaxa` in `app.py`; `import re` in `visualization.py`).
- **L2.** ✅ *(2026-06-15)* `dict.keys()` usage in `pipeline_build_db.py:53`.
- **L3.** ✅ *(2026-06-15)* Inconsistent error contracts in `ete_utils.py`.
- **L4.** ✅ *(2026-06-15)* README inaccuracy about "patch missing zero-count taxonomic entries".
- **L5.** `__main__` smoke-tests in `db_builder/build_db/*.py` aren't real entry points.
- **L6.** ✅ *(2026-06-15)* Unused deps (`pandas`, possibly `scipy`) in `environment.yml`.
- **L7.** ✅ *(2026-06-15)* Pipeline step-counter mismatch.

---

## Refactor Roadmap

### Phase 1 — Quick wins (<1 hour each)

1. ✅ Delete dead imports (`from ete3 import NCBITaxa` at top of `app.py`; `import re` in `visualization.py`; also unused `NCBITaxa` in `pipeline_build_db.py`).
2. ✅ Fix `pipeline_build_db.py:53`: `9606 not in short_read_taxids and 10090 not in short_read_taxids` and fix inverted message.
3. ✅ Fix step-counter strings in `pipeline_build_db.py`.
4. ✅ Add `p.join(timeout=120)` + `p.terminate()` fallback in `generate_tree_svg_cached`.
5. ✅ Wrap `urlretrieve` in atomic `.tmp` + `os.replace` with timeout.
6. ✅ Centralize common-taxa list in `src/constants.py`; import from `app.py`, `precompute_taxa.py`, `pipeline_build_db.py`, `get_assemblies.py`, `get_reads.py`.
7. ✅ Add covering index in `precompute_taxa.py`: `CREATE INDEX idx_precomputed_taxa_cover ON precomputed_taxa(root_taxid, target_rank, taxid, name)`. *(Takes effect on next DB regen.)*
8. ✅ `@functools.lru_cache` on `get_name_from_taxid` and `get_rank_from_taxid`.
9. ✅ Use `mode=ro` URI for ETE3 SQLite in `get_all_descendant_taxids`.
10. ✅ Update README.md (remove stale "patch missing zero-count" line).
11. ✅ Drop unused `pandas`/`scipy` from `environment.yml`, add missing `tenacity`, document the `numpy<2.0` pin.
12. ✅ Switch `db_builder/` `print` to `logging` with `basicConfig(level=INFO)`.
13. ✅ Add `closing(...)` to `precompute_taxa.py` and `precompute_aggregations.py`.
14. ✅ Add DB-smoke-test step to the workflow (size + per-table row counts).

### Phase 2 — Medium-effort improvements

15. ✅ Extract `_row_to_metadata` helper in `database.py`; reuse in both functions.
16. ✅ Replace `"Match ALL (AND)"` string compare with `FilterLogic` enum in `app.py` and `database.py`.
17. ✅ Move filter/sort/limit into single pure helper `filter_sort_limit_metadata(metadata, ...) -> (dict, int)`. Both paths feed it.
18. ⏳ Single `NCBITaxa` accessor in `src/ete_utils.py`; replace all `NCBITaxa()` calls. *(Blocked by Streamlit thread-affinity; needs thread-local accessor.)*
19. ✅ Pull rank-resolution out of `app.py` into `taxonomy.resolve_valid_ranks(root_taxid)`.
20. ⊘ Reimplement `get_taxa_at_rank` using the recursive-CTE pattern from `ete_utils`. *(Investigated and rejected: CTE is slower because ETE3 SQLite has no parent index.)*
21. ✅ Use `tempfile.TemporaryDirectory()` per render in `visualization.render_tree_in_process`; drop globals.
22. ✅ Pin matplotlib backend to Agg at start of `render_tree_in_process`.
23. ✅ Batch lineage lookup in `render_tree_in_process`.
24. ✅ Chunk `get_lineage_translator` calls in `precompute_aggregations.py` (50k chunks).
25. ⊘ Stream ENA reads via `iter_lines()` (TSV format) — *Investigated and rejected. TSV+iter_lines path silently returned ~28% of rows (likely undocumented server-side TSV row cap or stream truncation). Reverted in commit `0fcb54b`; `format=json` + `r.json()` retained as the correct path. No outstanding bug; the optimization is not in place and is parked unless we diagnose the row-count discrepancy.*
26. ✅ Per-step try/except in `pipeline_build_db.py`; `.partial` + rename. Call `precompute_taxa.precompute_common_clades` from the pipeline.
27. ✅ Replace `sys.exit(1)` in `get_assemblies` with `raise RuntimeError(...)`. *(Pulled forward in Batch 2.)*
28. ✅ *(2026-06-15)* Move all `@st.cache_*` wrappers into `src/cache.py`. *(Batch 12: all 7 wrappers — get_db_ready, get_db_connection, get_taxa_count_cached, fetch_taxa_cached, get_phylum_metadata_cached, get_filtered_taxa_metadata_cached, generate_tree_svg_cached — now live in src/cache.py and are imported from there by app.py + ui/.)*

### Phase 3 — Large architectural improvements

29. ✅ *(2026-06-15)* Split `app.py` into `ui/` modules + thin orchestrator. *(Batch 12: app.py now 57 lines — set_page_config + main() that calls the five renderers. Sections live in ui/sidebar.py, ui/query_config.py, ui/summary.py, ui/tree.py, ui/export.py with shared state in ui/state.py::QueryState.)*
30. ✅ *(2026-06-15)* Replace dict-of-dicts metadata with `@dataclass(frozen=True, slots=True) CladeMetadata` end-to-end. *(Batch 13: `CladeMetadata` in `src/metrics.py` carries taxid + 9 count fields + `percent(key)` + `zero(taxid)`. `_row_to_metadata` is now `CladeMetadata(*row)` — guarded by `test_sql_columns_match_clade_metadata_field_order`. Consumers — `src/utils.generate_tsv`, `src/visualization.py`, `ui/summary.py` — use attribute access or `getattr(m, key)` for dynamic Metric-driven keys. Full suite: 92 passed, 3 skipped.)*
31. ✅ *(2026-06-15)* `Metric` enum + config table for the four resources. *(Batch 11: new `src/metrics.py` with frozen `Metric` dataclass + `METRICS` tuple. Drives `database.py` column groups, `visualization.py` bar/legend/count colors, `app.py` filter/sort dropdowns, and `utils.py` TSV schema. 10 metric-config sanity tests + 3 database-drift guards; full suite 83 passed / 3 skipped.)*
32. ✅ *(2026-06-15)* Pipeline as staged state machine (per-step snapshot files; idempotent build). *(Batch 14: steps 1–4 pickle return values into `.<partial>.snapshots/stepN_<key>.pkl` via `_run_cached`; main() loads on hit, skips fetch, logs `Resumed from snapshot: …`. Snapshots survive crashes, get nuked on success. Steps 5–7 are recomputed unconditionally — the `.partial` DB is their state. `--from-step N` purges snapshots ≥ N for forced re-fetches. 18 unit tests in `tests/test_pipeline_snapshots.py`; full suite 110 passed, 3 skipped.)*
33. ✅ Add `pyproject.toml`; drop `sys.path.insert` hacks. *(Batch 7 added pyproject.toml; Batch 8 removed the 5 sys.path hacks across db_builder/ and tests/conftest.py.)*
34. ✅ `tests/` with fixture SQLite + parity test (SQL path vs Python path produce identical results) — done as Batch 6.
35. ✅ `PRAGMA user_version` schema versioning. *(Batch 9: pipeline stamps version on every build; app validates on startup via `_check_schema_version`; legacy unstamped DBs accepted as compatible with v1 so existing users aren't broken; 7 new tests including stamper/reader drift guard.)*
36. Long-lived Qt render worker (retire spawn-per-render).
37. ✅ Versioned releases + `latest` pointer supporting rollback. *(Batch 10: workflow now tags each release `db-YYYY.MM.DD.HHMM` with `make_latest: true`. Past releases kept for rollback; app's `/releases/latest/download/` URL keeps working.)*
