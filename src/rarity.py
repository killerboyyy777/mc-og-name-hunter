"""Banded, class-ordered rarity score (0-1000).

The score answers one question: **how desirable is this username to the
Minecraft name community?**  It is a ranking device, not a price.

The model is deliberately *not* a weighted sum of independent factors.  The
community reasons class-first, then tiebreaks (see
``docs/name-rarity-community-consensus.md``): a random 3-letter name does not
become "almost a word" by being short.  So every name is first placed in a
class, and within-class modifiers only move it inside that class's band.  No
combination of modifiers can cross a class boundary:

    base = mcindex class value x 10
    width = min(99, next_base - base - 1)
    score = base + round(width * clamp(sum(modifiers), 0, 1))

Class table (ascending, so each band's upper bound is the next base)::

    range     class
    900-999   1-2 characters          (rank/explain only; min length is 3)
    850-899   illegal characters      (rank/explain only)
    800-849   top word
    600-699   OG word / first name / gaming term / German word
    520-599   3L pronounceable
    450-519   3L random / 3 digits     (random at the bottom, 666/777/100 high)
    400-449   3-char mixed
    350-399   semi-OG (other non-English words, inflections, rare/long words)
    200-299   4L pronounceable
    120-199   compound / leet / curated rare  (compounds near the top)
    80-119    4L random
    50-79     4-char mixed
    30-49     clean handle
    0-29      nothing special

Why 1000 and not 100: mcindex's 18 classes give ~15 useful values; 50k names
over 15 values ties thousands per score.  Multiplying by ten keeps the class
values recognisable while giving each band ~50-99 points of room, and an
INTEGER sorts correctly in SQLite without a REAL migration.

This module must not import :mod:`src.models` (models re-exports from here, so
the reverse import would be a cycle).  ``tier_for_score`` therefore returns the
tier *value* (``"top"``/``"og"``/``"semi_og"``); models wraps it in
``RarityTier``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from src.paths import resource_path

try:
    from wordfreq import zipf_frequency as _wordfreq_zipf
except Exception:  # pragma: no cover - wordfreq is a hard requirement
    _wordfreq_zipf = None


# --------------------------------------------------------------------------
# Text helpers (also re-exported by src.models for backwards compatibility)
# --------------------------------------------------------------------------

#: Digit/character substitutions used to detect leetspeak spellings.
_LEET_SUBS = str.maketrans({
    "4": "a", "3": "e", "1": "i", "0": "o", "5": "s",
    "7": "t", "8": "b", "6": "g", "9": "g", "2": "z",
    "$": "s", "@": "a", "!": "i",
})


@lru_cache(maxsize=200_000)
def _zipf(word: str) -> float:
    """English word frequency on the Zipf scale (0.0 for non-words).

    ``wordfreq`` is English-only in the bundled build (see the PyInstaller
    spec).  Non-English words therefore return 0.0; the frequency modifier
    treats 0.0 as *neutral*, never as "worst", so multilingual lists do not
    collapse to the bottom of their band.
    """
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

    Both parts need real word frequency (Zipf >= 3.5), so rare fragments like
    "tobi" or "mora" do not qualify.
    """
    for i in range(2, len(word) - 1):
        if _zipf(word[:i]) >= 3.5 and _zipf(word[i:]) >= 3.5:
            return True
    return False


def _is_inflected(word: str, z: float) -> bool:
    """Heuristic: plural/past-tense/-ing form of a commoner stem.

    The community rates inflections (carbons, getting, wanted) as semi-OG even
    when they are frequent, so they sit below base-form words.
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


def _is_compound_plural(word: str) -> bool:
    """Heuristic for plurals whose singular is a compound noun.

    ``policymakers`` is more frequent than ``policymaker`` in some corpora, so
    the normal stem-frequency check misses it.  Both forms split into words.
    """
    if len(word) < 6 or not word.endswith("s") or word.endswith("ss"):
        return False
    singular = word[:-1]
    return _is_compound(word) and _is_compound(singular)


def _split_level_suffix(core: str) -> tuple[str, bool]:
    """Split a trailing level indicator (digits or Roman numerals).

    The Roman branch only strips when the remainder is a real word, so plain
    words ending in i/v/x (taxi, ski) are left intact.
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


