"""SQLite storage for checked usernames."""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from src.models import CheckResult, RarityTier, CheckStatus, rarity_points


class Storage:
    """Persistent storage for checked usernames."""
    
    def __init__(self, db_path: str = "data/checked.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
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
                    rarity_points INTEGER
                )
            """)
            columns = [row[1] for row in conn.execute("PRAGMA table_info(checked)")]
            if "source" not in columns:
                conn.execute("ALTER TABLE checked ADD COLUMN source TEXT")
            if "rarity_points" not in columns:
                conn.execute("ALTER TABLE checked ADD COLUMN rarity_points INTEGER")
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
            self._backfill_points()
    
    def _backfill_points(self):
        """Compute rarity points for rows stored before points existed."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT username FROM checked WHERE rarity_points IS NULL"
            ).fetchall()
            if not rows:
                return
            print(f"Backfilling rarity points for {len(rows)} rows...")
            conn.executemany(
                "UPDATE checked SET rarity_points = ? WHERE username = ?",
                [(rarity_points(r["username"]), r["username"]) for r in rows],
            )
            conn.commit()
            print("Backfill complete.")
    
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
        """Check if username has ever been checked (any tier except errors).
        
        Errors are always rechecked on next run.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM checked WHERE username = ? AND status != ?", 
                (username.lower(), CheckStatus.ERROR.value)
            )
            return cursor.fetchone() is not None
    
    def get_checked_tiers(self) -> dict[str, RarityTier]:
        """Return {username: tier} for all non-error rows in a single query.

        Used to pre-filter large word lists in memory instead of issuing
        one DB query per candidate.
        """
        checked: dict[str, RarityTier] = {}
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT username, tier FROM checked WHERE status != ?",
                (CheckStatus.ERROR.value,),
            )
            for row in cursor.fetchall():
                try:
                    checked[row["username"]] = RarityTier(row["tier"])
                except ValueError:
                    continue
        return checked
    
    def is_checked_at_or_above_tier(self, username: str, tier: RarityTier) -> bool:
        """
        Check if username was checked at same or higher priority tier.
        Lower sort_order = higher priority (TOP=0 > OG=1 > SEMI_OG=2).
        Returns True if should skip, False if should re-check.
        Errors are always rechecked.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT tier FROM checked WHERE username = ? AND status != ?", 
                (username.lower(), CheckStatus.ERROR.value)
            )
            row = cursor.fetchone()
            if row is None:
                return False
            checked_tier = RarityTier(row["tier"])
            # Skip if checked tier has same or higher priority (lower or equal sort_order)
            return checked_tier.sort_order <= tier.sort_order
    
    def save_result(self, result: CheckResult):
        """Save a check result to the database."""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO checked 
                (username, tier, status, checked_at, verified, error_message, source, rarity_points)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.username.lower(),
                result.tier.value,
                result.status.value,
                result.checked_at.isoformat(),
                1 if result.verified else 0,
                result.error_message,
                result.source,
                rarity_points(result.username),
            ))
            conn.commit()
    
    def get_available(self, verified_only: bool = True, trusted_only: bool = True) -> list[CheckResult]:
        """Get available usernames from database, ordered by rarity (most rare first).

        Trusted results are auth-verified hits or public AVAILABLE decisions made
        by the canonical Mojang endpoint. Legacy public AVAILABLE rows without
        provenance are excluded when trusted_only is True.
        """
        # Rarity ordering: community points first (higher = rarer), then
        # shorter names, then tier priority (top > og > semi_og).
        rarity_order = """
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
                       ORDER BY {rarity_order}
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
                       ORDER BY {rarity_order}
                    """,
                    (CheckStatus.VERIFIED_AVAILABLE.value, CheckStatus.AVAILABLE.value)
                )
            else:
                cursor = conn.execute(
                    f"""SELECT * FROM checked 
                       WHERE status = ? 
                       ORDER BY {rarity_order}
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
            
            return stats
    
    def export_available(self, output_path: str, verified_only: bool = True, trusted_only: bool = True, include_banned: bool = False, min_points: int = 0):
        """Export available usernames to a text file.

        By default only trusted results are exported: auth-verified hits or
        public AVAILABLE decisions made by the canonical Mojang endpoint.
        Banned words (matching Mojang's filter) are EXCLUDED by default.
        Set include_banned=True to include them with a BANNED flag.
        min_points drops names below that rarity score (scope: rarest first).

        Output format: username, tier, status, source, banned_flag
        banned_flag is "BANNED" if the username matches Mojang's filter, empty otherwise.
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
                if min_points and rarity_points(result.username) < min_points:
                    continue
                source = result.source or "unrecorded"
                banned_flag = "BANNED" if is_banned(result.username) else ""
                f.write(f"{result.username}\t{result.tier.value}\t{result.status.value}\t{source}\t{banned_flag}\n")
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
        )


# Global instance
_storage: Optional[Storage] = None


def get_storage(db_path: str = "data/checked.db") -> Storage:
    """Get or create the global storage instance."""
    global _storage
    if _storage is None:
        _storage = Storage(db_path)
    return _storage