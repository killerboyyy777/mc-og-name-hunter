#!/usr/bin/env python3
"""Find the N most desirable currently-available usernames across every word list.

Strategy: score every unchecked word-list name, sort descending, then walk that
order from the top.  Because the walk is score-ordered, the first names that
survive verification *are* the rarest available ones -- no need to check the
whole corpus.

Two phases per name (same documented rate limits as the rest of the project):

  Phase 1  Public batch lookup via
           ``minecraftservices.com/minecraft/profile/lookup/bulk/byname``,
           10 names/request at 1.5 req/s (Mojang allows 200/2 min).  A name
           present in the response is TAKEN; an absent name is recorded as
           publicly AVAILABLE.
  Phase 2  Absent names are confirmed one-by-one on the authenticated endpoint
           at 20 requests / 5 min, which separates AVAILABLE from
           NOT_ALLOWED (blocked) and DUPLICATE (taken).

The run stops as soon as ``--target`` names are auth-verified available.

Usage:
    python find_rarest_available.py                 # top 20, floor 300
    python find_rarest_available.py --target 20 --floor 0
"""

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from tqdm import tqdm

from src.auth import get_access_token
from src.models import (
    CheckResult, CheckStatus, rarity_points, tier_for_score,
)
from src.storage import get_storage

PUBLIC_URL = "https://api.minecraftservices.com/minecraft/profile/lookup/bulk/byname"
AUTH_URL = "https://api.minecraftservices.com/minecraft/profile/name/{}/available"
USER_AGENT = "mc-og-name-hunter/2.0"

VALID_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")

WORDLIST_DIR = Path("data/word_lists")
DB_PATH = "data/checked.db"
OUT_PATH = Path("data/rarest_available_20.txt")


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------

