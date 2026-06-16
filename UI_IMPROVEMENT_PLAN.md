# EukaSurvey — UI Improvement Plan

Living document for the UI/UX work on the Streamlit web app. The big code
**refactor is essentially done** (see `REFACTORING_AUDIT.md` — only a few Low
items remain); focus has now shifted to making the app look and feel better.

**Source of truth for UI work.** Update statuses as items land. Add new ideas
under the relevant theme. Keep it honest — mark things DONE only when actually
verified in the running app.

- Streamlit version: **1.58.0** (recent — modern theming, `st.fragment`,
  `st.navigation`, `column_config`, `st.metric(border=, chart_data=)`,
  `st.space`, `width="stretch"` all available).
- Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[⊘]` rejected/parked.

---

## 1. Current UI inventory (so future sessions don't re-read all the code)

Single scrolling page (`layout="wide"`, light theme), composed by `app.py` from
five `ui/` renderers. Shared `QueryState` flows from `render_query_config` to the
rest.

| Section | File | What it shows |
|---|---|---|
| Header | `app.py::main` | `st.title("EukaSurvey")` + blue-divider subheader + one-line tagline |
| Sidebar | `ui/sidebar.py` | "How to use EukaSurvey" expander (collapsed) + GitHub link. No controls. |
| Query Configuration | `ui/query_config.py` | Bordered container, 3 cols: **Root Taxon** selectbox (6 common clades or "Enter your own" → text input) · **Breakdown by Rank** selectbox (ranks below root) · live **"Tree size: N nodes"** `st.info` + >100 caption |
| Genomic Resource Summary | `ui/summary.py` | `st.metric` "Total Species" + 4 bordered cards (one per `Metric`): title, "Species Covered", total, "View on NCBI/Annotrieve/ENA" link |
| Tree Visualization | `ui/tree.py` | `st.form`: filter multiselect + AND/OR `segmented_control` · sort selectbox · exclude-empty toggle · max-nodes selectbox/custom · show-counts toggle · **Generate** button → spinners → nodes-included `st.info` → static ETE3 **SVG via `st.image`** → Download SVG button |
| Export Data | `ui/export.py` | One-line blurb + **Download TSV** button |

Data model: four resources (`METRICS` in `src/metrics.py`) — Assemblies (blue),
Annotations (orange card / dark-blue bar), RNA-Seq Any (green), Long-Read RNA
(dark green). Per clade: `n_rows` (species), `c_*` (species covered), `s_*`
(total counts), `percent()` (coverage %).

**Key UX facts:**
- Defaults to **Eukaryota / phylum** on load and renders the summary immediately
  (good — no blank landing state).
- The tree is a **static server-rendered SVG** (ETE3 in a spawn subprocess, Qt
  offscreen). Not zoom/pan-interactive inside the app; `st.image` shows it at
  container width. Big trees (up to `HARD_NODE_CAP=500`) get tall and slow.
- Tree settings are gated behind a **form** (no rerun until "Generate") — good.
  But the *summary* and *query config* rerun the whole page on every widget poke.
- The only in-app "data" is the SVG + the metric cards; the actual numbers per
  clade are only obtainable via **TSV download** (no in-app table).

---

## 2. Design goals

1. **Look polished and on-brand** — a coherent theme (the assemblies-blue /
   RNA-green palette already in `METRICS`), better typography, consistent spacing.
2. **Make the data explorable in-app** — not just a static picture + a download.
   A sortable table and a quick chart let users answer questions without ETE3.
3. **Reduce scroll / clarify flow** — group controls vs. results; consider
   tabs and/or a sidebar control panel.
4. **Feel responsive** — partial reruns (`st.fragment`), clear progress, toasts.
5. **Be shareable & guided** — URL-encoded queries, inline help, a landing
   experience for first-time users.
6. **Don't regress** the things that already work well (form-gated rendering,
   immediate default view, the divergent-bar tree).

---

## 3. Open decisions (need user input before some items start)

- **D1 — Control placement.** ✅ RESOLVED (2026-06-16) — settled on a two-tier
  split: **sidebar = root taxon only** (the global "which clade?"), **main =
  rank + filters + sort + limit** (results parameters, in Explore Results).
  See A2 + H5.
- **D2 — Theme direction.** Light-only polish vs. light+dark with a toggle; how
  bold a primary color. → see Theme B.
- **D3 — Static vs. interactive tree.** Keep the ETE3 SVG as the canonical
  figure (it's publication-quality and downloadable) and *add* interactive views
  around it, or invest in an interactive tree? Recommended: keep SVG, add
  table/chart around it. → see Theme E / Theme G stretch.
- **D4 — Scope of "table" view.** In-app `st.dataframe` as a complement, or as a
  replacement for the TSV-only flow? → see Theme E.

---

## 4. Themed task backlog

### ✅ Done — Quick visual pass (2026-06-16)

First session landed the low-risk visual upgrade (verified via
`streamlit.testing.v1.AppTest`: boots clean, 0 errors/warnings, 9 metrics +
4 coverage bars render):

- [x] **B1.** Brand-colored light theme in `.streamlit/config.toml` —
  `primaryColor #1f78b4`, tinted card surface, cool-black text, soft radius,
  widget/sidebar borders. All keys verified against the 1.58 build.