# --------------------------------------------------------------------------
# Class table
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NameClass:
    """One band of the score.  ``width`` is filled in at import time."""

    key: str
    label: str
    base: int
    length_range: tuple[int, int]
    zipf_floor: float = 0.0
    short_shape: bool = False  # pronounceability applies to this class
    width: int = 0


# Ascending order matters: band width is derived from the next class's base.
_CLASSES: list[NameClass] = [
    NameClass("nothing", "nothing special", 0, (3, 16)),
    NameClass("clean", "clean handle", 30, (3, 16), short_shape=True),
    NameClass("4char_mixed", "4-char mixed", 50, (4, 4), short_shape=True),
    NameClass("4l_random", "4L random", 80, (4, 4), short_shape=True),
    NameClass("compound", "compound / leet / rare", 120, (3, 16), 2.0, True),
    NameClass("4l_pronounceable", "4L pronounceable", 200, (4, 4), 0.0, True),
    NameClass("semi_og", "semi-OG", 350, (3, 16), 2.5),
    NameClass("3char_mixed", "3-char mixed", 400, (3, 3), 0.0, True),
    NameClass("3l_random", "3L random / digits", 450, (3, 3), 0.0, True),
    NameClass("3l_pronounceable", "3L pronounceable", 520, (3, 3), 0.0, True),
    NameClass("og", "OG word", 600, (3, 10), 3.5),
    NameClass("top", "top word", 800, (3, 6), 4.5),
    NameClass("illegal", "illegal characters", 850, (1, 16), 0.0, True),
    NameClass("sub3", "1-2 characters", 900, (1, 2), 0.0, True),
]

for _i, _cls in enumerate(_CLASSES):
    _next = _CLASSES[_i + 1].base if _i + 1 < len(_CLASSES) else _cls.base + 100
    object.__setattr__(_cls, "width", min(99, _next - _cls.base - 1))

_CLASS_BY_KEY: dict[str, NameClass] = {c.key: c for c in _CLASSES}

#: Aliases accepted in the optional third ``class`` column of the overrides
#: file and in tests.  Both class keys and the historical point values work.
_CLASS_ALIASES: dict[str, NameClass] = {}
for _cls in _CLASSES:
    _CLASS_ALIASES[_cls.key] = _cls
    _CLASS_ALIASES[_cls.label.lower()] = _cls
    _CLASS_ALIASES[str(_cls.base)] = _cls
_CLASS_ALIASES.update({
    "top_word": _CLASS_BY_KEY["top"],
    "og_word": _CLASS_BY_KEY["og"],
    "semi": _CLASS_BY_KEY["semi_og"],
    "semi-og": _CLASS_BY_KEY["semi_og"],
    "3l": _CLASS_BY_KEY["3l_pronounceable"],
    "4l": _CLASS_BY_KEY["4l_pronounceable"],
    "sub_3": _CLASS_BY_KEY["sub3"],
    "invalid": _CLASS_BY_KEY["illegal"],
})

#: Legacy 0-80 values in ``rarity_overrides.tsv`` reinterpreted as class floors.
LEGACY_CLASS_HINTS: dict[int, int] = {
    80: 800, 60: 600, 52: 520, 45: 450, 40: 400, 35: 350,
    20: 200, 12: 120, 8: 80, 5: 50, 3: 30, 0: 0,
}


def class_for_score(score: int) -> NameClass:
    """Return the class whose band contains ``score`` (nearest base below)."""
    found = _CLASSES[0]
    for cls in _CLASSES:
        if score >= cls.base:
            found = cls
        else:
            break
    return found


