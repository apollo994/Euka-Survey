# Development

This document is for people contributing to EukaSurvey or running it
from source. For *using* the deployed app, see [the README](../README.md).
For architectural background, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Environment

The project uses [uv](https://docs.astral.sh/uv/) for Python
dependency management. Install uv once
(`curl -LsSf https://astral.sh/uv/install.sh | sh`), then:

```bash
uv sync                          # main deps only (web-app shape)
uv sync --extra pipeline         # + tenacity for db_builder/
uv sync --extra pipeline --group dev   # + pytest for tests
```

`uv sync` creates `.venv/`, installs from `uv.lock` (deterministic
versions), and pins the Python version from `.python-version`.

Run commands inside the env without activating it:

```bash
uv run streamlit run app.py
uv run pytest
uv run python db_builder/pipeline_build_db.py
```

### Why we don't use conda anymore

The conda env (now deleted) existed because PyQt5 wheels used to be
unreliable on PyPI. They've been solid since ~2021 — `pyqt5==5.15.11`
installs cleanly via uv/pip on Linux/macOS/Windows x86_64. The other
historical conda-only dep, `ncbi-datasets-cli`, is a standalone binary
that's downloaded with `curl` in the GitHub Actions workflow (see
[PIPELINE.md](PIPELINE.md)).

### Why `numpy<2.0` is pinned

`ete3==3.1.3` and the matplotlib version we use were both built against
the NumPy 1.x ABI. With NumPy 2.0 you get `ImportError`s deep inside
ete3's drawing code. If you need to bump it, plan to bump ete3 and
matplotlib in the same PR.

### What's in `packages.txt`

Streamlit Cloud reads this for apt packages. We declare the minimal
Qt5 system libraries the PyQt5 wheel links against at import time:

- `libdbus-1-3` — Qt5 dbus integration
- `libfontconfig1` — font lookup for SVG rendering
- `libxkbcommon-x11-0` — Qt5 keyboard library (linked even when we use
  the offscreen plugin)
- `libgl1` — provides `libGL.so.1`, needed by `from PyQt5 import QtGui`
- `libglib2.0-0t64` — provides `libgthread-2.0.so.0` (+ the rest of
  glib), also needed by `from PyQt5 import QtGui`

