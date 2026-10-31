#!/usr/bin/env python3
"""Generate focused wordlists for rare/valuable username categories.

The community consensus (docs/name-rarity-community-consensus.md) treats some
structural classes as desirable even when they are not dictionary words:
repeaters, palindromes, keyboard patterns, Roman numerals, and meme/culture
short names.  This script emits small curated lists that can be audited with
``audit_wordlists.py`` instead of checking the entire 3-4 character space.
"""

from pathlib import Path

OUT_DIR = Path("data/word_lists")
VALID = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def is_valid_username(w: str) -> bool:
    return bool(w) and 3 <= len(w) <= 16 and all(c in VALID for c in w)


def write_list(name: str, items: set[str]) -> None:
    path = OUT_DIR / name
    cleaned = sorted({w.lower() for w in items if is_valid_username(w)})
    path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
    print(f"  {name}: {len(cleaned)} names")


def digits_repeaters(length: int = 4) -> set[str]:
    return {str(d) * length for d in range(10)}


def digits_palindromes(length: int = 4) -> set[str]:
    """All n-digit palindromes, e.g. 1221."""
    out = set()
    half = length // 2
    for n in range(10 ** half):
        s = str(n).zfill(half)
        if length % 2 == 0:
            out.add(s + s[::-1])
        else:
            for m in range(10):
                out.add(s + str(m) + s[::-1])
    return out


def digits_sequential(length: int = 4) -> set[str]:
    out = set()
    for start in range(10):
        s = ""
        for i in range(length):
            s += str((start + i) % 10)
        out.add(s)
        # reverse
        out.add(s[::-1])
    return out


def digits_meme() -> set[str]:
    return {
        "1337", "6969", "8008", "4200", "0420", "6666", "7777", "8888",
        "9999", "0000", "1111", "2222", "1234", "4321", "5678", "8765",
        "2468", "8642", "1024", "2024", "2025", "2026", "2019", "2020",
        "2021", "2022", "2023", "2000", "1999", "1984", "1492", "0666",
    }


def keyboard_patterns(min_len: int = 3, max_len: int = 4) -> set[str]:
    rows = [
        "qwertyuiop",
        "asdfghjkl",
        "zxcvbnm",
        "qazwsxedc",
        "rfvtgb",
    ]
    out = set()
    for row in rows:
        for length in range(min_len, max_len + 1):
            for i in range(len(row) - length + 1):
                out.add(row[i:i + length])
                out.add(row[i:i + length][::-1])
    return out


def alpha_palindromes(length: int = 4) -> set[str]:
    out = set()
    if length % 2 == 0:
        for a in range(26):
            for b in range(26):
                s = chr(ord("a") + a) + chr(ord("a") + b)
                out.add(s + s[::-1])
    else:
        for a in range(26):
            for b in range(26):
                for m in range(26):
                    s = chr(ord("a") + a) + chr(ord("a") + b) + chr(ord("a") + m)
                    out.add(s + s[::-1])
    return out


def alpha_repeaters_and_doubled(length: int = 4) -> set[str]:
    out = set()
    # aaaa, bbbb, ...
    for c in "abcdefghijklmnopqrstuvwxyz":
        out.add(c * length)
    # aabb, abab, abba already handled by palindromes
    for a in "abcdefghijklmnopqrstuvwxyz":
        for b in "abcdefghijklmnopqrstuvwxyz":
            out.add(a + a + b + b)
            out.add(a + b + a + b)
    return out


def roman_numerals(max_value: int = 3999, min_len: int = 3, max_len: int = 8) -> set[str]:
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syb = ["m", "cm", "d", "cd", "c", "xc", "l", "xl", "x", "ix", "v", "iv", "i"]
    out = set()
    for num in range(1, max_value + 1):
        n = num
        s = ""
        for i, v in enumerate(val):
            while n >= v:
                n -= v
                s += syb[i]
        if min_len <= len(s) <= max_len:
            out.add(s)
    return out


