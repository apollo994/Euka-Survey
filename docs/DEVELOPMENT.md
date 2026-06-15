# Development

This document is for people contributing to EukaSurvey or running it
from source. For *using* the deployed app, see [the README](../README.md).
For architectural background, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Environment

```bash
conda env create -f environment.yml
conda activate euka_refactored
```

The conda env is **required** (not just preferred) because:

- ETE3 + PyQt5 need C extensions that are flaky to install from pip.
- The pipeline shells out to the `datasets` CLI, distributed via
  `ncbi-datasets-cli` on conda-forge.

### Why `numpy<2.0` is pinned

`ete3==3.1.3` and the matplotlib version we use were both built against
the NumPy 1.x ABI. With NumPy 2.0 you get `ImportError`s deep inside
ete3's drawing code. If you need to bump it, plan to bump ete3 and
matplotlib in the same PR.

### Why `xvfb` is in `packages.txt`

Streamlit Community Cloud runs in a container without a display server.
`pyvirtualdisplay` + `xvfb` give the ETE3 render subprocess a
fake X server so PyQt5 can render. See [ARCHITECTURE.md § Why tree
rendering happens in a subprocess](ARCHITECTURE.md#why-tree-rendering-happens-in-a-subprocess).

---

## Running locally

```bash
streamlit run app.py
```

On first launch the app downloads `eukaryotes.db` (~300 MB) from the
latest GitHub Release. Subsequent launches use the cached copy.

If you want to **rebuild the DB from scratch** instead of downloading,
see [PIPELINE.md](PIPELINE.md).

If you want to **force a fresh download** of the DB, delete the local
file:

```bash
rm eukaryotes.db
streamlit run app.py
```

(The download is now atomic — it writes to `eukaryotes.db.tmp` and
renames on success, so an interrupted download won't leave a corrupt
file behind.)

---

## Code layout

See [ARCHITECTURE.md § Repository layout](ARCHITECTURE.md#repository-layout)
for the full tree. Short version:

- `app.py` — Streamlit UI + orchestration. Currently a large single
  file; targeted for splitting into `ui/` modules (Phase 3 in the
  audit).
- `src/` — web-app domain logic, importable from `app.py`. No
  Streamlit imports outside `app.py` and `src/utils.py`.
- `db_builder/` — offline data pipeline. Not used at runtime by the
  app. Has its own `__main__` entry points.

`src/constants.py` is the single source of truth for taxids, ranks, UI
limits, and timeouts. Do not duplicate these literals in new code.

---

## Conventions emerging from the refactor

The codebase is in the middle of a multi-batch refactor. New code
should follow these conventions; existing violations are tracked in
the audit.

1. **No Streamlit imports outside `app.py`/`src/utils.py`.** Domain
   modules should be importable from a plain Python script.
2. **`logging`, not `print`.** Every `db_builder/` module already uses
   `logging.getLogger("euka.<module>")`. Follow the same pattern for
   new modules.
3. **Use `contextlib.closing(...)` for raw `sqlite3.connect()`.** The
   default `with sqlite3.connect(...)` commits but does not close.
4. **No new `NCBITaxa()` instantiations on hot paths.** Use the
   cached helpers in `src/ete_utils.py` (`get_name_from_taxid`,
   `get_rank_from_taxid`) where possible. A proper singleton is in
   the audit (Phase 2 #18) — for now `lru_cache` on the lookups is
   the workaround.
5. **Atomic file writes.** When producing a file the next run will
   depend on, write to `<file>.tmp` and `os.replace` on success.
6. **Constants over magic numbers.** Add new constants to
   `src/constants.py`, not inline.
7. **Match the existing typed-dict shape for metadata** (`n_rows`,
   `c_*`, `s_*`, `p_*`) for now. A real `@dataclass` migration is
   tracked as Phase 3 #30.

---

## Testing

There is **no test suite yet**. Tracked as audit item **H7** and as
roadmap Phase 3 #34.

Until that's in place, the testing checklist is manual. See
[Manual testing checklist](#manual-testing-checklist) below.

### Manual testing checklist

After non-trivial changes to `app.py` or `src/`:

1. **Cold start (no `eukaryotes.db`):**
   ```bash
   rm -f eukaryotes.db
   streamlit run app.py
   ```
   Verify the download spinner appears and the app loads after it
   finishes.

2. **Precomputed root + tree render:**
   - Pick "Mammalia (40674)" + "Family"
   - Verify "Tree size: ~N family nodes" appears
   - Click "Generate Visualization"
   - Verify the SVG tree renders and "Download SVG" works

3. **Non-precomputed root (live ETE3 fallback path):**
   - Pick "Enter your own", enter a taxid not in the common list
     (e.g. `7742` for Vertebrata)
   - Pick a valid rank below it (e.g. Family)
   - Verify the tree-size info appears and the tree renders

4. **Filter / sort / limit:**
   - Pick a root with many children (Plants 33090 + Genus)
   - Apply a filter ("Must have Annotations AND Long-Read RNA")
   - Sort by a different metric
   - Set a low top-N
   - Verify only N nodes render, "Nodes included: N/M" message
     appears

5. **TSV export:**
   - Click "Download TSV"
   - Open in a spreadsheet, verify columns + rows look sane

6. **Edge cases:**
   - Enter an invalid taxid string ("abc") → should warn, not crash
   - Enter a taxid that doesn't exist (`999999999`) → should show error
   - Enter a species-level taxid → should show "no further breakdown"
     message

For UI behaviour the deployed app at
<https://euka-survey-62bi4d34cytdpb56zmhms2.streamlit.app/> is the
reference.

---

## Pipeline development

If you're working on `db_builder/`, see [PIPELINE.md](PIPELINE.md) for
how to run it and what each step does.

A full pipeline run takes 30–60 minutes. For faster iteration:

- Each step's module has a `__main__` block you can run in isolation.
- Mock the ENA fetch by writing a fixture JSON and pointing
  `get_reads.py` at it (the function returns plain dicts).

---

## Refactor in flight

The codebase is being refactored in phases. Before adding a feature
that overlaps with refactor territory, check:

- **[REFACTORING_AUDIT.md](../REFACTORING_AUDIT.md)** — full findings,
  technical-debt ranking, and roadmap.
- **[REFACTORING_CHANGELOG.md](../REFACTORING_CHANGELOG.md)** — what's
  been changed and why.

Notable invariants that PRs need to respect:

- The **two filter/sort/limit code paths** in `app.py` and
  `database.py` must produce identical results until they are unified
  (audit C1, the top-priority refactor).
- The `precomputed_*` tables are read-only at app runtime. New schema
  goes through the pipeline and is gated on the workflow smoke test.
