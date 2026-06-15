# Architecture

EukaSurvey has two halves that don't talk to each other at runtime:

1. **The web app** (`app.py` + `src/`) — reads a prebuilt, read-only
   `eukaryotes.db`. This is what users hit.
2. **The offline pipeline** (`db_builder/`) — fetches data from NCBI,
   Annotrieve, and ENA, and produces `eukaryotes.db`. Run manually or
   by the monthly GitHub Action. See [PIPELINE.md](PIPELINE.md).

This document covers the web-app half. For the pipeline, see
[PIPELINE.md](PIPELINE.md).

---

## Repository layout

```
.
├── app.py                  # Streamlit entry point (UI + orchestration)
├── src/                    # Web-app domain logic
│   ├── constants.py        #   Shared constants (taxids, ranks, limits)
│   ├── database.py         #   SQL layer over the precomputed tables
│   ├── taxonomy.py         #   Live ETE3 fallback for non-precomputed roots
│   ├── ete_utils.py        #   taxid → name/rank helpers, descendant CTE
│   ├── visualization.py    #   ETE3 tree rendering + bar-chart panel
│   └── utils.py            #   DB download + TSV export
├── db_builder/             # Offline pipeline (see docs/PIPELINE.md)
├── .streamlit/             # Streamlit theme config
├── environment.yml         # Conda env (numpy<2, ete3, PyQt5, streamlit, …)
├── packages.txt            # apt packages for Streamlit Cloud (xvfb, etc.)
└── eukaryotes.db           # The data — NOT in git, downloaded on first run
```

---

## Database schema

`eukaryotes.db` is a single SQLite file with three tables.

### `taxid_features`

Raw per-species counts (one row per species-rank taxid).

| column             | type    | notes                                  |
|--------------------|---------|----------------------------------------|
| `taxid`            | INTEGER | PK                                     |
| `short_read_count` | INTEGER | RNA-Seq runs on Illumina/etc.          |
| `long_read_count`  | INTEGER | RNA-Seq runs on ONT / PacBio SMRT      |
| `assembly_count`   | INTEGER | Genome assemblies                      |
| `annotation_count` | INTEGER | Functional annotations                 |

The web app does not query this table directly — it reads the
precomputed aggregations below.

### `precomputed_clade_features`

One row per taxid **at any rank** (not just species). Rolled up across
the entire subtree under each taxid.

| column   | type    | notes                                                       |
|----------|---------|-------------------------------------------------------------|
| `taxid`  | INTEGER | PK                                                          |
| `n_rows` | INTEGER | Species *count* in this subtree                             |
| `c_ass`  | INTEGER | Species *covered* — i.e. with ≥1 assembly                   |
| `c_ann`  | INTEGER | Species with ≥1 annotation                                  |
| `c_rna`  | INTEGER | Species with ≥1 RNA-Seq run (any kind)                      |
| `c_lng`  | INTEGER | Species with ≥1 long-read RNA-Seq run                       |
| `s_ass`  | INTEGER | Total assembly *count* across the subtree                   |
| `s_ann`  | INTEGER | Total annotations across the subtree                        |
| `s_rna`  | INTEGER | Total RNA-Seq runs (any kind) across the subtree            |
| `s_lng`  | INTEGER | Total long-read RNA-Seq runs across the subtree             |