No `xvfb` — tree rendering uses Qt5's built-in `offscreen` platform
plugin (`QT_QPA_PLATFORM=offscreen`) instead of a virtual X server.
See [ARCHITECTURE.md § Why tree rendering happens in a subprocess](ARCHITECTURE.md#why-tree-rendering-happens-in-a-subprocess).

#### ⚠️ The Streamlit Cloud / Debian trixie `t64` trap (read before editing `packages.txt`)

Streamlit Community Cloud's build image is **Debian trixie**, which
completed the [64-bit `time_t` transition](https://wiki.debian.org/ReleaseGoals/64bit-time).
Many runtime libraries were **renamed with a `t64` suffix**, and the
*old* unsuffixed name no longer exists as an installable package.

The one that bites us is glib:

| You want | On trixie it's called | The old name does |
| -------- | --------------------- | ----------------- |
| `libgthread-2.0.so.0`, `libglib-2.0.so.0`, … | `libglib2.0-0t64` | **fails** — `libglib2.0-0` is unsatisfiable, so `apt-get` aborts the *entire* `packages.txt` install |

**Why this is so easy to get stuck on:** when the bare `libglib2.0-0`
name fails, apt aborts everything in `packages.txt`, so you end up
*removing* the line to get the build to go green — and then the app
crashes at runtime with a missing `.so` instead. That's the loop:
add-bare-name → apt fails → drop the line → runtime crash → repeat. The
escape is the `t64` name, which both installs cleanly **and** ships the
`.so`.

**The symptom in the deploy log** (the app, not apt, is what crashes):

```
File ".../ete3/treeview/qt.py", line 27, in <module>
    from PyQt5 import QtGui, QtCore
ImportError: libgthread-2.0.so.0: cannot open shared object file: No such file or directory
```

…followed immediately by a **misleading cascade** on the next rerun:

```
ImportError: cannot import name 'get_db_connection' from 'src.cache'
```

That second error is **not a real bug** — `src/cache.py` imports
`src/visualization.py`, which dies on the `.so` load above and leaves
`src.cache` half-initialized in `sys.modules` for the concurrent
rerun. Fix the missing lib and both errors disappear. Don't go chasing
`src.cache`.

**How to fix / debug the next missing lib** (the libs above are the
known-complete set, but if a future ete3/PyQt5 bump links a new one):

1. Read the deploy log for `<libfoo>.so.N: cannot open shared object file`.
2. Find the trixie package that ships it — search
   <https://packages.debian.org/trixie/> by *Contents* for the exact
   `.so` filename. **Use the name the search returns verbatim**
   (it will include `t64` where applicable). Do not assume the
   Ubuntu/older-Debian name.
3. Add that exact package name to `packages.txt`, push to the deployed
   branch, and re-watch the log.

---

## Running locally

```bash
uv run streamlit run app.py
```

On first launch the app downloads `eukaryotes.db` (~300 MB) from the
latest GitHub Release. Subsequent launches use the cached copy.

If you want to **rebuild the DB from scratch** instead of downloading,
see [PIPELINE.md](PIPELINE.md).

If you want to **force a fresh download** of the DB, delete the local
file:

```bash
rm eukaryotes.db
uv run streamlit run app.py
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

### Running the test suite

```bash
uv run pytest                 # default: 63 tests, ~1 second
uv run pytest -v              # verbose: shows each test name + outcome
uv run pytest -m network      # also run the network smoke tests against ENA
uv run pytest tests/test_database.py    # run a single file
uv run pytest -k filter_sort  # run by name pattern
```

`pytest` is declared in `pyproject.toml`'s `dev` dependency group, so
`uv sync` installs it automatically.

### What's covered

- **`test_constants.py`** — sanity checks: `COMMON_CLADES` is well-
  formed, `ALLOWED_RANKS ⊆ FULL_RANKS`, rank ordering is canonical.
- **`test_filter_sort_limit.py`** — pure unit tests on the canonical
  filter/sort/limit helper that backs both the SQL and Python paths.
- **`test_database.py`** — SQL pushdown vs Python helper parity
  across a 16-scenario matrix; `build_phylum_metadata` chunking +
  zero-fill behavior. This is the regression net for audit C1.
- **`test_taxonomy.py`** — `resolve_valid_ranks` against live ETE3:
  the six common clades + Vertebrata (unranked lineage walk) +
  species-rank root (empty result) + unknown taxid (raises).
- **`test_aggregations.py`** — `_precompute_clades_impl` rollup
  correctness against real ETE3 taxonomy (human, chimp, mouse,
  zebrafish). Includes the **audit C4 regression test**: a
  synthesized species with no ETE3 lineage must be SKIPPED, not
  self-attributed. (Hostile-tested: confirmed to fail if C4 is
  reintroduced.)
- **`test_ena_smoke.py`** — `@pytest.mark.network`, opt-in.
  Hits real ENA with a tiny query, verifies response shape and that
  short reads dominate for Homo sapiens.

Tests that need live ETE3 (`test_taxonomy.py`, `test_aggregations.py`)
auto-skip if `~/.etetoolkit/taxa.sqlite` isn't present. Tests that
need the internet (`test_ena_smoke.py`) are skipped by default —
opt in with `-m network`.

### Adding a test

- Use the `fixture_db` fixture in `tests/conftest.py` for anything
  database-shaped. It returns an in-memory SQLite with the real
  schema and a small hand-crafted dataset.
- If your test would catch a real reported bug, name it
  `test_<short_description>` and add a comment referencing the
  audit / changelog item.
- Tests should run in under a second unless marked `@pytest.mark.slow`.

### Manual testing checklist

Even with the suite, the Streamlit UI itself has no automated tests.
After non-trivial changes to `app.py` or `src/`:

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
