# mc-og-name-hunter

A fast, clean Minecraft username sniper that searches for rare available usernames across all wordlists and checks them against Mojang's API.

## Features

- **Clean live display** - Single-screen updating progress with percentage, actual counts, speed, top 5 hits by rarity
- **Async checking** - 10 concurrent requests with automatic retries and exponential backoff
- **Canonical Mojang authority** - Only `api.mojang.com/users/profiles/minecraft/` decides public availability; mirrors are hints and must be canonically confirmed
- **Trusted exports** - Exports contain only auth-verified hits or canonical-confirmed public hits
- **Validation command** - Revalidates suspect legacy public positives against canonical Mojang
- **Rarity tiers** - TOP (80pts), OG (60pts), SEMI-OG (35pts) based on word frequency (Zipf)
- **Config file** - All settings in `config.yaml`; CLI flags override it, built-in defaults are sane
- **Rarity gate** - `--min-points` skips low-value names before any API call
- **Persistent storage** - SQLite tracks checked usernames, prevents re-checking across runs
- **Smart re-check** - Only re-checks if previously checked at lower priority tier; errors are always rechecked
- **Rate limiting** - Token bucket (3 req/s, burst 10) with state persistence
- **Graceful shutdown** - Ctrl+C finishes the current batch and saves progress; press again to force-exit

## Installation

```bash
git clone https://github.com/killerboyyy777/mc-og-name-hunter.git
cd mc-og-name-hunter
pip install -r requirements.txt
```

## Configuration

Settings live in `config.yaml` and are resolved in this order (highest wins):

1. **CLI flags**
2. **Config file** (`config.yaml`, or a path passed with `--config`)
3. **Built-in defaults** (`src/config.py`)

Point at a different file with the global `--config`/`-c` flag:

```bash
python main.py --config my.yaml snipe --hits 10
```

| Key | Default | Description |
|-----|---------|-------------|
| `generation.tiers` | `top,og,semi_og` | Default tiers |
| `generation.max_candidates` | `50000` | Candidate cap per run |
| `generation.min_points` | `0` | Rarity gate (`35` = OG+) |
| `generation.min_length` / `max_length` | `3` / `16` | Username length bounds |
| `checking.verify_auth` | `true` | Verify public hits via auth API |
| `checking.batch_size` | `50` | Usernames per async batch (all commands) |
| `checking.concurrency` | `10` | Max concurrent requests (all commands) |
| `rate_limit.requests_per_second` | `3.0` | Token bucket refill rate |
| `rate_limit.burst` | `10` | Token bucket size |
| `rate_limit.backoff_base_seconds` | `2.0` | 429 backoff base |
| `snipe.hits` | `5` | Stop after N hits |
| `snipe.output` | `data/available.txt` | Export path |
| `snipe.tui` | `false` | Live TUI display |
| `snipe.wordlists` | `[]` | Custom lists checked first |
| `check.output` | `data/available.txt` | `check` export path |
| `validate.max` | `1000` | Unvalidated rows to recheck |
| `validate.output` | `data/available.txt` | `validate` export path |
| `storage.db_path` | `data/checked.db` | SQLite database |

`check`/`validate` inherit `batch_size` and `concurrency` from `checking.*`
unless they set their own `check.batch_size` / `validate.batch_size`.

## Usage

### Snipe for rare names

```bash
# Full exhaustive run - checks all ~50k words across all tiers
python main.py snipe --hits 10000 --max-candidates 50000 --tiers top,og,semi_og --no-verify --batch-size 50 --concurrency 10

# Quick run - stop after 5 available hits from top+og tiers
python main.py snipe --hits 5 --tiers top,og --no-verify

# With auth verification (requires MOJANG_ACCESS_TOKEN env var)
export MOJANG_ACCESS_TOKEN=your_token
python main.py snipe --hits 5 --tiers top,og
```

### Check a custom wordlist

```bash
python main.py check --input mylist.txt --output available.txt --no-verify
```

### Snipe custom wordlists (with rarity tiers)

Curated lists ship in `data/word_lists/` and any of them can be checked
*before* the built-in tiers via `--wordlist PATH[:TIER]` (repeatable):

