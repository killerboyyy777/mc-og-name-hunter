"""Access token loading and validation tests."""

import base64
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from src import auth


def _jwt(payload: dict) -> str:
    """Return a minimally valid JWT-shaped string for validation tests."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.signature"


@pytest.fixture
def token_env(tmp_path, monkeypatch):
    """Point candidate paths at a temporary data directory."""
    monkeypatch.setattr(
        auth, "_candidate_paths", lambda: [tmp_path / auth.TOKEN_FILENAME]
    )
    return tmp_path / auth.TOKEN_FILENAME


def test_valid_file_token_is_returned(token_env):
    token = _jwt({"exp": time.time() + 3600})
    token_env.write_text(token, encoding="utf-8")
    assert auth.get_access_token() == token


def test_expired_file_token_triggers_refresh(token_env, monkeypatch):
    expired = _jwt({"exp": time.time() - 3600})
    token_env.write_text(expired, encoding="utf-8")

    fresh = _jwt({"exp": time.time() + 3600})
    def fake_refresh():
        token_env.write_text(fresh, encoding="utf-8")
        return True

    monkeypatch.setattr(auth, "_try_silent_refresh", fake_refresh)
    assert auth.get_access_token() == fresh


def test_expired_file_token_without_refresh_returns_none(token_env, monkeypatch):
    expired = _jwt({"exp": time.time() - 3600})
    token_env.write_text(expired, encoding="utf-8")
    monkeypatch.setattr(auth, "_try_silent_refresh", lambda: False)
    assert auth.get_access_token() is None


def test_env_token_wins_when_valid(monkeypatch):
    env_token = _jwt({"exp": time.time() + 3600})
    monkeypatch.setenv("MOJANG_ACCESS_TOKEN", env_token)
    assert auth.get_access_token() == env_token


def test_env_token_ignored_when_expired(monkeypatch, token_env):
    expired_env = _jwt({"exp": time.time() - 3600})
    file_token = _jwt({"exp": time.time() + 3600})
    monkeypatch.setenv("MOJANG_ACCESS_TOKEN", expired_env)
    token_env.write_text(file_token, encoding="utf-8")
    assert auth.get_access_token() == file_token


def test_token_expiry_with_leeway(token_env):
    # Token expiring in 6 minutes is still usable (default leeway is 5 min).
    usable = _jwt({"exp": time.time() + 360})
    token_env.write_text(usable, encoding="utf-8")
    assert auth.get_access_token() == usable

    # Token expiring in 4 minutes is treated as expired so the caller does not
    # get cut off mid-run.
    borderline = _jwt({"exp": time.time() + 240})
    token_env.write_text(borderline, encoding="utf-8")
    assert auth.get_access_token() is None


def test_is_token_valid_handles_malformed_tokens():
    assert auth._is_token_valid("") is False
    assert auth._is_token_valid("not-a-jwt") is True  # unknown format, let API decide
    assert auth._is_token_valid("header.payload") is False  # bad base64
