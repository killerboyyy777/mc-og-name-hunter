# mc-og-name-hunter

A fast, clean Minecraft username sniper that searches for rare available usernames across all wordlists and checks them against Mojang's API.

## Features

- **Clean live display** - Single-screen updating progress with percentage, actual counts, speed, top 5 hits by rarity
- **Async checking** - 10 concurrent requests with automatic retries and exponential backoff
- **Canonical Mojang authority** - Only `api.mojang.com/users/profiles/minecraft/` decides public availability; mirrors are hints and must be canonically confirmed
- **Trusted exports** - Exports contain only auth-verified hits or canonical-confirmed public hits
- **Validation command** - Revalidates suspect legacy public positives against canonical Mojang
- **Rarity tiers** - mcindex.gg/Hypixel community model: common short words 80, common words/names 60, 3-letter shapes 52/45, second-tier words 35, 4-letter shapes 20/8, minor variants 12
- **Config file** - All settings in `config.yaml`; CLI flags override it, built-in defaults are sane
- **Rarity gate** - `--min-points` skips low-value names before any API call
- **Supplemental themed lists** - Multilingual words, names, geography, nature, mythology/Latin, Wordle, tech, food, music, sports, space, Minecraft creators/meta, brands and compound names, with consensus-scored rarity overrides
- **Persistent storage** - SQLite tracks checked usernames, prevents re-checking across runs
- **Smart re-check** - Only re-checks if previously checked at lower priority tier; errors are always rechecked
- **Rate limiting** - Token bucket (1.5 req/s, burst 10) with state persistence; authenticated audits are paced to Mojang's 20-per-5-minute limit
- **Graceful shutdown** - Ctrl+C finishes the current batch and saves progress; press again to force-exit

## Installation

```bash
git clone https://github.com/killerboyyy777/mc-og-name-hunter.git
cd mc-og-name-hunter
pip install -r requirements.txt
```

### Prebuilt executable (Windows)