```bash
# All 3-letter + 4-letter combos as TOP, Halloween words as OG
python main.py snipe --hits 100 --tiers top,og --no-verify \
  --wordlist short_all_3_4.txt:top \
  --wordlist halloween.txt:og

# Regenerate the custom lists (short combos: 474,552 names)
python generate_custom_wordlists.py

# Snipe Minecraft item names as OG, checked before built-in tiers
python main.py snipe --hits 50 --tiers top,og --no-verify \
  --wordlist minecraft_items.txt:og

# Snipe the new community lists: faces + digits as TOP, German as semi-OG
python main.py snipe --hits 20 --tiers semi_og --no-verify \
  --wordlist faces.txt:top \
  --wordlist digits_all_3.txt:top \
  --wordlist underscore_pairs_3.txt:top \
  --wordlist german.txt:semi_og \
  --wordlist gaming_terms.txt:og
```

Bare filenames resolve against `data/word_lists/`; absolute or
subdirectory paths work too. Without `:TIER`, lists default to SEMI_OG.

### Revalidate suspect public positives

```bash
# Recheck the rarest 1000 unvalidated public AVAILABLE rows via canonical Mojang
python main.py validate --max 1000 --batch-size 20 --concurrency 5 --output data/available.txt
```

Public `available` rows created before canonical enforcement do not have endpoint provenance and must be revalidated. New runs store canonical provenance automatically.

### Show statistics

```bash
python main.py stats
```

## Command Reference

### `snipe`

| Option | Default | Description |
|--------|---------|-------------|
| `--hits`, `-n` | 5 | Stop after N available names (auth-verified or canonical public hits) |
| `--max-candidates`, `-m` | 50000 | Maximum candidates to check |
| `--tiers`, `-t` | top,og,semi_og | Comma-separated tiers |
| `--no-verify` | false | Skip auth verification (canonical public API only) |
| `--verify-all` | false | Verify ALL public-API available with auth API |
| `--batch-size` | 50 | Batch size for async processing |
| `--concurrency` | 10 | Max concurrent requests |
| `--output`, `-o` | data/available.txt | Output file for trusted names |
| `--min-points` | 0 | Skip candidates scoring below this (0-80); `35` = OG+ only |
| `--tui` | false | Use TUI mode with live updating display (elapsed time updates every second) |
| `--wordlist` | — | Custom list checked before built-in tiers. `PATH[:TIER]`, repeatable |

