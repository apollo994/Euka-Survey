"""Unit tests on the per-step snapshot layer in `pipeline_build_db`.

The fetch steps themselves hit external APIs and aren't exercised here.
The helpers below (_save/_load/_run_cached/_purge_snapshots_from /
_cleanup_snapshots) carry the resumability contract — if they regress,
the pipeline will silently re-fetch on every retry or fail to clean up
on success.
"""

from pathlib import Path

import pytest

from db_builder.pipeline_build_db import (
    _cleanup_snapshots,
    _load_snapshot,
    _purge_snapshots_from,
    _run_cached,
    _save_snapshot,
    _snapshot_dir,
    _snapshot_path,
)


# --------------------------------------------------------------------- #
# _snapshot_dir / _snapshot_path
# --------------------------------------------------------------------- #


def test_snapshot_dir_is_hidden_sibling_of_partial(tmp_path):
    """The snapshot dir lives next to the .partial with a leading dot,
    so `mv eukaryote_taxid_features_*.db` and similar globs in the
    workflow skip it."""
    partial = tmp_path / "eukaryote_taxid_features_2026_06_15.db.partial"
    snap_dir = _snapshot_dir(partial)
    assert snap_dir.parent == tmp_path
    assert snap_dir.name.startswith(".")
    assert snap_dir.name.endswith(".snapshots")
    assert "eukaryote_taxid_features_2026_06_15" in snap_dir.name


def test_snapshot_path_includes_step_number_and_key(tmp_path):
    p = _snapshot_path(tmp_path, 4, "reads")
    assert p.name == "step4_reads.pkl"


# --------------------------------------------------------------------- #
# save / load roundtrip
# --------------------------------------------------------------------- #


def test_save_load_roundtrip_preserves_value(tmp_path):
    data = {1: 10, 2: 20, 9606: 12345}
    _save_snapshot(tmp_path, 2, "assemblies", data)
    assert _load_snapshot(tmp_path, 2, "assemblies") == data


def test_save_load_roundtrip_handles_tuples(tmp_path):
    """Step 4 returns a 3-tuple (long_reads, short_reads, count) — make
    sure non-dict payloads roundtrip too."""
    payload = ({1: 5}, {2: 7, 3: 11}, 23)
    _save_snapshot(tmp_path, 4, "reads", payload)
    assert _load_snapshot(tmp_path, 4, "reads") == payload


def test_load_returns_none_when_missing(tmp_path):
    assert _load_snapshot(tmp_path, 1, "descendants") is None


def test_save_creates_dir_if_missing(tmp_path):
    """Caller shouldn't have to pre-create the snapshot dir."""
    snap_dir = tmp_path / ".snaps"
    assert not snap_dir.exists()
    _save_snapshot(snap_dir, 1, "descendants", [1, 2, 3])
    assert snap_dir.is_dir()
    assert _load_snapshot(snap_dir, 1, "descendants") == [1, 2, 3]


def test_save_is_atomic_no_tmp_left_behind(tmp_path):
    """Successful save replaces the tmp file — no stray .pkl.tmp."""
    _save_snapshot(tmp_path, 1, "descendants", [1])
    stragglers = list(tmp_path.glob("*.tmp"))
    assert stragglers == []


# --------------------------------------------------------------------- #
# _run_cached
# --------------------------------------------------------------------- #


def test_run_cached_calls_fn_on_first_invocation(tmp_path):
    calls = []
    def fn():
        calls.append(1)
        return "result"

    result = _run_cached(tmp_path, 1, "descendants", fn)
    assert result == "result"
    assert calls == [1]


def test_run_cached_returns_cached_value_on_second_invocation(tmp_path):
    calls = []
    def fn():
        calls.append(1)
        return [1, 2, 3]

    first = _run_cached(tmp_path, 1, "descendants", fn)
    second = _run_cached(tmp_path, 1, "descendants", fn)

    assert first == second == [1, 2, 3]
    assert calls == [1], "fn must NOT be called when snapshot is cached"


def test_run_cached_separates_by_step_number(tmp_path):
    """Each (step, key) pair has its own snapshot — two different steps
    must not collide."""
    _run_cached(tmp_path, 1, "a", lambda: "one")
    _run_cached(tmp_path, 2, "a", lambda: "two")
    assert _load_snapshot(tmp_path, 1, "a") == "one"
    assert _load_snapshot(tmp_path, 2, "a") == "two"


def test_run_cached_propagates_exception_and_skips_save(tmp_path):
    """Failure inside fn must not poison the cache with a partial
    result — the snapshot file should not be written at all."""
    def fn():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _run_cached(tmp_path, 1, "descendants", fn)
    assert _load_snapshot(tmp_path, 1, "descendants") is None
    assert list(tmp_path.glob("*.pkl")) == []


# --------------------------------------------------------------------- #
# _purge_snapshots_from
# --------------------------------------------------------------------- #


def test_purge_from_step_keeps_earlier_drops_later(tmp_path):
    for n, key in [(1, "descendants"), (2, "assemblies"),
                   (3, "annotations"), (4, "reads")]:
        _save_snapshot(tmp_path, n, key, [n])

    purged = _purge_snapshots_from(tmp_path, 3)
    assert purged == 2  # step3 + step4

    remaining = sorted(p.name for p in tmp_path.glob("step*_*.pkl"))
    assert remaining == ["step1_descendants.pkl", "step2_assemblies.pkl"]


def test_purge_from_step_1_drops_everything(tmp_path):
    for n in (1, 2, 3, 4):
        _save_snapshot(tmp_path, n, "k", [n])

    purged = _purge_snapshots_from(tmp_path, 1)
    assert purged == 4
    assert list(tmp_path.glob("step*_*.pkl")) == []


def test_purge_from_step_higher_than_any_is_noop(tmp_path):
    _save_snapshot(tmp_path, 1, "descendants", [1])
    purged = _purge_snapshots_from(tmp_path, 99)
    assert purged == 0
    assert _load_snapshot(tmp_path, 1, "descendants") == [1]


def test_purge_from_missing_dir_is_noop(tmp_path):
    """No snapshot dir → nothing to purge, no exception."""
    assert _purge_snapshots_from(tmp_path / "does_not_exist", 1) == 0


# --------------------------------------------------------------------- #
# _cleanup_snapshots
# --------------------------------------------------------------------- #


def test_cleanup_removes_snapshot_pkls_and_dir(tmp_path):
    snap_dir = tmp_path / ".snaps"
    for n in (1, 2, 3, 4):
        _save_snapshot(snap_dir, n, "k", [n])

    _cleanup_snapshots(snap_dir)
    assert not snap_dir.exists()


def test_cleanup_leaves_unrelated_files_in_place(tmp_path):
    """If a user dropped a file into the snapshot dir, don't `rm -rf`
    it — only the stepN_*.pkl files we own."""
    snap_dir = tmp_path / ".snaps"
    snap_dir.mkdir()
    _save_snapshot(snap_dir, 1, "descendants", [1])
    user_file = snap_dir / "NOTES.md"
    user_file.write_text("don't delete me")

    _cleanup_snapshots(snap_dir)

    # The user file (and therefore the dir) must survive.
    assert user_file.exists()
    assert user_file.read_text() == "don't delete me"
    # But the snapshot is gone.
    assert not (snap_dir / "step1_descendants.pkl").exists()


def test_cleanup_on_missing_dir_is_noop(tmp_path):
    """Idempotent — calling cleanup twice should not raise."""
    snap_dir = tmp_path / ".never_existed"
    _cleanup_snapshots(snap_dir)  # must not raise
    assert not snap_dir.exists()
