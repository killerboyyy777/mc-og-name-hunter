"""Storage tests for score model 2: in-place migration, checked gate, export.

The migration is the risky part of a scoring change: it rewrites every row of
a 200k-row database.  These tests pin the two guarantees that make it safe --
availability data is untouched, and a second open is a no-op -- plus the
checked-at-all gate and the export format.
"""

import sqlite3
from datetime import datetime

import pytest

from src.models import CheckResult, CheckStatus, RarityTier
from src.rarity import score
from src.storage import SCORE_MODEL, Storage


def _make_legacy_db(path, rows):
    """Create a pre-score-model-2 database (no ``score_model`` column)."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE checked (
            username TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            source TEXT,
            rarity_points INTEGER
        )
        """
    )
    conn.executemany(
        "INSERT INTO checked (username, tier, status, checked_at, verified, "
        "error_message, source, rarity_points) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


LEGACY_ROWS = [
    # username, tier, status, checked_at, verified, error, source, points
    ("the", "top", "taken", "2026-01-01T00:00:00", 0, None, "mojang-primary", 80),
    ("because", "og", "taken", "2026-01-02T00:00:00", 0, None, "minecraftapi", 60),
    ("harbor", "og", "available", "2026-01-03T00:00:00", 0, None, "mojang-primary", 35),
    ("6633", "semi_og", "available", "2026-01-04T00:00:00", 0, None, None, 12),
    ("qzvk", "semi_og", "invalid", "2026-01-05T00:00:00", 0, None, "unknown", 8),
    ("zzzz", "semi_og", "error", "2026-01-06T00:00:00", 0, "timeout", None, 8),
    ("yyyy", "semi_og", "rate_limited", "2026-01-07T00:00:00", 0, "429", None, 8),
    ("zq", "top", "verified_available", "2026-01-08T00:00:00", 1, None, "mojang-primary", 80),
]

SNAPSHOT_COLUMNS = ("username", "status", "checked_at", "verified",
                    "error_message", "source")


def _snapshot(path, columns):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT {', '.join(columns)} FROM checked ORDER BY username"
    ).fetchall()
    conn.close()
    return [tuple(row) for row in rows]


def test_migration_rescores_without_touching_availability(tmp_path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, LEGACY_ROWS)
    before = _snapshot(db, SNAPSHOT_COLUMNS)

    storage = Storage(str(db))

    # Availability fields are identical, row by row.
    assert _snapshot(db, SNAPSHOT_COLUMNS) == before
    # Scores and tiers now come from the 0-1000 model.
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = {row["username"]: row for row in conn.execute("SELECT * FROM checked")}
    conn.close()
    assert set(rows) == {row[0] for row in LEGACY_ROWS}
    for username, row in rows.items():
        assert row["score_model"] == SCORE_MODEL
        expected = score(username)
        assert row["rarity_points"] == expected
        assert row["tier"] == storage_tier(expected)
    assert rows["the"]["rarity_points"] >= 800


def storage_tier(points):
    from src.models import tier_for_score

    return tier_for_score(points).value


def test_migration_is_idempotent(tmp_path, capsys):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, LEGACY_ROWS)
    Storage(str(db))
    first_scores = _snapshot(db, ("username", "rarity_points", "tier", "score_model"))
    capsys.readouterr()

    # Second open must not rescore anything and must not print progress.
    Storage(str(db))
    assert "Rescoring" not in capsys.readouterr().out
    assert _snapshot(db, ("username", "rarity_points", "tier", "score_model")) == first_scores


def test_migration_upgrades_tier_to_new_bands(tmp_path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, LEGACY_ROWS)
    Storage(str(db))
    conn = sqlite3.connect(db)
    tiers = dict(conn.execute("SELECT username, tier FROM checked"))
    conn.close()
    assert tiers["the"] == "top"
    assert tiers["zq"] == "top"
    assert tiers["because"] == "og"
    # qzvk (4L random, 99) is semi-OG under the new bands.
    assert tiers["qzvk"] == "semi_og"


