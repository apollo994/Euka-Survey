"""Shared state passed between UI sections.

`render_query_config` is the producer; the rest of the UI consumes a
`QueryState`. The dataclass replaces the implicit, easy-to-drift
state-coupling block that used to live in the middle of `app.py::main`,
where `query_taxids` was populated in one `if` arm and read from a
different one ~250 lines later.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class QueryState:
    """Result of `render_query_config`.

    - `root_taxid` / `target_rank` / `root_name` / `root_rank`: the
      user's chosen root and rank, plus the resolved display strings.
      `root_taxid` is `None` when the user hasn't entered a valid one
      yet; `root_name` is `"Unknown"` when the taxid doesn't resolve.
    - `num_nodes`: how many `target_rank` nodes live below the root.
    - `is_precomputed`: did the (root, rank) pair hit `precomputed_taxa`?
      `True` means the tree section can take the SQL pushdown path;
      `False` means the Python fallback path needs `query_taxids`.
    - `query_taxids`: the resolved taxid list — populated *only* when
      `is_precomputed` is False (the precomputed path doesn't need it).
    """

    root_taxid: int | None
    target_rank: str | None
    root_name: str
    root_rank: str
    num_nodes: int
    is_precomputed: bool
    query_taxids: list[int] = field(default_factory=list)

    @property
    def is_valid_root(self) -> bool:
        """Root taxon is real and resolvable. Gate for the summary
        section, which works even when there are zero target-rank
        nodes (it shows totals over the whole root)."""
        return self.root_taxid is not None and self.root_name != "Unknown"

    @property
    def has_results(self) -> bool:
        """Valid root with at least one matching node. Gate for the
        tree + export sections."""
        return self.is_valid_root and self.num_nodes > 0
