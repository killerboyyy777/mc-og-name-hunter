"""Generator tests: score gate, checked-at-all gate and tier derivation.

The generator decides what gets spent on the rate-limited API, so the two
gates are load-bearing: a name below ``min_score`` is skipped, and any name
already checked (except a retryable error) is skipped regardless of its tier.
"""

import pytest

from src.generators import CandidateGenerator, WordListLoader, _score_to_tier, create_generator
from src.models import RarityTier, tier_for_score
from src.rarity import score


class FakeStorage:
    """Minimal stand-in for :class:`src.storage.Storage`."""

    def __init__(self, checked=()):
        self._checked = set(checked)
        self.bulk_calls = 0

    def get_checked(self):
        self.bulk_calls += 1
        return set(self._checked)

    def is_checked(self, word):
        return word in self._checked


#: Small fixture corpus with one name from each interesting class.
WORDS = [
    ("the", 7.73),        # top word, 848
    ("because", 6.03),    # OG word, 699
    ("elk", 3.49),        # 3L pronounceable, 568
    ("zzzz", 0.0),        # 4L random
    ("qzvk", 0.0),        # 4L random
]


@pytest.fixture
def small_lists(monkeypatch):
    """Serve ``WORDS`` instead of the 50k-row shipped lists."""
    monkeypatch.setattr(
        WordListLoader, "load_all_words",
        lambda self, tier: list(WORDS),
    )
    monkeypatch.setattr(
        WordListLoader, "load_custom_file",
        lambda self, filename: list(WORDS),
    )


def _generate(storage=None, min_score=0, tiers=(RarityTier.TOP, RarityTier.OG,
                                               RarityTier.SEMI_OG)):
    # Filtering (and therefore the filtered-list cache) requires storage.
    generator = CandidateGenerator(
        tiers=list(tiers), min_length=3, max_length=16,
        storage=storage if storage is not None else FakeStorage(),
        min_score=min_score,
    )
    return list(generator.generate())


def test_generator_covers_the_fixture(small_lists):
    names = [c.username for c in _generate()]
    assert names == [w for w, _ in WORDS]


def test_min_score_gate_skips_before_generation(small_lists):
    names = [c.username for c in _generate(min_score=800)]
    assert names == ["the"]

    names = [c.username for c in _generate(min_score=600)]
    assert names == ["the", "because"]


def test_checked_at_all_gate_skips_taken_but_retries_errors(small_lists):
    # "the" is taken; "because" errored last time (absent from get_checked).
    storage = FakeStorage(checked=["the", "qzvk"])
    names = [c.username for c in _generate(storage=storage)]
    assert names == ["because", "elk", "zzzz"]
    assert storage.bulk_calls == 1  # one bulk query, not one per word


def test_tier_is_derived_from_the_score(small_lists):
    candidates = {c.username: c for c in _generate()}
    for name, candidate in candidates.items():
        assert candidate.tier is tier_for_score(score(name))
    assert candidates["the"].tier is RarityTier.TOP
    assert candidates["because"].tier is RarityTier.OG
    assert candidates["elk"].tier is RarityTier.OG
    assert candidates["qzvk"].tier is RarityTier.SEMI_OG


def test_custom_list_is_checked_before_tier_lists(small_lists):
    storage = FakeStorage()
    generator = CandidateGenerator(
        tiers=[RarityTier.SEMI_OG], min_length=3, max_length=16,
        storage=storage, extra_lists=[("custom.txt", RarityTier.SEMI_OG, "custom")],
        min_score=0,
    )
    names = [c.username for c in generator.generate()]
    # Deduped: a name in both lists is yielded once, and the custom source wins.
    assert names == [w for w, _ in WORDS]
    assert all(c.source == "custom" for c in generator.generate())


def test_score_to_tier_matches_the_single_source_of_truth():
    assert _score_to_tier(800) is RarityTier.TOP
    assert _score_to_tier(799) is RarityTier.OG
    assert _score_to_tier(350) is RarityTier.OG
    assert _score_to_tier(349) is RarityTier.SEMI_OG


def test_create_generator_passes_min_score(small_lists):
    generator = create_generator(
        [RarityTier.TOP],
        {"min_length": 3, "max_length": 16, "min_score": 800},
        storage=FakeStorage(),
    )
    assert generator.min_score == 800
    assert [c.username for c in generator.generate()] == ["the"]


def test_generate_with_zero_max_candidates_yields_nothing(small_lists):
    """A ``max_candidates`` of 0 must stop immediately, not run forever."""
    generator = CandidateGenerator(
        tiers=[RarityTier.TOP, RarityTier.OG, RarityTier.SEMI_OG],
        min_length=3, max_length=16,
        storage=FakeStorage(),
        min_score=0,
    )
    assert list(generator.generate(max_candidates=0)) == []
    assert generator.exhausted
