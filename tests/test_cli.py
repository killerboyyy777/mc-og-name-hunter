"""Tests for CLI argument parsing helpers."""

import pytest

from src.cli import parse_tiers
from src.models import RarityTier


def test_parse_tiers_accepts_all_supported_names_and_alias():
    assert parse_tiers("top, OG, semi_og,semi") == [
        RarityTier.TOP,
        RarityTier.OG,
        RarityTier.SEMI_OG,
        RarityTier.SEMI_OG,
    ]


@pytest.mark.parametrize("value", ["", ",", "top,", ",og", "unknown", "top,unknown"])
def test_parse_tiers_rejects_unknown_or_empty_entries(value):
    with pytest.raises(ValueError, match="Unknown or empty tier"):
        parse_tiers(value)