def tier_for_score(score: int) -> str:
    """Tier value for a score: TOP >= 800, OG >= 350, SEMI_OG below.

    Returns the string value (not ``RarityTier``) to keep this module free of
    model imports.  ``src.models.tier_for_score`` wraps it.
    """
    if score >= 800:
        return "top"
    if score >= 350:
        return "og"
    return "semi_og"


# --------------------------------------------------------------------------
# Curated data files
# --------------------------------------------------------------------------

def _parse_class_hint(raw_value: str, raw_class: str = "") -> int:
    """Turn a ``rarity_overrides.tsv`` row into a class floor (0 if unusable)."""
    if raw_class:
        cls = _CLASS_ALIASES.get(raw_class.strip().lower())
        if cls is not None:
            return cls.base
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 0
    # The shipped file uses the historical 0-80 scale; new files also carry an
    # explicit class column, so a bare 2-column value in that scale stays
    # unambiguous (80 -> top word, not 4L random).
    if value in LEGACY_CLASS_HINTS:
        return LEGACY_CLASS_HINTS[value]
    if 0 <= value <= 1000:
        return class_for_score(value).base
    return 0


@lru_cache(maxsize=1)
def _load_rarity_overrides() -> dict[str, int]:
    """Load curated class hints bundled with the data files.

    Format: ``word<TAB>hint[<TAB>class]``.  The hint is either a historical
    0-80 class value or a 0-1000 class base; the optional third column names
    the class directly and wins.  Supplemental lists (multilingual words,
    names, geography, ...) contain many handles the English ``wordfreq`` model
    does not know; this file records the intended class so every consumer
    (generation, filtering, storage, display, audit) agrees.

    Hints are *floors*: they can move a name up a class, never down.
    """
    overrides: dict[str, int] = {}
    path = resource_path("data", "word_lists", "rarity_overrides.tsv")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                word = parts[0].strip().lower()
                if not word:
                    continue
                hint = _parse_class_hint(parts[1], parts[2] if len(parts) > 2 else "")
                if hint:
                    overrides[word] = hint
    except OSError:
        pass
    return overrides


@lru_cache(maxsize=1)
def _german_words() -> frozenset[str]:
    """German dictionary words (``german.txt``).

    mcindex rates German words alongside English ones (OG class).  The bundled
    build ships only English ``wordfreq`` data, so membership in this curated
    list is the detector.
    """
    words: set[str] = set()
    path = resource_path("data", "word_lists", "german.txt")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                word = line.split("\t")[0].strip().lower()
                if word.isalpha():
                    words.add(word)
    except OSError:
        pass
    return frozenset(words)


@dataclass(frozen=True)
class _Pattern:
    regex: re.Pattern
    classes: Optional[frozenset[str]]
    offset: float

    def matches(self, name: str, class_key: str) -> bool:
        if self.classes is not None and class_key not in self.classes:
            return False
        return self.regex.fullmatch(name) is not None


@lru_cache(maxsize=1)
def _patterns() -> tuple[_Pattern, ...]:
    """Curated pattern/culture bonuses (``rarity_patterns.tsv``).

    Format: ``regex<TAB>class<TAB>offset``.  ``class`` is a class key or ``*``.
    ``offset`` is a fraction of the band (-1..1); a match takes the offset with
    the largest magnitude, so a demotion is not cancelled by a small bonus.
    """
    loaded: list[_Pattern] = []
    path = resource_path("data", "word_lists", "rarity_patterns.tsv")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                try:
                    offset = float(parts[2])
                    regex = re.compile(parts[0].strip(), re.IGNORECASE)
                except (ValueError, re.error):
                    continue
                raw_class = parts[1].strip().lower()
                classes = None if raw_class in ("", "*", "any") else frozenset(
                    {raw_class}
                )
                loaded.append(_Pattern(regex, classes, max(-1.0, min(1.0, offset))))
    except OSError:
        pass
    return tuple(loaded)


