"""Command-line interface for the Minecraft username sniper."""

import argparse
import asyncio
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from tqdm import tqdm

from src.models import (
    SnipeConfig, RarityTier, CheckStatus, CheckResult, UsernameCandidate,
    rarity_points, rarity_label, is_banned,
)
from src.storage import get_storage
from src.rate_limiter import get_rate_limiter
from src.checkers import (
    PublicAPIChecker, AuthAPIChecker, CheckerManager,
    AsyncPublicChecker, AsyncAuthChecker, AsyncCheckerManager,
    CANONICAL_PUBLIC_ENDPOINT,
)
from src.generators import create_generator
from src.config import load_config, find_config_path, get_config_value
from src.display import CleanDisplay, SimpleLineDisplay
from src.auth import get_access_token


# Colors for output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    GRAY = "\033[90m"
    GOLD = "\033[33m"


def colorize(text: str, color: str) -> str:
    """Add color to text if stdout supports it."""
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.RESET}"
    return text


def print_hit(username: str, tier: RarityTier, hit_num: int, points: int = 0):
    """Print a hit with colors and community rarity points."""
    tier_colors = {
        RarityTier.TOP: Colors.MAGENTA,
        RarityTier.OG: Colors.BLUE,
        RarityTier.SEMI_OG: Colors.CYAN,
    }
    tier_color = tier_colors.get(tier, Colors.GREEN)
    score_str = f" ({points} pts)" if points > 0 else ""
    print(f"\n{colorize(f'[HIT #{hit_num}]', Colors.GREEN + Colors.BOLD)} "
          f"{colorize(username, tier_color + Colors.BOLD)} "
          f"({colorize(tier.value.upper(), tier_color)})"
          f"{colorize(score_str, Colors.GRAY)} "
          f"{colorize('- VERIFIED AVAILABLE!', Colors.GREEN)}")


def print_taken(username: str):
    """Print taken username (quiet)."""
    if sys.stdout.isatty():
        sys.stdout.write(f"\r{colorize(f'  taken: {username}', Colors.GRAY)}")
        sys.stdout.flush()


def print_error(username: str, error: str):
    """Print error with colors."""
    print(f"\n{colorize('[ERROR]', Colors.RED)} {username}: {error}")


def print_rate_limited():
    """Print rate limited warning."""
    print(f"\n{colorize('[RATE LIMITED]', Colors.YELLOW)} Backing off...")


class GracefulShutdown:
    """Handle graceful shutdown on SIGINT/SIGTERM."""
    
    def __init__(self):
        self.shutdown_requested = False
        self.shutdown_count = 0
        self._original_handlers = {}
    
    def __enter__(self):
        self._original_handlers[signal.SIGINT] = signal.signal(signal.SIGINT, self._handle_signal)
        if hasattr(signal, 'SIGTERM'):
            self._original_handlers[signal.SIGTERM] = signal.signal(signal.SIGTERM, self._handle_signal)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
    
    def _handle_signal(self, signum, frame):
        self.shutdown_count += 1
        if self.shutdown_count == 1:
            print(f"\n{colorize('[SHUTDOWN]', Colors.YELLOW)} Requested... finishing current batch.")
            self.shutdown_requested = True
        elif self.shutdown_count == 2:
            print(f"\n{colorize('[FORCE SHUTDOWN]', Colors.RED)} Immediate exit!")
            # A second SIGINT means "stop now". Raising SystemExit here would
            # unwind through the running asyncio task (e.g. out of a blocking
            # rate-limiter sleep) and surface as "Task exception was never
            # retrieved". Terminate the process immediately instead.
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            os._exit(1)


def parse_tiers(tier_str: str) -> List[RarityTier]:
    """Parse comma-separated tier string into list of RarityTier."""
    tier_map = {
        "top": RarityTier.TOP,
        "og": RarityTier.OG,
        "semi_og": RarityTier.SEMI_OG,
        "semi": RarityTier.SEMI_OG,
    }
    tiers = []
    for part in tier_str.split(","):
        part = part.strip().lower()
        if part in tier_map:
            tiers.append(tier_map[part])
        else:
            print(f"Warning: Unknown tier '{part}', skipping")
    return tiers or [RarityTier.TOP, RarityTier.OG, RarityTier.SEMI_OG]


