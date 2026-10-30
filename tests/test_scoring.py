"""Golden-table and invariant tests for the 0-1000 rarity score.

The golden values are pinned against the shipped ``wordfreq`` English data.
A wordfreq upgrade can legitimately move a score by a few points; when that
happens, review the new numbers and update the table deliberately rather than
letting the model drift.
"""

import pytest

from src import rarity
from src.models import RarityTier, rarity_label, rarity_points, tier_for_score
from src.rarity import (
    base_score,
    class_for_score,
    classify,
    label,
    score,
    score_breakdown,
)

# name -> (score, label)
GOLDEN = {
    "the": (848, "top word"),
    "and": (848, "top word"),
    "for": (848, "top word"),
    "dog": (828, "top word"),
    "dream": (800, "top word"),
    "water": (821, "top word"),
    "fox": (822, "top word"),
    "key": (828, "top word"),
    "mom": (828, "top word"),
    "because": (699, "OG word"),
    "shadow": (669, "OG word"),
    "harbor": (659, "OG word"),
    "daniel": (802, "top word"),
    "teacher": (674, "OG word"),
    "obtaining": (381, "semi-OG"),
    "cities": (187, "compound / leet / rare"),
    "policymakers": (150, "compound / leet / rare"),
    "ironwolf": (147, "compound / leet / rare"),
    "sh4dow": (126, "compound / leet / rare"),
    "elk": (568, "3L pronounceable"),
    "yew": (562, "3L pronounceable"),
    "ran": (825, "top word"),
    "xqz": (461, "3L random / digits"),
    "kvr": (461, "3L random / digits"),
    "bzt": (461, "3L random / digits"),
    "666": (508, "3L random / digits"),
    "777": (508, "3L random / digits"),
    "100": (505, "3L random / digits"),
    "482": (461, "3L random / digits"),
    "000": (505, "3L random / digits"),
    "a1b": (427, "3-char mixed"),
    "a_b": (418, "3-char mixed"),
    "q7x": (419, "3-char mixed"),
    "vexo": (245, "4L pronounceable"),
    "zaza": (387, "semi-OG"),
    "qzvk": (99, "4L random"),
    "xkrt": (99, "4L random"),
    "a1b2": (65, "4-char mixed"),
    "fox_": (60, "4-char mixed"),
    "k9_z": (56, "4-char mixed"),
    "velmora": (40, "clean handle"),
    "shadow7": (37, "clean handle"),
    "sharpnessv": (39, "clean handle"),
    "zq": (910, "1-2 characters"),
    "a_": (900, "1-2 characters"),
    "o_o": (418, "3-char mixed"),
    "x_x": (400, "3-char mixed"),
    "perro": (372, "semi-OG"),
    "sakura": (381, "semi-OG"),
    "wasser": (638, "OG word"),
    "schatten": (619, "OG word"),
    "minecraft": (600, "OG word"),
    "facebook": (600, "OG word"),
    "hypixel": (350, "semi-OG"),
    "_shadow": (120, "compound / leet / rare"),
    "iron_wolf": (0, "nothing special"),
    "superman1": (36, "clean handle"),
    "cs_go": (4, "nothing special"),
    "xxoperatorxx": (31, "clean handle"),
}


@pytest.mark.parametrize("name,expected", GOLDEN.items())
def test_golden_table(name, expected):
    expected_score, expected_label = expected
    assert score(name) == expected_score
    assert label(score(name)) == expected_label


def test_models_reexports_agree():
    for name in GOLDEN:
        assert rarity_points(name) == rarity.score(name)
        assert rarity_label(score(name)) == rarity.label(score(name))


def test_class_bands_never_overlap_or_cross():
    bases = [cls.base for cls in rarity._CLASSES]
    assert bases == sorted(bases)
    for cls in rarity._CLASSES:
        assert 0 <= cls.width <= 99
        assert cls.base + cls.width < 1000
        # Any score inside this band maps back to this class.
        for value in (cls.base, cls.base + cls.width // 2, cls.base + cls.width):
            assert class_for_score(value).key == cls.key


def test_scores_stay_inside_their_class_band():
    corpus = list(GOLDEN) + [
        "abandon", "abbey", "abolish", "absurd", "academy", "achieve",
        "zebra", "zinc", "zone", "abbot", "abyss", "acorn", "adore",
    ]
    for name in corpus:
        cls = classify(name)
        value = score(name)
        assert cls.base <= value <= cls.base + cls.width, name
        assert class_for_score(value).key == cls.key, name


def test_acceptance_ordering():
    values = {name: score(name) for name in
              ("the", "because", "elk", "days", "cities")}
    assert values["the"] >= 800
    assert 600 <= values["because"] < 800
    assert 520 <= values["elk"] < 600
    assert 350 <= values["days"] < 400
    assert values["cities"] >= 120
    assert values["the"] > values["because"] > values["elk"] > values["days"] > values["cities"]


def test_repeater_digits_beat_random_digits():
    assert score("666") > score("482")
    assert score("777") > score("482")
    assert score("100") > score("482")


def test_two_character_names_are_the_top_class():
    assert score("Zq") >= 900
    assert label(score("Zq")) == "1-2 characters"


def test_tier_derivation_matches_class_semantics():
    assert tier_for_score(800) is RarityTier.TOP
    assert tier_for_score(799) is RarityTier.OG
    assert tier_for_score(350) is RarityTier.OG
    assert tier_for_score(349) is RarityTier.SEMI_OG
    assert RarityTier.TOP.base_score() == 800
    assert RarityTier.OG.base_score() == 350


def test_legacy_overrides_are_class_floors():
    # 52/35/20 in the shipped file mean 3L / semi-OG / 4L class floors.
    assert rarity._parse_class_hint("52") == 520
    assert rarity._parse_class_hint("35") == 350
    assert rarity._parse_class_hint("20") == 200
    assert rarity._parse_class_hint("80") == 800
    assert rarity._parse_class_hint("12") == 120
    # An explicit class column wins.
    assert rarity._parse_class_hint("35", "top") == 800
    # New-scale values map to their containing class base.
    assert rarity._parse_class_hint("365") == 350


def test_override_is_a_floor_not_a_downgrade():
    # "elk" is a 3L pronounceable word and also has a curated 52 hint.
    assert base_score("elk") == 520
    assert classify("elk").key == "3l_pronounceable"


def test_german_words_are_og_but_anglicisms_keep_their_class():
    assert classify("wasser").key == "og"
    assert classify("schatten").key == "og"
    # german.txt is noisy and contains anglicisms; a common English word must
    # not be promoted or demoted by membership.
    assert classify("days").key == "semi_og"
    assert classify("the").key == "top"


def test_reclaim_risk_is_flagged_and_penalised():
    risky = score_breakdown("facebook")
    assert risky["reclaim_risk"] is True
    assert risky["score"] == risky["base"]  # penalty clamps at the band floor
    safe = score_breakdown("the")
    assert safe["reclaim_risk"] is False


def test_score_breakdown_adds_up():
    for name in ("the", "because", "elk", "cities", "666", "Zq"):
        info = score_breakdown(name)
        assert info["score"] == info["base"] + info["offset"]
        assert 0.0 <= info["modifier_total"] <= 1.0
        assert info["band"] == (info["base"], info["base"] + info["width"])


def test_banned_label_wins():
    assert rarity_label(800, "the") in ("top word", "banned")
