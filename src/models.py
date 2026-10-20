"""Data models for the Minecraft username sniper."""

import itertools
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
from datetime import datetime

try:
    from wordfreq import zipf_frequency as _wordfreq_zipf
except Exception:
    _wordfreq_zipf = None


#: Digit/character substitutions used to detect leetspeak spellings.
_LEET_SUBS = str.maketrans({
    "4": "a", "3": "e", "1": "i", "0": "o", "5": "s",
    "7": "t", "8": "b", "6": "g", "9": "g", "2": "z",
    "$": "s", "@": "a", "!": "i",
})
_ROMAN_CHARS = frozenset("ivxlcdm")


# Import banned words system from the canonical implementation
from generate_custom_wordlists import (
    _BANNED_WORDS,
    _FALSE_POSITIVES,
    add_banned_word,
    is_banned,
    load_banned_words,
    save_banned_words,
)
from src.paths import resource_path


def _load_rarity_overrides() -> dict[str, int]:
    """Load curated ``word<TAB>points`` overrides bundled with the data files.

    Supplemental lists (multilingual words, names, geography, ...) contain
    many handles that the English ``wordfreq`` model does not know.  The
    generator records their intended tier here so every consumer of
    ``rarity_points`` (generation, filtering, storage, display, audit) agrees.
    """
    overrides: dict[str, int] = {}
    path: Path = resource_path("data", "word_lists", "rarity_overrides.tsv")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                word, _, points = line.strip().partition("\t")
                if not word or not points:
                    continue
                try:
                    overrides[word.lower()] = int(points)
                except ValueError:
                    continue
    except OSError:
        pass
    return overrides


_RARITY_OVERRIDES = _load_rarity_overrides()


def _zipf(word: str) -> float:
    """English word frequency on the Zipf scale (0.0 for non-words)."""
    if not word or not word.isalpha() or _wordfreq_zipf is None:
        return 0.0
    try:
        return float(_wordfreq_zipf(word, "en"))
    except Exception:
        return 0.0


def _pronounceable(word: str) -> bool:
    """Heuristic: reads like a word (has a vowel, no 4+ consonant run)."""
    w = "".join(c for c in word.lower() if c.isalpha())
    if not w:
        return False
    vowels = set("aeiouy")
    if not any(c in vowels for c in w):
        return False
    run = worst = 0
    for c in w:
        if c in vowels:
            run = 0
        else:
            run += 1
            worst = max(worst, run)
    return worst <= 3


def _is_compound(word: str) -> bool:
    """Heuristic: two common dictionary words joined together.

    Both parts need real word frequency (Zipf >= 3.5, the OG threshold),
    so rare fragments like "tobi" or "mora" don't qualify.
    """
    for i in range(2, len(word) - 1):
        if _zipf(word[:i]) >= 3.5 and _zipf(word[i:]) >= 3.5:
            return True
    return False


def rarity_label(points: int, username: str = "") -> str:
    """Human-readable class label for a rarity-points value.

    If the username is banned/blocked, returns "banned" regardless of points.
    """
    if username and is_banned(username):
        return "banned"
    if points >= 80:
        return "top word"
    if points >= 60:
        return "OG word"
    if points >= 52:
        return "3-letter pronounceable"
    if points >= 45:
        return "3-letter random/digits"
    if points >= 40:
        return "3-character mixed"
    if points >= 35:
        return "semi-OG"
    if points >= 20:
        return "4-letter pronounceable"
    if points >= 12:
        return "minor variant"
    if points >= 8:
        return "4-letter random"
    if points >= 5:
        return "4-character mixed"
    if points >= 3:
        return "clean handle"
    return "nothing special"


