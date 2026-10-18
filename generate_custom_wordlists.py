#!/usr/bin/env python3
"""Generate custom word lists: short combos, digits, faces, Halloween,
gaming terms, German words, and Minecraft items.

The Minecraft items list merges a hand-curated base (concepts, common
names, wood/wool/material expansions) with the authoritative
PrismarineJS minecraft-data registry (items, blocks, entities,
enchantments, effects, biomes) so it stays complete as the game updates.
The registry fetch needs network; use --offline to skip it and use only
the hand-curated base.
"""

import argparse
import itertools
import json
import string
import tempfile
import urllib.request
from pathlib import Path

# Community-maintained list of blocked/offensive words (lowercase).
# This list approximates Mojang's username blocking policy while avoiding
# known false positives that the Minecraft community has identified.
# Note: Mojang's exact blocked list is not publicly documented, but community
# testing has identified certain words that are consistently blocked vs. falsely blocked.
_BANNED_WORDS: set[str] = set()


def _init_banned_words() -> None:
    """Initialize the banned words list with words Mojang blocks."""
    banned = [
        # Genuinely vulgar/sexual terms (these are consistently blocked by Mojang)
        "anal", "anus", "ass", "asshole", "bitch", "blowjob", "cum", "cumming",
        "cunt", "dick", "fuck", "fucking", "git", "horny", "jap", "kike",
        "mistress", "nigga", "nigger", "pee", "penis", "piss", "poop", "shit",
        "shitty", "slut", "spunk", "twat", "vagina", "wet", "whore",
        # Hate speech and discriminatory terms
        "racist", "nazi", "supremacist", "sexist", "transphobic", "homophobic",
        "negro", "negroes", "slavery", "apartheid",
        # Drug/alcohol related (Mojang blocks these in usernames)
        "cocaine", "heroin", "lsd", "mdma", "marijuana", "weed", "opium",
        # Violence and harmful content
        "hitman", "killer", "murder", "rapist", "terrorist",
# Self-harm / death references (Mojang blocks these)
        "die", "death", "suicide", "suicidal", "kill", "killing", "killed",
        "selfharm", "self-harm", "cutting", "overdose",
        # Explicit content / sexual
        "porn", "porno", "xxx", "sex", "sexy", "nude", "naked",
        "erotic", "fetish", "kink", "bdsm",
        "herpes",
        # Sexual violence / extreme
        "rape", "rapist", "raping", "molest", "molester", "pedo", "pedophile",
        "cp", "csam", "childporn",
        # Explicit anatomy
        "cock", "cocks", "pussy", "cunt", "clit", "dick", "penis", "vagina",
        "anus", "asshole", "butthole", "nipple", "erection", "sperm",
        "tits", "tit", "boobs", "boob", "playboy",
        "milf", "dildo", "bondage", "genital",
        "semen", "testicles",
        # Homophobic slurs and common leet/abbreviated variants (Mojang blocks these)
        "fag", "faggot", "fuc", "fck", "fvk", "f4g",
        # Sexual acts / prostitution
        "intercourse", "prostitute", "prostitutes", "whore", "whores",
        "hooker", "hookers", "escort", "escorts",
        "suck", "sucked", "sucking", "blowjob", "handjob", "rimjob",
        "masturbate", "masturbation", "orgasm", "cum", "cumming",
        "orgy", "shag",
        # Violence / weapons
        "slaughter", "murder", "murderer", "assassin", "assassinate",
        "massacre", "genocide", "violence", "violent",
        "gun", "guns", "shoot", "shooting", "shot", "stab", "knife",
        "bomb", "explosive", "grenade", "missile",
        # Hate figures / extremism
        "hitler", "nazi", "fascist", "kkk", "klan", "aryan", "supremacist",
        "antisemitic", "antisemite", "holocaust",
        # Ableist slurs
        "retard", "retarded", "retardation", "spastic", "spaz",
        "cripple", "crippled", "mong", "mongoloid",
        # Mild profanity / offensive
        "damn", "dammit", "damnit", "goddamn", "goddamnit", "hell",
        "crap", "crap", "crap",
        "assclown", "asspirin", "bastard", "bitchass", "bullshit", "crap",
        "dickhead", "dickwipe", "fuckface", "fuckhead", "motherfucker",
        "shithead", "shitfuck", "shithead",
        "gtfo",
        # Drug references
        "drugs", "drug", "high", "stoned", "drunk", "wasted",
    ]
    for word in banned:
        _BANNED_WORDS.add(word.lower())

_init_banned_words()


def add_banned_word(word: str) -> None:
    """Add a word to the banned words list (normalized to lowercase)."""
    _BANNED_WORDS.add(word.lower().strip())