def parse_wordlist(spec: str) -> tuple[str, RarityTier, str]:
    """Parse a --wordlist spec of the form PATH[:TIER].

    Returns (filename, tier, source_label). Filenames are resolved relative
    to data/word_lists/ unless an absolute path or subdirectory is given.
    Defaults to SEMI_OG tier when no tier suffix is provided.
    """
    from pathlib import Path

    tier_map = {
        "top": RarityTier.TOP,
        "og": RarityTier.OG,
        "semi_og": RarityTier.SEMI_OG,
        "semi": RarityTier.SEMI_OG,
    }
    # Split on the last colon so Windows drive letters (C:/...) survive.
    # The suffix is only a tier if it names a known tier; otherwise the whole
    # spec is the path (e.g. a bare "C:/lists/custom.txt").
    path_part, sep, maybe_tier = spec.rpartition(":")
    if sep and maybe_tier.strip().lower() in tier_map:
        tier = tier_map[maybe_tier.strip().lower()]
    else:
        path_part, tier = spec, RarityTier.SEMI_OG
    path_part = path_part.strip()
    if not path_part:
        raise ValueError(f"Empty --wordlist path in spec: {spec!r}")

    # Resolve bare filenames against the bundled word list directory
    candidate = Path(path_part)
    if not candidate.is_absolute() and len(candidate.parts) == 1:
        filename = path_part
    else:
        filename = str(candidate)

    source_label = Path(filename).stem
    return filename, tier, source_label


