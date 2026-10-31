"""Resolve the Minecraft access token used for authenticated checks.

Order of precedence:
1. ``MOJANG_ACCESS_TOKEN`` environment variable.
2. ``data/mojang_token.txt`` written by ``get_token.py``.

The file fallback makes ``python get_token.py`` a one-time setup step: after it
runs, the sniper picks the token up automatically without exporting anything.
"""

import os
import sys
import json
import time
import base64
from pathlib import Path
from typing import Optional
from mcauth3 import MCMSA, OAuthError

TOKEN_FILENAME = "mojang_token.txt"


def _candidate_paths() -> list[Path]:
    paths = [Path.cwd() / "data" / TOKEN_FILENAME]

    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).parent / "data" / TOKEN_FILENAME)

    paths.append(Path(__file__).resolve().parent.parent / "data" / TOKEN_FILENAME)
    return paths


def _token_expires_at(token: str) -> Optional[float]:
    """Return the JWT ``exp`` claim for a token, or None if not parseable."""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    # Pad to a multiple of 4
    payload_b64 += "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    exp = payload.get("exp")
    return float(exp) if exp is not None else None


def _is_token_valid(token: str, leeway_seconds: int = 300) -> bool:
    """Return True if the token exists and is not within leeway of expiry."""
    if not token:
        return False
    exp = _token_expires_at(token)
    if exp is None:
        # Opaque strings (no dots) are accepted and validated by the API later.
        # JWT-shaped strings that fail parsing are rejected here to avoid using
        # a clearly broken token.
        return "." not in token
    return time.time() + leeway_seconds < exp


def get_access_token() -> Optional[str]:
    """Return a Minecraft access token, or ``None`` if none is available."""
    token = os.environ.get("MOJANG_ACCESS_TOKEN")
    if token and token.strip() and _is_token_valid(token.strip()):
        return token.strip()

    # File tokens are only returned if still valid.  If expired, try silent
    # refresh first; this avoids returning a token that the caller will use
    # and then fail with 401.
    for path in _candidate_paths():
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token and _is_token_valid(token):
            return token

    # Attempt silent refresh
    if _try_silent_refresh():
        for path in _candidate_paths():
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if token and _is_token_valid(token):
                return token

    return None


def _try_silent_refresh() -> bool:
    """Attempt to refresh the token if it has expired."""
    cache_path = Path(__file__).resolve().parent.parent / "data" / "mcauth.json"
    token_path = Path(__file__).resolve().parent.parent / "data" / TOKEN_FILENAME

    if not cache_path.exists():
        return False

    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        refresh_token = (cache.get("tokens") or {}).get("microsoft_refresh_token")
        if not refresh_token:
            return False

        auth = MCMSA()
        result = auth.refresh_auth(refresh_token)
        tokens = result["tokens"]
        token_path.write_text(tokens["minecraft_access_token"], encoding="utf-8")
        # Also update the cache
        cache["tokens"] = tokens
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        return True
    except (ValueError, OSError, OAuthError):
        return False