def underscore_patterns() -> set[str]:
    out = set()
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    for c in chars:
        out.add(f"_{c}_")
        out.add(f"__{c}")
        out.add(f"{c}__")
        out.add(f"_{c}{c}")
        out.add(f"{c}{c}_")
    # triple and quadruple underscore
    out.add("___")
    out.add("____")
    return out


def mixed_2l2d_patterns() -> set[str]:
    """Patterns like aa00, a0a0, a00a, 0aa0."""
    out = set()
    chars = "abcdefghijklmnopqrstuvwxyz"
    digits = "0123456789"
    for a in chars:
        for d in digits:
            out.add(f"{a}{a}{d}{d}")
            out.add(f"{a}{d}{a}{d}")
            out.add(f"{a}{d}{d}{a}")
            out.add(f"{d}{a}{a}{d}")
            out.add(f"{d}{a}{d}{a}")
            out.add(f"{d}{d}{a}{a}")
    return out


def meme_culture_short() -> set[str]:
    return {
        # Social platforms / brands
        "tiktok", "twitch", "discord", "reddit", "twitter", "youtube", "netflix",
        "spotify", "steam", "roblox", "minecraft", "notch", "mojang", "hypixel",
        "facebook", "google", "apple", "amazon", "tesla", "nvidia", "intel",
        "amd", "xbox", "playstation", "nintendo", "sega", "atari",
        # Memes / culture
        "pepe", "doge", "wojak", "chad", " Karen", " based", "sigma", "alpha",
        "beta", "omega", "chungus", "yeet", "sus", "impostor", "amongus",
        "creeper", "herobrine", "enderman", "enderdragon", "wither", "steve",
        "alex", "villager", "creepa", "hiss", "boomer", "zoomer", "doomer",
        "coomer", "wagie", "neet", "gamer", "streamer", "vtuber", "esports",
        # Crypto/web slang
        "bitcoin", "ethereum", "crypto", "nft", "defi", "hodl", "moon", "whale",
        # Short handles
        "lol", "lmao", "omg", "wtf", "brb", "afk", "gg", "ez", "noob", "pro",
        "pog", "poggers", "kek", "lolz", "rofl", "cya", "ty", "np", "tyvm",
        # Numbers/memes
        "uwu", "owo", "rawr", "xd", "xdd", "lul", "kappa", "monka", "pepega",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating rare-category wordlists...")

    write_list("rare_4digit_repeaters.txt", digits_repeaters(4))
    write_list("rare_4digit_palindromes.txt", digits_palindromes(4))
    write_list("rare_4digit_sequential.txt", digits_sequential(4))
    write_list("rare_4digit_meme.txt", digits_meme())
    write_list("rare_3digit_special.txt", {"666", "777", "888", "999", "000", "100", "111", "222", "333", "444", "555", "123", "321", "420", "911", "007", "101", "404", "911", "133", "313"})
    write_list("rare_keyboard_3_4.txt", keyboard_patterns(3, 4))
    write_list("rare_alpha_palindromes_4.txt", alpha_palindromes(4))
    write_list("rare_alpha_repeaters_4.txt", alpha_repeaters_and_doubled(4))
    write_list("rare_roman_numerals.txt", roman_numerals())
    write_list("rare_underscore_patterns.txt", underscore_patterns())
    write_list("rare_mixed_2l2d.txt", mixed_2l2d_patterns())
    write_list("rare_meme_culture.txt", meme_culture_short())

    print("\nDone. Suggested audit command:")
    print("  python audit_wordlists.py --lists rare_4digit_repeaters.txt rare_4digit_palindromes.txt rare_4digit_sequential.txt rare_4digit_meme.txt rare_3digit_special.txt rare_keyboard_3_4.txt rare_alpha_palindromes_4.txt rare_alpha_repeaters_4.txt rare_roman_numerals.txt rare_underscore_patterns.txt rare_mixed_2l2d.txt rare_meme_culture.txt --min-score 0 --public-rps 1.5 --auth-rps 0.06")


if __name__ == "__main__":
    main()