async def run_snipe_async(
    config: SnipeConfig,
    use_tui: bool = False,
    extra_lists: Optional[list[tuple[str, RarityTier, str]]] = None,
    settings: Optional[dict] = None,
    batch_size: int = 50,
    concurrency: int = 10,
) -> int:
    """Run the one-shot snipe operation (async).

    ``settings`` is the loaded config dict; CLI flags have already been folded
    into ``config``/``batch_size``/``concurrency``, so it is only consulted for
    values that have no dedicated flag (rate limits, name length bounds).
    """
    settings = settings or {}
    shutdown = GracefulShutdown()
    # Install the SIGINT/SIGTERM handler. Must happen *inside* the coroutine
    # (after asyncio.run's Runner installs its own handler) so that our
    # graceful handler takes precedence over asyncio's default, which would
    # otherwise raise KeyboardInterrupt and cancel the task mid-batch.
    shutdown.__enter__()

    # Initialize components
    storage = get_storage()
    rate_limiter = get_rate_limiter(
        requests_per_second=get_config_value(settings, "rate_limit.requests_per_second", 1.5),
        burst=get_config_value(settings, "rate_limit.burst", 10),
        backoff_base=get_config_value(settings, "rate_limit.backoff_base_seconds", 2.0),
    )
    
    # Create async checkers
    public_checker = AsyncPublicChecker(
        rate_limiter=rate_limiter,
        max_concurrent=concurrency,
        max_retries=3,
    )
    
    auth_checker = None
    if config.verify_auth:
        access_token = get_access_token()
        if access_token:
            auth_checker = AsyncAuthChecker(
                access_token,
                rate_limiter=rate_limiter,
                max_concurrent=5,
            )
        else:
            print(f"{colorize('[WARN]', Colors.YELLOW)} No access token found, auth verification disabled")
            config.verify_auth = False
    
    checker = AsyncCheckerManager(
        public_checker,
        auth_checker,
        verify_on_hit=config.verify_auth,
        verify_all_available=getattr(config, 'verify_all', False),
    )
    
    generator = create_generator(config.tiers, {
        "min_length": get_config_value(settings, "generation.min_length", 3),
        "max_length": get_config_value(settings, "generation.max_length", 16),
        "min_points": config.min_points,
    }, storage, extra_lists=extra_lists)
    
    total_to_check = min(config.max_candidates, generator.total_candidates)
    
    # Stats
    checked = 0
    hits = 0
    taken = 0
    errors = 0
    rate_limited = 0
    
    # Track hits with tier info for rarity ranking
    hits_detail = []  # List of (username, tier, score, timestamp)
    
    # Choose display mode
    if use_tui:
        display = CleanDisplay(total_to_check, config.target_hits, config.tiers, force_tui=True)
        display.__enter__()
    else:
        display = SimpleLineDisplay(total_to_check, config.target_hits, config.tiers)
        display.__enter__()
    
    batch_candidates = []
    
    async def process_batch(candidates: List[UsernameCandidate]) -> List:
        """Process a batch of candidates."""
        nonlocal checked, hits, taken, errors, rate_limited
        
        results = await checker.check_batch(candidates)
        
        for candidate, result in zip(candidates, results):
            storage.save_result(result)
            
            checked += 1
            display.update_checked(checked)
            
            if result.status == CheckStatus.TAKEN:
                taken += 1
                display.update_stats(taken=taken)
            elif result.status == CheckStatus.AVAILABLE:
                # Only canonical public AVAILABLE results count as hits.
                # Third-party hints are confirmed by canonical Mojang inside
                # the checker before they can reach this branch.
                # Belt-and-braces: banlist-filtered names should never reach
                # here (pre-filtered before the API call), but never count
                # or display a banned name as a hit if one slips through.
                if result.source == "mojang-primary" and not is_banned(result.username):
                    hits += 1
                    points = rarity_points(result.username)
                    hits_detail.append((result.username, result.tier, points, datetime.now()))
                    display.add_hit(result.username, result.tier, points)
            elif result.status == CheckStatus.VERIFIED_AVAILABLE:
                if is_banned(result.username):
                    taken += 1
                    display.update_stats(taken=taken)
                else:
                    hits += 1
                    points = rarity_points(result.username)
                    hits_detail.append((result.username, result.tier, points, datetime.now()))
                    display.add_hit(result.username, result.tier, points)
            elif result.status == CheckStatus.VERIFIED_TAKEN:
                taken += 1
                display.update_stats(taken=taken)
            elif result.status == CheckStatus.BLOCKED:
                errors += 1
                display.update_stats(errors=errors)
            elif result.status == CheckStatus.INVALID:
                errors += 1
                display.update_stats(errors=errors)
            elif result.status == CheckStatus.RATE_LIMITED:
                rate_limited += 1
                display.update_stats(rate_limited=rate_limited)
            elif result.status == CheckStatus.ERROR:
                errors += 1
                display.update_stats(errors=errors)
        
        return results
    
    try:
        for candidate in generator.generate(config.max_candidates):
            if shutdown.shutdown_requested:
                display.finish(f"\n{colorize('[SHUTDOWN]', Colors.YELLOW)} Stopping after current batch...")
                break

            # Banlist pre-filter: never waste an API call on a banned name.
            # Persist as locally-taken so future runs skip it in pre-filtering.
            if is_banned(candidate.username):
                storage.save_result(CheckResult(
                    username=candidate.username,
                    status=CheckStatus.TAKEN,
                    tier=candidate.tier,
                    checked_at=datetime.now(),
                    source="local-banlist",
                ))
                checked += 1
                taken += 1
                display.update_checked(checked)
                display.update_stats(taken=taken)
                continue

            batch_candidates.append(candidate)
            
            if len(batch_candidates) >= batch_size:
                await process_batch(batch_candidates)
                batch_candidates = []
                
                if hits >= config.target_hits:
                    display.finish(f"\n{colorize('[DONE]', Colors.GREEN)} Target hits ({config.target_hits}) reached!")
                    break
        
        # Process remaining batch
        if batch_candidates and not shutdown.shutdown_requested:
            await process_batch(batch_candidates)
        
        if generator.exhausted and not shutdown.shutdown_requested:
            display.finish(f"\n{colorize('[DONE]', Colors.BLUE)} All wordlists exhausted.")
    
    except (asyncio.CancelledError, KeyboardInterrupt):
        display.finish(f"\n{colorize('[SHUTDOWN]', Colors.YELLOW)} Interrupted.")
    finally:
        try:
            await checker.close()
        except (asyncio.CancelledError, KeyboardInterrupt, Exception):
            pass
        display.__exit__(None, None, None)
        shutdown.__exit__(None, None, None)
    
    # Export trusted available names: auth-verified hits plus canonical
    # Mojang public AVAILABLE decisions.
    exported = storage.export_available(config.output_file, trusted_only=True)
    if exported > 0:
        print(f"\nExported {colorize(str(exported), Colors.GREEN)} trusted available names to {config.output_file}")
    
    # Display top 10 available names
    hits = storage.get_available(verified_only=True, trusted_only=True)
    if hits:
        print(f"\n{colorize('Top 10 Available:', Colors.BOLD + Colors.CYAN)}")
        print(f"{'Rank':>4}  {'Username':<16}  {'Points':>5}  {'Tier':<10}  {'Label'}")
        print("-" * 60)
        shown = 0
        for hit in hits:
            if is_banned(hit.username):
                continue
            shown += 1
            pts = rarity_points(hit.username)
            label = rarity_label(pts, hit.username)
            tier_color = {
                'top': Colors.MAGENTA,
                'og': Colors.BLUE,
                'semi_og': Colors.CYAN,
            }.get(hit.tier.value, Colors.GREEN)
            tier_str = colorize(hit.tier.value.upper(), tier_color)
            print(f"{shown:>4}  {colorize(hit.username, Colors.BOLD):<16}  {pts:>5}  {tier_str:<10}  {label}")
            if shown >= 10:
                break
    
    return 0 if exported > 0 else 1


