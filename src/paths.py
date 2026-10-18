"""Filesystem path helpers that are aware of frozen (PyInstaller) builds.

In a normal source checkout the read-only assets (word lists) live at
``data/word_lists`` relative to the repository root. A one-file PyInstaller
build instead unpacks bundled assets into a temporary directory exposed as
``sys._MEIPASS``, so the generator has to resolve them differently.
"""

import sys
from pathlib import Path

#: Default word-list location relative to the working directory / repo root.
WORDLIST_DIR = "data/word_lists"


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) frozen bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory holding bundled read-only assets.

    For a frozen one-file build this is the temporary extraction directory
    (``sys._MEIPASS``); otherwise it is the repository root.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled asset, e.g. ``resource_path("data", "word_lists")``."""
    return resource_root().joinpath(*parts)


def default_wordlist_dir() -> str:
    """Word-list directory to use: bundled assets when frozen, else the default."""
    if is_frozen():
        return str(resource_path("data", "word_lists"))
    return WORDLIST_DIR