- [x] **B2.** Sidebar theming (`[theme.sidebar]` deeper blue tint + border).
- [x] **B3.** `chartCategoricalColors` set to the METRICS palette.
- [x] **C1.** Coverage rendered as a `st.progress` bar ("X% of species") on
  each card.
- [x] **C2.** `border=True` on the top "Total Species" metric. (The four
  resource cards intentionally keep a single `st.container(border=True)`
  rather than per-metric borders — nested borders look worse.)
- [x] **C4.** External links are now `st.link_button`s (full-width, icon).
- [x] **A4.** Hero polish — `🧬` brand mark in the title, tagline demoted to
  `st.caption` for cleaner hierarchy.

### ✅ Done — In-app data table + Tree/Table tabs (2026-06-16)

Second session. The "Explore Results" section (renamed from "Tree
Visualization") now renders both views in tabs from the *same*
filtered/sorted/limited `phylum_metadata`. Verified via AppTest: form submit
→ no exceptions, 2 tabs, 1 dataframe, 3 download buttons (SVG / table TSV /
full TSV), 0 errors/warnings.

- [x] **E1.** Interactive `st.dataframe` table — Taxon, TaxID, Species, four
  `ProgressColumn` coverage bars (on-brand), four formatted total columns
  (`localized`). Client-side column sorting/search for free; no rerun needed.
  Total-column labels use `{card_title} (total)` to avoid the "Total Runs"
  collision between the two RNA metrics.
- [x] **E3.** "Download table (TSV)" of exactly the displayed rows (respects
  current filters/sort/limit), distinct from the full Export Data TSV.
- [x] **A1 (partial).** Results split into `st.tabs(["🌳 Tree", "📊 Table"])`.
  Tree render no longer `st.stop()`s on failure, so the Table tab still shows.
  *Remaining:* fold Overview (summary) and Export into the tab set if we want
  a fully tabbed page (revisit after A2 control-placement decision).

### Theme A — Information architecture & layout
- [~] **A1. Tabs for results.** Tree + Table tabs landed (see Done section).
  Could still fold Summary / Export into a fuller `st.tabs(["Overview", "Tree",
  "Table", "Export"])` to cut scroll further. (Revisit after A2.)
- [x] **A2. Controls in the sidebar (D1).** DONE (2026-06-16), then refined by
  H5: the sidebar holds **only the root taxon** (the one global control, made
  prominent). The breakdown rank + size readback moved into Explore Results
  (it's a results parameter), and the filter/sort/limit form stays there too.
  Net: sidebar = "which clade?", main = everything that flows from it.
- [x] **A3. Lineage breadcrumb.** DONE (2026-06-16) —
  `taxonomy.get_lineage_breadcrumb` (lru_cached, canonical ranks
  domain..species), e.g. *Eukaryota › Metazoa › Chordata › **Mammalia***.
  Relocated (see H7) from the top of the summary into the **sidebar, directly
  under the root picker** — it describes the selected root, so it lives where
  you pick it. Rendered as a compact `st.caption`.
- [ ] **A4. Tighten the hero.** Logo/`🧬` lockup, smaller tagline, consistent
  `st.space` rhythm; consider `st.container(border=...)` framing per section so
  the page reads as cards. (Low.)
- [ ] **A5. Landing / empty state.** When no valid root, show a short "what this
  is + pick a clade" panel instead of just an error. (Low.)

### Theme B — Theme & visual language
- [ ] **B1. Custom `[theme]` in `.streamlit/config.toml`.** Set `primaryColor`
  (assemblies blue `#1f78b4` or a brand teal), `backgroundColor`,
  `secondaryBackgroundColor`, `textColor`, `font`/`headingFont`, `baseRadius`,
  `borderColor`. Currently only `base="light"`. Biggest visual ROI for the effort.
  (Low.) Verify keys against current docs — 1.58 supports `headingFont`,
  `codeFont`, `baseRadius`, `borderColor`, `showWidgetBorder`, `baseFontSize`.
- [ ] **B2. Sidebar theming.** `[theme.sidebar]` to give the control panel a
  distinct, slightly tinted surface. (Low; pairs with A2.)
- [ ] **B3. Chart palette alignment.** Set `chartCategoricalColors` /
  `chartSequentialColors` to the METRICS palette so any st-native charts match
  the tree bars and cards. (Low; pairs with E2.)
- [ ] **B4. Dark mode (D2).** Decide whether to offer light+dark. Streamlit
  respects OS theme if both are defined; a manual toggle needs care. (Low–Med.)
- [ ] **B5. Custom font** via `[[theme.fontFaces]]` if a brand font is wanted
  (e.g. a clean grotesk for headings). (Low; optional.)

### Theme C — Summary cards & metrics polish
- [ ] **C1. Coverage as a visual.** Each card shows coverage % — render it as a
  small progress bar (`st.progress`) or as a `st.metric` `delta`, not just a raw
  number. Makes "70% of species assembled" legible at a glance. (Low.)
- [ ] **C2. `st.metric(border=True)`** on the cards / top metric for consistent
  framing instead of manual `st.container(border=True)` + markdown title. (Low.)
- [ ] **C3. Sparklines.** `st.metric(chart_data=..., chart_type="bar")` could
  show the top sub-clades' contribution inline. (Med; verify API in 1.58.)
- [ ] **C4. Make external links buttons.** `st.link_button` with the source icon
  instead of inline markdown links — bigger tap target, clearer affordance. (Low.)
- [ ] **C5. Totals readability.** Thousands separators are already there; add the
  resource icon + a one-line "what this counts" caption under each card. (Low.)
  (Partly addressed: the progress bar now carries a "% of species" label.)

### Theme D — Tree visualization UX
- [ ] **D1. `st.status` for rendering.** Replace the two sequential spinners with
  one `st.status("Building tree…")` that updates through aggregate → filter →
  render and collapses on success, showing elapsed time. (Low.) *Note: the
  aggregate spinner and the render spinner now sit on opposite sides of the
  tab boundary — a single status box across that boundary is awkward; revisit
  if/when render moves out of the tab.*
- [x] **D2. `st.toast` on completion.** DONE (2026-06-16) — "Tree & table
  ready ✅" fires once per Generate.
- [ ] **D3. Scrollable tree container + height control.** Tall trees overflow;
  wrap the `st.image` in a fixed-height scroll container and/or expose a
  "compact / comfortable" density toggle. (Med.)
- [ ] **D4. Zoom affordance.** SVG in `st.image` isn't zoomable; offer a
  full-width `st.dialog` ("Open large view") or note the SVG download for zoom.
  (Med.)
- [ ] **D5. Filter UX.** Use `st.pills` for the feature filters (more compact
  than multiselect); show an active-filter summary chip row. (Low.)
- [ ] **D6. Persist last render across reruns.** Currently a non-form widget
  change wipes the rendered tree. Cache the last SVG in session_state and keep it
  visible until re-generated. (Med; pairs with F1 fragment.)
- [ ] **D7. Tree download formats.** Offer PNG/PDF in addition to SVG (ETE3 can
  render PNG/PDF directly). (Med.)

### Theme E — In-app data table & charts (new views)
- [x] **E1. Interactive results table.** DONE (2026-06-16) — see Done section.
  `LinkColumn` for per-row external links not yet added (follow-up).
- [ ] **E2. Coverage bar chart.** An Altair/`st.bar_chart` of top-N clades'
  coverage % per resource — an interactive complement to the static tree, good
  for screenshots/talks. (Med.) **Next candidate.**
- [x] **E3. Table download.** DONE (2026-06-16) — "Download table (TSV)".
- [ ] **E4. Per-row drill-down.** Selecting a table row could set it as the new
  root (re-query one level deeper) — turns the table into a navigator. (Med–High.)

### Theme F — Interaction performance
- [ ] **F1. `@st.fragment` for the tree section.** Isolate the form + render so
  changing tree knobs / re-generating doesn't rerun the summary + query blocks.
  (Med.) Pairs with D6.
- [ ] **F2. `@st.fragment` for the table** likewise (sort/filter without full
  rerun). (Med; depends on E1.)
- [ ] **F3. Audit cache keys.** `generate_tree_svg_cached` hashes a dict-of-dicts;
  confirm it's still keyed efficiently after CladeMetadata change. (Low; verify.)

### Theme G — Shareability, guidance, stretch
- [ ] **G1. URL query params.** Encode `root_taxid` + `rank` (+ filters) in
  `st.query_params` so a configured view is a shareable link / bookmarkable, and
  restore from them on load. (Med.) **High value for a research tool.**
- [ ] **G2. Inline help & first-run tour.** Promote key bits of the sidebar
  "How to use" into inline `help=` / a dismissible `st.info` banner. (Low.)
- [ ] **G3. Multipage via `st.navigation`.** Split into Explorer / About&Methods
  / Data Sources pages once content grows. (Med.)
- [ ] **G4. Compare mode.** Two roots side-by-side (e.g. Fungi vs. Plants
  coverage). (High; stretch.)
- [ ] **G5. Interactive tree (D3).** Replace/augment the ETE3 SVG with an
  interactive phylo component. Large effort; only if the static SVG proves
  limiting. (High; stretch / likely parked.)
- [ ] **G6. Accessibility & meta.** Alt text on the tree image, color-contrast
  check on the palette, `st.set_page_config` description, social/OG preview. (Low–Med.)

### Theme H — CTA, terminology & safety (user feedback 2026-06-16)

Now that the Table is a first-class view (not a "secondary feature"), the
results section's framing needs to catch up, and the limits need to be safer.

- [x] **H1. Co-equal Tree/Table framing.** DONE (2026-06-16) — CTA renamed
  "Generate Tree & Table" with a neutral `:material/analytics:` icon; the table
  TSV download is now `type="primary"` to match the SVG download.
- [x] **H2. Lower the node cap to avoid OOM.** DONE (2026-06-16) —
  `HARD_NODE_CAP 500 → 200`, breakpoints trimmed to `…200`, help reworded to
  "Capped at 200 taxa to stay within memory limits."
- [x] **H3. Terminology pass.** DONE (2026-06-16) — "nodes" → "taxa"
  everywhere user-facing: size readback ("N {rank}-level taxa in this
  selection"), form ("Filter taxa", "Sort & limit", "Rank taxa by number of",
  "Max taxa to display"), and the included message ("Showing X of Y taxa, Z
  hidden by your filters"). Tree-only control kept tree-scoped but clarified
  ("Show numeric details on the tree … does not affect the table").
- [x] **H4. Make the root control prominent (sidebar).** DONE (2026-06-16) —
  sidebar leads with a `##` "→ Start here" heading + a plain-language
  instruction (reworded — see H7), with the root taxon as the single global
  control. Font bump: "Root taxon" is an `###` heading-label (native label
  collapsed) and a scoped, best-effort CSS rule lifts the sidebar selectbox +
  text-input font to 1.05rem (targets the stable `stSidebar` testid; no-ops if
  Streamlit internals change).
- [x] **H5. Move "Break down by rank" into Explore Results.** DONE
  (2026-06-16) — the summary cards depend only on the root, so the rank is a
  *results parameter*, not a global selector. New `RootChoice` state (sidebar,
  root-only) + `render_results(conn, root) -> QueryState` which owns the rank
  selector + size readback (reactive, outside the form) and returns the full
  `QueryState` for export gating. `render_summary` now takes `RootChoice`.
- [x] **H6. Interface guidance.** DONE (2026-06-16) — Explore Results opens
  with a caption explaining the rank → filter → tree/table flow; the sidebar
  instruction tells the user the page reflects the clade they pick. (More
  guidance possible: per-section tooltips, a first-run banner — see G2.)
- [x] **H7. Refinement pass (post-review).** DONE (2026-06-16) — (a) breadcrumb
  moved into the sidebar under the root picker (see A3); (b) reworded the Step-1
  line from the techy "Everything on the page updates from this" to "Choose a
  clade to explore. You'll see the genomic data available across every species
  it contains."; (c) sidebar font bump (see H4).
- [x] **H8. Explore Results layout polish.** DONE (2026-06-16) — killed the
  dead space above the rank selector (it came from `vertical_alignment="center"`
  centering the selectbox against a chunky `st.info` box → now `"bottom"`), and
  replaced the big blue `st.info` size callout with a subtle gray inline
  readback (":material/category: **N** {rank}-level taxa · larger selections
  take longer to render").

---

## 5. Suggested sequencing

A pragmatic order that front-loads visible wins and unblocks later work:

1. **Quick visual pass (Theme B + C + A4):** B1 theme → C2/C1 card polish →
   A4 hero. One session, big perceived improvement, no architecture risk.
2. **Explorability (Theme E):** E1 table → E2 chart → E3 download. The biggest
   functional upgrade.
3. **Layout (Theme A):** A1 tabs (now that there's a Table to tab to) → A3
   breadcrumb → decide A2 (sidebar controls, D1).
4. **Polish & perf (Theme D + F):** D1/D2 status+toast → F1 fragment + D6
   persist render → D3 scroll container.
5. **Shareability (Theme G):** G1 query params → G2 help.
6. **Stretch:** G3 multipage, G4 compare, G5 interactive tree.

---

## 6. Notes / constraints to remember

- **Don't break the form-gated render** — it's what keeps the expensive ETE3
  subprocess from firing on every keystroke.
- **Theme keys change between Streamlit versions** — verify against the 1.58 docs
  before committing `config.toml` keys; a bad key is silently ignored.
- **The tree SVG path** (`st.image` of a temp `.svg`) is load-bearing: PIL can't
  read raw SVG bytes, hence the temp-file dance. Don't "simplify" it to
  `st.image(svg_bytes)`.
- **Streamlit Cloud apt trap** (`packages.txt`, trixie `t64` suffixes) is
  unrelated to UI but is the deploy gotcha — see CLAUDE.md if a deploy breaks.
- Keep `ui/` modules single-responsibility (`render_*`), cross-section state via
  `QueryState` only — preserve the clean split the refactor produced.

---

## 7. Changelog (append as items land)

- 2026-06-16 — Document created. Captured current UI inventory + backlog.
- 2026-06-16 — Quick visual pass landed: B1/B2/B3 (brand-colored light theme +
  sidebar + chart palette), C1/C2/C4 (coverage progress bars, top-metric
  border, link buttons), A4 (hero). User chose "light, brand-colored". Verified
  with AppTest (clean boot). Files: `.streamlit/config.toml`, `ui/summary.py`,
  `app.py`.
- 2026-06-16 — In-app table + tabs: E1 (st.dataframe with coverage
  ProgressColumns), E3 (displayed-rows TSV download), A1 partial (Tree/Table
  tabs; section renamed "Explore Results"). Verified with AppTest (submit →
  2 tabs, dataframe, 3 download buttons, 0 errors). Files: `ui/tree.py`,
  `ui/sidebar.py`.
- 2026-06-16 — Orientation + feedback: A3 (lineage breadcrumb via
  `taxonomy.get_lineage_breadcrumb`), D2 (completion toast). Verified with
  AppTest (Mammalia breadcrumb renders; clean run). Files: `src/taxonomy.py`,
  `ui/summary.py`, `ui/tree.py`.
- 2026-06-16 — User-feedback batch H: H1 (CTA "Generate Tree & Table" +
  co-equal primary table download), H2 (HARD_NODE_CAP 500→200 to avoid OOM),
  H3 (terminology "nodes"→"taxa", de-tree-centric labels). Verified with
  AppTest (submit clean; new wording confirmed). Files: `src/constants.py`,
  `ui/tree.py`, `ui/query_config.py`.
- 2026-06-16 — A2: moved root/rank query controls into a sidebar "Query" panel
  (vertical), help below a divider; main area leads with results. D1 resolved.
  Verified with AppTest (controls in sidebar, summary + submit flow intact).
  Files: `ui/query_config.py`, `ui/sidebar.py`, `app.py`.
- 2026-06-16 — Feedback batch H4–H6 (IA rework): sidebar now holds ONLY the
  root taxon, made prominent ("Start here / Step 1"); breakdown rank + size
  readback moved into Explore Results; added flow-guidance captions. New
  `RootChoice` state; `render_root_control` (sidebar) + `render_results(conn,
  root)->QueryState` (owns rank); `render_summary` takes `RootChoice`. Verified
  with AppTest incl. species-level + invalid-taxid edge cases. Files:
  `ui/state.py`, `ui/query_config.py`, `ui/summary.py`, `ui/tree.py`, `app.py`.
- 2026-06-16 — Refinement pass H7–H8 (post-review): breadcrumb → sidebar under
  the root picker; reworded Step-1; sidebar font bump (heading-labels + scoped
  CSS); Explore Results dead space removed + subtle inline size readback
  (replacing the loud `st.info`). Verified with AppTest (sidebar breadcrumb for
  Eukaryota + Mammalia; no main breadcrumb; subtle readback; clean run).