@lru_cache(maxsize=1)
def _reclaim_risk() -> frozenset[str]:
    """Brand / meme / celebrity names Mojang may reclaim (``reclaim_risk.txt``)."""
    names: set[str] = set()
    path = resource_path("data", "word_lists", "reclaim_risk.txt")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                name = line.split("#", 1)[0].strip().lower()
                if name:
                    names.add(name)
    except OSError:
        pass
    return frozenset(names)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

_LEGAL_NAME = re.compile(r"^[a-z0-9_]+$")
_DECORATION = re.compile(r"_?[a-z]+[0-9]{0,2}_?")


def _classify_alpha(name: str) -> NameClass:
    """Classify an all-letters name (mirrors the historical model's order)."""
    n = len(name)
    z = _zipf(name)
    inflected = _is_inflected(name, z)
    if not inflected and _is_compound_plural(name):
        return _CLASS_BY_KEY["compound"]
    if z >= 4.5 and n <= 6:
        return _CLASS_BY_KEY["semi_og"] if inflected else _CLASS_BY_KEY["top"]
    if z >= 3.5 and n <= 10:
        return _CLASS_BY_KEY["semi_og"] if inflected else _CLASS_BY_KEY["og"]
    if n == 3:
        if _pronounceable(name):
            return _CLASS_BY_KEY["3l_pronounceable"]
        return _CLASS_BY_KEY["3l_random"]
    if z >= 1.0 and n >= 11 and _is_compound(name):
        return _CLASS_BY_KEY["semi_og"]
    if z >= 2.5:
        return _CLASS_BY_KEY["semi_og"]
    if n == 4:
        if _pronounceable(name):
            return _CLASS_BY_KEY["4l_pronounceable"]
        return _CLASS_BY_KEY["4l_random"]
    if _is_compound(name):
        return _CLASS_BY_KEY["compound"]
    if _pronounceable(name):
        return _CLASS_BY_KEY["clean"]
    return _CLASS_BY_KEY["nothing"]


def _classify_mixed(name: str) -> NameClass:
    """Classify names containing digits or underscores."""
    n = len(name)
    if n == 3:
        return _CLASS_BY_KEY["3char_mixed"]
    if n == 4:
        return _CLASS_BY_KEY["4char_mixed"]

    core = name.lstrip("_")
    base, had_suffix = _split_level_suffix(core)
    deleet = base.translate(_LEET_SUBS) if any(c.isdigit() for c in base) else base
    wordy = deleet.isalpha() and _zipf(deleet) > 0
    if had_suffix and wordy:
        # Word plus level/trailing digits (Shadow7, sharpnessV): clean handle.
        return _CLASS_BY_KEY["clean"]

    flat = re.sub(r"[^a-z]", "", name.translate(_LEET_SUBS))
    flat_wordy = flat.isalpha() and _zipf(flat) > 0

    has_middle_underscore = False
    if "_" in core and not core.startswith("_") and not core.endswith("_"):
        parts = core.split("_")
        if len(parts) == 2 and all(p.isalpha() and 2 <= len(p) <= 12 for p in parts):
            has_middle_underscore = True

    modified = (
        core != name
        or (("_" in name) and not has_middle_underscore)
        or deleet != base
    )
    if modified and (flat_wordy or _is_compound(flat)):
        # Minor variant of a real word (_Shadow, Sh4dow, iron_wolf).
        return _CLASS_BY_KEY["compound"]
    if modified:
        if _pronounceable(flat):
            return _CLASS_BY_KEY["clean"]
        return _CLASS_BY_KEY["nothing"]
    return _CLASS_BY_KEY["nothing"]


