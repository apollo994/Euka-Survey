"""Single source of truth for the four resource metrics tracked per clade.

The app and pipeline both reason about four genomic resources:

| key   | title            | what it means                                  |
|-------|------------------|------------------------------------------------|
| ass   | Assemblies       | whole-genome assemblies                        |
| ann   | Annotations      | functional annotations of assemblies           |
| rna   | RNA-Seq (Any)    | RNA-Seq runs, any sequencing platform          |
| lng   | Long-Read RNA    | RNA-Seq runs on Oxford Nanopore or PacBio SMRT |

Each resource produces three columns in `precomputed_clade_features`:

    c_<key>  species covered (>=1 of that resource)
    s_<key>  total resource count summed across the clade's species
    p_<key>  derived percentage (c_<key> / n_rows * 100), computed in code

This module replaces the 10+ hardcoded references to
("ass", "ann", "rna", "lng") that the refactoring audit (Phase 3 #31)
flagged across `database.py`, `visualization.py`, `app.py`, and
`utils.py`. To add or rename a metric, edit METRICS and every consumer
follows.
"""

from dataclasses import dataclass
from typing import Literal

Side = Literal["left", "right"]


@dataclass(frozen=True, slots=True)
class Metric:
    """A single tracked resource.

    The fields cover four concerns:

    - data layer: `key` drives the `c_/s_/p_` column suffixes.
    - bar chart: `color`, `side`, `overlay` define the divergent bar
      (left half = assemblies/annotations, right half = RNA-Seq runs;
      overlay=True is the darker overlaid metric in each pair).
    - UI controls: `filter_label`, `sort_count_label`, `sort_total_label`
      feed the multiselect + sort dropdown.
    - TSV export: `tsv_count_column`, `tsv_total_column` are the
      snake_case column names in the public TSV schema.
    """

    key: str
    title: str
    color: str
    side: Side
    overlay: bool
    legend_label: str
    filter_label: str
    sort_count_label: str
    sort_total_label: str
    tsv_count_column: str
    tsv_total_column: str

    @property
    def coverage_key(self) -> str:
        return f"c_{self.key}"

    @property
    def total_key(self) -> str:
        return f"s_{self.key}"

    @property
    def percent_key(self) -> str:
        return f"p_{self.key}"


METRICS: tuple[Metric, ...] = (
    Metric(
        key="ass",
        title="Assemblies",
        color="#a6cee3",  # light blue
        side="left",
        overlay=False,
        legend_label="Assembled",
        filter_label="Assemblies",
        sort_count_label="Species with Assemblies",
        sort_total_label="Assemblies",
        tsv_count_column="species_with_assemblies",
        tsv_total_column="total_assemblies",
    ),
    Metric(
        key="ann",
        title="Annotations",
        color="#1f78b4",  # dark blue
        side="left",
        overlay=True,
        legend_label="Annotated",
        filter_label="Annotations",
        sort_count_label="Species with Annotations",
        sort_total_label="Annotations",
        tsv_count_column="species_with_annotations",
        tsv_total_column="total_annotations",
    ),
    Metric(
        key="rna",
        title="RNA-Seq (Any)",
        color="#b2df8a",  # light green
        side="right",
        overlay=False,
        legend_label="RNA-Seq (Any)",
        filter_label="RNA-Seq (Any)",
        sort_count_label="Species with RNA-Seq (Any)",
        sort_total_label="RNA-Seq experiments (Any)",
        tsv_count_column="species_with_rna_seq",
        tsv_total_column="total_rna_seq",
    ),
    Metric(
        key="lng",
        title="Long-Read RNA",
        color="#33a02c",  # dark green
        side="right",
        overlay=True,
        legend_label="Long-Read RNA",
        filter_label="Long-Read RNA",
        sort_count_label="Species with Long-Read RNA",
        sort_total_label="Long-Read RNA-Seq experiments",
        tsv_count_column="species_with_long_read_rna_seq",
        tsv_total_column="total_long_read_rna_seq",
    ),
)


# Derived column tuples — most callers just want one of these.
METRIC_KEYS: tuple[str, ...] = tuple(m.key for m in METRICS)
COVERAGE_KEYS: tuple[str, ...] = tuple(m.coverage_key for m in METRICS)
TOTAL_KEYS: tuple[str, ...] = tuple(m.total_key for m in METRICS)
PERCENT_KEYS: tuple[str, ...] = tuple(m.percent_key for m in METRICS)