# Known false positives from Mojang's username filter that should NOT be blocked:
# These words have been reported by the Minecraft community as incorrectly blocked.
# Note: These are based on community reports (Minecraft Feedback posts), not
# independently verified against the API. The API should be the final authority.
_FALSE_POSITIVES: set[str] = {
    "furry",  # Reported blocked unnecessarily (Minecraft Feedback Mar 2026)
    "gay",    # Reported blocked, considered silencing (Minecraft Feedback Mar 2026)
    "homosexual",  # Reported blocked (Minecraft Feedback Mar 2026)
    "trans",  # Reported blocked (Minecraft Feedback Jun 2026)
    "hoe",    # Reported blocked - tool name (Minecraft Feedback Mar 2026)
    # Note: "terf", "tucute" removed - unverified, context-dependent
}

def is_banned(username: str) -> bool:
    """Check if a username contains or matches a banned word."""
    name = username.lower().strip()
    # Check _FALSE_POSITIVES first - these are NEVER banned per community findings
    if name in _FALSE_POSITIVES:
        return False
    # Exact match against real banned words
    if name in _BANNED_WORDS:
        return True
    # Check if any banned word is a substring (but skip false positives)
    for banned in _BANNED_WORDS:
        if banned and banned in name and name not in _FALSE_POSITIVES:
            return True
    return False


def load_banned_words(path: Path) -> None:
    """Load banned words from a file (one per line)."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            word = line.strip().lower()
            if word and word not in _FALSE_POSITIVES:
                _BANNED_WORDS.add(word)


def save_banned_words(path: Path) -> None:
    """Save the current banned words list to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write real banned words, excluding false positives
    words_to_save = _BANNED_WORDS - _FALSE_POSITIVES
    with open(path, "w", encoding="utf-8") as f:
        for word in sorted(words_to_save):
            f.write(word + "\n")

OFFICIAL_DATA_VERSION = "26.1"
OFFICIAL_BASE_URL = (
    "https://raw.githubusercontent.com/PrismarineJS/minecraft-data"
    "/master/data/pc"
)
OFFICIAL_FILES = (
    "items.json",
    "blocks.json",
    "entities.json",
    "enchantments.json",
    "effects.json",
    "biomes.json",
)


def fetch_official_names(version: str = OFFICIAL_DATA_VERSION) -> set[str]:
    """Fetch raw item/block/entity registry names from minecraft-data.

    Returns an empty set (with a warning) if the network fetch fails,
    so generation still works offline with the hand-curated base list.
    """
    names: set[str] = set()
    tmpdir = Path(tempfile.gettempdir()) / "mcusersnipe-official"
    tmpdir.mkdir(parents=True, exist_ok=True)
    for filename in OFFICIAL_FILES:
        url = f"{OFFICIAL_BASE_URL}/{version}/{filename}"
        dest = tmpdir / f"{version}_{filename}"
        try:
            if not dest.exists():
                print(f"downloading {url} ...")
                urllib.request.urlretrieve(url, dest)
            with open(dest, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"WARNING: could not fetch {url}: {e}")
            continue
        entries = data.values() if isinstance(data, dict) else data
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw = entry.get("name") or entry.get("displayName") or ""
            if raw:
                names.add(str(raw))
    print(f"official registry names: {len(names)} (version {version})")
    return names


def fetch_enchantment_levels(
    version: str = OFFICIAL_DATA_VERSION,
) -> dict[str, int]:
    """Fetch enchantment max levels from minecraft-data.

    Returns {enchantment_name: maxLevel}. Empty dict (with a warning) if
    the fetch fails, so generation still works offline.
    """
    tmpdir = Path(tempfile.gettempdir()) / "mcusersnipe-official"
    tmpdir.mkdir(parents=True, exist_ok=True)
    url = f"{OFFICIAL_BASE_URL}/{version}/enchantments.json"
    dest = tmpdir / f"{version}_enchantments.json"
    try:
        if not dest.exists():
            print(f"downloading {url} ...")
            urllib.request.urlretrieve(url, dest)
        with open(dest, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"WARNING: could not fetch {url}: {e}")
        return {}
    levels: dict[str, int] = {}
    entries = data.values() if isinstance(data, dict) else data
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        max_level = entry.get("maxLevel", 1)
        if name and isinstance(max_level, int) and max_level > 1:
            levels[str(name)] = max_level
    print(f"official enchantments with levels: {len(levels)} (version {version})")
    return levels


def generate_short_combos(output_path: Path) -> int:
    """Write all lowercase a-z 3-letter then 4-letter combinations.

    26^3 + 26^4 = 17,576 + 456,976 = 474,552 entries.
    Shorter (3-letter) combos come first since shorter = rarer.
    """
    alphabet = string.ascii_lowercase
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for length in (3, 4):
            for combo in itertools.product(alphabet, repeat=length):
                f.write("".join(combo) + "\n")
                count += 1
    print(f"short combos: {count} names -> {output_path}")
    return count


