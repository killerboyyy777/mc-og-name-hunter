#!/usr/bin/env python3
"""Auth-verify every public-only available name at or above a score.

Reports at score >= 500 were resolved with the authenticated endpoint, but
older public screens left thousands of rows marked ``available`` on the
strength of the public lookup alone.  Those rows can be stale (a name may
have been claimed since), so a "top N" ranking that mixes them with
auth-verified rows is not comparable.

This script closes that gap for the score band that actually matters for a
top-N list: it takes every ``available`` row at or above ``--min-score``,
checks it against the authenticated availability endpoint (20 requests per
5 minutes, so a 15 s interval), and writes the real status back.  Names come
back as ``verified_available``, ``verified_taken`` or ``blocked``.

  python verify_top_available.py --min-score 638
"""

import argparse
import sqlite3
import sys

from recheck_high_scores import auth_phase, save_results


def load_public_only(db_path: str, min_score: int) -> list[str]:
    """Return public-only ``available`` names at/above ``min_score``."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT username FROM checked WHERE status = 'available' "
        "AND rarity_points >= ? "
        "ORDER BY rarity_points DESC, LENGTH(username), username",
        (min_score,),
    )
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


def print_top(db_path: str, limit: int = 20) -> None:
    """Print the top auth-verified available names."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT username, rarity_points, source FROM checked "
        "WHERE status = 'verified_available' "
        "ORDER BY rarity_points DESC, LENGTH(username), username LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()

    print(f"\n=== Top {limit} auth-verified available ===")
    for rank, (name, score, source) in enumerate(rows, 1):
        print(f"{rank:>3}. {name:<14}{score:>5}  {source or '-'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auth-verify public-only available names above a score"
    )
    parser.add_argument("--db", default="data/checked.db", help="Path to checked.db")
    parser.add_argument(
        "--min-score",
        type=int,
        default=638,
        help="Only verify public-only available rows at or above this score",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after N names (0 = all matching)",
    )
    args = parser.parse_args()

    names = load_public_only(args.db, args.min_score)
    if args.limit:
        names = names[: args.limit]

    if not names:
        print(f"[INFO] No public-only available names at score >= {args.min_score}")
        print_top(args.db)
        return 0

    minutes = len(names) * 15 / 60
    print(
        f"[INFO] Auth-verifying {len(names):,} public-only names "
        f"at score >= {args.min_score} (~{minutes:.0f} min at 15s/name)"
    )

    results = auth_phase(names)
    counts = save_results(args.db, {}, results)

    print("\n=== Results ===")
    for status, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<20}: {n:,}")

    print_top(args.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