@lru_cache(maxsize=200_000)
def classify(username: str) -> NameClass:
    """Return the effective class for ``username`` (override floor applied)."""
    name = username.lower()
    if not name:
        return _CLASS_BY_KEY["nothing"]
    if not _LEGAL_NAME.match(name) or len(name) > 16:
        return _CLASS_BY_KEY["illegal"]
    if len(name) <= 2:
        return _CLASS_BY_KEY["sub3"]

    if name.isalpha():
        cls = _classify_alpha(name)
    elif name.isdigit():
        cls = _CLASS_BY_KEY["3l_random"] if len(name) == 3 else _CLASS_BY_KEY["nothing"]
    else:
        cls = _classify_mixed(name)

    # German words rate alongside English ones (OG).  Only promote when the
    # English model has no strong word signal: german.txt is a frequency list
    # and contains some anglicisms ("days", "shadow"), so a name that already
    # reads as a common English word keeps its English class.
    if cls.base < 600 and _zipf(name) < 3.5 and name in _german_words():
        cls = _CLASS_BY_KEY["og"]

    floor = _load_rarity_overrides().get(name, 0)
    if floor > cls.base:
        cls = _CLASS_BY_KEY[class_for_score(floor).key]
    return cls


def base_class(username: str) -> NameClass:
    """Public alias for :func:`classify`."""
    return classify(username)


def base_score(username: str) -> int:
    """Class base for ``username``, before within-class modifiers."""
    return classify(username).base


# --------------------------------------------------------------------------
# Within-class modifiers
# --------------------------------------------------------------------------

#: Weight of each modifier as a fraction of the band.  The maximum positive
#: sum is just under 1.0 (0.996), so a name can approach but never reach the
#: next class's base.  Documented here because these are policy, not facts.
WEIGHTS: dict[str, float] = {
    "frequency": 0.30,        # monotone Zipf, normalized inside the class
    "length": 0.20,           # shorter is better, inside the class's range
    "pronounceability": 0.15,  # 3L/4L shapes only; deliberately weak
    "form": 0.15,             # leet/underscore/trailing-digit purity
    "pattern": 0.20,          # curated repeaters / culture strings
    "reclaim": -0.25,         # brand/meme risk, applied last
}

#: Pronounceability passes only 26% of 3L and 15% of 4L, so it is worth at most
#: 7/12 of its sub-weight (research: "the points are set low").
PRONOUNCEABILITY_VALUE = 7 / 12

#: Zipf value treated as "maximally frequent" for normalization ("the" is 7.7,
#: but frequency is capped so no single common stop word dominates).
_ZIPF_TOP = 6.5


#: Classes where English Zipf frequency is meaningful.  In the shape classes
#: (3L random, 3/4-char mixed, ...) wordfreq's token table returns noise for
#: abbreviation-like strings, so frequency is not used there.
_FREQUENCY_CLASSES = frozenset({
    "top", "og", "semi_og", "compound", "3l_pronounceable", "4l_pronounceable",
})

#: Practical range of the weighted modifier sum inside each class, measured on
#: the built-in 50,409-name corpus.  The sum is mapped linearly from this range
#: onto the class band so the band is actually used: without it, 71% of the
#: corpus sat within 12 points (score 362-374) because the components are
#: concentrated.  Names outside the range clamp to the band edges.
_CLASS_SPREAD: dict[str, tuple[float, float]] = {
    "semi_og": (0.20, 0.46),
    "og": (0.15, 0.45),
    "top": (0.15, 0.66),
    "compound": (0.21, 0.65),
    "3l_pronounceable": (0.44, 0.70),
    "3l_random": (0.30, 0.60),
    "4l_pronounceable": (0.30, 0.60),
}
_DEFAULT_SPREAD = (0.10, 0.60)


def _frequency_value(name: str, cls: NameClass) -> float:
    """Monotone, class-normalized frequency.  0.0 means "neutral"."""
    if cls.key not in _FREQUENCY_CLASSES:
        return 0.0
    z = _zipf(name)
    if z <= 0 or z <= cls.zipf_floor:
        return 0.0
    return min(1.0, (z - cls.zipf_floor) / (_ZIPF_TOP - cls.zipf_floor))


