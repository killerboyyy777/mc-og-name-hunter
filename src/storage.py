"""SQLite storage for checked usernames.

``rarity_points`` holds the 0-1000 score from :mod:`src.rarity` and
``score_model`` records which scoring model produced it.  Opening a database
written by an older model rescored it in place (one transaction, no API calls,
status/verified/source/checked_at untouched); the second open is a no-op.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from src.models import (
    CheckResult,
    RarityTier,
    CheckStatus,
    rarity_points,
    tier_for_score,
)

#: Bump when the scoring model changes; rows with another value are rescored.
SCORE_MODEL = 2

#: Statuses that do not count as "checked": they are retried on the next run.
RETRYABLE_STATUSES = (CheckStatus.ERROR.value, CheckStatus.RATE_LIMITED.value)


class Storage:
    """Persistent storage for checked usernames."""

    def __init__(self, db_path: str = "data/checked.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema and migrate old scores."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checked (
                    username TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    source TEXT,
                    rarity_points INTEGER,
                    score_model INTEGER
                )
            """)
            columns = [row[1] for row in conn.execute("PRAGMA table_info(checked)")]
            if "source" not in columns:
                conn.execute("ALTER TABLE checked ADD COLUMN source TEXT")
            if "rarity_points" not in columns:
                conn.execute("ALTER TABLE checked ADD COLUMN rarity_points INTEGER")
            if "score_model" not in columns:
                conn.execute("ALTER TABLE checked ADD COLUMN score_model INTEGER")
            conn.commit()
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checked_status
                ON checked(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checked_tier
                ON checked(tier)
            """)
            conn.commit()
        self._migrate_scores()

    @staticmethod
    def _status_counts(conn: sqlite3.Connection) -> dict[str, int]:
        return {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT status, COUNT(*) FROM checked GROUP BY status"
            )
        }

    def _migrate_scores(self):
        """Rescore every row not written by the current model, in one transaction.

        The score depends only on the username, so this is a pure local
        recomputation: availability status, provenance, verification and the
        check timestamp are never touched and no API request is made.  Status
        counts are compared before committing; a mismatch rolls the whole
        transaction back.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT username FROM checked "
                "WHERE score_model IS NULL OR score_model != ?",
                (SCORE_MODEL,),
            ).fetchall()
            if not rows:
                return

            print(f"Rescoring {len(rows):,} rows with score model {SCORE_MODEL}...")
            updates = []
            for row in rows:
                username = row["username"]
                points = rarity_points(username)
                updates.append(
                    (points, tier_for_score(points).value, SCORE_MODEL, username)
                )

            before = self._status_counts(conn)
            conn.execute("BEGIN")
            try:
                conn.executemany(
                    "UPDATE checked SET rarity_points = ?, tier = ?, score_model = ? "
                    "WHERE username = ?",
                    updates,
                )
                after = self._status_counts(conn)
                if after != before:
                    raise RuntimeError(
                        "Score migration would change status counts "
                        f"(before={before}, after={after}); rolled back."
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            print("Rescore complete.")

    @contextmanager
    def _conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def is_checked(self, username: str) -> bool:
        """True when the name was checked at all (checked-at-all gate).

        Any row except ``error``/``rate_limited`` counts: availability is
        Mojang's fact and never changes because the local scoring model did,
        so a rescore must not cause a re-check that burns rate-limit budget.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM checked WHERE username = ? "
                "AND status NOT IN (?, ?)",
                (username.lower(), *RETRYABLE_STATUSES),
            )
            return cursor.fetchone() is not None

    def get_checked(self) -> set[str]:
        """Return every checked username in one query (checked-at-all gate).

        Used to pre-filter large word lists in memory instead of issuing one
        DB query per candidate.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT username FROM checked WHERE status NOT IN (?, ?)",
                RETRYABLE_STATUSES,
            )
            return {row["username"] for row in cursor.fetchall()}

    def save_result(self, result: CheckResult):
        """Save a check result, deriving score and tier from the username."""
        points = rarity_points(result.username)
        tier = tier_for_score(points)
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO checked
                (username, tier, status, checked_at, verified, error_message,
                 source, rarity_points, score_model)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.username.lower(),
                tier.value,
                result.status.value,
                result.checked_at.isoformat(),
                1 if result.verified else 0,
                result.error_message,
                result.source,
                points,
                SCORE_MODEL,
            ))
            conn.commit()

    def get_available(self, verified_only: bool = True, trusted_only: bool = True) -> list[CheckResult]:
        """Get available usernames from database, ordered by score (rarest first).

        Trusted results are auth-verified hits or public AVAILABLE decisions made
        by the canonical Mojang endpoint. Legacy public AVAILABLE rows without
        provenance are excluded when trusted_only is True.
        """
        score_order = """
            COALESCE(rarity_points, 0) DESC,
            LENGTH(username) ASC,
            CASE tier
                WHEN 'top' THEN 0
                WHEN 'og' THEN 1
                WHEN 'semi_og' THEN 2
            END ASC
        """
        with self._conn() as conn:
            if trusted_only:
                cursor = conn.execute(
                    f"""SELECT * FROM checked
                       WHERE status = ?
                          OR (status = ? AND source = ?)
                       ORDER BY {score_order}
                    """,
                    (
                        CheckStatus.VERIFIED_AVAILABLE.value,
                        CheckStatus.AVAILABLE.value,
                        "mojang-primary",
                    ),
                )
            elif verified_only:
                cursor = conn.execute(
                    f"""SELECT * FROM checked
                       WHERE status IN (?, ?)
                       ORDER BY {score_order}
                    """,
                    (CheckStatus.VERIFIED_AVAILABLE.value, CheckStatus.AVAILABLE.value)
                )
            else:
                cursor = conn.execute(
                    f"""SELECT * FROM checked
                       WHERE status = ?
                       ORDER BY {score_order}
                    """,
                    (CheckStatus.AVAILABLE.value,)
                )
            return [self._row_to_result(row) for row in cursor.fetchall()]

    def get_unvalidated_available(self, limit: Optional[int] = None) -> list[tuple[str, RarityTier]]:
        """Get public AVAILABLE rows that still need canonical validation.

        These are unverified public hits without canonical provenance. They may
        include false positives from previously trusted auxiliary endpoints.
        """
        with self._conn() as conn:
            query = """SELECT username, tier FROM checked
                       WHERE status = ?
                         AND verified = 0
                         AND (source IS NULL OR source != ?)
                       ORDER BY
                            COALESCE(rarity_points, 0) DESC,
                            LENGTH(username) ASC
                     """
            params: list[object] = [CheckStatus.AVAILABLE.value, "mojang-primary"]
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            cursor = conn.execute(query, params)
            results: list[tuple[str, RarityTier]] = []
            for row in cursor.fetchall():
                try:
                    results.append((row["username"], RarityTier(row["tier"])))
                except ValueError:
                    continue
            return results

    def get_stats(self) -> dict:
        """Get statistics about checked usernames."""
        with self._conn() as conn:
            stats = {}
            cursor = conn.execute("SELECT COUNT(*) as total FROM checked")
            stats["total_checked"] = cursor.fetchone()["total"]

            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM checked
                GROUP BY status
            """)
            for row in cursor.fetchall():
                stats[f"status_{row['status']}"] = row["count"]

            cursor = conn.execute("""
                SELECT tier, COUNT(*) as count
                FROM checked
                GROUP BY tier
            """)
            for row in cursor.fetchall():
                stats[f"tier_{row['tier']}"] = row["count"]

            cursor = conn.execute(
                """SELECT COUNT(*) as count FROM checked
                   WHERE status = ?
                      OR (status = ? AND source = ?)
                """,
                (
                    CheckStatus.VERIFIED_AVAILABLE.value,
                    CheckStatus.AVAILABLE.value,
                    "mojang-primary",
                ),
            )
            stats["trusted_available"] = cursor.fetchone()["count"]

            cursor = conn.execute(
                """SELECT COUNT(*) as count FROM checked
                   WHERE status = ?
                     AND verified = 0
                     AND (source IS NULL OR source != ?)
                """,
                (CheckStatus.AVAILABLE.value, "mojang-primary"),
            )
            stats["unvalidated_available"] = cursor.fetchone()["count"]

            # Model version actually on disk (None when the table is empty).
            cursor = conn.execute(
                "SELECT score_model, COUNT(*) FROM checked "
                "GROUP BY score_model ORDER BY COUNT(*) DESC LIMIT 1"
            )
            row = cursor.fetchone()
            stats["score_model"] = row["score_model"] if row else SCORE_MODEL

            return stats

    def export_available(self, output_path: str, verified_only: bool = True,
                         trusted_only: bool = True, include_banned: bool = False,
                         min_score: int = 0):
        """Export available usernames to a text file.

        By default only trusted results are exported: auth-verified hits or
        public AVAILABLE decisions made by the canonical Mojang endpoint.
        Banned words (matching Mojang's filter) are EXCLUDED by default.
        Set include_banned=True to include them with a BANNED flag.
        min_score drops names below that score (scope: rarest first).

        Output format, tab separated: username, tier, status, source,
        banned_flag, score.  The score column was appended in score model 2;
        consumers reading the first five columns keep working.
        """
        available = self.get_available(
            verified_only=verified_only, trusted_only=trusted_only
        )
        from generate_custom_wordlists import is_banned
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(output_path, 'w') as f:
            for result in available:
                if is_banned(result.username) and not include_banned:
                    continue
                points = result.score if result.score is not None else rarity_points(result.username)
                if min_score and points < min_score:
                    continue
                source = result.source or "unrecorded"
                banned_flag = "BANNED" if is_banned(result.username) else ""
                f.write(
                    f"{result.username}\t{result.tier.value}\t"
                    f"{result.status.value}\t{source}\t{banned_flag}\t{points}\n"
                )
                written += 1
        return written

    def _row_to_result(self, row: sqlite3.Row) -> CheckResult:
        columns = set(row.keys())
        return CheckResult(
            username=row["username"],
            status=CheckStatus(row["status"]),
            tier=RarityTier(row["tier"]),
            checked_at=datetime.fromisoformat(row["checked_at"]),
            verified=bool(row["verified"]),
            error_message=row["error_message"],
            source=row["source"] if "source" in columns else None,
            score=row["rarity_points"] if "rarity_points" in columns else None,
        )


# Global instance
_storage: Optional[Storage] = None


def get_storage(db_path: str = "data/checked.db") -> Storage:
    """Get or create the global storage instance."""
    global _storage
    if _storage is None:
        _storage = Storage(db_path)
    return _storage
