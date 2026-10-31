"""Token bucket rate limiter tests."""

import json
import os
import time
from pathlib import Path

import pytest

from src.rate_limiter import TokenBucket


def test_load_state_accounts_for_elapsed_time_and_does_not_double_refill():
    """A saved state with zero tokens from 10s ago should refill to burst."""
    with _temp_state({"tokens": 0.0, "timestamp": time.monotonic() - 10}) as state:
        bucket = TokenBucket(rate=1.0, burst=5, state_file=str(state))
        assert bucket._tokens == 5.0

        # The elapsed time was consumed by _load_state.  A tiny sleep and take
        # should only add that tiny amount, not another 10 seconds.
        time.sleep(0.05)
        bucket.take(1)
        assert 3.5 <= bucket._tokens <= 4.5


def test_load_state_uses_defaults_on_corrupt_file():
    with _temp_state("not json") as state:
        bucket = TokenBucket(rate=1.0, burst=5, state_file=str(state))
        assert bucket._tokens == 5.0


def test_take_blocks_until_token_available():
    with _temp_state({"tokens": 0.0, "timestamp": time.monotonic()}) as state:
        bucket = TokenBucket(rate=10.0, burst=1, state_file=str(state))
        start = time.monotonic()
        assert bucket.take(1) is True
        elapsed = time.monotonic() - start
        assert elapsed >= 0.08  # ~0.1s to earn one token at 10/s


@pytest.fixture
def isolated_bucket(tmp_path):
    """Return a bucket that never reads an existing state file."""
    return TokenBucket(rate=10.0, burst=5, state_file=str(tmp_path / "state.json"))


def test_available_tokens_reflects_refill(isolated_bucket):
    isolated_bucket.take(1)
    time.sleep(0.1)
    assert isolated_bucket.available_tokens > 0.5


def _temp_state(data):
    """Context manager that writes data to a temporary state file."""
    import tempfile

    class _Ctx:
        def __enter__(self):
            self.fd, self.path = tempfile.mkstemp(suffix=".json")
            Path(self.path).write_text(
                json.dumps(data) if isinstance(data, dict) else str(data),
                encoding="utf-8",
            )
            return Path(self.path)

        def __exit__(self, *exc):
            os.close(self.fd)
            Path(self.path).unlink(missing_ok=True)

    return _Ctx()