def _is_inflected(word: str, z: float) -> bool:
    """Heuristic: plural/past-tense/-ing form of a commoner stem.

    The community rates inflections (carbons, getting, wanted) as semi-OG
    even when frequent, so they score below base-form OG words.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)]
            if _zipf(stem) > z:
                return True
            # Doubled consonant: running -> run.
            if len(stem) >= 4 and stem[-1] == stem[-2]:
                if _zipf(stem[:-1]) > z:
                    return True
    return False


def _split_level_suffix(core: str) -> tuple[str, bool]:
    """Split a trailing level indicator (digits or Roman numerals).

    Returns (base, had_suffix). The Roman branch only strips when the
    remainder is a real word, so plain words ending in i/v/x (taxi, ski)
    are left intact.
    """
    m = re.match(r"^(.*?)_([0-9]{1,2}|[ivxlcdm]{1,4})$", core)
    if m and m.group(1):
        return m.group(1), True
    m = re.match(r"^(.*?[a-z])([0-9]{1,2})$", core)
    if m:
        return m.group(1), True
    m = re.match(r"^(.*)([ivxlcdm]{1,3})$", core)
    if m and len(m.group(1)) >= 4 and _zipf(m.group(1)) > 0:
        return m.group(1), True
    return core, False


def _base_rarity_points(username: str) -> int:
    """English-frequency rarity model (see :func:`rarity_points`)."""
    name = username.lower()
    n = len(name)

    # Pure dictionary words: top (80) > OG (60) > short classes > semi (35).
    # Inflected forms (plurals, past tense, -ing) drop to semi-OG per
    # community consensus, even when frequent.
    if name.isalpha():
        z = _zipf(name)
        if z >= 4.5 and n <= 6:
            return 80
        if z >= 3.5 and n <= 10:
            return 35 if _is_inflected(name, z) else 60
        if n == 3:
            return 52 if _pronounceable(name) else 45
        if z >= 2.5:
            return 35
        if n == 4:
            return 20 if _pronounceable(name) else 8
        if _is_compound(name):
            return 12
        return 3 if _pronounceable(name) else 0

    # All-digit names: only 3-digit handles rate (e.g. 777).
    if name.isdigit():
        return 45 if n == 3 else 0

    # Short mixed names: shape decides, not meaning.
    if n == 3:
        return 40
    if n == 4:
        return 2

    # Longer names with digits/underscores.
    core = name.lstrip("_")
    base, had_suffix = _split_level_suffix(core)
    deleet = base.translate(_LEET_SUBS) if any(c.isdigit() for c in base) else base
    wordy = deleet.isalpha() and _zipf(deleet) > 0
    if had_suffix and wordy:
        # Word plus level/trailing digits (Shadow7, sharpnessV): clean handle.
        return 3
    flat = re.sub(r"[^a-z]", "", name.translate(_LEET_SUBS))
    flat_wordy = flat.isalpha() and _zipf(flat) > 0
    
    # Check if underscore is in middle of two dictionary words (iron_wolf style)
    has_middle_underscore = False
    if "_" in core and not core.startswith("_") and not core.endswith("_"):
        parts = core.split("_")
        if len(parts) == 2 and all(p.isalpha() and 2 <= len(p) <= 12 for p in parts):
            # Both parts look like real words (alphabetic, reasonable length)
            has_middle_underscore = True
    
    modified = core != name or (("_" in name) and not has_middle_underscore) or deleet != base
    if modified and (flat_wordy or _is_compound(flat)):
        # Minor variant of a real word (_Shadow, Sh4dow, iron_wolf).
        return 12
    if modified:
        # Variants with underscore/leetspeak score lower than clean words
        return 1 if _pronounceable(flat) else 0
    return 0


def rarity_points(username: str) -> int:
    """Rate a username's rarity in community points (higher = rarer).

    Model follows the community consensus (mcindex.gg classes, Hypixel OG
    guides, NameMC): common short dictionary words score highest, then
    short pronounceable names, then semi-OG words; leet spellings,
    underscores and trailing numbers score low.

    Curated supplemental lists can raise a name to a minimum tier via
    ``data/word_lists/rarity_overrides.tsv``; the higher of the English
    model and the curated tier wins.
    """
    base = _base_rarity_points(username)
    return max(base, _RARITY_OVERRIDES.get(username.lower(), 0))


class RarityTier(Enum):
    """Rarity tiers based on mcindex.gg classification."""
    TOP = "top"           # Zipf >= 4.5, <= 6 chars, 80 pts
    OG = "og"             # Zipf >= 3.5, <= 10 chars, 60 pts
    SEMI_OG = "semi_og"   # Zipf >= 2.5, <= 16 chars, 35 pts
    
    def base_score(self) -> int:
        return {
            RarityTier.TOP: 80,
            RarityTier.OG: 60,
            RarityTier.SEMI_OG: 35,
        }[self]
    
    @property
    def sort_order(self) -> int:
        """Lower = higher priority for generation."""
        return {"top": 0, "og": 1, "semi_og": 2}[self.value]


class CheckStatus(Enum):
    """Result of availability check."""
    TAKEN = "taken"
    AVAILABLE = "available"
    BLOCKED = "blocked"       # NOT_ALLOWED from auth API
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    INVALID = "invalid"       # not a legal Minecraft username; never checked
    VERIFIED_AVAILABLE = "verified_available"  # Auth API confirmed AVAILABLE
    VERIFIED_TAKEN = "verified_taken"          # Auth API confirmed DUPLICATE


@dataclass
class UsernameCandidate:
    """A candidate username to check."""
    username: str
    tier: RarityTier
    zipf: float = 0.0
    source: str = "dictionary"  # "dictionary", "firstnames", "variant"
    
    @property
    def score(self) -> int:
        """Calculate score based on tier + length bonus."""
        base = self.tier.base_score()
        # Bonus for shorter names (more rare)
        length_bonus = max(0, (10 - len(self.username))) * 2
        return base + length_bonus
    
    @property
    def rank_key(self) -> tuple:
        """Rarity ordering by community points (higher first), then shorter
        names, then tier priority as a final tiebreak."""
        return (
            -rarity_points(self.username),
            len(self.username),
            self.tier.sort_order,
        )
    
    def __lt__(self, other: "UsernameCandidate") -> bool:
        """Sort by rarity, most rare first."""
        return self.rank_key < other.rank_key


@dataclass
class CheckResult:
    """Result of an availability check."""
    username: str
    status: CheckStatus
    tier: RarityTier
    checked_at: datetime
    verified: bool = False
    error_message: Optional[str] = None
    source: Optional[str] = None
    
    @property
    def is_available(self) -> bool:
        return self.status in (CheckStatus.AVAILABLE, CheckStatus.VERIFIED_AVAILABLE)
    
    @property
    def is_verified_hit(self) -> bool:
        return self.status == CheckStatus.VERIFIED_AVAILABLE
    
    @property
    def is_taken(self) -> bool:
        return self.status in (CheckStatus.TAKEN, CheckStatus.VERIFIED_TAKEN)
    
    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "status": self.status.value,
            "tier": self.tier.value,
            "checked_at": self.checked_at.isoformat(),
            "verified": self.verified,
            "error_message": self.error_message,
            "source": self.source,
        }


@dataclass
class SnipeConfig:
    """Configuration for a snipe run."""
    target_hits: int = 5
    max_candidates: int = 50000
    tiers: list[RarityTier] = None
    verify_auth: bool = True
    output_file: str = "data/available.txt"
    min_points: int = 0  # skip candidates rarer-scoring below this threshold
    
    def __post_init__(self):
        if self.tiers is None:
            self.tiers = [RarityTier.TOP, RarityTier.OG, RarityTier.SEMI_OG]