def test_checked_gate_retries_only_errors(tmp_path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, LEGACY_ROWS)
    storage = Storage(str(db))

    assert storage.is_checked("the") is True          # taken
    assert storage.is_checked("harbor") is True       # available
    assert storage.is_checked("qzvk") is True         # invalid
    assert storage.is_checked("THE") is True          # lower-cased lookup
    assert storage.is_checked("zzzz") is False        # error is retryable
    assert storage.is_checked("yyyy") is False        # rate_limited is retryable
    assert storage.is_checked("never-seen") is False

    checked = storage.get_checked()
    assert "zzzz" not in checked and "yyyy" not in checked
    assert {"the", "harbor", "qzvk", "6633", "zq"} <= checked


def test_save_result_writes_current_model(tmp_path):
    db = tmp_path / "fresh.db"
    storage = Storage(str(db))
    result = CheckResult(
        username="Elk",
        status=CheckStatus.AVAILABLE,
        tier=RarityTier.OG,  # deliberately wrong; save_result must recompute
        checked_at=datetime(2026, 10, 30, 12, 0, 0),
        source="mojang-primary",
    )
    storage.save_result(result)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT username, tier, rarity_points, score_model, source FROM checked"
    ).fetchone()
    conn.close()
    assert row[0] == "elk"
    assert row[2] == score("elk")
    assert row[3] == SCORE_MODEL
    assert row[1] == "og"
    assert row[4] == "mojang-primary"


def test_export_has_score_column_and_honours_min_score(tmp_path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, LEGACY_ROWS)
    storage = Storage(str(db))
    out = tmp_path / "available.txt"

    written = storage.export_available(str(out))
    lines = out.read_text(encoding="utf-8").splitlines()
    # Only trusted rows: harbor (available + mojang-primary) and zq (verified).
    assert written == 2
    assert len(lines) == 2
    for line in lines:
        fields = line.split("\t")
        assert len(fields) == 6, line
        assert int(fields[5]) == score(fields[0])

    # 900 keeps only the 2-character name (910); harbor is 659.
    out_high = tmp_path / "available_high.txt"
    assert storage.export_available(str(out_high), min_score=900) == 1
    assert out_high.read_text(encoding="utf-8").split("\t")[0] == "zq"

    out_none = tmp_path / "available_none.txt"
    assert storage.export_available(str(out_none), min_score=950) == 0
    assert out_none.read_text(encoding="utf-8") == ""


def test_stats_report_model_version(tmp_path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, LEGACY_ROWS)
    stats = Storage(str(db)).get_stats()
    assert stats["score_model"] == SCORE_MODEL
    assert stats["total_checked"] == len(LEGACY_ROWS)
    assert stats["status_error"] == 1
    assert stats["status_rate_limited"] == 1


def test_migration_rolls_back_on_status_drift(tmp_path, monkeypatch):
    """If a status count changes mid-migration, nothing is committed."""
    db = tmp_path / "legacy.db"
    _make_legacy_db(db, LEGACY_ROWS)
    original = Storage._status_counts

    calls = {"n": 0}

    def drifting_counts(conn):
        calls["n"] += 1
        counts = dict(original(conn))
        if calls["n"] == 2:  # the post-update check
            counts["taken"] = counts.get("taken", 0) + 1
        return counts

    monkeypatch.setattr(Storage, "_status_counts", staticmethod(drifting_counts))
    with pytest.raises(RuntimeError, match="status counts"):
        Storage(str(db))

    # Rolled back: every row still has a NULL score_model and the old points.
    conn = sqlite3.connect(db)
    models = conn.execute("SELECT DISTINCT score_model FROM checked").fetchall()
    points = dict(conn.execute("SELECT username, rarity_points FROM checked"))
    conn.close()
    assert models == [(None,)]
    assert points["the"] == 80
