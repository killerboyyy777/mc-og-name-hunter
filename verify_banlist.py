#!/usr/bin/env python3
"""
Verify the banlist against Mojang's API - batched version.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.checkers import AsyncPublicChecker, AsyncAuthChecker, AsyncCheckerManager
from src.rate_limiter import RateLimiter
from src.models import UsernameCandidate, RarityTier
from src.auth import get_access_token
from generate_custom_wordlists import _BANNED_WORDS


async def verify_banlist():
    access_token = get_access_token()

    public_limiter = RateLimiter(requests_per_second=1.5, burst=10)
    # Auth endpoint allows ~20 requests / 5 min per account; pace at 0.06 rps
    # and wait the full cooldown on a 429 instead of hammering it.
    auth_limiter = RateLimiter(
        requests_per_second=0.06, burst=10, backoff_base=300, max_backoff=300
    )

    public_checker = AsyncPublicChecker(rate_limiter=public_limiter)
    auth_checker = None
    if access_token:
        auth_checker = AsyncAuthChecker(access_token, rate_limiter=auth_limiter)
        print(f"[INFO] Auth verification enabled")
    else:
        print(f"[WARN] No access token - auth verification disabled")

    manager = AsyncCheckerManager(public_checker, auth_checker, verify_on_hit=bool(access_token))

    banned_words = sorted(_BANNED_WORDS)
    print(f"[INFO] Checking {len(banned_words)} banned words in batches...")

    to_remove = []
    to_keep = []
    errors = []

    BATCH_SIZE = 10
    for batch_idx in range(0, len(banned_words), BATCH_SIZE):
        batch = banned_words[batch_idx:batch_idx + BATCH_SIZE]
        print(f"  Batch {batch_idx//BATCH_SIZE + 1}/{(len(banned_words) + BATCH_SIZE - 1)//BATCH_SIZE}: {batch}")

        candidates = [UsernameCandidate(username=w, tier=RarityTier.SEMI_OG) for w in batch]
        try:
            results = await manager.check_batch(candidates)
            for word, result in zip(batch, results):
                status = result.status.value
                if status in ("taken", "available", "verified_available", "verified_taken"):
                    to_remove.append(word)
                    print(f"    REMOVE: {word} ({status})")
                elif status == "blocked":
                    to_keep.append(word)
                    print(f"    KEEP: {word} (blocked)")
                else:
                    errors.append((word, status))
                    print(f"    ERROR: {word} -> {status}")
        except Exception as e:
            errors.extend((w, str(e)) for w in batch)
            print(f"    BATCH ERROR: {e}")

    await public_checker.close()
    if auth_checker:
        await auth_checker.close()

    print(f"\n=== SUMMARY ===")
    print(f"Total checked: {len(banned_words)}")
    print(f"To REMOVE (valid/available): {len(to_remove)}")
    print(f"To KEEP (blocked): {len(to_keep)}")
    print(f"Errors: {len(errors)}")

    if to_remove:
        print(f"\nWords to REMOVE from banlist:")
        for w in sorted(to_remove):
            print(f"  {w}")

    if to_keep:
        print(f"\nWords to KEEP (confirmed blocked):")
        for w in sorted(to_keep):
            print(f"  {w}")

    if errors:
        print(f"\nErrors:")
        for w, e in errors:
            print(f"  {w}: {e}")

    if to_remove:
        cleaned = {w for w in _BANNED_WORDS if w not in to_remove}
        print(f"\nCleaned banlist size: {len(cleaned)} (was {len(_BANNED_WORDS)})")

        # Generate the updated _init_banned_words function
        print(f"\n--- Updated _init_banned_words() ---")
        print("banned = [")
        for w in sorted(cleaned):
            print(f'    "{w}",')
        print("    ]")

    return to_remove, to_keep, errors


if __name__ == "__main__":
    asyncio.run(verify_banlist())