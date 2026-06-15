"""Sanity checks on the METRICS config.

Single source of truth for the four tracked resources. These tests
exist so that an unsafe edit to `src/metrics.py` (renaming a key,
swapping a side, dropping a metric) fails loudly here rather than in
production where it would silently change the DB column shape, the
bar chart, the filter dropdown, or the public TSV column ordering.
"""

import re

from src.database import _COUNT_KEYS, _COVERAGE_KEYS, _SQL_COLUMNS
from src.metrics import (
    COVERAGE_KEYS,
    METRIC_KEYS,
    METRICS,
    PERCENT_KEYS,
    TOTAL_KEYS,
)


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_exactly_four_metrics():
    """The DB schema, bar chart, summary cards, and TSV columns all
    assume four resources. Adding/removing one is a schema change."""
    assert len(METRICS) == 4


def test_metric_keys_are_the_canonical_set():
    """`ass/ann/rna/lng` are the column suffixes the SQLite schema bakes
    in (c_ass, s_ass, c_ann, ...). Drift here = schema bug."""
    assert METRIC_KEYS == ("ass", "ann", "rna", "lng")


def test_metric_keys_unique():
    assert len(set(METRIC_KEYS)) == len(METRIC_KEYS)


def test_colors_are_hex_triplets():
    for m in METRICS:
        assert _HEX_RE.match(m.color), f"{m.key} color {m.color!r} is not #rrggbb"


def test_sides_split_two_and_two():
    """The divergent bar chart needs exactly two metrics per side
    (one light + one overlay). Any other split breaks the legend."""
    by_side = {"left": 0, "right": 0}
    for m in METRICS:
        by_side[m.side] += 1
    assert by_side == {"left": 2, "right": 2}


def test_each_side_has_one_overlay_and_one_base():
    for side in ("left", "right"):
        metrics = [m for m in METRICS if m.side == side]
        overlays = [m for m in metrics if m.overlay]
        bases = [m for m in metrics if not m.overlay]
        assert len(overlays) == 1, f"{side}: expected 1 overlay, got {len(overlays)}"
        assert len(bases) == 1, f"{side}: expected 1 base, got {len(bases)}"


def test_derived_key_tuples_match_metric_order():
    assert COVERAGE_KEYS == tuple(f"c_{k}" for k in METRIC_KEYS)
    assert TOTAL_KEYS == tuple(f"s_{k}" for k in METRIC_KEYS)
    assert PERCENT_KEYS == tuple(f"p_{k}" for k in METRIC_KEYS)


def test_metric_property_helpers_agree_with_derived_tuples():
    for m, ck, tk, pk in zip(METRICS, COVERAGE_KEYS, TOTAL_KEYS, PERCENT_KEYS):
        assert m.coverage_key == ck
        assert m.total_key == tk
        assert m.percent_key == pk


def test_tsv_column_names_unique_and_snake_case():
    """The TSV column list is the public schema. Names must be unique
    and pure snake_case (downstream tools split on `\\t` and trust the
    header to be a stable identifier)."""
    names = [m.tsv_count_column for m in METRICS] + [m.tsv_total_column for m in METRICS]
    assert len(names) == len(set(names))
    for n in names:
        assert n == n.lower()
        assert re.fullmatch(r"[a-z][a-z0-9_]*", n), f"bad TSV column name: {n!r}"


def test_filter_and_sort_labels_unique():
    """The filter multiselect and sort selectbox key on labels — duplicates
    would silently merge entries."""
    assert len({m.filter_label for m in METRICS}) == len(METRICS)
    assert len({m.sort_count_label for m in METRICS}) == len(METRICS)
    assert len({m.sort_total_label for m in METRICS}) == len(METRICS)


# --------------------------------------------------------------------- #
# Summary-card UI fields (drive ui/summary.py)
# --------------------------------------------------------------------- #


def test_summary_card_required_fields_populated():
    """Every metric must carry the strings the card render fn reads."""
    for m in METRICS:
        for field in (
            "card_title", "card_color", "card_icon",
            "species_help", "total_label", "total_help",
            "external_source_name", "external_url_template",
        ):
            value = getattr(m, field)
            assert value, f"{m.key}.{field} is empty"
            assert isinstance(value, str)


def test_card_titles_unique():
    """Two cards with the same title would confuse users."""
    titles = [m.card_title for m in METRICS]
    assert len(set(titles)) == len(titles)


def test_external_url_template_substitutes_taxid():
    """Each template must accept a {taxid} placeholder and produce a
    valid-looking https URL when formatted."""
    for m in METRICS:
        url = m.external_url(42)
        assert "42" in url
        assert "{taxid}" not in url
        assert url.startswith("https://")


def test_only_lng_has_card_title_help_today():
    """If a second metric gains a title tooltip we want to know about it
    (it's currently the only field with a default, and the summary
    renderer treats `None` as 'no help')."""
    with_help = [m for m in METRICS if m.card_title_help is not None]
    assert {m.key for m in with_help} == {"lng"}


# --------------------------------------------------------------------- #
# database.py reads from METRICS — these tests guard against drift
# between the config and the SQL layer that consumes it.
# --------------------------------------------------------------------- #


def test_database_count_keys_derive_from_metrics():
    """`_COUNT_KEYS` must equal (n_rows,) + coverage + total in METRICS
    order — that's what `_row_to_metadata` unpacks."""
    assert _COUNT_KEYS == ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS


def test_database_coverage_keys_match_metrics():
    assert _COVERAGE_KEYS == COVERAGE_KEYS


def test_database_sql_columns_match_metric_order():
    """`_SQL_COLUMNS` is interpolated into SELECTs; if its order desyncs
    from `_row_to_metadata`'s unpacking we'd silently swap values."""
    expected = ", ".join(("taxid", "n_rows") + COVERAGE_KEYS + TOTAL_KEYS)
    assert _SQL_COLUMNS == expected
