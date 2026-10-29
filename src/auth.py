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


def get_access_token() -> Optional[str]:
    """Return a Minecraft access token, or ``None`` if none is available."""
    token = os.environ.get("MOJANG_ACCESS_TOKEN")
    if token and token.strip():
        return token.strip()

    for path in _candidate_paths():
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token:
            return token

    # Attempt silent refresh
    if _try_silent_refresh():
        for path in _candidate_paths():
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if token:
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