def load_candidates(db_path: str) -> list[tuple[int, str, list[str]]]:
    """Score every unchecked word-list name; return (score, name, lists) desc."""
    checked: dict[str, str] = {}
    conn = sqlite3.connect(db_path)
    for username, status in conn.execute("SELECT username, status FROM checked"):
        checked[username.lower()] = status
    conn.close()

    seen: dict[str, set[str]] = {}
    files = sorted(glob.glob(str(WORDLIST_DIR / "*.txt")))
    for path in tqdm(files, unit="list", desc="reading"):
        name_of_file = os.path.basename(path)
        try:
            with open(path, encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    word = line.split("\t")[0].strip().lower()
                    if word and VALID_USERNAME.match(word):
                        seen.setdefault(word, set()).add(name_of_file)
        except OSError as exc:
            print(f"  ! {name_of_file}: {exc}")

    def is_done(name: str) -> bool:
        status = checked.get(name)
        return status is not None and status not in ("error", "rate_limited")

    scored: list[tuple[int, str, list[str]]] = []
    for word, lists in tqdm(seen.items(), unit="name", desc="scoring"):
        if is_done(word):
            continue
        scored.append((rarity_points(word), word, sorted(lists)))

    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return scored


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------

def public_screen(session, names: list[str], rps: float) -> dict[str, str]:
    """Batch-screen names. Returns name -> 'taken' | 'absent' | 'error'."""
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    delay = 1.0 / rps if rps > 0 else 0.0
    out: dict[str, str] = {}

    for start in range(0, len(names), 10):
        batch = names[start:start + 10]
        backoffs = 0
        while True:
            try:
                resp = session.post(PUBLIC_URL, json=batch, headers=headers, timeout=20)
            except requests.RequestException:
                if backoffs >= 3:
                    out.update({n: "error" for n in batch})
                    break
                backoffs += 1
                time.sleep(30)
                continue

            limit = resp.headers.get("x-minecraft-rate-limit-result", "")
            if resp.status_code == 429 or limit == "OVER_LIMIT":
                if backoffs >= 5:
                    out.update({n: "rate_limited" for n in batch})
                    break
                backoffs += 1
                time.sleep(60)
                continue

            if resp.status_code != 200:
                out.update({n: "error" for n in batch})
                break

            try:
                found = {item.get("name", "").lower() for item in resp.json()}
            except Exception:
                out.update({n: "error" for n in batch})
                break

            for name in batch:
                out[name] = "taken" if name in found else "absent"
            break

        if delay and start + 10 < len(names):
            time.sleep(delay)

    return out


def auth_check(session, token: str, name: str) -> tuple[str, str]:
    """Confirm one name. Returns (status string, error message)."""
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    backoffs = 0
    while True:
        try:
            resp = session.get(AUTH_URL.format(name), headers=headers, timeout=20)
        except requests.RequestException as exc:
            if backoffs >= 3:
                return "error", str(exc)
            backoffs += 1
            time.sleep(30)
            continue

        if resp.status_code == 429:
            if backoffs >= 3:
                return "rate_limited", "auth API 429"
            backoffs += 1
            time.sleep(120)
            continue

        if resp.status_code == 401:
            return "error", "invalid or expired auth token"

        if resp.status_code == 200:
            try:
                status = resp.json().get("status", "").upper()
            except Exception:
                return "error", f"non-JSON 200: {resp.text[:80]}"
            if status == "AVAILABLE":
                return "verified_available", ""
            if status == "DUPLICATE":
                return "verified_taken", ""
            if status == "NOT_ALLOWED":
                return "blocked", ""
            return "error", f"unknown status: {status}"

        if resp.status_code in (400, 404):
            return "blocked", f"HTTP {resp.status_code}"
        return "error", f"HTTP {resp.status_code}"


def save(storage, name: str, status_str: str, error: str = "", source: str = "") -> None:
    status = getattr(CheckStatus, status_str.upper(), CheckStatus.ERROR)
    result = CheckResult(
        username=name,
        status=status,
        tier=tier_for_score(rarity_points(name)),
        checked_at=datetime.now(),
        verified=status_str.startswith("verified_"),
        error_message=error or None,
        source=source or ("mojang-auth" if status_str.startswith(("verified_", "blocked"))
                          else "mojang-primary"),
    )
    storage.save_result(result)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", type=int, default=20, help="verified available names to find")
    parser.add_argument("--floor", type=int, default=300,
                        help="lowest score worth screening (raised only if the floor is exhausted)")
    parser.add_argument("--public-rps", type=float, default=1.5)
    parser.add_argument("--auth-interval", type=float, default=15.0,
                        help="seconds between auth requests (20/5min = 15s)")
    parser.add_argument("--chunk", type=int, default=1000, help="names screened per batch before auth")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    candidates = load_candidates(args.db)
    print(f"[INFO] {len(candidates):,} unchecked scored names "
          f"(top {candidates[0][0] if candidates else '-'})")

    storage = get_storage(args.db)
    public_session = requests.Session()
    auth_session = requests.Session()

    token: str | None = None
    found: list[tuple[int, str, list[str]]] = []
    auth_done: set[str] = set()
    screened = 0

    def ensure_token() -> bool:
        nonlocal token
        if token is None:
            token = get_access_token()
            if not token:
                print("[WARN] no auth token; run `python get_token.py`")
            return bool(token)
        return True

    def verify_queue(queue: list[tuple[int, str, list[str]]]) -> None:
        nonlocal token
        for score, name, lists in queue:
            if len(found) >= args.target or name in auth_done:
                continue
            if not ensure_token():
                return
            status, error = auth_check(auth_session, token, name)
            auth_done.add(name)
            save(storage, name, status, error)
            if status == "verified_available":
                found.append((score, name, lists))
                print(f"  [AVAILABLE] {name}  {score}  ({len(found)}/{args.target})")
            elif status in ("error", "rate_limited"):
                print(f"  [!] {name}: {status} {error}")
            time.sleep(args.auth_interval)

    queue: list[tuple[int, str, list[str]]] = []
    offset = 0
    while offset < len(candidates) and len(found) < args.target:
        chunk = [c for c in candidates[offset:offset + args.chunk] if c[0] >= args.floor]
        if not chunk:
            print(f"[INFO] floor {args.floor} exhausted at offset {offset:,}; lowering")
            args.floor = 0
            continue
        offset += args.chunk

        names = [c[1] for c in chunk]
        statuses = public_screen(public_session, names, args.public_rps)
        screened += len(names)

        for score, name, lists in chunk:
            status = statuses.get(name, "error")
            if status == "taken":
                save(storage, name, "taken")
            elif status == "absent":
                save(storage, name, "available")
                queue.append((score, name, lists))
            elif status == "rate_limited":
                save(storage, name, "rate_limited", "public API 429")
            else:
                save(storage, name, "error", "public lookup failed")

        print(f"[INFO] screened {screened:,} | queue {len(queue):,} | found {len(found)}/{args.target}")
        verify_queue(queue)
        queue.clear()

    if found:
        lines = ["# Rarest available usernames (auth-verified)", ""]
        for rank, (score, name, lists) in enumerate(found, 1):
            lines.append(f"{rank}\t{name}\t{score}\t{','.join(lists)}")
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n[INFO] wrote {len(found)} names to {args.out}")

    print("\n=== Result ===")
    for rank, (score, name, lists) in enumerate(found, 1):
        print(f"{rank:>3}. {name:<17} {score:>4}  {','.join(lists)[:60]}")
    if len(found) < args.target:
        print(f"[WARN] only {len(found)} of {args.target} found")

    json_path = Path(args.out).with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(
            [{"rank": i, "username": n, "score": s, "lists": l}
             for i, (s, n, l) in enumerate(found, 1)],
            handle, indent=2,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