async def run_check_wordlist_async(
    input_file: str,
    output_file: str,
    verify_auth: bool = True,
    batch_size: int = 50,
    concurrency: int = 10,
) -> int:
    """Check usernames from a wordlist file (async)."""
    shutdown = GracefulShutdown()
    shutdown.__enter__()
    
    storage = get_storage()
    rate_limiter = get_rate_limiter()
    
    public_checker = AsyncPublicChecker(rate_limiter=rate_limiter, max_concurrent=concurrency)
    
    auth_checker = None
    if verify_auth:
        access_token = get_access_token()
        if access_token:
            auth_checker = AsyncAuthChecker(access_token, rate_limiter=rate_limiter)
        else:
            print(f"{colorize('[WARN]', Colors.YELLOW)} No access token found, auth verification disabled")
            verify_auth = False
    
    checker = AsyncCheckerManager(public_checker, auth_checker, verify_on_hit=verify_auth)
    
    # Read input file
    with open(input_file) as f:
        usernames = [line.strip() for line in f if line.strip()]
    
    print(f"{colorize('[INFO]', Colors.BLUE)} Checking {len(usernames)} usernames from {input_file}")
    
    # Filter already checked
    new_usernames = [u for u in usernames if not storage.is_checked(u)]
    skipped = len(usernames) - len(new_usernames)
    if skipped:
        print(f"{colorize('[INFO]', Colors.BLUE)} Skipped {skipped} already checked")
    
    hits = 0
    checked = 0
    errors = 0
    rate_limited = 0
    
    try:
        with tqdm(total=len(new_usernames), desc="Checking", unit="names") as pbar:
            for i in range(0, len(new_usernames), batch_size):
                if shutdown.shutdown_requested:
                    break
                
                batch = new_usernames[i:i+batch_size]
                candidates = [UsernameCandidate(username=u, tier=RarityTier.SEMI_OG) for u in batch]
                
                results = await checker.check_batch(candidates)
                
                for u, result in zip(batch, results):
                    storage.save_result(result)
                    checked += 1
                    pbar.update(1)

                    if is_banned(u):
                        continue

                    if result.status == CheckStatus.VERIFIED_AVAILABLE:
                        hits += 1
                        print_hit(u, RarityTier.SEMI_OG, hits, rarity_points(u))
                    elif result.status == CheckStatus.AVAILABLE and result.source == "mojang-primary":
                        hits += 1
                        print_hit(u, RarityTier.SEMI_OG, hits, rarity_points(u))
                    elif result.status == CheckStatus.ERROR:
                        errors += 1
                        if result.error_message:
                            print_error(u, result.error_message)
                    elif result.status == CheckStatus.INVALID:
                        errors += 1
                        if result.error_message:
                            print_error(u, result.error_message)
                    elif result.status == CheckStatus.RATE_LIMITED:
                        rate_limited += 1
                    
                    pbar.set_postfix({"hits": hits, "errors": errors})
    
    except (asyncio.CancelledError, KeyboardInterrupt):
        print(f"\n{colorize('[SHUTDOWN]', Colors.YELLOW)} Interrupted.")
    finally:
        try:
            await checker.close()
        except (asyncio.CancelledError, KeyboardInterrupt, Exception):
            pass
        shutdown.__exit__(None, None, None)
    
    exported = storage.export_available(output_file, trusted_only=True)
    if exported > 0:
        print(f"Exported {exported} trusted available names to {output_file}")
    
    # Display top 10 available names
    hits = storage.get_available(verified_only=True, trusted_only=True)
    if hits:
        print(f"\n{colorize('Top 10 Available:', Colors.BOLD + Colors.CYAN)}")
        print(f"{'Rank':>4}  {'Username':<16}  {'Points':>5}  {'Tier':<10}  {'Label'}")
        print("-" * 60)
        shown = 0
        for hit in hits:
            if is_banned(hit.username):
                continue
            shown += 1
            pts = rarity_points(hit.username)
            label = rarity_label(pts, hit.username)
            tier_color = {
                'top': Colors.MAGENTA,
                'og': Colors.BLUE,
                'semi_og': Colors.CYAN,
            }.get(hit.tier.value, Colors.GREEN)
            tier_str = colorize(hit.tier.value.upper(), tier_color)
            print(f"{shown:>4}  {colorize(hit.username, Colors.BOLD):<16}  {pts:>5}  {tier_str:<10}  {label}")
            if shown >= 10:
                break
    
    return 0 if exported > 0 else 1


