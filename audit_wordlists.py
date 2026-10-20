#!/usr/bin/env python3
"""Audit word lists against Mojang's APIs using their documented rate limits.

Documented limits (minecraft.wiki / wiki.vg):
  * Public lookup, per IP: 200 requests / 2 minutes, max 10 names per batch.
  * Name availability, per account: 20 requests / 5 minutes.
  * 429s carry no Retry-After on the auth endpoint (observed), so back off
    the full 5-minute window.

Because the authenticated endpoint is the scarce one, the audit is two-phase:

  Phase 1  Public batch lookup (10 names/request) marks every name that is
           already held by a player as TAKEN. A taken name can never be
           banned, so it never needs an auth check.
  Phase 2  Only names absent from the public API are checked with the
           authenticated endpoint, which resolves them to AVAILABLE or
           NOT_ALLOWED (banned).

In practice ~99% of high-score words are already taken, so phase 2 is small.

Outputs (in ``data/``):
    wordlist_audit.csv       per-word result (used for resume)
    wordlist_banned.txt      words confirmed NOT_ALLOWED
    wordlist_available.txt   available words, rarest first

Examples:
    python audit_wordlists.py --count-only
    python audit_wordlists.py                       # score >= 45
    python audit_wordlists.py --min-points 60
    python audit_wordlists.py --public-rps 1.5 --auth-rps 0.06
    python audit_wordlists.py --skip-public          # auth-check everything
"""

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))

from src.auth import get_access_token
from src.models import rarity_points

VALID_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")

PUBLIC_URL = "https://api.mojang.com/profiles/minecraft"
AUTH_URL = "https://api.minecraftservices.com/minecraft/profile/name/{}/available"

FINAL_STATUSES = {"available", "taken", "banned"}
INTERMEDIATE_STATUSES = {"absent"}

CSV_FIELDS = ["word", "points", "status", "lists", "checked_at", "error"]

USER_AGENT = "mc-og-name-hunter/1.0"


def load_words(list_paths):
    words = {}
    for path in list_paths:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            word = line.split("\t")[0].strip()
            if not word or not VALID_USERNAME.match(word):
                continue
            key = word.lower()
            entry = words.setdefault(key, {"lists": set()})
            entry["lists"].add(path.name)
    for key, entry in words.items():
        entry["points"] = rarity_points(key)
        entry["lists"] = sorted(entry["lists"])
    return words


def load_previous(csv_path):
    rows = {}
    if not csv_path.exists():
        return rows
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") in FINAL_STATUSES | INTERMEDIATE_STATUSES:
                rows[row["word"]] = row
    return rows


def write_csv(csv_path, rows):
    tmp = csv_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for word in sorted(rows):
            writer.writerow(rows[word])
    tmp.replace(csv_path)


def write_outputs(data_dir, rows):
    banned = sorted(w for w, r in rows.items() if r["status"] == "banned")
    available = sorted(
        (r for r in rows.values() if r["status"] == "available"),
        key=lambda r: (-int(r["points"]), len(r["word"]), r["word"]),
    )
    (data_dir / "wordlist_banned.txt").write_text(
        "\n".join(banned) + ("\n" if banned else ""), encoding="utf-8"
    )
    (data_dir / "wordlist_available.txt").write_text(
        "\n".join(f"{r['word']}\t{r['points']}" for r in available)
        + ("\n" if available else ""),
        encoding="utf-8",
    )
    return banned, available


def summarize(rows, source_lists, elapsed, screened, auth_checked):
    counts = {}
    per_list = {
        name: {"eligible": 0, "taken": 0, "banned": 0, "available": 0}
        for name in source_lists
    }

    for row in rows.values():
        status = row["status"]
        counts[status] = counts.get(status, 0) + 1
        for name in row["lists"].split(";"):
            if name not in per_list:
                continue
            per_list[name]["eligible"] += 1
            if status in per_list[name]:
                per_list[name][status] += 1

    print("\n=== SUMMARY ===")
    print(f"Public screens   : {screened:,}")
    print(f"Auth checks      : {auth_checked:,}")
    print(f"Results on disk  : {len(rows):,}")
    for status in ("available", "banned", "taken", "absent",
                   "rate_limited", "error"):
        if status in counts:
            print(f"  {status:<13}: {counts[status]:,}")
    if elapsed > 0:
        print(f"Elapsed          : {elapsed/60:.1f} min")

    print("\nPer word list:")
    header = f"{'list':<34}{'eligible':>10}{'taken':>9}{'banned':>9}{'free':>9}"
    print(header)
    print("-" * len(header))
    for name in sorted(per_list):
        s = per_list[name]
        if not s["eligible"]:
            continue
        print(f"{name:<34}{s['eligible']:>10,}{s['taken']:>9,}"
              f"{s['banned']:>9,}{s['available']:>9,}")


