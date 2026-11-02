#!/usr/bin/env python3
"""Build ``data/word_lists/german_og.txt``: German words common enough for OG.

Only German words with ``zipf_frequency(word, "de") >= THRESHOLD`` keep the OG
class.  ``german.txt`` is a wide lemma list that also carries administrative and
technical vocabulary (``bistum``, ``belagerung``, ``bushaltestelle``) and
inflected forms; wordfreq puts all of those on its 3.6 floor, while everyday
German (``haus`` 5.4, ``stadt`` 5.7) sits far above.

The frozen build bundles English wordfreq data only, so the German value is
computed here, once, and shipped as a list.  ``german.txt`` stays in place: it
is still the dictionary used for inflection detection.

    python generate_german_og.py
"""

import sys
from pathlib import Path

from wordfreq import zipf_frequency

from src.paths import default_wordlist_dir

THRESHOLD = 4.0


def main() -> int:
    list_dir = Path(default_wordlist_dir())
    source = list_dir / "german.txt"
    target = list_dir / "german_og.txt"

    words = []
    for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        word = line.split("\t")[0].strip().lower()
        if word.isalpha():
            words.append(word)

    kept = sorted(
        (w for w in set(words) if zipf_frequency(w, "de") >= THRESHOLD),
        key=lambda w: (len(w), w),
    )

    target.write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(
        f"{len(set(words)):,} German words -> {len(kept):,} at "
        f"zipf(de) >= {THRESHOLD} ({len(kept) / max(len(set(words)), 1):.0%}) "
        f"-> {target}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
