# EukaSurvey

**A genomic resource explorer for the eukaryotic tree of life.**

EukaSurvey is a Streamlit web app that lets you see, at a glance, which
clades of eukaryotes have what kinds of genomic data publicly available:
genome assemblies (NCBI), functional annotations (Annotrieve), and RNA-seq
runs (ENA), split into short-read and long-read.

The data is precomputed monthly into a SQLite database
(`eukaryotes.db`, ~300 MB) that the app downloads on first launch.

**Try it now:** <https://euka-survey-62bi4d34cytdpb56zmhms2.streamlit.app/>

---

## Who it's for

- **Comparative genomicists** evaluating data coverage across a clade
  before designing a study.
- **Bioinformaticians** identifying data gaps (e.g. "which mammalian
  families have an assembly but no annotation?").
- **Evolutionary biologists** building reading lists or grant proposals
  around well- or under-sampled lineages.

## What you can do with it

1. Pick a **root taxon** (a built-in clade like Mammalia, or any NCBI
   Taxon ID).
2. Pick a **breakdown rank** (phylum / class / order / family / genus /
   species — restricted to ranks below the root's own rank).
3. See an instant summary of how many species in that clade have
   assemblies / annotations / RNA-seq / long-read RNA-seq.
4. **Filter** the breakdown (e.g. "must have an assembly AND long-read
   RNA-Seq"), **sort** by any metric, and **limit** to the top N.
5. Generate a **phylogenetic tree visualization** with per-leaf
   divergent bar charts, downloadable as SVG.
6. **Export TSV** of the full breakdown for downstream analysis.

---

## Quick start (local)

```bash
git clone https://github.com/Cobos-Bioinfo/Euka-Survey.git
cd Euka-Survey

# uv handles Python + deps. Install once: https://docs.astral.sh/uv/
uv sync                       # creates .venv and installs the app deps
uv run streamlit run app.py
```

The app will open in your browser. On first launch it downloads
`eukaryotes.db` (~300 MB) from the latest GitHub Release. Subsequent
launches use the cached copy.

`uv` reads `pyproject.toml` + `uv.lock` for a reproducible environment.
The dev tools (pytest) are pulled in automatically; pipeline-only deps
are opt-in via `uv sync --extra pipeline`.

## Cloud deployment

The repo is configured for one-click Streamlit Community Cloud
deployment. Streamlit Cloud detects `uv.lock` (highest priority among
supported dependency formats) and installs the Python deps via uv;
`packages.txt` declares the minimal Qt5 system libraries needed for
headless tree rendering.

---

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the code is laid
  out, the SQLite schema, why tree rendering needs a subprocess.
- [docs/PIPELINE.md](docs/PIPELINE.md) — the offline `db_builder`
  pipeline that produces `eukaryotes.db`. Read this if you want to
  rebuild the DB or contribute to data sourcing.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — dev environment,
  conventions, in-flight refactor work.

If you're auditing or planning improvements:

- [REFACTORING_AUDIT.md](REFACTORING_AUDIT.md) — full architectural
  audit + technical-debt ranking + roadmap.
- [REFACTORING_CHANGELOG.md](REFACTORING_CHANGELOG.md) — per-item log
  of refactor work done, with rationale.

---

## License

See [LICENSE](LICENSE).

## Contributing

Issues and pull requests welcome. For larger changes please open an
issue first — see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the
conventions emerging from the in-flight refactor.
