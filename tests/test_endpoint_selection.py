"""Tests for selecting endpoints compatible with Minecraft usernames."""

from src.checkers import (
    AsyncPublicChecker,
    CANONICAL_PUBLIC_ENDPOINT,
    THIRD_PARTY_ENDPOINTS,
)


class FakeRateLimiter:
    def acquire(self):
        pass


def test_non_alphabetic_names_never_fall_back_to_third_party_endpoints():
    checker = AsyncPublicChecker(rate_limiter=FakeRateLimiter())
    canonical = checker.endpoint_stats[CANONICAL_PUBLIC_ENDPOINT]
    canonical.requests = 1
    canonical.errors = 1  # Mark the only compatible endpoint unhealthy.

    selected = checker._select_endpoint("name_123")

    assert selected == CANONICAL_PUBLIC_ENDPOINT
    assert selected not in THIRD_PARTY_ENDPOINTS


def test_alphabetic_names_can_use_healthy_third_party_endpoints():
    checker = AsyncPublicChecker(rate_limiter=FakeRateLimiter())

    assert checker._select_endpoint("username").startswith("https://")
