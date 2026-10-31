#!/usr/bin/env python3
"""Re-check availability for every stored name with score >= 500.

This overrides the normal checked-at-all gate for high-value names.  It runs
two phases:

  Phase 1  Public batch lookup (10 names/request) against the canonical Mojang
           endpoint.  Names found there are marked TAKEN.
  Phase 2  Names absent from the public API are checked one-by-one with the
           authenticated endpoint to distinguish AVAILABLE, BANNED/BLOCKED and
           TAKEN.

Rate limits used:
  * Public: 1.5 requests/second (Mojang allows 200/2 min; this stays under it).
  * Auth:   one request every 15 seconds (20/5 min).
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from tqdm import tqdm

# We import only models/storage/auth here; checkers.py is one-name-at-a-time,
# so this script uses the public batch endpoint directly for efficiency.
from src.auth import get_access_token
from src.models import CheckResult, CheckStatus, RarityTier, rarity_points, tier_for_score
from src.storage import get_storage

PUBLIC_URL = "https://api.minecraftservices.com/minecraft/profile/lookup/bulk/byname"
AUTH_URL = "https://api.minecraftservices.com/minecraft/profile/name/{}/available"
USER_AGENT = "mc-og-name-hunter/2.0"


def load_usernames(db_path: str, min_score: int) -> list[str]:
    """Return all usernames in the DB with rarity_points >= min_score."""
    storage = get_storage(db_path)
    conn = sqlite3.connect(storage.db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT username FROM checked WHERE rarity_points >= ? ORDER BY rarity_points DESC",
        (min_score,),
    )
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def public_phase(usernames: list[str], rps: float = 1.5) -> tuple[dict[str, str], list[str]]:
    """
    Screen usernames with the canonical public batch endpoint.

    Returns:
        status_map: username -> status string ("taken" or "absent")
        absent:     usernames that need auth-phase checking
    """
    session = requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    delay = 1.0 / rps if rps > 0 else 0.0

    status_map: dict[str, str] = {}
    absent: list[str] = []
    errors = 0

    print(f"[INFO] Public phase: {len(usernames):,} names in batches of 10")
    with tqdm(total=len(usernames), unit="name") as bar:
        for start in range(0, len(usernames), 10):
            batch = usernames[start:start + 10]
            backoffs = 0
            while True:
                try:
                    resp = session.post(PUBLIC_URL, json=batch, headers=headers, timeout=20)
                except requests.RequestException as exc:
                    if backoffs >= 5:
                        for name in batch:
                            status_map[name] = "error"
                            errors += 1
                        break
                    backoffs += 1
                    time.sleep(30)
                    continue

                limit = resp.headers.get("x-minecraft-rate-limit-result", "")
                if resp.status_code == 429 or limit == "OVER_LIMIT":
                    if backoffs >= 5:
                        for name in batch:
                            status_map[name] = "rate_limited"
                            errors += 1
                        break
                    backoffs += 1
                    time.sleep(60)
                    continue

                if resp.status_code != 200:
                    for name in batch:
                        status_map[name] = "error"
                        errors += 1
                    break

                try:
                    found = {item.get("name", "").lower() for item in resp.json()}
                except Exception:
                    found = set()

                for name in batch:
                    if name.lower() in found:
                        status_map[name] = "taken"
                    else:
                        status_map[name] = "absent"
                        absent.append(name)
                break

            bar.update(len(batch))
            if delay and start + 10 < len(usernames):
                time.sleep(delay)

    print(f"[INFO] Public phase done: {len(absent):,} absent, {errors:,} errors")
    return status_map, absent


def auth_phase(usernames: list[str]) -> dict[str, tuple[str, str]]:
    """
    Check absent names with the authenticated endpoint.

    Returns:
        username -> (status string, error_message)
    """
    token = get_access_token()
    if not token:
        print("[WARN] No auth token; cannot resolve absent names. Run: python get_token.py")
        return {name: ("error", "no auth token") for name in usernames}

    session = requests.Session()
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }

    results: dict[str, tuple[str, str]] = {}
    print(f"[INFO] Auth phase: {len(usernames):,} names at 15s interval")

    for name in tqdm(usernames, unit="name"):
        backoffs = 0
        while True:
            try:
                resp = session.get(AUTH_URL.format(name), headers=headers, timeout=20)
            except requests.RequestException as exc:
                if backoffs >= 3:
                    results[name] = ("error", str(exc))
                    break
                backoffs += 1
                time.sleep(30)
                continue

            if resp.status_code == 429:
                if backoffs >= 3:
                    results[name] = ("rate_limited", "auth API 429")
                    break
                backoffs += 1
                time.sleep(60)
                continue

            if resp.status_code == 401:
                results[name] = ("error", "invalid or expired auth token")
                break

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    status = data.get("status", "").upper()
                except Exception:
                    results[name] = ("error", f"non-JSON 200: {resp.text[:80]}")
                    break

                if status == "AVAILABLE":
                    results[name] = ("verified_available", "")
                elif status == "DUPLICATE":
                    results[name] = ("verified_taken", "")
                elif status == "NOT_ALLOWED":
                    results[name] = ("blocked", "")
                else:
                    results[name] = ("error", f"unknown status: {status}")
                break

            # 404 / 400 often means NOT_ALLOWED or invalid; map conservatively.
            if resp.status_code in (400, 404):
                results[name] = ("blocked", f"HTTP {resp.status_code}")
                break

            results[name] = ("error", f"HTTP {resp.status_code}")
            break

        time.sleep(15)  # 20 requests / 5 minutes

    return results


def save_results(
    db_path: str,
    public_status: dict[str, str],
    auth_results: dict[str, tuple[str, str]],
) -> dict[str, int]:
    """Persist the re-check results into the SQLite database."""
    storage = get_storage(db_path)
    counts: dict[str, int] = {}

    def _save(username: str, status_str: str, error: str = ""):
        status = getattr(CheckStatus, status_str.upper(), CheckStatus.ERROR)
        tier = tier_for_score(rarity_points(username))
        result = CheckResult(
            username=username,
            status=status,
            tier=tier,
            checked_at=datetime.now(),
            verified=status_str.startswith("verified_"),
            error_message=error or None,
            source="mojang-primary" if status in (CheckStatus.TAKEN, CheckStatus.AVAILABLE) else "mojang-auth",
        )
        storage.save_result(result)
        counts[status_str] = counts.get(status_str, 0) + 1

    for name, status in public_status.items():
        if status == "absent":
            # Resolved by auth phase below.
            continue
        _save(name, status)

    for name, (status, error) in auth_results.items():
        _save(name, status, error)

    return counts


def main():
    parser = argparse.ArgumentParser(description="Re-check high-score names against Mojang")
    parser.add_argument("--db", default="data/checked.db", help="Path to checked.db")
    parser.add_argument("--min-score", type=int, default=500, help="Minimum score to re-check")
    parser.add_argument("--public-rps", type=float, default=1.5, help="Public API requests per second")
    args = parser.parse_args()

    usernames = load_usernames(args.db, args.min_score)
    if not usernames:
        print("[INFO] No usernames match the criteria.")
        return 0

    print(f"[INFO] Re-checking {len(usernames):,} names with score >= {args.min_score}")

    public_status, absent = public_phase(usernames, rps=args.public_rps)
    auth_results = auth_phase(absent)
    counts = save_results(args.db, public_status, auth_results)

    print("\n=== Results ===")
    for status, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<20}: {n:,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