def _length_value(name: str, cls: NameClass) -> float:
    """Shorter is better inside the class's allowed length range."""
    lo, hi = cls.length_range
    if hi <= lo:
        # The class already gates length (3L, 4L); a uniform boost keeps the
        # class ordering intact and avoids inventing a difference.
        return 1.0
    return max(0.0, min(1.0, (hi - len(name)) / (hi - lo)))


def _pronounceability_value(name: str, cls: NameClass) -> float:
    if not cls.short_shape:
        return 0.0
    return PRONOUNCEABILITY_VALUE if _pronounceable(name) else 0.0


def _form_value(name: str, cls: NameClass) -> float:
    """Form purity: clean shape > single decoration > leet/framing.

    "Clean" is relative to the class: in the 3L random / 3-digit class a pure
    digit string is just as pure as a pure letter string.
    """
    if name.isalpha():
        return 1.0
    if cls.key == "3l_random" and name.isdigit():
        return 1.0
    if _DECORATION.fullmatch(name):
        return 0.4
    return 0.0


def _pattern_value(name: str, cls: NameClass) -> float:
    best = 0.0
    for pattern in _patterns():
        if pattern.matches(name, cls.key) and abs(pattern.offset) > abs(best):
            best = pattern.offset
    return best


def _is_reclaim_risk(name: str) -> bool:
    return name in _reclaim_risk()


def within_class_offset(username: str) -> tuple[float, dict[str, float]]:
    """Return ``(total, components)`` where total is in [0, 1].

    ``components`` holds each modifier's *weighted* contribution, i.e. its
    share of the band before the class spread mapping.  ``total`` is the
    mapped share actually added to the base, so it uses the whole band.
    A reclaim-risk name therefore has a negative ``reclaim`` component and
    the total is clamped at 0.
    """
    name = username.lower()
    cls = classify(name)
    components = {
        "frequency": WEIGHTS["frequency"] * _frequency_value(name, cls),
        "length": WEIGHTS["length"] * _length_value(name, cls),
        "pronounceability": WEIGHTS["pronounceability"]
        * _pronounceability_value(name, cls),
        "form": WEIGHTS["form"] * _form_value(name, cls),
        "pattern": WEIGHTS["pattern"] * _pattern_value(name, cls),
        "reclaim": WEIGHTS["reclaim"] * (1.0 if _is_reclaim_risk(name) else 0.0),
    }
    raw = sum(components.values())
    lo, hi = _CLASS_SPREAD.get(cls.key, _DEFAULT_SPREAD)
    if hi <= lo:
        total = 0.0
    else:
        total = (raw - lo) / (hi - lo)
    return max(0.0, min(1.0, total)), components


def score(username: str) -> int:
    """Community desirability score, 0-1000 (higher = more desirable)."""
    cls = classify(username)
    total, _ = within_class_offset(username)
    return cls.base + round(cls.width * total)


def score_breakdown(username: str) -> dict:
    """Full explanation of a score, for ``rank``/``explain``/``score_report``."""
    name = username.lower()
    cls = classify(name)
    total, components = within_class_offset(username)
    offset = round(cls.width * total)
    return {
        "username": username,
        "class": cls.label,
        "class_key": cls.key,
        "base": cls.base,
        "width": cls.width,
        "band": (cls.base, cls.base + cls.width),
        "normalization": _CLASS_SPREAD.get(cls.key, _DEFAULT_SPREAD),
        "modifiers": components,
        "modifier_total": total,
        "offset": offset,
        "score": cls.base + offset,
        "tier": tier_for_score(cls.base + offset),
        "reclaim_risk": _is_reclaim_risk(name),
    }


def label(points: int) -> str:
    """Human-readable class label for a score."""
    return class_for_score(points).label
