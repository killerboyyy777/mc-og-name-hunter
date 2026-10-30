"""Candidate username generators by rarity tier."""

from pathlib import Path
from typing import Generator, Optional
from src.models import UsernameCandidate, RarityTier, rarity_points, tier_for_score
from src.paths import default_wordlist_dir


class WordListLoader:
    """Load and manage word lists from files."""
    
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or default_wordlist_dir())
        self._cache: dict[str, list[tuple[str, float]]] = {}
    
    def load_tier(self, tier: RarityTier) -> list[tuple[str, float]]:
        """Load words for a specific tier: returns list of (word, zipf)."""
        key = f"words_{tier.value}"
        if key not in self._cache:
            self._cache[key] = self._load_file(f"words_{tier.value}.txt")
        return self._cache[key]
    
    def load_firstnames(self, tier: RarityTier) -> list[tuple[str, float]]:
        """Load first names for a specific tier."""
        key = f"firstnames_{tier.value}"
        if key not in self._cache:
            self._cache[key] = self._load_file(f"firstnames_{tier.value}.txt")
        return self._cache[key]
    
    def _load_file(self, filename: str) -> list[tuple[str, float]]:
        """Load words from a tab-separated file: word\tzipf.

        Also accepts plain one-word-per-line files (zipf defaults to 0.0),
        which is the format used for custom word lists.
        """
        filepath = self.base_path / filename
        words = []
        if filepath.exists():
            with open(filepath, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split('\t')
                    word = parts[0].lower()
                    if len(parts) >= 2:
                        try:
                            zipf = float(parts[1])
                        except ValueError:
                            zipf = 0.0
                    else:
                        zipf = 0.0
                    words.append((word, zipf))
        return words
    
    def load_custom_file(self, filename: str) -> list[tuple[str, float]]:
        """Load a custom word list file (tier files or plain word lists)."""
        key = f"custom_{filename}"
        if key not in self._cache:
            self._cache[key] = self._load_file(filename)
        return self._cache[key]
    
    def load_all_words(self, tier: RarityTier) -> list[tuple[str, float]]:
        """Load both dictionary words and first names for a tier."""
        words = self.load_tier(tier)
        words.extend(self.load_firstnames(tier))
        return words


def _score_to_tier(points: int) -> RarityTier:
    """Derive the generation tier from the 0-1000 score.

    TOP >= 800, OG >= 350, SEMI_OG below; one source of truth (see
    ``src.rarity.tier_for_score``).
    """
    return tier_for_score(points)


class CandidateGenerator:
    """Generate username candidates tier by tier."""
    
    def __init__(
        self,
        tiers: list[RarityTier],
        min_length: int = 3,
        max_length: int = 16,
        storage=None,
        extra_lists: Optional[list[tuple[str, RarityTier, str]]] = None,
        min_score: int = 0,
    ):
        self.tiers = sorted(tiers, key=lambda t: t.sort_order)
        self.min_length = min_length
        self.max_length = max_length
        self.storage = storage
        self.loader = WordListLoader()
        # Custom word lists as (filename, tier, source_label) tuples.
        # Checked before the built-in tier lists (explicit user request).
        self.extra_lists = extra_lists or []
        # Score gate: candidates scoring below this are skipped before any API
        # call. Scope is "rarest free names", so low-value names are not worth
        # spending the rate-limited request budget on.
        self.min_score = min_score
        self._exhausted = False
        self._total_candidates = 0
        self._filtered_cache: dict[str, list[tuple[str, float]]] = {}
        self._checked: Optional[set[str]] = None
        self._prefilter_words()
    
    def _prefilter_words(self):
        """Pre-filter word lists against already-checked database."""
        if not self.storage:
            return
        
        print("Pre-filtering word lists against checked database...")
        total_before = 0
        total_after = 0
        
        # Bulk-load the checked-at-all set once so large lists (e.g. all
        # 3/4-letter combos) filter in memory instead of one DB query per word.
        # The set is reused by _generate_from_list during generation.
        self._checked = self.storage.get_checked()

        def keep(word: str, tier: RarityTier) -> bool:
            if rarity_points(word) < self.min_score:
                return False
            return not self._is_checked(word)
        
        for filename, tier, source_label in self.extra_lists:
            # Load custom word list (plain or tab-separated format)
            all_words = self.loader.load_custom_file(filename)
            total_before += len(all_words)
            
            # Filter out low-rarity words and already checked names
            filtered = [
                (word, zipf) for word, zipf in all_words
                if keep(word, tier)
            ]
            total_after += len(filtered)
            
            # Cache filtered list
            self._filtered_cache[f"custom_{filename}_{tier.value}"] = filtered
        
        for tier in self.tiers:
            # Load all words for this tier (dictionary + first names)
            all_words = self.loader.load_all_words(tier)
            total_before += len(all_words)
            
            # Filter out low-rarity words and already checked names
            filtered = [
                (word, zipf) for word, zipf in all_words
                if keep(word, tier)
            ]
            total_after += len(filtered)
            
            # Cache filtered list
            self._filtered_cache[f"{tier.value}"] = filtered
        
        self._total_candidates = total_after
        print(f"Filtered {total_before} -> {total_after} words "
              f"({total_before - total_after} dropped: already checked or below {self.min_score} score)")
    
    def _is_checked(self, word: str) -> bool:
        """Check if a word was already checked (checked-at-all gate).

        Uses the bulk-loaded set when available, otherwise queries storage.
        Any non-error/non-rate-limited row counts, regardless of tier.
        """
        if self._checked is not None:
            return word in self._checked
        if self.storage:
            return self.storage.is_checked(word)
        return False
    
    @property
    def total_candidates(self) -> int:
        """Return total number of candidates that will be generated."""
        return self._total_candidates
    
    @property
    def exhausted(self) -> bool:
        return self._exhausted
    
    def generate(self, max_candidates: Optional[int] = None) -> Generator[UsernameCandidate, None, None]:
        """Generate candidates: custom lists first, then tier priority order."""
        yielded = 0
        # Dedupe within a single run: the same name can appear in several
        # custom lists (and variant generation can collide across words).
        # Usernames are case-insensitively unique, so track emitted names
        # lower-cased and never yield one twice, avoiding duplicate API calls.
        emitted: set[str] = set()

        def remaining() -> Optional[int]:
            return (max_candidates - yielded) if max_candidates else None

        for filename, tier, source_label in self.extra_lists:
            if max_candidates and yielded >= max_candidates:
                break
            
            words = self._filtered_cache.get(f"custom_{filename}_{tier.value}", [])
            
            for candidate in self._generate_from_list(
                words, tier, source_label, remaining(), emitted
            ):
                yield candidate
                yielded += 1
                if max_candidates and yielded >= max_candidates:
                    break
        
        for tier in self.tiers:
            if max_candidates and yielded >= max_candidates:
                break
            
            # Get pre-filtered words for this tier
            words = self._filtered_cache.get(f"{tier.value}", [])
            
            for candidate in self._generate_from_list(
                words, tier, "dictionary", remaining(), emitted
            ):
                yield candidate
                yielded += 1
                if max_candidates and yielded >= max_candidates:
                    break
        
        self._exhausted = True

    def _generate_from_list(
        self,
        words: list[tuple[str, float]],
        tier: RarityTier,
        source: str,
        remaining: Optional[int] = None,
        emitted: Optional[set[str]] = None,
    ) -> Generator[UsernameCandidate, None, None]:
        """Generate candidates from a word list."""
        yielded = 0
        
        for word, zipf in words:
            if remaining and yielded >= remaining:
                break
            
            # Validate length
            if not (self.min_length <= len(word) <= self.max_length):
                continue

            # Dedupe across lists/variants within this run.
            key = word.lower()
            if emitted is not None:
                if key in emitted:
                    continue
                emitted.add(key)
            
            # Calculate the actual score for this word
            points = rarity_points(word)

            # Score gate: skip anything that cannot be a rare name.
            if points < self.min_score:
                continue

            actual_tier = _score_to_tier(points)
            
            # Skip if already checked (checked-at-all gate)
            if self._is_checked(word):
                continue
            
            # Base candidate with tier based on actual rarity
            yield UsernameCandidate(
                username=word,
                tier=actual_tier,
                zipf=zipf,
                source=source,
            )
            yielded += 1


def create_generator(
    tiers: list[RarityTier],
    config: dict,
    storage=None,
    extra_lists: Optional[list[tuple[str, RarityTier, str]]] = None,
) -> CandidateGenerator:
    """Factory function to create generator from config."""
    return CandidateGenerator(
        tiers=tiers,
        min_length=config.get("min_length", 3),
        max_length=config.get("max_length", 16),
        storage=storage,
        extra_lists=extra_lists,
        min_score=config.get("min_score", 0),
    )