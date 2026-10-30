"""Data models for the Minecraft username sniper.

Scoring itself lives in :mod:`src.rarity` (a banded, class-ordered model on a
0-1000 scale).  This module keeps the historical names -- ``rarity_points``,
``rarity_label``, ``_base_rarity_points`` -- as thin re-exports so existing
imports keep working.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime

# Import banned words system from the canonical implementation
from generate_custom_wordlists import (
    _BANNED_WORDS,
    _FALSE_POSITIVES,
    add_banned_word,
    is_banned,
    load_banned_words,
    save_banned_words,
)
from src.rarity import (
    base_class,
    base_score,
    score as _score,
    score_breakdown,
    tier_for_score as _tier_value,
    label as _rarity_label,
    # Re-exported for callers that imported the heuristics from here.
    _is_compound,
    _is_compound_plural,
    _is_inflected,
    _load_rarity_overrides,
    _pronounceable,
    _split_level_suffix,
    _zipf,
)

__all__ = [
    "CheckResult",
    "CheckStatus",
    "RarityTier",
    "SnipeConfig",
    "UsernameCandidate",
    "_base_rarity_points",
    "base_class",
    "base_score",
    "is_banned",
    "rarity_label",
    "rarity_points",
    "score_breakdown",
    "tier_for_score",
]


def _base_rarity_points(username: str) -> int:
    """Class base for a name, before within-class modifiers (0-1000).

    Kept as an alias for :func:`src.rarity.base_score` because older helper
    scripts import this name.
    """
    return base_score(username)


def rarity_points(username: str) -> int:
    """Rate a username's desirability on the 0-1000 community score.

    The class ordering follows mcindex.gg's 18 name classes, cross-checked
    against Hypixel OG-name usage; within a class, frequency, length,
    pronounceability, form purity and curated patterns decide the tiebreak.
    Curated supplemental lists can raise a name to a class floor via
    ``data/word_lists/rarity_overrides.tsv``; a floor never lowers a name.
    """
    return _score(username)


def rarity_label(points: int, username: str = "") -> str:
    """Human-readable class label for a score.

    If the username is banned/blocked, returns "banned" regardless of points.
    """
    if username and is_banned(username):
        return "banned"
    return _rarity_label(points)


def tier_for_score(points: int) -> "RarityTier":
    """Map a 0-1000 score to its generation tier."""
    return RarityTier(_tier_value(points))


class RarityTier(Enum):
    """Coarse generation buckets, derived from the score.

    TOP >= 800 (top words), OG >= 350 (OG words, 3L shapes, semi-OG words),
    SEMI_OG < 350 (4L shapes, compounds, clean handles, nothing special).
    """
    TOP = "top"
    OG = "og"
    SEMI_OG = "semi_og"

    def base_score(self) -> int:
        return {
            RarityTier.TOP: 800,
            RarityTier.OG: 350,
            RarityTier.SEMI_OG: 0,
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
        """Score for this candidate (tier base plus a small length bonus)."""
        base = self.tier.base_score()
        length_bonus = max(0, (10 - len(self.username))) * 2
        return base + length_bonus

    @property
    def rank_key(self) -> tuple:
        """Rarity ordering by score (higher first), then shorter names, then
        tier priority as a final tiebreak."""
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
    score: Optional[int] = None  # stored 0-1000 score, when read from storage

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
            "score": self.score,
        }


@dataclass
class SnipeConfig:
    """Configuration for a snipe run."""
    target_hits: int = 5
    max_candidates: int = 50000
    tiers: list[RarityTier] = None
    verify_auth: bool = True
    output_file: str = "data/available.txt"
    min_score: int = 0  # skip candidates scoring below this (0-1000)

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = [RarityTier.TOP, RarityTier.OG, RarityTier.SEMI_OG]
