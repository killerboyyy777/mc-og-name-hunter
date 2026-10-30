"""Configuration loading.

Precedence for every setting (highest wins):

    1. CLI flags (see ``main()`` in :mod:`src.cli`)
    2. Config file (``config.yaml``, or a path passed with ``--config``)
    3. ``DEFAULTS`` below (reasonable out-of-the-box values)

The CLI seeds each argparse option's default from here, so a flag only needs
to be supplied when it should differ from the config file / defaults.
"""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config.yaml"

# Single source of truth for reasonable defaults. Every key may be overridden
# by the config file, and most have a matching CLI flag that overrides both.
DEFAULTS: dict[str, Any] = {
    "generation": {
        "tiers": "top,og,semi_og",
        "max_candidates": 50000,
        "min_score": 0,
        "min_length": 3,
        "max_length": 16,
    },
    "checking": {
        "public_api": "https://api.mojang.com/users/profiles/minecraft/",
        "auth_api": "https://api.minecraftservices.com/minecraft/profile/name/",
        "verify_auth": True,
        "batch_size": 50,
        "concurrency": 10,
    },
    "rate_limit": {
        "requests_per_second": 1.5,
        "burst": 10,
        "backoff_base_seconds": 2.0,
    },
    "snipe": {
        "hits": 5,
        "output": "data/available.txt",
        "tui": False,
        "wordlists": [],
    },
    "check": {
        "output": "data/available.txt",
    },
    "validate": {
        "max": 1000,
        "output": "data/available.txt",
    },
    "storage": {
        "db_path": "data/checked.db",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively overlay ``override`` on a copy of ``base``."""
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load the config file merged over :data:`DEFAULTS`.

    A missing default file is fine (defaults are returned); an explicitly
    requested file that does not exist raises ``FileNotFoundError`` so a typo
    does not silently fall back to defaults.
    """
    if config_path is None:
        path = Path(DEFAULT_CONFIG_PATH)
        required = False
    else:
        path = Path(config_path)
        required = True

    file_config: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}
        if not isinstance(file_config, dict):
            raise ValueError(f"Config file {path} must contain a YAML mapping")
    elif required:
        raise FileNotFoundError(f"Config file not found: {path}")

    return _migrate_legacy_keys(_deep_merge(DEFAULTS, file_config), file_config)


def _migrate_legacy_keys(merged: dict, file_config: dict) -> dict:
    """Translate removed config keys in place.

    ``generation.min_points`` was the old 0-80 rarity gate; it is honoured as
    ``min_points x 10`` on the 0-1000 scale, but only when ``min_score`` is not
    set (an explicit new key always wins).
    """
    generation = (file_config or {}).get("generation")
    if not isinstance(generation, dict) or "min_points" not in generation:
        return merged
    if "min_score" not in generation:
        try:
            merged["generation"]["min_score"] = int(generation["min_points"]) * 10
            print(
                "Config: generation.min_points is deprecated; "
                f"{generation['min_points']} -> min_score "
                f"{merged['generation']['min_score']} (0-1000 scale)."
            )
        except (TypeError, ValueError):
            pass
    merged["generation"].pop("min_points", None)
    return merged


def find_config_path(argv: list[str]) -> str | None:
    """Pre-scan ``argv`` for ``--config``/``-c`` before argparse runs.

    Config values seed the parser defaults, so the file must be located before
    the parser is built. Supports ``--config PATH``, ``-c PATH`` and
    ``--config=PATH``.
    """
    for i, arg in enumerate(argv):
        if arg in ("--config", "-c"):
            if i + 1 < len(argv):
                return argv[i + 1]
        elif arg.startswith("--config=") or arg.startswith("-c="):
            return arg.split("=", 1)[1]
    return None


def get_config_value(config: dict, key: str, default: Any = None) -> Any:
    """Get a nested config value using dot notation.

    e.g. ``get_config_value(cfg, "rate_limit.requests_per_second", 1.5)``.
    """
    value: Any = config
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default
    return value