async def run_validate_async(
    max_candidates: Optional[int] = 1000,
    batch_size: int = 20,
    concurrency: int = 5,
    output_file: str = "data/available.txt",
) -> int:
    """Revalidate suspect public AVAILABLE rows against canonical Mojang only."""
    shutdown = GracefulShutdown()
    storage = get_storage()
    rate_limiter = get_rate_limiter()

    rows = storage.get_unvalidated_available(limit=max_candidates)
    if not rows:
        exported = storage.export_available(output_file, trusted_only=True)
        print("No unvalidated public AVAILABLE rows remain.")
        print(f"Trusted available names: {exported} -> {output_file}")
        return 0

    shutdown.__enter__()
    candidates = [UsernameCandidate(username=u, tier=t) for u, t in rows]
    tiers = sorted({t for _, t in rows}, key=lambda x: x.sort_order)

    public_checker = AsyncPublicChecker(
        endpoints=[CANONICAL_PUBLIC_ENDPOINT],
        rate_limiter=rate_limiter,
        max_concurrent=concurrency,
        max_retries=5,
    )
    checker = AsyncCheckerManager(public_checker, None, verify_on_hit=False)
    display = SimpleLineDisplay(len(candidates), len(candidates), tiers)
    display.__enter__()

    confirmed = 0
    corrected_taken = 0
    errors = 0
    checked = 0

    try:
        for i in range(0, len(candidates), batch_size):
            if shutdown.shutdown_requested:
                break
            batch = candidates[i:i + batch_size]
            results = await checker.check_batch(batch)
            for candidate, result in zip(batch, results):
                storage.save_result(result)
                checked += 1
                display.update_checked(checked)
                if result.status == CheckStatus.TAKEN:
                    corrected_taken += 1
                    display.update_stats(taken=corrected_taken)
                elif result.status == CheckStatus.AVAILABLE and result.source == "mojang-primary":
                    if is_banned(result.username):
                        corrected_taken += 1
                        display.update_stats(taken=corrected_taken)
                    else:
                        confirmed += 1
                        display.add_hit(result.username, result.tier, rarity_points(result.username))
                elif result.status == CheckStatus.ERROR:
                    errors += 1
                    display.update_stats(errors=errors)
                elif result.status == CheckStatus.INVALID:
                    errors += 1
                    display.update_stats(errors=errors)
        display.finish("Validation batch complete.")
    except (asyncio.CancelledError, KeyboardInterrupt):
        display.finish("Validation interrupted.")
    finally:
        try:
            await checker.close()
        except (asyncio.CancelledError, KeyboardInterrupt, Exception):
            pass
        display.__exit__(None, None, None)
        shutdown.__exit__(None, None, None)

    exported = storage.export_available(output_file, trusted_only=True)
    print(f"Validated: {checked} | Confirmed available: {confirmed} | Corrected taken: {corrected_taken} | Errors: {errors}")
    print(f"Exported {exported} trusted available names to {output_file}")
    
    # Display top 10 available names
    hits = storage.get_available(verified_only=True, trusted_only=True)
    if hits:
        print(f"\n{colorize('Top 10 Available:', Colors.BOLD + Colors.CYAN)}")
        print(f"{'Rank':>4}  {'Username':<16}  {'Points':>5}  {'Tier':<10}  {'Label'}")
        print("-" * 60)
        shown = 0
        for hit in hits:
            if is_banned(hit.username):
                continue
            shown += 1
            pts = rarity_points(hit.username)
            label = rarity_label(pts, hit.username)
            tier_color = {
                'top': Colors.MAGENTA,
                'og': Colors.BLUE,
                'semi_og': Colors.CYAN,
            }.get(hit.tier.value, Colors.GREEN)
            tier_str = colorize(hit.tier.value.upper(), tier_color)
            print(f"{shown:>4}  {colorize(hit.username, Colors.BOLD):<16}  {pts:>5}  {tier_str:<10}  {label}")
            if shown >= 10:
                break
    
    return 0