def mark(rows, eligible, word, status, error=""):
    rows[word] = {
        "word": word,
        "points": eligible[word]["points"],
        "status": status,
        "lists": ";".join(eligible[word]["lists"]),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "error": error,
    }


def public_screen(rows, pending, eligible, csv_path, rps, cooldown, session):
    if not pending:
        return 0

    url = PUBLIC_URL
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    delay = 1.0 / rps if rps > 0 else 0.0
    screened = 0
    written = 0

    with tqdm(total=len(pending), unit="name", smoothing=0.05) as bar:
        for start in range(0, len(pending), 10):
            batch = pending[start:start + 10]
            backoffs = 0
            while True:
                try:
                    resp = session.post(url, json=batch, headers=headers, timeout=20)
                except requests.RequestException as exc:
                    if backoffs >= 5:
                        for word in batch:
                            mark(rows, eligible, word, "error", str(exc))
                        break
                    backoffs += 1
                    time.sleep(cooldown)
                    continue

                limit = resp.headers.get("x-minecraft-rate-limit-result", "")
                if resp.status_code == 429 or limit == "OVER_LIMIT":
                    if backoffs >= 5:
                        for word in batch:
                            mark(rows, eligible, word, "rate_limited",
                                 "public API 429")
                        break
                    backoffs += 1
                    time.sleep(cooldown)
                    continue
                if resp.status_code != 200:
                    for word in batch:
                        mark(rows, eligible, word, "error",
                             f"public HTTP {resp.status_code}")
                    break

                found = {item.get("name", "").lower() for item in resp.json()}
                for word in batch:
                    mark(rows, eligible, word,
                         "taken" if word in found else "absent")
                screened += len(batch)
                break

            bar.update(len(batch))
            written += len(batch)
            if written >= 500:
                write_csv(csv_path, rows)
                written = 0
            if delay and start + 10 < len(pending):
                time.sleep(delay)

    write_csv(csv_path, rows)
    return screened


def auth_check(rows, pending, eligible, csv_path, rps, cooldown,
               max_backoffs, session):
    if not pending:
        return 0

    token = get_access_token()
    if not token:
        print("\nNo access token. Run: python get_token.py")
        return 0

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    delay = 1.0 / rps if rps > 0 else 0.0
    checked = 0
    written = 0

    with tqdm(total=len(pending), unit="name", smoothing=0.05) as bar:
        for index, word in enumerate(pending):
            backoffs = 0
            while True:
                try:
                    resp = session.get(
                        AUTH_URL.format(word), headers=headers, timeout=20
                    )
                except requests.RequestException as exc:
                    if backoffs >= max_backoffs:
                        mark(rows, eligible, word, "error", str(exc))
                        break
                    backoffs += 1
                    time.sleep(cooldown)
                    continue

                if resp.status_code == 200:
                    status = resp.json().get("status", "").upper()
                    mapped = {
                        "AVAILABLE": "available",
                        "DUPLICATE": "taken",
                        "NOT_ALLOWED": "banned",
                    }.get(status, "error")
                    mark(rows, eligible, word, mapped,
                         "" if mapped != "error" else f"unknown status {status}")
                    checked += 1
                    break

                if resp.status_code == 429:
                    if backoffs >= max_backoffs:
                        mark(rows, eligible, word, "rate_limited",
                             "auth API 429")
                        break
                    backoffs += 1
                    time.sleep(cooldown)
                    continue

                if resp.status_code == 401:
                    print("\nAuth token rejected. Run: python get_token.py")
                    return checked

                mark(rows, eligible, word, "error",
                     f"auth HTTP {resp.status_code}")
                break

            bar.update(1)
            written += 1
            if written >= 25:
                write_csv(csv_path, rows)
                written = 0
            if delay and index + 1 < len(pending):
                time.sleep(delay)

    write_csv(csv_path, rows)
    return checked


