#!/usr/bin/env python3
"""Sweep unchecked word-list names inside a score band against Mojang.

``find_rarest_available.py`` walks the score-sorted queue and stops once it
has found its targets, so the band directly below the point where it stopped
is still unexplored.  This script closes that gap: it takes every word-list
name that is not already settled in the database, keeps the ones scoring in
``[--min-score, --max-score]``, screens them with the public batch endpoint and
auth-verifies the absences.

Rows already in the database are left alone unless they are ``error`` or
``rate_limited`` (the checked-at-all gate).

  python sweep_unchecked.py --min-score 500 --max-score 637
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

from recheck_high_scores import auth_phase, public_phase, save_results
from src.models import rarity_points
from src.paths import default_wordlist_dir

VALID = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def load_settled(db_path: str) -> set[str]:
    """Usernames whose availability we should not re-test."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT username FROM checked WHERE status NOT IN ('error', 'rate_limited')")
    settled = {r[0].lower() for r in cur.fetchall()}
    conn.close()
    return settled


def load_band(min_score: int, max_score: int, settled: set[str],
              list_dir: Path) -> list[tuple[str, int]]:
    """Word-list names scoring in the band that are not settled yet."""
    seen: dict[str, int] = {}
    for path in sorted(list_dir.glob("*.txt")):
        if path.name in {"semi_names.txt"}:
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            word = line.split("\t")[0].strip().lower()
            if not word or not VALID.match(word) or word in settled or word in seen:
                continue
            score = rarity_points(word)
            if min_score <= score <= max_score:
                seen[word] = score
    return sorted(seen.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep unchecked names in a score band")
    parser.add_argument("--db", default="data/checked.db")
    parser.add_argument("--min-score", type=int, default=500)
    parser.add_argument("--max-score", type=int, default=637)
    parser.add_argument("--public-rps", type=float, default=1.5)
    parser.add_argument("--limit", type=int, default=0, help="Cap names (0 = all)")
    args = parser.parse_args()

    settled = load_settled(args.db)
    band = load_band(args.min_score, args.max_score, settled, Path(default_wordlist_dir()))
    if args.limit:
        band = band[: args.limit]

    if not band:
        print("[INFO] Nothing in the band is unchecked.")
        return 0

    print(
        f"[INFO] {len(band):,} unchecked names in "
        f"{args.min_score}-{args.max_score} (top {band[0][0]} {band[0][1]})"
    )
    names = [name for name, _ in band]
    public_status, absent = public_phase(names, rps=args.public_rps)
    print(f"[INFO] {len(absent):,} absent; auth-verifying at 15s/name")
    auth_results = auth_phase(absent)
    counts = save_results(args.db, public_status, auth_results)

    print("\n=== Results ===")
    for status, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<20}: {n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