def run_snipe(
    config: SnipeConfig,
    use_tui: bool = False,
    extra_lists: Optional[list[tuple[str, RarityTier, str]]] = None,
    settings: Optional[dict] = None,
    batch_size: int = 50,
    concurrency: int = 10,
) -> int:
    """Sync entry point for snipe."""
    return asyncio.run(run_snipe_async(
        config,
        use_tui=use_tui,
        extra_lists=extra_lists,
        settings=settings,
        batch_size=batch_size,
        concurrency=concurrency,
    ))


def run_validate(
    max_candidates: Optional[int] = 1000,
    batch_size: int = 20,
    concurrency: int = 5,
    output_file: str = "data/available.txt",
) -> int:
    """Sync entry point for validate."""
    return asyncio.run(
        run_validate_async(
            max_candidates=max_candidates,
            batch_size=batch_size,
            concurrency=concurrency,
            output_file=output_file,
        )
    )


def run_check_wordlist(
    input_file: str,
    output_file: str,
    verify_auth: bool = True,
    batch_size: int = 50,
    concurrency: int = 10,
) -> int:
    """Sync entry point for check."""
    return asyncio.run(run_check_wordlist_async(
        input_file, output_file, verify_auth, batch_size=batch_size, concurrency=concurrency
    ))


def run_rank(usernames: list) -> int:
    """Rate usernames with the community rarity model (no API calls)."""
    from src.models import rarity_label, rarity_points

    # Sort rarest first, matching export/TUI ordering.
    ranked = sorted(
        usernames, key=lambda u: (-rarity_points(u), len(u), u.lower())
    )
    for i, username in enumerate(ranked, 1):
        points = rarity_points(username)
        label = rarity_label(points, username)
        color = (
            Colors.MAGENTA if points >= 60
            else Colors.BLUE if points >= 40
            else Colors.CYAN if points >= 20
            else Colors.GREEN if points >= 3
            else Colors.GRAY
        )
        print(f"  {colorize(f'#{i}', Colors.BOLD + Colors.GOLD)}  "
              f"{colorize(username, Colors.BOLD):<18s}  "
              f"{colorize(f'{points} pts', color):>8s}  "
              f"{colorize(label, color)}")
    return 0


def run_stats() -> int:
    """Show enhanced storage statistics."""
    storage = get_storage()
    stats = storage.get_stats()
    
    total = stats.get('total_checked', 0)
    if total == 0:
        print(f"{colorize('No data yet. Run a snipe first.', Colors.GRAY)}")
        return 0
    
    print(f"{colorize(' Storage Statistics ', Colors.BOLD + Colors.CYAN):=^60}")
    print(f"Total checked: {colorize(str(total), Colors.BOLD)}")
    print()
    
    # By Status
    print(f"{colorize('By Status:', Colors.BOLD)}")
    status_order = [
        (CheckStatus.VERIFIED_AVAILABLE.value, Colors.GREEN, "[OK] Verified"),
        (CheckStatus.AVAILABLE.value, Colors.BLUE, "[..] Available"),
        (CheckStatus.TAKEN.value, Colors.RED, "[XX] Taken"),
        (CheckStatus.BLOCKED.value, Colors.MAGENTA, "[!!] Blocked"),
        (CheckStatus.RATE_LIMITED.value, Colors.YELLOW, "[!!] Rate Limited"),
        (CheckStatus.ERROR.value, Colors.GRAY, "[XX] Error"),
    ]
    
    for status_val, color, label in status_order:
        count = stats.get(f"status_{status_val}", 0)
        if count > 0:
            pct = (count / total) * 100
            bar = "#" * int(pct / 2)
            print(f"  {colorize(label, color)}: {colorize(str(count), color):>6} ({pct:5.1f}%) {bar}")
    
    trusted = stats.get("trusted_available", 0)
    unvalidated = stats.get("unvalidated_available", 0)
    print()
    print(f"{colorize('Trust:', Colors.BOLD)}")
    print(f"  {colorize('Trusted available:', Colors.GREEN)} {trusted}")
    print(f"  {colorize('Unvalidated public available:', Colors.YELLOW)} {unvalidated}")
    if unvalidated > 0:
        print(f"  Run {colorize('python main.py validate --max 1000', Colors.BOLD)} to recheck suspect rows.")
    
    print()
    
    # By Tier
    print(f"{colorize('By Tier:', Colors.BOLD)}")
    tier_order = [
        (RarityTier.TOP.value, Colors.MAGENTA, "[*] Top"),
        (RarityTier.OG.value, Colors.BLUE, "[*] OG"),
        (RarityTier.SEMI_OG.value, Colors.CYAN, "[*] Semi-OG"),
    ]
    
    for tier_val, color, label in tier_order:
        count = stats.get(f"tier_{tier_val}", 0)
        if count > 0:
            pct = (count / total) * 100
            bar = "=" * int(pct / 2)
            print(f"  {colorize(label, color)}: {colorize(str(count), color):>6} ({pct:5.1f}%) {bar}")
    
    return 0