def generate_digit_combos(output_path: Path) -> int:
    """Write all 3-digit combinations (000-999, exactly 1,000 entries).

    The community rates 3-digit names (777, 911, 666) as collectible.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for n in range(1000):
            f.write(f"{n:03d}\n")
    print(f"digit combos: 1000 names -> {output_path}")
    return 1000


def generate_underscore_pairs(output_path: Path) -> int:
    """Write all 2-letter combos with one underscore (AB_, _AB, A_B).

    26^2 x 3 patterns = 2,028 entries. The community counts patterns
    like ab_/_ad as semi-OG-style 3-character names.
    """
    alphabet = string.ascii_lowercase
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for a in alphabet:
            for b in alphabet:
                f.write(f"{a}{b}_\n")
                f.write(f"_{a}{b}\n")
                f.write(f"{a}_{b}\n")
                count += 3
    print(f"underscore pairs: {count} names -> {output_path}")
    return count


def generate_german(output_path: Path, top_n: int = 20000) -> int:
    """Write common German words valid as Minecraft usernames.

    German words are an explicit semi-OG class in community rarity guides
    (e.g. Schatten). Ordered by German word frequency, most common first.
    """
    from wordfreq import top_n_list, zipf_frequency

    words = top_n_list("de", top_n)
    kept: list[tuple[str, float]] = []
    for word in words:
        word = word.lower()
        if not (3 <= len(word) <= 16):
            continue
        if not all(("a" <= c <= "z") or ("0" <= c <= "9") or c == "_" for c in word):
            continue
        kept.append((word, zipf_frequency(word, "de")))
    kept.sort(key=lambda x: -x[1])
    with open(output_path, "w", encoding="utf-8") as f:
        for word, _ in kept:
            f.write(word + "\n")
    print(f"german: {len(kept)} words -> {output_path}")
    return len(kept)

FACES = [
    # Face emoticons are a community OG exception (o_o, x_x).
    "o_o", "x_x", "u_u", "0_0", "q_q", "d_d", "b_b", "p_p",
    # Extended face emoticons (UwU, owo, etc.) - community OG class
    "uwu", "owo", "qwq", "qaq",
    "uwu_", "owo_", "qwq_", "qaq_",
    "uwu~", "owo~", "qwq~", "qaq~",
    "uwu.", "owo.", ">w<", "<w>", "0w0",
    "uwuuwu", "owoowo", "uwuowo", "owo_uwu",
]

def generate_faces(output_path: Path) -> int:
    """Write face emoticons valid as Minecraft usernames."""
    with open(output_path, "w", encoding="utf-8") as f:
        for face in FACES:
            f.write(face + "\n")
    print(f"faces: {len(FACES)} names -> {output_path}")
    return len(FACES)


GAMING_TERMS = [
    # Well-known gaming terms (an explicit OG-class input per mcindex).
    "noob", "newb", "pro", "pwn", "pwned", "gg", "glhf", "camper",
    "camping", "griefer", "grief", "spawnkill", "killstreak", "combo",
    "clutch", "frag", "frags", "headshot", "noscope", "quickscope",
    "trickshot", "aimbot", "hacker", "cheater", "lagger", "sweaty",
    "sweat", "tryhard", "casual", "smurf", "smurfing", "alt", "main",
    "op", "nerf", "buff", "patch", "meta", "strat", "strats", "rush",
    "rushing", "turtle", "turtling", "spawncamping", "killfeed",
    "respawn", "checkpoint", "bossfight", "speedrun", "speedrunner",
    "worldrecord", "clutchgod", "fragmovie", "montage",
    # Extended gaming terms
    "esports", "esport", "gamer", "gamers", "gaming", "streamer",
    "stream", "youtuber", "content", "creator", "mod", "mods",
    "modding", "modder", "modders", "skin", "skins", "cape", "capes",
    "texture", "textures", "resourcepack", "resourcepack", "datapack",
    "datapacks", "shader", "shaders", "optifine", "fabric", "forge",
    "liteloader", "liteloader", "lite", "optifine", "sodium", "lithium",
    "phosphor", "ferritecore", "hydrogen", "paper", "spigot", "purpur",
    "tuinity", "airplane", "velocity", "waterfall", "bungeecord",
    "proxy", "proxy", "proxied", "backend", "frontend", "backend",
    "api", "rest", "websocket", "tcp", "udp", "http", "https",
    "discord", "discordjs", "discordpy", "discordjs", "discord.py",
    "bot", "bots", "bot", "bots", "selfbot", "selfbots", "nitro",
    "boost", "boosts", "boosting", "booster", "server", "servers",
    "guild", "guilds", "channel", "channels", "category", "categories",
    "role", "roles", "permission", "permissions", "admin", "admins",
    "mod", "mods", "mod", "admin", "admins", "owner", "owners",
    "coowner", "coowners", "manager", "managers", "developer",
    "developers", "dev", "devs", "code", "coding", "programmer",
    "programmers", "coder", "coders", "script", "scripts", "scripting",
    "python", "javascript", "typescript", "java", "kotlin", "rust",
    "go", "golang", "cpp", "c++", "c#", "csharp", "lua", "luau",
    "roblox", "minecraft", "mc", "mcpe", "mcbe", "mcje", "java",
    "bedrock", "education", "pocket", "console", "ps4", "ps5",
    "xbox", "switch", "mobile", "android", "ios", "pc", "windows",
    "linux", "mac", "macos", "steam", "epic", "origin", "uplay",
    "battlenet", "battle.net", "riot", "valorant", "league",
    "legends", "lol", "lol", "dota", "dota2", "csgo", "cs2",
    "cs", "csgo", "valorant", "valorant", "ow", "ow2", "overwatch",
    "overwatch2", "apex", "apexlegends", "fortnite", "fn",
    "pubg", "warzone", "mw", "mw2", "mw3", "bo", "bo2", "bo3",
    "bo4", "coldwar", "vanguard", "mw2019", "mw2", "mw3",
    "zombies", "multiplayer", "campaign", "specops", "specops",
    "dmz", "dmz", "battle", "royale", "br", "brs", "br",
    "arena", "arenas", "ranked", "competitive", "casual",
    "unranked", "normals", "norms", "flex", "solo", "duo",
    "duos", "trio", "trios", "squad", "squads", "party", "parties",
    "lobby", "lobbies", "matchmaking", "mmr", "elo", "sr",
    "rank", "ranks", "rank", "tier", "tiers", "division", "divisions",
    "promo", "promos", "promotion", "promotions", "demotion",
    "demotions", "lp", "lp", "rr", "rr", "mmr", "mmr",
    "kd", "kda", "kda", "kd", "winrate", "wr", "winrate", "wr",
    "hs", "hs", "headshot", "headshots", "bodyshot", "bodyshots",
    "awp", "awp", "awper", "awpers", "rifle", "rifles", "rifle",
    "pistol", "pistols", "pistol", "deagle", "deagle", "awp",
    "ak", "ak47", "ak47", "ak74", "ak74", "m4", "m4a1", "m4a4",
    "m4a1s", "m4a1_s", "aug", "aug", "sg", "sg553", "sg553",
    "famas", "famas", "galil", "galilar", "galil", "mac10",
    "mac10", "mp9", "mp9", "mp7", "mp7", "mp5", "mp5sd",
    "ump45", "ump45", "p90", "p90", "bizon", "bizon", "mag7",
    "mag7", "xm1014", "xm1014", "nova", "nova", "sawedoff",
    "sawedoff", "m249", "m249", "negev", "negev", "scar20",
    "scar20", "g3sg1", "g3sg1", "ssg08", "ssg08", "awp", "awp",
    "scar17", "scar17", "hk416", "hk416", "mcx", "mcx", "honeybadger",
    "honeybadger", "rz", "rz", "rpg", "rpg", "rpg7", "rpg7",
    "at4", "at4", "smaw", "smaw", "javelin", "javelin",
    "stinger", "stinger", "igla", "igla", "manpads", "manpads",
    "aa", "aa", "spaa", "spaa", "aa", "spaa", "shilka", "shilka",
    "tunguska", "tunguska", "pantsir", "pantsir", "tornado",
    "tornado", "gryphon", "gryphon", "f15", "f15", "f16", "f16",
    "f18", "f18", "f22", "f22", "f35", "f35", "su27", "su27",
    "su30", "su30", "su35", "su35", "su57", "su57", "j20", "j20",
    "j31", "j31", "mig29", "mig29", "mig31", "mig31", "su33",
    "su33", "su34", "su34", "su35", "su35", "su57", "su57",
    "rafale", "rafale", "eurofighter", "eurofighter", "typhoon",
    "typhoon", "gripen", "gripen", "jf17", "j17", "tejas",
    "tejas", "kf21", "kf21", "tf", "tf", "tf2", "tf2",
    "halo", "halo", "halo2", "halo3", "halo4", "halo5", "infinite",
    "infinite", "reach", "reach", "ce", "ce", "mcc", "mcc",
    "destiny", "destiny2", "destiny2", "d2", "d2", "guardian",
    "guardians", "titan", "titans", "hunter", "hunters", "warlock",
    "warlocks", "cayde6", "cayde6", "cayde", "cayde", "cayde-6",
    "ikora", "ikora", "zvala", "zvala", "cayde", "cayde-6",
    "cayde6", "cayde-6", "cayde-6", "cayde-6", "cayde-6",
    "drang", "drang", "trin", "trin", "trin", "trin",
    "arnment", "arnment", "arsenal", "arsenal", "arsenal",
    "arsenal", "loadout", "loadouts", "loadout", "build", "builds",
    "build", "meta", "metas", "meta", "offmeta", "offmeta",
    "offmeta", "viable", "viable", "nonviable", "nonviable",
    "broken", "op", "nerf", "buff", "rework", "reworks", "rework",
    "patch", "patches", "patchnotes", "patchnotes", "hotfix",
    "hotfixes", "hotfix", "bug", "bugs", "glitch", "glitches",
    "exploit", "exploits", "dupe", "dupes", "duping", "duped",
    "cheat", "cheats", "hack", "hacks", "aimbot", "aimbots",
    "wallhack", "wallhacks", "esp", "esp", "triggerbot", "triggerbots",
    "bhop", "bhop", "bhopping", "strafe", "strafing", "surf",
    "surfing", "kz", "kz", "kz_climb", "kzclimb", "surf", "surf",
    "surf_", "surf_", "kz_", "kz_", "bhop_", "bhop_", "kz_",
    "surf_", "bhop_", "kz_", "surf_", "bhop_", "kz_", "surf_",
    "bhop_", "kz_", "surf_", "bhop_", "kz_", "surf_", "bhop_",
    "kz_", "surf_", "bhop_", "kz_", "surf_", "bhop_", "kz_",
    "surf_", "bhop_", "kz_", "surf_", "bhop_", "kz_", "surf_",
    "bhop_", "kz_", "surf_", "bhop_", "kz_", "surf_", "bhop_",
    "kz_", "surf_", "bhop_", "kz_", "surf_", "bhop_", "kz_",
]


def generate_gaming_terms(output_path: Path) -> int:
    """Write well-known gaming terms valid as Minecraft usernames."""
    seen: set[str] = set()
    words: list[str] = []
    for word in GAMING_TERMS:
        word = word.strip().lower()
        if not (3 <= len(word) <= 16):
            continue
        if not all(("a" <= c <= "z") or ("0" <= c <= "9") or c == "_" for c in word):
            continue
        if word not in seen:
            seen.add(word)
            words.append(word)
    with open(output_path, "w", encoding="utf-8") as f:
        for word in words:
            f.write(word + "\n")
    print(f"gaming terms: {len(words)} words -> {output_path}")
    return len(words)


HALLOWEEN_WORDS = [
    # Core Halloween
    "halloween", "spooky", "scary", "creepy", "eerie", "haunted", "haunt",
    "ghost", "ghosts", "phantom", "specter", "spectre", "spirit", "soul",
    "pumpkin", "jackolantern", "lantern", "candle", "candy", "treat", "trick",
    "costume", "mask", "disguise",
    # Monsters & creatures
    "witch", "witches", "wizard", "warlock", "vampire", "dracula", "werewolf",
    "zombie", "zombies", "mummy", "skeleton", "skull", "demon", "devil",
    "monster", "monsters", "goblin", "ghoul",
    "ogre", "troll", "orc", "gargoyle", "banshee", "wraith", "poltergeist",
    "reaper", "grimreaper", "boogeyman", "frankenstein",
    # Spooky places & things
    "graveyard", "cemetery", "tomb", "tombstone", "coffin", "crypt", "mausoleum",
    "mansion", "castle", "dungeon", "attic", "basement", "forest", "swamp",
    "fog", "mist", "darkness", "midnight", "nightmare", "dream",
    "cobweb", "spider", "spiders", "bat", "bats", "owl", "crow", "raven",
    "rat", "rats", "snake", "blackcat",
    # Magic & occult
    "magic", "spell", "spells", "potion", "potions", "cauldron", "broom",
    "broomstick", "wand", "curse", "cursed", "hex", "voodoo", "ouija",
    "tarot", "crystal", "crystalball", "moon", "fullmoon", "eclipse",
    "pentagram", "rune", "sigil", "alchemy",
    # Horror vibes
    "horror", "terror", "fear", "scream", "screams", "blood", "bloody",
    "fangs", "claws", "howl", "whisper", "shadow", "shadows", "dark",
    "chill", "shiver", "goosebumps", "night", "october", "autumn", "fall",
    "harvest", "scarecrow", "cornmaze",
    # Fun / aesthetic
    "spooktober", "creep", "creepypasta", "slenderman", "pennywise",
    "chucky", "freddy", "jason", "myers", "ghostface", "scream",
    "corpse", "corpsebride", "beetlejuice", "addams", "morticia", "gomez",
    "wednesday", "casper", "scooby", "mystery",
]


def generate_halloween(output_path: Path) -> int:
    """Write curated spooky/Halloween words, deduplicated, lowercase."""
    seen = set()
    words = []
    for word in HALLOWEEN_WORDS:
        word = word.strip().lower()
        # Valid Minecraft username characters only, 3-16 chars
        if not (3 <= len(word) <= 16):
            continue
        if not all(("a" <= c <= "z") or ("0" <= c <= "9") or c == "_" for c in word):
            continue
        if word not in seen:
            seen.add(word)
            words.append(word)
    with open(output_path, "w", encoding="utf-8") as f:
        for word in words:
            f.write(word + "\n")
    print(f"halloween: {len(words)} words -> {output_path}")
    return len(words)


WOOD_TYPES = [
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
    "mangrove", "cherry", "bamboo", "crimson", "warped", "pale_oak",
]

WOOD_PRODUCTS = [
    "log", "wood", "planks", "leaves", "sapling", "boat", "door",
    "trapdoor", "fence", "stairs", "slab", "button", "sign",
]

WOOL_COLORS = [
    "white", "light_gray", "gray", "black", "brown", "red", "orange",
    "yellow", "lime", "green", "cyan", "light_blue", "blue", "purple",
    "magenta", "pink",
]

WOOL_PRODUCTS = ["wool", "carpet", "concrete", "bed", "candle", "banner"]

TOOL_MATERIALS = [
    "wooden", "wood", "stone", "iron", "golden", "gold",
    "diamond", "netherite",
]
TOOL_TYPES = ["sword", "axe", "pickaxe", "shovel", "hoe"]
ARMOR_PIECES = ["helmet", "chestplate", "leggings", "boots"]

MINECRAFT_ITEMS = [
    # Natural blocks
    "stone", "granite", "diorite", "andesite", "deepslate", "tuff",
    "dirt", "grass_block", "coarse_dirt", "rooted_dirt", "mud", "clay",
    "sand", "red_sand", "gravel", "cobblestone", "mossy_cobblestone",
    "bedrock", "obsidian", "crying_obsidian", "glass", "tinted_glass",
    "ice", "packed_ice", "blue_ice", "snow", "snow_block", "glowstone",
    "sea_lantern", "sponge", "wet_sponge", "sandstone", "red_sandstone",
    "prismarine", "dark_prismarine", "prismarine_bricks",
    # Bricks & crafted blocks
    "stone_bricks", "mossy_stone_bricks", "cracked_stone_bricks",
    "chiseled_stone_bricks", "bricks", "mud_bricks", "bookshelf",
    "chiseled_bookshelf", "crafting_table", "furnace", "blast_furnace",
    "smoker", "anvil", "grindstone", "smithing_table", "loom",
    "fletching_table", "cartography_table", "enchanting_table",
    "brewing_stand", "cauldron", "composter", "barrel", "chest",
    "trapped_chest", "ender_chest", "shulker_box", "jukebox", "noteblock",
    "dispenser", "dropper", "observer", "piston", "sticky_piston", "hopper",
    "tnt", "beacon", "conduit", "dragon_egg", "spawner", "trial_spawner",
    "vault", "trial_key", "ominous_trial_key", "lodestone", "respawn_anchor",
    "end_crystal", "dragon_head", "end_rod", "chorus_plant", "chorus_flower",
    "chorus_fruit", "popped_chorus_fruit", "shulker_shell",
    # Ores & minerals
    "coal", "iron", "gold", "diamond", "emerald", "lapis", "redstone",
    "quartz", "netherite", "copper", "amethyst", "raw_iron", "raw_gold",
    "raw_copper", "iron_ingot", "gold_ingot", "copper_ingot",
    "netherite_ingot", "netherite_scrap", "ancient_debris",
    "lapis_block", "redstone_block", "quartz_block", "amethyst_shard",
    "prismarine_shard", "prismarine_crystals", "echo_shard", "disc_fragment",
    # Tools & weapons
    "sword", "axe", "pickaxe", "shovel", "hoe", "bow", "crossbow",
    "shield", "trident", "mace", "arrow", "spectral_arrow", "tipped_arrow",
    "fishing_rod", "flint_and_steel", "shears", "brush", "spyglass",
    "compass", "recovery_compass", "clock", "map", "lead", "name_tag",
    "saddle", "totem_of_undying", "elytra", "firework_rocket",
    # Armor
    "helmet", "chestplate", "leggings", "boots", "turtle_helmet",
    "horse_armor", "wolf_armor", "leather", "chainmail",
    # Food
    "apple", "golden_apple", "carrot", "golden_carrot", "potato",
    "baked_potato", "poisonous_potato", "beetroot", "beetroot_soup",
    "bread", "cookie", "cake", "pumpkin_pie", "melon", "melon_slice",
    "sweet_berries", "glow_berries", "dried_kelp", "kelp", "steak",
    "porkchop", "chicken", "mutton", "rabbit", "rabbit_stew",
    "mushroom_stew", "suspicious_stew", "honey_bottle", "honeycomb",
    "milk_bucket", "water_bucket", "lava_bucket", "rotten_flesh",
    "spider_eye", "fermented_spider_eye",
    # Redstone & transport
    "redstone_torch", "repeater", "comparator", "daylight_detector",
    "sculk_sensor", "target", "lightning_rod", "tripwire_hook", "lever",
    "rail", "powered_rail", "detector_rail", "activator_rail", "minecart",
    # Potions & brewing
    "potion", "splash_potion", "lingering_potion", "glass_bottle",
    "nether_wart", "blaze_powder", "blaze_rod", "ghast_tear",
    "magma_cream", "rabbit_foot", "phantom_membrane", "turtle_scute",
    "armadillo_scute", "dragon_breath", "experience_bottle",
    "ender_pearl", "eye_of_ender",
    # Nether
    "netherrack", "soul_sand", "soul_soil", "basalt", "blackstone",
    "gilded_blackstone", "nether_wart_block", "shroomlight",
    "nether_bricks", "red_nether_bricks", "soul_torch", "soul_lantern",
    "soul_campfire", "twisted_vines", "weeping_vines", "crimson_fungus",
    "warped_fungus", "crimson_roots", "warped_roots", "nether_sprouts",
    # End
    "end_stone", "end_stone_bricks", "purpur_block", "purpur_pillar",
    "purpur_stairs", "purpur_slab",
    # Ocean
    "sea_lantern", "wet_sponge", "seagrass", "sea_pickle", "turtle_egg",
    "nautilus_shell", "heart_of_the_sea", "kelp_block", "dried_kelp_block",
    "tube_coral", "brain_coral", "bubble_coral", "fire_coral", "horn_coral",
    # Mobs & drops
    "zombie", "skeleton", "creeper", "spider", "enderman", "blaze",
    "ghast", "slime", "magma_cube", "silverfish", "endermite", "witch",
    "guardian", "elder_guardian", "shulker", "phantom", "drowned", "husk",
    "stray", "pillager", "ravager", "evoker", "vex", "vindicator",
    "wither", "wither_skeleton", "ender_dragon", "warden", "allay",
    "frog", "tadpole", "axolotl", "goat", "bee", "panda", "fox",
    "polar_bear", "llama", "villager", "zombie_villager", "iron_golem",
    "snow_golem", "cat", "ocelot", "parrot", "wolf", "slimeball",
    "gunpowder", "string", "feather", "rabbit_hide",
    # Music discs
    "disc_cat", "disc_blocks", "disc_chirp", "disc_far", "disc_mall",
    "disc_mellohi", "disc_stal", "disc_strad", "disc_ward", "disc_eleven",
    "disc_thirteen", "disc_pigstep", "disc_otherside", "disc_relic",
    "disc_creator", "disc_precipice",
    # Iconic enchantments (full set also merged from the registry)
    "mending", "fortune", "silk_touch", "sharpness", "looting", "unbreaking",
    "fire_aspect", "knockback", "infinity", "multishot", "swift_sneak",
    # Villager professions
    "armorer", "butcher", "cartographer", "cleric", "farmer", "fisherman",
    "fletcher", "leatherworker", "librarian", "mason", "nitwit", "shepherd",
    "toolsmith", "weaponsmith", "trader",
    # Illager raid mechanics
    "raid", "patrol",
    # Iconic title-screen splash texts
    "punchtrees", "terraria", "dropbears", "spock", "waterproof", "lol",
    # In-game rider/jockey mechanics (not registry IDs, but real combos)
    "chicken_jockey", "spider_jockey", "spider_rider",
    "skeleton_horseman", "skeleton_trap",
]


GENERIC_GAME_WORDS = [
    # Item / entity categories
    "armor", "item", "weapon", "tool", "block", "ore", "ingot", "nugget",
    "gear", "loot", "drop", "mob", "boss", "pickup", "biome",
    # Gameplay & mechanics
    "crafting", "smelting", "mining", "farming", "fishing", "brewing",
    "enchanting", "trading", "building", "exploring", "spawn", "skin",
    "cape", "realm", "server", "seed", "world", "chunk", "inventory",
    "hotbar", "health", "hunger", "level", "achievement", "advancement",
    "recipe", "guide", "tutorial", "player", "multiplayer", "singleplayer",
    "survival", "creative", "adventure", "hardcore", "spectator",
    "peaceful", "easy", "normal", "hard", "day", "night", "dawn", "dusk",
    "weather", "rain", "thunder", "storm",
    # Dimensions
    "overworld", "nether", "end", "the_nether", "the_end",
    # Player defaults
    "steve", "alex",
    # Biomes
    "plains", "desert", "savanna", "taiga", "jungle", "ocean", "river",
    "beach", "mountain", "cave", "mesa", "badlands", "forest",
    "birch_forest", "dark_forest", "flower_forest", "swamp",
    "mangrove_swamp", "cherry_grove", "frozen_peaks", "jagged_peaks",
    "stony_peaks", "snowy_plains", "snowy_taiga", "ice_spikes",
    "mushroom_fields", "lush_caves", "dripstone_caves", "deep_dark",
    "windswept_hills", "old_growth_taiga", "bamboo_jungle", "sparse_jungle",
    # Structures
    "village", "pillager_outpost", "woodland_mansion", "ocean_monument",
    "nether_fortress", "bastion_remnant", "end_city", "igloo",
    "desert_pyramid", "jungle_temple", "witch_hut", "mineshaft",
    "stronghold", "buried_treasure", "shipwreck", "ocean_ruins",
    "trail_ruins", "trial_chambers", "ancient_city", "desert_well",
    "fossil", "amethyst_geode",
    # Iconic status effects
    "speed", "strength", "regeneration", "fire_resistance", "night_vision",
    "invisibility", "water_breathing", "slow_falling", "poison", "wither",
    "hunger", "nausea", "weakness", "slowness", "mining_fatigue", "haste",
    "jump_boost", "levitation", "glowing", "luck", "unluck", "bad_omen",
    "hero_of_the_village", "darkness", "infested", "oozing", "weaving",
    "wind_charged",
]


def _normalize_item_name(raw: str) -> list[str]:
    """Return username-safe variants of a Minecraft item display name."""
    cleaned = raw.strip().lower().replace("'", "").replace("-", " ")
    cleaned = "_".join(cleaned.split())
    variants = {cleaned, cleaned.replace("_", "")}
    return sorted(variants)


def generate_minecraft_items(
    output_path: Path,
    official_names: set[str] | None = None,
    enchantment_levels: dict[str, int] | None = None,
) -> int:
    """Write Minecraft item/block/mob names as username candidates."""
    names: set[str] = set()

    def add(raw: str):
        for variant in _normalize_item_name(raw):
            if 3 <= len(variant) <= 16 and all(
                ("a" <= c <= "z") or ("0" <= c <= "9") or c == "_" for c in variant
            ):
                names.add(variant)

    for item in MINECRAFT_ITEMS:
        add(item)
    for word in GENERIC_GAME_WORDS:
        add(word)
    for raw in sorted(official_names or ()):
        add(raw)
    for wood in WOOD_TYPES:
        for product in WOOD_PRODUCTS:
            add(f"{wood}_{product}")
    for color in WOOL_COLORS:
        for product in WOOL_PRODUCTS:
            add(f"{color}_{product}")
    for material in TOOL_MATERIALS:
        for tool in TOOL_TYPES + ARMOR_PIECES:
            add(f"{material}_{tool}")
    for enchantment, max_level in sorted((enchantment_levels or {}).items()):
        # Level variants with Roman numerals like in-game, e.g. sharpness_V
        # (plus the joined form via normalization: sharpnessV). Over-long
        # variants are dropped by the length filter inside add().
        for level in range(1, max_level + 1):
            add(f"{enchantment}_{_roman(level)}")

    # Shorter names first: shorter = rarer, then alphabetical.
    ordered = sorted(names, key=lambda w: (len(w), w))
    with open(output_path, "w", encoding="utf-8") as f:
        for word in ordered:
            f.write(word + "\n")
    print(f"minecraft items: {len(ordered)} names -> {output_path}")
    return len(ordered)


def _roman(number: int) -> str:
    """Convert an enchantment level (1-10) to upper-case Roman numerals."""
    numerals = (
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    )
    result = ""
    for value, numeral in numerals:
        while number >= value:
            result += numeral
            number -= value
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate custom word lists for mc-og-name-hunter."
    )
    parser.add_argument(
        "--official-version",
        default=OFFICIAL_DATA_VERSION,
        help=f"minecraft-data version to merge (default: {OFFICIAL_DATA_VERSION})",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip the minecraft-data download; use the hand-curated base only.",
    )
    args = parser.parse_args()

    output_dir = Path("data/word_lists")
    output_dir.mkdir(parents=True, exist_ok=True)
    generate_short_combos(output_dir / "short_all_3_4.txt")
    generate_digit_combos(output_dir / "digits_all_3.txt")
    generate_underscore_pairs(output_dir / "underscore_pairs_3.txt")
    generate_halloween(output_dir / "halloween.txt")
    generate_german(output_dir / "german.txt")
    generate_faces(output_dir / "faces.txt")
    generate_gaming_terms(output_dir / "gaming_terms.txt")
    official = set() if args.offline else fetch_official_names(args.official_version)
    levels = {} if args.offline else fetch_enchantment_levels(args.official_version)
    generate_minecraft_items(output_dir / "minecraft_items.txt", official, levels)


if __name__ == "__main__":
    main()
