# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone mc-og-name-hunter executable.

Build (from the repository root):

    python -m PyInstaller --noconfirm --clean mc-og-name-hunter.spec

Use ``python -m PyInstaller`` so the build runs with the interpreter that has
``wordfreq`` installed (the bare ``pyinstaller`` shim may point elsewhere).

Output: ``dist/mc-og-name-hunter.exe`` (single file, console).

``wordfreq`` ships ~60 MB of per-language frequency data, but the rarity
model only ever queries English, so only the English lists are bundled. The
word lists under ``data/word_lists`` are packed into the executable and
resolved at runtime via ``src/paths.py`` (``sys._MEIPASS``).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, get_package_paths

datas = [("data/word_lists", "data/word_lists")]
binaries = []
hiddenimports = collect_submodules("wordfreq")

# English frequency lists only (used by src/models.py via zipf_frequency()).
_wordfreq_dir = get_package_paths("wordfreq")[1]
for _name in ("small_en.msgpack.gz", "large_en.msgpack.gz"):
    datas.append((str(Path(_wordfreq_dir) / "data" / _name), "wordfreq/data"))

# wordfreq's runtime dependencies (static analysis usually finds these, but
# collect_all also has to pull in their data files, e.g. langcodes' data).
for _pkg in ("langcodes", "locate", "ftfy", "regex", "msgpack"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mc-og-name-hunter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