A global `--config`/`-c PATH` option selects the config file (see
[Configuration](#configuration)); it applies to every command.

### `check`

| Option | Description |
|--------|-------------|
| `--input`, `-i` | Input file (one username per line) |
| `--output`, `-o` | Output file for trusted names |
| `--no-verify` | Skip auth verification |
| `--batch-size` | Batch size for async processing |
| `--concurrency` | Max concurrent requests |

### `validate`

| Option | Default | Description |
|--------|---------|-------------|
| `--max` | 1000 | Maximum unvalidated rows to recheck, rarest first |
| `--batch-size` | 50 | Batch size for async processing (inherits `checking.batch_size`) |
| `--concurrency` | 10 | Max concurrent requests (inherits `checking.concurrency`) |
| `--output`, `-o` | data/available.txt | Output file for trusted names |

### `rank`

Rates usernames with the community rarity model. No API calls, results
sorted rarest-first:

```bash
python main.py rank dog Sh4dow xqy
```

### `stats`

Shows storage statistics by status, tier, trusted available count, and unvalidated public available count.

## Display Modes

By default, mc-og-name-hunter uses a simple line-based progress display that updates on each check. For a richer experience with live elapsed time updates, use the `--tui` flag:

```bash
# TUI mode with live updating display (elapsed time updates every second)
python main.py snipe --hits 5 --tiers top,og --tui --no-verify

# Default simple line display (updates on each check)
python main.py snipe --hits 5 --tiers top,og --no-verify
```

**TUI Mode Features:**
- Live updating box display with progress bar, stats, and top 5 hits by rarity
- Elapsed time and ETA update every second automatically
- Color-coded stats (green=hits, red=taken, yellow=errors, magenta=rate limited)
- Top 5 hits ranked by rarity (TOP > OG > SEMI-OG); only auth-verified or canonical-confirmed public hits are shown
- Graceful Ctrl+C handling

**Simple Line Display (Default):**
- Single line progress that updates on each check
- Shows percentage, actual counts, speed, hits, taken, and errors
- Works in any terminal and when output is redirected
- Minimal resource usage

**Note:** TUI mode requires a real terminal (TTY). When output is redirected or piped, it automatically falls back to simple line display. Use `--tui` to force TUI mode even without a TTY.

## Rarity Tiers

Based on mcindex.gg research using Zipf frequency from SUBTLEX-US:

| Tier | Criteria | Points | Example Words |
|------|----------|--------|---------------|
| **TOP** | Zipf ≥4.5, ≤6 chars | 80 | dog, stone, dream, fox |
| **OG** | Zipf ≥3.5, ≤10 chars | 60 | harbor, swift, wander |
| **SEMI-OG** | Zipf ≥2.5, ≤16 chars | 35 | wandered, meticulous |

Scoring: Base tier points + length bonus (shorter = rarer)

Ranking (exports, top-5 hits, validation order) follows community consensus
(mcindex.gg classes, Hypixel OG guides, NameMC) via points, highest first:
top word 80 > OG word 60 > 3-letter pronounceable 52 > 3-letter
random/digits 45 > 3-char mixed 40 > semi-OG 35 (incl. plurals, past tense,
`-ing` forms) > 4-letter pronounceable 20 > minor variants like
`_Shadow`/`Sh4dow`/compounds 12 > 4-letter random 8 > 4-char mixed 5 >
word + trailing digits/level (`Shadow7`, `sharpnessV`) or readable handles
3 > 0. Ties break toward shorter names. Capitals never matter. Points are
stored per row in SQLite (`rarity_points`, backfilled automatically), so
older database rows are already reordered by the new system.

Ranking (exports, top-5 hits, validation order): **any name containing a
digit always ranks below every digit-free name; shorter names always rank
above longer ones;** ties break by tier (TOP > OG > SEMI-OG).

## API Endpoints

| Endpoint | Type | Format | Notes |
|----------|------|--------|-------|
| `api.mojang.com/users/profiles/minecraft/{username}` | Canonical Mojang authority | 200=taken, 404=available | Only endpoint trusted for final public decisions |
| `mc-api.bisai.dev/v1/name/{username}` | Third-party hint | JSON `{"available": true/false}` | Alphabetic only; AVAILABLE must be canonically confirmed |
| `api.minecraftapi.net/v3/profile/{username}` | Third-party hint | 200=profile (taken), 404=available | AVAILABLE must be canonically confirmed |

Do not use `api.mojang.com/user/profile/agent/minecraft/name/{username}` for availability: it can return 404 even for taken names such as `key`, `hey`, `mom`, and `dog`.

## Word Lists

Auto-generated from wordfreq (top 100k English words) filtered by:
- Valid MC username format (3-16 chars, ASCII letters/numbers/underscore)
- Minimal stop-word filtering (only unusable contraction fragments)
- Zipf frequency thresholds per tier

Short common words such as `the`, `and`, `for`, `dog`, `key`, and `mom` are intentionally kept as candidates; availability is decided by Mojang, not by the word list.

Files in `data/word_lists/`:
- `words_top.txt` (~1,726 words)
- `words_og.txt` (~11,617 words)
- `words_semi_og.txt` (~37,066 words)
- First names variants
- `short_all_3_4.txt` (474,552 names: all a-z 3-letter then 4-letter combos)
- `digits_all_3.txt` (1,000 names: all 3-digit combos `000`–`999`)
- `underscore_pairs_3.txt` (2,028 names: `ab_`, `_ab`, `a_b` patterns)
- `faces.txt` (face emoticons like `o_o`, `x_x` — a community OG exception)
- `gaming_terms.txt` (~410 well-known gaming terms: `clutch`, `noscope`, `smurf`…)
- `german.txt` (~16,700 common German words — an explicit semi-OG class)
- `halloween.txt` (~150 spooky/Halloween words)
- `minecraft_items.txt` (~2,890 names: hand-curated blocks, items, tools, armor, food, mobs, discs, enchantments (incl. in-game Roman level variants like `sharpnessV`/`sharpness_V`), villager professions, splash texts, generic game words like `armor`/`biome`/`spawn`, jockey mechanics like `chicken_jockey`, wood-type/wool-color/material×tool expansions, **plus every name from the PrismarineJS minecraft-data 26.1 registry** — items, blocks, entities, enchantments, effects, biomes)
- Proper-noun lists from `generate_extra_wordlists.py`: `franchise_characters.txt`, `minecraft_ecosystem.txt`, `brands.txt`, `music_artists.txt`, `sports.txt`, `famous_people.txt`, `astronomy.txt`, `chemistry.txt` (names already present in the core corpus are dropped to avoid duplicate requests)

Regenerate with:
```bash
python generate_wordlists.py        # tier lists (wordfreq-based)
python generate_custom_wordlists.py # short combos, digits, underscores, faces, Halloween, German, Minecraft items
python generate_extra_wordlists.py  # franchise/game, Minecraft, brands, music, sports, people, astronomy, chemistry
```

`generate_extra_wordlists.py` downloads from PokeAPI/LoL/Valorant/Overwatch
and falls back to curated data with `--offline`. Generated/combo lists must be
regenerated after a fresh clone (`data/word_lists/` ships the curated lists;
`short_all_3_4.txt` — 474,552 names — is produced by the custom generator).

## Requirements

- Python 3.10+
- Dependencies: `requests`, `aiohttp`, `pyyaml`, `wordfreq`, `tqdm`

```bash
pip install -r requirements.txt
```

## Auth Verification (Optional)

For highest accuracy, set a Microsoft/Minecraft access token:

```bash
export MOJANG_ACCESS_TOKEN=your_access_token
python main.py snipe --hits 5 --tiers top,og
```

The auth API (`api.minecraftservices.com/minecraft/profile/name/{username}/available`) returns:
- `AVAILABLE` - truly available
- `DUPLICATE` - taken (including pseudo-hard-deleted)
- `NOT_ALLOWED` - blocked by filter

Without auth, the canonical public endpoint returns 404 (available) or 200 (taken). Public `available` results can still have false positives for blocked names, so use auth verification for final certainty whenever possible. `data/available.txt` now contains only trusted results: auth-verified hits or canonical-confirmed public hits.

## Project Structure

```
mc-og-name-hunter/
├── main.py                       # Entry point
├── config.yaml                   # Configuration (flags override this)
├── requirements.txt              # Dependencies
├── LICENSE                       # MIT
├── generate_wordlists.py         # Tier word list generator
├── generate_custom_wordlists.py  # Short-combo / digits / items / etc. generator
├── generate_extra_wordlists.py   # Proper-noun (franchise/brands/music/…) generator
├── data/
│   ├── checked.db                # SQLite database (created at runtime, git-ignored)
│   ├── available.txt             # Exported trusted names (git-ignored)
│   └── word_lists/               # Word lists by tier
└── src/
    ├── config.py                # Config loading + defaults
    ├── models.py                # Data models (RarityTier, CheckStatus, etc.)
    ├── storage.py               # SQLite persistence
    ├── rate_limiter.py          # Token bucket rate limiter
    ├── checkers.py              # Async API checkers
    ├── generators.py            # Candidate generation
    ├── display.py               # Clean live display
    └── cli.py                   # Command-line interface
```

## Running in Background

```bash
nohup python -u main.py snipe --hits 10000 --max-candidates 50000 --tiers top,og,semi_og --no-verify --batch-size 50 --concurrency 10 > snipe.log 2>&1 &
```

Do not use `--tui` for background/redirected runs; it needs an interactive terminal.

Check progress:
```bash
tail -f snipe.log
python main.py stats
```

## License

[MIT](LICENSE) - Feel free to use and modify.