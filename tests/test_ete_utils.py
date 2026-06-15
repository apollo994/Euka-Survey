"""Tests for `src.ete_utils.get_ncbi` thread-local accessor.

Closes audit Top 10 #2 / Roadmap #18 / H4. The accessor lets us drop
the 5+ `NCBITaxa()` instantiations that used to fire per Streamlit
rerun (each opening a fresh ETE3 SQLite handle) down to one per worker
thread for the process lifetime — without crossing thread boundaries
on the underlying sqlite3 connection.
"""

import os
import threading

import pytest


def _ete3_db_available() -> bool:
    try:
        from ete3 import NCBITaxa
        return os.path.exists(NCBITaxa().dbfile)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ete3_db_available(),
    reason="ETE3 taxonomy DB not available (~/.etetoolkit/taxa.sqlite)",
)


def test_get_ncbi_returns_same_instance_on_same_thread():
    """The whole point of the accessor — repeated calls on one thread
    hand back the cached instance, not a fresh `NCBITaxa()`."""
    from src.ete_utils import get_ncbi
    a = get_ncbi()
    b = get_ncbi()
    assert a is b


def test_get_ncbi_returns_distinct_instances_on_different_threads():
    """Sqlite3 handles default to check_same_thread=True, so each
    worker thread MUST get its own NCBITaxa to stay correct."""
    from src.ete_utils import get_ncbi

    instances: dict[str, object] = {}

    def collect(name: str) -> None:
        instances[name] = get_ncbi()

    t1 = threading.Thread(target=collect, args=("t1",))
    t2 = threading.Thread(target=collect, args=("t2",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert "t1" in instances and "t2" in instances
    # Different threads get different NCBITaxa instances, but each one
    # is a stable `NCBITaxa`.
    assert instances["t1"] is not instances["t2"]
    main_instance = get_ncbi()
    assert main_instance is not instances["t1"]
    assert main_instance is not instances["t2"]


def test_get_ncbi_instance_actually_works():
    """Sanity check that the cached instance is a usable NCBITaxa — guards
    against a future refactor that hands back e.g. a None placeholder."""
    from src.ete_utils import get_ncbi
    ncbi = get_ncbi()
    # 2759 is Eukaryota — present in any non-empty ETE3 taxonomy DB.
    name = ncbi.get_taxid_translator([2759]).get(2759)
    assert name == "Eukaryota"