def main():
    parser = argparse.ArgumentParser(
        description="Audit word lists for banned/taken/available names using "
                    "the documented Mojang rate limits.",
    )
    parser.add_argument("--wordlist-dir", default="data/word_lists")
    parser.add_argument("--lists", nargs="*", default=None,
                        help="Only these filenames (default: all *.txt)")
    parser.add_argument("--min-points", type=int, default=45,
                        help="Minimum rarity score to check (default: 45)")
    parser.add_argument("--public-rps", type=float, default=1.5,
                        help="Public batch requests/s, 10 names each "
                             "(documented ceiling 200/2min = 1.67; default 1.5)")
    parser.add_argument("--auth-rps", type=float, default=0.06,
                        help="Auth checks/s (documented 20/5min = 0.067; "
                             "default 0.06, i.e. one every ~17s)")
    parser.add_argument("--public-cooldown", type=float, default=90.0,
                        help="Seconds to pause on a public 429 (default 90)")
    parser.add_argument("--auth-cooldown", type=float, default=300.0,
                        help="Seconds to pause on an auth 429 (default 300)")
    parser.add_argument("--max-backoffs", type=int, default=3,
                        help="Retries per name before marking it an error")
    parser.add_argument("--limit", type=int, default=0,
                        help="Check at most N words (0 = all)")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--fresh", action="store_true",
                        help="Ignore previous results and recheck everything")
    parser.add_argument("--skip-public", action="store_true",
                        help="Skip phase 1 and auth-check every word (slow)")
    parser.add_argument("--count-only", action="store_true",
                        help="Only report volumes and ETAs")
    args = parser.parse_args()

    data_dir = Path(args.output_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / "wordlist_audit.csv"

    list_paths = sorted(Path(args.wordlist_dir).glob("*.txt"))
    if args.lists:
        wanted = set(args.lists)
        list_paths = [p for p in list_paths if p.name in wanted]
    if not list_paths:
        print("No word lists found.")
        return 1

    print(f"Loading {len(list_paths)} word lists from {args.wordlist_dir} ...")
    words = load_words(list_paths)
    eligible = {
        w: meta for w, meta in words.items() if meta["points"] >= args.min_points
    }
    if args.limit:
        top = sorted(eligible, key=lambda w: (-eligible[w]["points"], len(w), w))
        eligible = {w: eligible[w] for w in top[: args.limit]}

    previous = {} if args.fresh else load_previous(csv_path)

    if args.skip_public:
        public_pending = []
        auth_pending = [w for w in eligible if w not in previous]
    else:
        public_pending = [
            w for w in eligible
            if w not in previous or previous[w]["status"] in {"error", "rate_limited"}
        ]
        auth_pending = [w for w in eligible
                        if previous.get(w, {}).get("status") == "absent"]
        public_pending = [w for w in public_pending
                          if previous.get(w, {}).get("status") != "absent"]

    public_pending.sort(key=lambda w: (-eligible[w]["points"], len(w), w))
    auth_pending.sort(key=lambda w: (-eligible[w]["points"], len(w), w))

    public_eta = (len(public_pending) / 10) / args.public_rps if args.public_rps else 0
    auth_eta = len(auth_pending) / args.auth_rps if args.auth_rps else 0

    print(f"Unique valid words : {len(words):,}")
    print(f"At/above {args.min_points:<3} points: {len(eligible):,}")
    print(f"Phase 1 (public)   : {len(public_pending):,} names "
          f"({len(public_pending)//10+1:,} requests, ~{public_eta/60:.1f} min)")
    print(f"Phase 2 (auth)     : {len(auth_pending):,} names "
          f"(~{auth_eta/60:.1f} min)")
    print(f"Resumed results    : {len(previous):,}")
    print(f"Output             : {csv_path}")

    if args.count_only:
        return 0

    session = requests.Session()
    rows = dict(previous)
    started = time.time()
    screened = auth_checked = 0

    try:
        if public_pending:
            print("\nPhase 1: public batch screening ...")
            screened = public_screen(
                rows, public_pending, eligible, csv_path,
                args.public_rps, args.public_cooldown, session,
            )
            # Newly resolved absent names join phase 2.
            auth_pending = [w for w in eligible
                            if rows.get(w, {}).get("status") == "absent"]

        if auth_pending:
            print("\nPhase 2: authenticated availability checks ...")
            auth_checked = auth_check(
                rows, auth_pending, eligible, csv_path,
                args.auth_rps, args.auth_cooldown, args.max_backoffs, session,
            )
    except KeyboardInterrupt:
        print("\nInterrupted - progress saved; rerun to resume.")
        write_csv(csv_path, rows)
        return 1

    write_csv(csv_path, rows)
    banned, available = write_outputs(data_dir, rows)
    summarize(rows, [p.name for p in list_paths],
              time.time() - started, screened, auth_checked)

    print(f"\nBanned words -> {data_dir / 'wordlist_banned.txt'} ({len(banned):,})")
    print(f"Free names   -> {data_dir / 'wordlist_available.txt'} ({len(available):,})")
    print(f"Full results -> {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())