Download `mc-og-name-hunter.exe` from the [latest release](https://github.com/killerboyyy777/mc-og-name-hunter/releases/latest) and run it directly - no Python install required. The executable bundles the word lists and the English frequency data, so it runs standalone. Results (`data/available.txt`, `data/checked.db`) and an optional `config.yaml` are read/written in the directory you launch it from. Launching it with no arguments starts a default snipe (all tiers, 5 hits); auth verification is enabled automatically when a token is found in `MOJANG_ACCESS_TOKEN` or `data/mojang_token.txt`.

```powershell
.\mc-og-name-hunter.exe snipe --hits 5 --tiers top,og --no-verify
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
| `generation.min_points` | `25` | Rarity gate (`35` = second-tier and above); built-in default is `0` |
| `generation.min_length` / `max_length` | `3` / `16` | Username length bounds |
| `checking.verify_auth` | `true` | Verify public hits via auth API |
| `checking.batch_size` | `50` | Usernames per async batch (all commands) |
| `checking.concurrency` | `10` | Max concurrent requests (all commands) |
| `rate_limit.requests_per_second` | `1.5` | Token bucket refill rate |
| `rate_limit.burst` | `10` | Token bucket size |
| `rate_limit.backoff_base_seconds` | `2.0` | 429 backoff base |
| `snipe.hits` | `5` | Stop after N hits |
| `snipe.output` | `data/available.txt` | Export path |
| `snipe.tui` | `false` | Live TUI display |
| `snipe.wordlists` | `[]` | Custom lists checked first (e.g. `["og_names_first.txt:og"]`) |
| `check.output` | `data/available.txt` | `check` export path |
| `validate.max` | `1000` | Unvalidated rows to recheck |
| `validate.output` | `data/available.txt` | `validate` export path |
| `storage.db_path` | `data/checked.db` | SQLite database |

`check`/`validate` inherit `batch_size` and `concurrency` from `checking.*`
unless they set their own `check.batch_size` / `validate.batch_size`.

## Usage

Omitting the subcommand defaults to `snipe` with config/default settings, so `python main.py` (or double-clicking the executable) starts a snipe run.

### Snipe for rare names

```bash
# Full exhaustive run over the built-in tier corpus (~50k words)
python main.py snipe --hits 10000 --max-candidates 50000 --tiers top,og,semi_og --no-verify --batch-size 50 --concurrency 10

# Quick run - stop after 5 available hits from top+og tiers
python main.py snipe --hits 5 --tiers top,og --no-verify

# With auth verification (run the device login once - see Authentication)
python main.py snipe --hits 5 --tiers top,og

# Or export a token directly
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

# Snipe community lists: faces are an OG exception, digits are 45-point OG,
# German and compounds are second-tier
python main.py snipe --hits 20 --tiers semi_og --no-verify \
  --wordlist faces.txt:og \
  --wordlist digits_all_3.txt:og \
  --wordlist underscore_pairs_3.txt:semi_og \
  --wordlist german.txt:semi_og \
  --wordlist gaming_terms.txt:og

# Themed lists: ~54.6k supplemental second-tier names from multilingual,
# first/surnames, geography, nature, mythology, Wordle, tech, food, music,
# sports, space and Minecraft
python main.py snipe --hits 50 --tiers semi_og --no-verify \
  --wordlist semi_names.txt:semi_og

# Refresh the themed lists (uses data/themed_cache for offline reruns)
python generate_themed_wordlists.py
python generate_themed_wordlists.py --offline
```

Themed names are scored through `data/word_lists/rarity_overrides.tsv`, so a
foreign word such as `perro`, `sakura` or `zhongguo` is treated as OG (60)
instead of falling back to the English frequency model.

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

### Audit word lists (authenticated)

`audit_wordlists.py` screens whole word lists against Mojang's real limits and
separates **taken** names from **banned** ones. It uses the public batch
endpoint first, then checks only the names that are absent with the
authenticated availability endpoint (a taken name can never be banned):

```bash
# Count eligible words without making any API calls
python audit_wordlists.py --count-only

# Audit everything scoring 45+ (TOP + OG)
python audit_wordlists.py --min-points 45

# Restrict to specific lists, or start over instead of resuming
python audit_wordlists.py --lists words_top.txt words_og.txt
python audit_wordlists.py --fresh
```

Outputs in `data/`:

- `wordlist_audit.csv` - resumable per-word results (git-ignored)
- `wordlist_banned.txt` - confirmed `NOT_ALLOWED` words (auto-loaded by the banlist)
- `wordlist_available.txt` - available words, rarest first (git-ignored)

The audit auto-loads every `*.txt` file, including the themed lists, and uses
the same `rarity_overrides.tsv` tiers as the sniper. `rarity_overrides.tsv`
itself is not a word list (it is `.tsv`, so the audit skips it). With the
themed lists present, `--count-only --min-points 35` reports roughly 107k
eligible names. A fresh audit has to public-screen all of them (about 2h at
the default pace); the CSV is resumable, so later runs only process new rows
and names still awaiting auth checks. At the 35+ threshold about 11.6k
second-tier names are still waiting on the auth endpoint (~54h at 0.06 rps).
Use `--lists semi_names.txt` or another themed filename to audit a subset.

Documented limits: public `200 req / 2 min` per IP (10 names per request) and
auth `20 req / 5 min` per account. Defaults are `--public-rps 1.5` and
`--auth-rps 0.06`; the auth endpoint sends no `Retry-After`, so a 429 waits the
full 5-minute window. `--skip-public` auth-checks every word (slow), `--limit N`
caps the run, and `--count-only` reports volumes and ETAs.

`verify_banlist.py` re-checks the exact-match banlist against the same APIs,
using a separate auth limiter paced at `0.06 rps`:

```bash
python verify_banlist.py
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
| `--min-points` | 0 | Skip candidates scoring below this (0-80); `35` = second-tier and above |
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

Based on the community model published by mcindex.gg (18 name classes,
October 2026), the Hypixel OG-name guides, and NameMC consensus. Common
English words and popular names score highest; a name is never promoted just
because it is short.

| Points | Class | Examples |
|--------|-------|----------|
| **80** | Very common English word, <=6 chars (TOP) | dog, stone, dream, fox |
| **60** | Common English word <=10, popular first name, well-known gaming term (OG) | harbor, swift, candle |
| **52** | 3 letters, pronounceable | zor, yew |
| **45** | 3 letters random, or 3 digits | xqz, 777 |
| **40** | 3-character mixed | a1b |
| **35** | Second-tier real word: rare English 11+, inflected forms, German, foreign dictionary (SEMI-OG) | wandered, incumbents, meticulous |
| **20** | 4 letters, pronounceable | vexo, yawl |
| **12** | Minor feature: compound, compound plural, leet, very rare word/name | ironwolf, policymakers, sh4dow |
| **8** | 4 letters, random | qzvk |
| **5** | 4-character mixed | a1b2 |
| **3** | Clean readable handle, or word + trailing digits/level | shadow7, sharpnessV |
| **0** | Nothing special | |

Scoring is by community points (higher = rarer); names with equal points are
ordered by shorter length, then tier. Capitals never matter. Points are
stored per row in SQLite (`rarity_points`, backfilled automatically), so
older database rows are reordered by the current model.

Community notes: 1-2 character names are legacy-only and effectively
unobtainable; 3-letter names are exhausted; 4-letter availability correlates
with pronounceability and rare letters (`q/j/x/z/k/v`). Hypixel's definition
of OG is the word alone, with no affixes or leetspeak; `o_o` and `x_x` are
explicit exceptions.

Sources: [mcindex.gg/names](https://mcindex.gg/names),
[mcindex.gg guides](https://mcindex.gg/guides),
[Hypixel OG guide](https://hypixel.net/threads/guide-everything-you-need-to-know-about-og-names.2036535),
[stupidfoot 4-letter analysis](https://stupidfoot.com/blog/minecraft-og-usernames/).

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

Themed lists from `generate_themed_wordlists.py` (all words are also recorded
in `rarity_overrides.tsv`):

- `rare_names.txt` (supplemental 60+ names) and `semi_names.txt` (~54.6k
  lower-tier names) - deduped aggregates, shortest first. The core corpus
  already contains the common English OG words, so `rare_names.txt` can be
  empty while the second-tier aggregate holds the supplemental names.
- `og_multilingual_*.txt` - 33 languages via `wordfreq` (Spanish, French,
  German, Italian, Portuguese, Dutch, Nordic, Polish, Czech, Slovak, Hungarian,
  Romanian, Turkish, Indonesian, Malay, Vietnamese, Tagalog, Afrikaans,
  Croatian, Serbian, Bulgarian, Ukrainian, Russian, Greek, Arabic, Persian,
  Hindi, Japanese, Korean, Chinese, ...). Latin-script transliterations are
  used for non-Latin scripts. Foreign dictionary words are second-tier (35)
  unless English usage makes the base model score them higher.
- `og_names_first.txt` / `og_names_surnames.txt` - public first-name and
  Census-surname datasets, filtered to 3-16 ASCII letters
- `og_geo.txt` - countries, capitals, ISO codes, US states, Canadian
  provinces, major cities, landmarks
- `og_nature_*.txt` - animals, birds, fish, plants, dinosaurs
- `og_mythology.txt` - Greek/Roman/Norse/Egyptian/Hindu/Japanese/Celtic
  mythology plus common Latin words
- `og_wordle.txt` - Wordle answers plus common allowed guesses
- `og_tech.txt`, `og_food.txt`, `og_music.txt`, `og_sports.txt`,
  `og_cosmos.txt`, `og_brands.txt` - specialist vocabulary
- `og_mc_creators.txt`, `og_mc_meta.txt` - Minecraft creators and SMP terms
- `semi_foreign_words.txt` - widely used loanwords and foreign dictionary
  words (second-tier, 35 pts unless English usage raises them)
- `semi_compounds.txt` - pronounceable root+suffix handles such as
  `ironclaw`/`frostwing` (minor name feature, 12 pts)

`rarity_overrides.tsv` maps every themed word to its consensus points
(12/20/35/40/45/52/60/80).
`src.models.rarity_points` uses `max(English model, curated tier)`, so the
generator, prefilter, storage, display, exports and audit all agree. The file
is bundled into the executable by the existing `data/word_lists` data entry.

Regenerate with:
```bash
python generate_wordlists.py        # tier lists (wordfreq-based)
python generate_custom_wordlists.py # short combos, digits, underscores, faces, Halloween, German, Minecraft items
python generate_extra_wordlists.py  # franchise/game, Minecraft, brands, music, sports, people, astronomy, chemistry
python generate_themed_wordlists.py # multilingual, names, geo, nature, mythology, Wordle, tech, food, music, sports, space, MC, brands, compounds
```

`generate_extra_wordlists.py` downloads from PokeAPI/LoL/Valorant/Overwatch
and falls back to curated data with `--offline`. Generated/combo lists must be
regenerated after a fresh clone (`data/word_lists/` ships the curated lists;
`short_all_3_4.txt` — 474,552 names — is produced by the custom generator).

## Requirements

- Python 3.10+
- Core: `requests`, `aiohttp`, `pyyaml`, `wordfreq`, `tqdm`
- Auth helper: `mcauth3` (device login via `get_token.py`)
- Generator-only: `unidecode` (transliterates non-Latin word lists)
- Build: `pyinstaller`

`requirements.txt` installs the core, auth helper, and generator dependencies.

```bash
pip install -r requirements.txt
```

## Authentication (Optional)

The auth API (`api.minecraftservices.com/minecraft/profile/name/{username}/available`)
returns:
- `AVAILABLE` - truly available
- `DUPLICATE` - taken (including pseudo-hard-deleted)
- `NOT_ALLOWED` - blocked by the name filter

It is the only way to detect banned names. There are two ways to provide a
token:

### Device login helper (recommended)

```bash
pip install mcauth3
python get_token.py --new    # prints a URL + code
python get_token.py --poll   # finish after signing in
```

This caches a refresh token in `data/mcauth.json` and writes the current
Minecraft access token to `data/mojang_token.txt`. Later runs can refresh
silently with `python get_token.py`; the sniper reads the cached file
automatically, so no environment variable is needed. Both token files are
git-ignored.

### Environment variable

```bash
export MOJANG_ACCESS_TOKEN=your_access_token
python main.py snipe --hits 5 --tiers top,og
```

`MOJANG_ACCESS_TOKEN` takes precedence over the cached file. The auth endpoint
is limited to **20 requests / 5 minutes per account**. The sniper's default
1.5 req/s applies to the public endpoint; use `audit_wordlists.py` (0.06 rps)
for bulk auth checks instead of hammering it.

Without a token the canonical public endpoint still returns 404 (available) or
200 (taken), but blocked names can look available. `data/available.txt`
contains only trusted results: auth-verified hits or canonical-confirmed
public hits.

## Project Structure

```
mc-og-name-hunter/
├── main.py                       # Entry point
├── config.yaml                   # Configuration (flags override this)
├── requirements.txt              # Dependencies
├── LICENSE                       # MIT
├── generate_wordlists.py         # Tier word list generator
├── generate_custom_wordlists.py  # Short-combo / digits / items / etc. generator
├── generate_extra_wordlists.py   # Proper-noun (franchise/brands/music/.) generator
├── generate_themed_wordlists.py  # Multilingual / themed / compound lists
├── get_token.py                  # Device-code login -> data/mojang_token.txt
├── audit_wordlists.py            # Two-phase word-list audit (public + auth)
├── verify_banlist.py             # Re-check the banlist against the APIs
├── data/
│   ├── checked.db                # SQLite database (created at runtime, git-ignored)
│   ├── available.txt             # Exported trusted names (git-ignored)
│   ├── wordlist_banned.txt       # Confirmed NOT_ALLOWED words (tracked)
│   ├── wordlist_audit.csv        # Audit results (git-ignored, resumable)
│   ├── wordlist_available.txt    # Available words (git-ignored)
│   ├── mojang_token.txt          # Cached access token (git-ignored)
│   ├── mcauth.json               # Refresh-token cache (git-ignored)
│   ├── themed_cache/             # Cached public datasets (git-ignored)
│   └── word_lists/               # Word lists by tier + themed overrides
└── src/
    ├── config.py                # Config loading + defaults
    ├── models.py                # Data models + rarity overrides
    ├── storage.py               # SQLite persistence
    ├── rate_limiter.py          # Token bucket rate limiter
    ├── auth.py                  # Access-token lookup (env var + cached file)
    ├── checkers.py              # Async API checkers
    ├── generators.py            # Candidate generation
    ├── display.py               # Clean live display
    ├── paths.py                 # Source/frozen asset paths
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

## Building a standalone executable

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean mc-og-name-hunter.spec
```

Use `python -m PyInstaller` rather than the bare `pyinstaller` shim: the shim
can point at a different interpreter than the one with `wordfreq` and the other
dependencies installed.

The single-file executable is written to `dist/mc-og-name-hunter.exe`. The spec (`mc-og-name-hunter.spec`) bundles the word lists from `data/word_lists` plus only the English `wordfreq` data (the rarity model is English-only), keeping the build compact. Frozen builds locate their bundled assets through `src/paths.py`.

## License

[MIT](LICENSE) - Feel free to use and modify.
