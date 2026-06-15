"""Single source of truth for the four resource metrics tracked per clade.

The app and pipeline both reason about four genomic resources:

| key   | card_title       | what it means                                  |
|-------|------------------|------------------------------------------------|
| ass   | Assemblies       | whole-genome assemblies                        |
| ann   | Annotations      | functional annotations of assemblies           |
| rna   | RNA-Seq (Any)    | RNA-Seq runs, any sequencing platform          |
| lng   | Long-Read RNA-Seq| RNA-Seq runs on Oxford Nanopore or PacBio SMRT |

Each resource produces three columns in `precomputed_clade_features`:

    c_<key>  species covered (>=1 of that resource)
    s_<key>  total resource count summed across the clade's species
    p_<key>  derived percentage (c_<key> / n_rows * 100), computed in code

This module replaces every hardcoded reference to ("ass", "ann", "rna",
"lng") that the refactoring audit (Phase 3 #31, arch improvement F)
flagged across `database.py`, `visualization.py`, `app.py` /
`ui/`, and `utils.py`. To add or rename a metric, edit METRICS and
every consumer follows.
"""

from dataclasses import dataclass
from typing import Literal

Side = Literal["left", "right"]


@dataclass(frozen=True, slots=True)
class Metric:
    """A single tracked resource.

    The fields cover five concerns:

    - data layer: `key` drives the `c_/s_/p_` column suffixes.
    - bar chart: `color`, `side`, `overlay`, `legend_label` define the
      divergent bar (left half = assemblies/annotations, right half =
      RNA-Seq runs; overlay=True is the darker overlaid metric in each
      pair).
    - filter / sort controls: `filter_label`, `sort_count_label`,
      `sort_total_label` feed the multiselect + sort dropdown.
    - summary card: `card_title`, `card_color` (Streamlit named color
      shorthand), `card_icon` (material icon name), `card_title_help`
      (optional tooltip on the title), `species_help`, `total_label`
      + `total_help`, `external_source_name`, `external_url_template`
      drive the four cards in `ui/summary.py`.
    - TSV export: `tsv_count_column`, `tsv_total_column` are the
      snake_case column names in the public TSV schema.
    """

    key: str
    color: str
    side: Side
    overlay: bool
    legend_label: str
    filter_label: str
    sort_count_label: str
    sort_total_label: str
    card_title: str
    card_color: str
    card_icon: str
    species_help: str
    total_label: str
    total_help: str
    external_source_name: str
    external_url_template: str
    tsv_count_column: str
    tsv_total_column: str
    # Optional — only `lng` carries a tooltip on the card title today.
    card_title_help: str | None = None

    @property
    def coverage_key(self) -> str:
        return f"c_{self.key}"

    @property
    def total_key(self) -> str:
        return f"s_{self.key}"

    @property
    def percent_key(self) -> str:
        return f"p_{self.key}"

    def external_url(self, taxid: int) -> str:
        """Return the per-taxon external link rendered in the card."""
        return self.external_url_template.format(taxid=taxid)


METRICS: tuple[Metric, ...] = (
    Metric(
        key="ass",
        color="#a6cee3",  # light blue
        side="left",
        overlay=False,
        legend_label="Assembled",
        filter_label="Assemblies",
        sort_count_label="Species with Assemblies",
        sort_total_label="Assemblies",
        card_title="Assemblies",
        card_color="blue",
        card_icon="database",
        species_help="Unique species with at least one genome assembly",
        total_label="Total Assemblies",
        total_help="Total number of genome assemblies across all species",
        external_source_name="NCBI",
        external_url_template="https://www.ncbi.nlm.nih.gov/datasets/genome/?taxon={taxid}",
        tsv_count_column="species_with_assemblies",
        tsv_total_column="total_assemblies",
    ),
    Metric(
        key="ann",
        color="#1f78b4",  # dark blue
        side="left",
        overlay=True,
        legend_label="Annotated",
        filter_label="Annotations",
        sort_count_label="Species with Annotations",
        sort_total_label="Annotations",
        card_title="Annotations",
        card_color="orange",
        card_icon="description",
        species_help="Unique species with at least one functional annotation",
        total_label="Total Annotations",
        total_help="Total number of annotated genomes across all species",
        external_source_name="Annotrieve",
        external_url_template="https://genome.crg.es/annotrieve/annotations/details/?taxon={taxid}",
        tsv_count_column="species_with_annotations",
        tsv_total_column="total_annotations",
    ),
    Metric(
        key="rna",
        color="#b2df8a",  # light green
        side="right",
        overlay=False,
        legend_label="RNA-Seq (Any)",
        filter_label="RNA-Seq (Any)",
        sort_count_label="Species with RNA-Seq (Any)",
        sort_total_label="RNA-Seq experiments (Any)",
        card_title="RNA-Seq (Any)",
        card_color="green",
        card_icon="segment",
        species_help="Unique species with any RNA-Seq read data",
        total_label="Total Runs",
        total_help="Total number of RNA-Seq runs across all species",
        external_source_name="ENA",
        external_url_template=(
            "https://www.ebi.ac.uk/ena/browser/advanced-search?"
            "result=read_run&query=tax_tree({taxid})%20AND%20"
            "library_strategy%3D%22rna-seq%22&"
            "fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy&limit=0"
        ),
        tsv_count_column="species_with_rna_seq",
        tsv_total_column="total_rna_seq",
    ),
    Metric(
        key="lng",
        color="#33a02c",  # dark green
        side="right",
        overlay=True,
        legend_label="Long-Read RNA",
        filter_label="Long-Read RNA",
        sort_count_label="Species with Long-Read RNA",
        sort_total_label="Long-Read RNA-Seq experiments",
        card_title="Long-Read RNA-Seq",
        card_color="green",
        card_icon="reorder",
        card_title_help="RNA-Seq experiments performed with Oxford Nanopore or PacBio SMRT platforms",
        species_help="Unique species with at least one long-read RNA-Seq experiment",
        total_label="Total Runs",
        total_help="Total number of Long-Read RNA-Seq runs across all species",
        external_source_name="ENA",
        external_url_template=(
            "https://www.ebi.ac.uk/ena/browser/advanced-search?"
            "result=read_run&query=tax_tree({taxid})%20AND%20"
            "library_strategy%3D%22rna-seq%22%20AND%20"
            "(instrument_platform%3D%22OXFORD_NANOPORE%22%20OR%20"
            "instrument_platform%3D%22PACBIO_SMRT%22)&"
            "fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy%2Cinstrument_platform&limit=0"
        ),
        tsv_count_column="species_with_long_read_rna_seq",
        tsv_total_column="total_long_read_rna_seq",
    ),
)


# Derived column tuples — most callers just want one of these.
METRIC_KEYS: tuple[str, ...] = tuple(m.key for m in METRICS)
COVERAGE_KEYS: tuple[str, ...] = tuple(m.coverage_key for m in METRICS)
TOTAL_KEYS: tuple[str, ...] = tuple(m.total_key for m in METRICS)
PERCENT_KEYS: tuple[str, ...] = tuple(m.percent_key for m in METRICS)