#: Recognized subcommands (used to detect a bare invocation).
_COMMANDS = {"snipe", "check", "validate", "stats", "rank"}


def _has_command(argv: list[str]) -> bool:
    """True when argv names a known subcommand (skipping global flag values)."""
    skip = False
    for tok in argv:
        if skip:
            skip = False
            continue
        if tok in ("-c", "--config"):
            skip = True
            continue
        if tok.startswith("-"):
            continue
        return tok in _COMMANDS
    return False


def main(argv: Optional[list[str]] = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # With no subcommand (e.g. double-clicking the executable), default to a
    # snipe using config/default settings instead of erroring out.
    if not _has_command(argv) and not any(a in ("-h", "--help") for a in argv):
        argv = ["snipe", *argv]
    try:
        settings = load_config(find_config_path(argv))
    except (FileNotFoundError, ValueError) as e:
        print(f"{colorize('[ERROR]', Colors.RED)} {e}")
        return 2

    def cfg(key: str, fallback=None):
        """Resolve a config value (config file merged over built-in defaults)."""
        return get_config_value(settings, key, fallback)

    # Shared option so --config works both before AND after the subcommand.
    # SUPPRESS keeps it from clobbering a value parsed at the top level.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", "-c", default=argparse.SUPPRESS,
        help="Path to a YAML config file (default: config.yaml if present)",
    )

    parser = argparse.ArgumentParser(
        description="mc-og-name-hunter - Find rare available Minecraft usernames",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
        epilog="""
Examples:
  # Snipe for 5 verified available names from top/og tiers
  python main.py snipe --hits 5 --tiers top,og

  # Use a custom config file (flags still override it)
  python main.py --config my.yaml snipe --hits 10

  # Snipe with async batch processing (faster)
  python main.py snipe --hits 10 --tiers top,og,semi_og --batch-size 100

  # Check a custom wordlist
  python main.py check --input mylist.txt --output available.txt

  # Rate usernames without API calls
  python main.py rank dog Sh4dow xqy

  # Show enhanced statistics
  python main.py stats

Values are resolved in this order (highest wins): CLI flags > config file
(config.yaml, or --config PATH) > built-in defaults.

Environment:
  MOJANG_ACCESS_TOKEN  - Microsoft/Minecraft access token for auth verification
        """
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Snipe command
    snipe_parser = subparsers.add_parser("snipe", parents=[common], help="One-shot snipe for rare names")
    snipe_parser.add_argument(
        "--hits", "-n", type=int, default=cfg("snipe.hits", 5),
        help="Stop after N verified available names (default: 5)"
    )
    snipe_parser.add_argument(
        "--max-candidates", "-m", type=int, default=cfg("generation.max_candidates", 50000),
        help="Maximum candidates to check (default: 50000)"
    )
    snipe_parser.add_argument(
        "--tiers", "-t", type=str, default=cfg("generation.tiers", "top,og,semi_og"),
        help="Comma-separated tiers: top,og,semi_og (default: all)"
    )
    snipe_parser.add_argument(
        "--no-verify", action="store_true", default=not cfg("checking.verify_auth", True),
        help="Skip auth verification (public API only)"
    )
    snipe_parser.add_argument(
        "--verify-all", action="store_true",
        help="Verify ALL public-API available with auth API (slower)"
    )
    snipe_parser.add_argument(
        "--batch-size", type=int, default=cfg("checking.batch_size", 50),
        help="Batch size for async processing (default: 50)"
    )
    snipe_parser.add_argument(
        "--concurrency", type=int, default=cfg("checking.concurrency", 10),
        help="Max concurrent requests (default: 10)"
    )
    snipe_parser.add_argument(
        "--output", "-o", type=str, default=cfg("snipe.output", "data/available.txt"),
        help="Output file for verified available names"
    )
    snipe_parser.add_argument(
        "--min-points", type=int, default=cfg("generation.min_points", 0),
        help=(
            "Skip candidates scoring below this many rarity points (0-80). "
            "Use e.g. 35 to hunt second-tier and rarer names and avoid "
            "wasting requests on low-value names. Default: 0 (no gate)"
        )
    )
    snipe_parser.add_argument(
        "--tui", action="store_true", default=cfg("snipe.tui", False),
        help="Use TUI mode with live updating display"
    )
    snipe_parser.add_argument(
        "--wordlist", action="append", default=cfg("snipe.wordlists", []),
        help=(
            "Custom word list checked before built-in tiers. "
            "Format: PATH[:TIER], e.g. short_all_3_4.txt:top or halloween.txt:og. "
            "Repeatable. Defaults to SEMI_OG tier when omitted."
        )
    )
    
    # Check command
    check_parser = subparsers.add_parser("check", parents=[common], help="Check usernames from a file")
    check_parser.add_argument("--input", "-i", required=True, help="Input file (one username per line)")
    check_parser.add_argument("--output", "-o", default=cfg("check.output", "data/available.txt"), help="Output file")
    check_parser.add_argument("--no-verify", action="store_true", default=not cfg("checking.verify_auth", True), help="Skip auth verification")
    check_parser.add_argument("--batch-size", type=int, default=cfg("check.batch_size", cfg("checking.batch_size", 50)), help="Batch size")
    check_parser.add_argument("--concurrency", type=int, default=cfg("check.concurrency", cfg("checking.concurrency", 10)), help="Max concurrent requests")
    
    # Validate command
    validate_parser = subparsers.add_parser(
        "validate",
        parents=[common],
        help="Revalidate suspect public AVAILABLE rows against canonical Mojang",
    )
    validate_parser.add_argument(
        "--max", type=int, default=cfg("validate.max", 1000),
        help="Maximum unvalidated rows to recheck, rarest first (default: 1000)",
    )
    validate_parser.add_argument("--batch-size", type=int, default=cfg("validate.batch_size", cfg("checking.batch_size", 50)), help="Batch size")
    validate_parser.add_argument("--concurrency", type=int, default=cfg("validate.concurrency", cfg("checking.concurrency", 10)), help="Max concurrent requests")
    validate_parser.add_argument("--output", "-o", default=cfg("validate.output", "data/available.txt"), help="Output file")
    
    # Stats command
    stats_parser = subparsers.add_parser("stats", parents=[common], help="Show storage statistics")
    stats_parser.add_argument("--detailed", action="store_true", help="Show detailed endpoint stats")
    
    # Rank command
    rank_parser = subparsers.add_parser(
        "rank", parents=[common], help="Rate username(s) with the community rarity model (no API calls)"
    )
    rank_parser.add_argument(
        "usernames", nargs="+", help="One or more usernames to rate"
    )
    
    args = parser.parse_args(argv)

    # Route storage to the configured database before any command uses it.
    get_storage(cfg("storage.db_path", "data/checked.db"))
    # Seed the shared rate limiter from config so every command honours it.
    get_rate_limiter(
        requests_per_second=cfg("rate_limit.requests_per_second", 1.5),
        burst=cfg("rate_limit.burst", 10),
        backoff_base=cfg("rate_limit.backoff_base_seconds", 2.0),
    )

    if args.command == "snipe":
        snipe_config = SnipeConfig(
            target_hits=args.hits,
            max_candidates=args.max_candidates,
            tiers=parse_tiers(args.tiers),
            verify_auth=not args.no_verify,
            output_file=args.output,
            min_points=args.min_points,
        )
        snipe_config.verify_all = args.verify_all
        try:
            extra_lists = [parse_wordlist(spec) for spec in (args.wordlist or [])]
        except ValueError as e:
            print(f"Error: {e}")
            return 2
        return run_snipe(
            snipe_config,
            use_tui=args.tui,
            extra_lists=extra_lists,
            settings=settings,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
        )
    
    elif args.command == "check":
        return run_check_wordlist(
            args.input,
            args.output,
            not args.no_verify,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
        )
    
    elif args.command == "validate":
        return run_validate(
            max_candidates=args.max,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            output_file=args.output,
        )
    
    elif args.command == "stats":
        return run_stats()
    
    elif args.command == "rank":
        return run_rank(args.usernames)
    
    return 1


if __name__ == "__main__":
    sys.exit(main())