The convention `c_*` = "covered species" / `s_*` = "summed runs" / `p_*`
= "percentage" runs through the codebase (the percentage is computed in
Python — it isn't stored).

### `precomputed_taxa`

Caches `(root_taxid, target_rank) → list of (taxid, name)` for the six
**common root clades** × six allowed ranks. Lets the UI skip live ETE3
traversal for the common cases.

| column        | type    |
|---------------|---------|
| `root_taxid`  | INTEGER |
| `target_rank` | TEXT    |
| `taxid`       | INTEGER |
| `name`        | TEXT    |

A covering index on `(root_taxid, target_rank, taxid, name)` lets the
hot read be served from the index alone.

**Common roots** baked in: Eukaryota (2759), Animals (33208), Mammalia
(40674), Primates (9443), Fungi (4751), Plants (33090) — see
`src/constants.py::COMMON_CLADES`. **Allowed ranks**: phylum, class,
order, family, genus, species.

For any other root/rank combination, the app falls back to a live ETE3
descendant traversal via `src.taxonomy.get_taxa_at_rank`.

---

## Query flow

```
User picks root_taxid + target_rank
        │
        ▼
get_taxa_count_cached(conn, root_taxid, target_rank)
        │                                       (precomputed_taxa hit?)
        ├── yes → is_precomputed = True
        │
        └── no  → fetch_taxa_cached  ── live ETE3 traversal
                                          (taxonomy.get_taxa_at_rank)
        ▼
User clicks "Generate Visualization"
        │
        ├── if precomputed:
        │     database.get_filtered_taxa_metadata (SQL JOIN + WHERE + ORDER + LIMIT)
        │
        └── else:
              database.build_phylum_metadata (bulk fetch)
              + Python-side filter/sort/limit  ⚠ duplicates the SQL path —
                                                see REFACTORING_AUDIT.md C1
        ▼
visualization.render_tree_in_process (in a SPAWNED subprocess, see below)
        │
        ▼
SVG written to a tempfile → read back → shown via st.image + downloadable
```

For TSV export, the flow is simpler:

```
utils.generate_tsv → database.build_phylum_metadata → csv.writer → TSV
```

TSV export does **not** apply filter/sort/limit — it always exports the
full breakdown.

---

## Streamlit caching

| Function                              | Decorator                    | Keyed on                                                                |
|---------------------------------------|------------------------------|-------------------------------------------------------------------------|
| `get_db_ready`                        | `@st.cache_resource`         | (one-time)                                                              |
| `get_db_connection`                   | `@st.cache_resource`         | (one-time read-only conn)                                               |
| `get_taxa_count_cached`               | `@st.cache_data`             | `root_taxid, target_rank`                                               |
| `fetch_taxa_cached`                   | `@st.cache_data`             | `root_taxid, target_rank`                                               |
| `get_phylum_metadata_cached`          | `@st.cache_data`             | `tuple(taxids), exclude_empty`                                          |
| `get_filtered_taxa_metadata_cached`   | `@st.cache_data`             | `root_taxid, target_rank, exclude_empty, filter keys, logic, sort, top` |
| `generate_tree_svg_cached`            | `@st.cache_data`             | `phylum_metadata, include_counts`                                       |
| `utils.generate_tsv`                  | `@st.cache_data`             | `root_taxid, target_rank, fetch_func`                                   |

Taxid lists passed to cached functions are passed as **tuples**, since
Streamlit's data cache requires hashable args.

---

## Why tree rendering happens in a subprocess

ETE3 calls into PyQt5 to render trees. PyQt5 requires its `QApplication`
to be created on a process's *main thread*. Streamlit, however, runs
user callbacks on worker threads. The workaround in
`app.py::generate_tree_svg_cached`:

1. `multiprocessing.get_context('spawn').Process(...)` launches a fresh
   process (the main thread of that process becomes Qt's main thread).
2. The child runs `visualization.render_tree_in_process` which:
   - Starts a `pyvirtualdisplay.Display` (uses `xvfb` from `packages.txt`
     on Streamlit Cloud).
   - Builds the ETE3 topology and writes the rendered SVG to the path
     handed in.
3. The parent waits with a **timeout** (`p.join(timeout=120)`). On
   timeout the child is `terminate()`d → `kill()`d.
4. The SVG bytes are read back from the file, the file is removed in a
   `try/finally`.

A second tempfile is needed for display because `st.image` chokes on
raw SVG bytes (PIL doesn't recognize the format), so we write the bytes
back to disk and pass `st.image` the path. The whole thing is wrapped
in `try/finally` to clean up.

---

## ETE3 NCBITaxa: the thread-affinity caveat

`NCBITaxa` opens a SQLite connection to the local NCBI taxonomy
database. SQLite connections are *not* safe to share across threads by
default. Streamlit runs callbacks on worker threads, so the codebase
currently instantiates a fresh `NCBITaxa()` per use rather than holding
a module-level singleton.

For pure taxid → name / rank lookups, `src/ete_utils.py` uses
`@functools.lru_cache` so each unique taxid resolves at most once per
process even though `NCBITaxa()` itself is re-instantiated on cache
miss. A proper thread-local singleton is tracked in
[REFACTORING_AUDIT.md](../REFACTORING_AUDIT.md) (Phase 2 #18).

---

## Known design issues

These are documented in detail in
[REFACTORING_AUDIT.md](../REFACTORING_AUDIT.md) — listed here so the
reader has the lay of the land before opening a PR:

- **No tests.** Audit item **H7**.
- **`NCBITaxa` instantiated per call** — `lru_cache` mitigates the
  hot-path repetition but a real thread-local singleton (Phase 2 #18)
  is still pending; blocked on the Streamlit worker-thread / SQLite
  thread-affinity interaction.
- **`app.py` is still a single ~500-line file.** A `ui/`-based split
  is in the Phase 3 roadmap.
