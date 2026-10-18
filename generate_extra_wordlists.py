#!/usr/bin/env python3
"""Generate extra proper-noun word lists for mc-og-name-hunter.

Categories: franchise/game characters, Minecraft ecosystem, brands, music
artists, sports, famous people, astronomy, and chemistry/minerals.

Every entry is folded to a valid Minecraft Java username and filtered:
  * length 3-16
  * characters only [a-z0-9_]
  * lower-cased (usernames are case-insensitively unique)

Franchise/game data (Pokemon, League of Legends, Valorant, Overwatch) is
fetched live where possible; everything else is curated. Names already
present in the bundled word lists are dropped so no duplicate name ever
reaches the checker. Pass --offline to skip the network fetches.
"""

import argparse
import json
import re
import string
import unicodedata
import urllib.request
from pathlib import Path

WORDLIST_DIR = Path("data/word_lists")
VALID_CHARS = set(string.ascii_lowercase + string.digits + "_")

# Files that make up the "already covered" corpus for cross-list dedupe.
# Any generated name found here is dropped.
def _existing_names(exclude: set[str]) -> set[str]:
    names: set[str] = set()
    if not WORDLIST_DIR.exists():
        return names
    for path in WORDLIST_DIR.glob("*.txt"):
        if path.name in exclude:
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                word = line.split("\t")[0].strip().lower()
                if word:
                    names.add(word)
    return names


def fold(raw: str) -> set[str]:
    """Fold a raw name to username-safe variant(s).

    Strips accents/symbols, lower-cases, turns spaces/hyphens into
    underscores, then returns the underscore and joined forms if valid.
    """
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    # Drop punctuation that never maps to a separator.
    s = re.sub(r"['\u2019.,:;/\\!?()\[\]{}]", "", s)
    # Whitespace / hyphen / existing underscore -> single underscore.
    s = re.sub(r"[\s\-_]+", "_", s)
    # Strip anything still invalid.
    s = re.sub(r"[^a-z0-9_]", "", s).strip("_")
    out = {s}
    if "_" in s:
        out.add(s.replace("_", ""))
    return {c for c in out if c}


def is_valid(name: str) -> bool:
    return 3 <= len(name) <= 16 and all(c in VALID_CHARS for c in name)


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "mc-og-name-hunter-gen"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_pokemon() -> list[str]:
    data = _http_json("https://pokeapi.co/api/v2/pokemon?limit=100000")
    return [e["name"] for e in data.get("results", [])]


def fetch_lol_champions() -> list[str]:
    versions = _http_json("https://ddragon.leagueoflegends.com/api/versions.json")
    ver = versions[0]
    data = _http_json(
        f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json"
    )
    out = []
    for champ in data.get("data", {}).values():
        out.append(champ.get("name", ""))
        out.append(champ.get("id", ""))
    return [n for n in out if n]


def fetch_valorant() -> list[str]:
    data = _http_json(
        "https://valorant-api.com/v1/agents?isPlayableCharacter=true"
    )
    return [a.get("displayName", "") for a in data.get("data", [])]


def fetch_overwatch() -> list[str]:
    data = _http_json("https://overfast-api.tekrop.fr/heroes")
    return [h.get("name", "") for h in data]


ANIME_CHARACTERS = [
    # One Piece
    "luffy", "zoro", "nami", "sanji", "usopp", "chopper", "robin", "franky",
    "brook", "jinbe", "shanks", "mihawk", "law", "ace", "sabo", "doflamingo",
    "kaido", "blackbeard", "crocodile", "buggy", "garp", "smoker", "tashigi",
    # Naruto
    "naruto", "sasuke", "sakura", "kakashi", "itachi", "hinata", "gaara",
    "jiraiya", "tsunade", "orochimaru", "madara", "obito", "pain", "minato",
    "kushina", "rocklee", "neji", "tenten", "shikamaru", "kiba", "shino",
    "boruto", "sarada", "mitsuki", "killerbee", "hashirama", "tobirama",
    # Dragon Ball
    "goku", "vegeta", "gohan", "goten", "trunks", "piccolo", "krillin",
    "bulma", "frieza", "beerus", "whis", "broly", "raditz", "nappa", "vegito",
    "gogeta", "kakarot", "bardock",
    # Attack on Titan
    "eren", "mikasa", "armin", "levi", "erwin", "hange", "sasha", "historia",
    "reiner", "bertholdt", "annie", "zeke", "grisha",
    # Demon Slayer
    "tanjiro", "nezuko", "zenitsu", "inosuke", "giyu", "shinobu", "rengoku",
    "tengen", "muichiro", "mitsuri", "obanai", "sanemi", "gyomei", "muzan",
    "akaza", "douma", "kokushibo", "kanao", "genya",
    # Jujutsu Kaisen
    "gojo", "yuji", "megumi", "nobara", "sukuna", "toji", "geto", "nanami",
    "maki", "yuta", "choso", "mahito", "kenjaku",
    # My Hero Academia
    "midoriya", "bakugo", "todoroki", "uraraka", "iida", "asui", "kirishima",
    "kaminari", "sero", "mineta", "momo", "jiro", "tokoyami", "aizawa",
    "allmight", "shigaraki", "dabi", "toga", "hawks", "endeavor", "overhaul",
    # Bleach
    "ichigo", "rukia", "orihime", "uryu", "renji", "kenpachi", "byakuya",
    "toshiro", "aizen", "yamamoto", "urahara", "yoruichi", "grimmjow",
    "ulquiorra",
    # Hunter x Hunter
    "gon", "killua", "kurapika", "leorio", "hisoka", "chrollo", "illumi",
    "netero", "meruem", "kite",
    # Tokyo Ghoul
    "kaneki", "touka", "rize", "ayato", "yamori",
    # Sword Art Online
    "kirito", "asuna", "sinon", "klein", "eugeo", "alice",
    # Fullmetal Alchemist
    "edward", "alphonse", "winry", "riza", "scar", "envy", "wrath", "lust",
    "greed", "homunculus",
    # Death Note
    "light", "ryuk", "misa", "near", "mello",
    # Code Geass
    "lelouch", "suzaku", "kallen", "nunnally",
    # Fairy Tail
    "natsu", "lucy", "gray", "erza", "happy", "wendy", "gajeel", "jellal",
    "zeref",
    # Re:Zero
    "subaru", "emilia", "rem", "ram", "puck", "echidna",
    # Ghibli
    "totoro", "ponyo", "calcifer", "howl", "chihiro", "haku", "kiki", "jiji",
    # TMNT
    "leonardo", "donatello", "raphael", "michelangelo", "shredder", "splinter",
    # Sailor Moon / others
    "sailormoon", "sailormars", "sailorvenus", "vegeta", "trunks",
]


BRANDS = [
    # Tech / internet
    "google", "apple", "microsoft", "amazon", "meta", "facebook", "instagram",
    "whatsapp", "youtube", "netflix", "spotify", "tiktok", "snapchat",
    "discord", "reddit", "twitch", "steam", "nvidia", "intel", "amd",
    "qualcomm", "samsung", "sony", "panasonic", "toshiba", "dell", "lenovo",
    "asus", "acer", "msi", "gigabyte", "logitech", "razer", "corsair",
    "hyperx", "nintendo", "playstation", "xbox", "sega", "atari", "valve",
    "epicgames", "roblox", "mojang", "oracle", "cisco", "adobe", "salesforce",
    "paypal", "visa", "mastercard", "stripe", "uber", "lyft", "airbnb",
    "tesla", "spacex", "boeing", "airbus",
    # Automotive
    "ford", "chevrolet", "dodge", "jeep", "toyota", "honda", "nissan",
    "mazda", "subaru", "mitsubishi", "hyundai", "kia", "bmw", "audi",
    "mercedes", "porsche", "volkswagen", "ferrari", "lamborghini", "bugatti",
    "mclaren", "astonmartin", "bentley", "rollsroyce", "jaguar", "landrover",
    "volvo", "peugeot", "renault", "citroen", "fiat", "alfaromeo", "maserati",
    "lexus", "infiniti", "acura", "cadillac", "chrysler", "rivian", "lucid",
    "polestar",
    # Fashion
    "nike", "adidas", "puma", "reebok", "underarmour", "newbalance",
    "converse", "vans", "fila", "asics", "skechers", "gucci", "prada",
    "versace", "armani", "chanel", "dior", "louisvuitton", "hermes",
    "burberry", "givenchy", "balenciaga", "fendi", "dolcegabbana",
    "valentino", "rolex", "omega", "cartier", "tiffany", "coach", "levis",
    "diesel", "zara", "uniqlo", "supreme", "northface", "columbia",
    "patagonia", "timberland", "drmartens",
    # Food / drink
    "cocacola", "pepsi", "sprite", "fanta", "mcdonalds", "burgerking", "kfc",
    "wendys", "subway", "dominos", "pizzahut", "tacobell", "starbucks",
    "dunkin", "nestle", "hershey", "snickers", "kitkat", "oreo", "pringles",
    "layz", "doritos", "cheetos", "redbull", "monster", "gatorade",
    "powerade", "heineken", "budweiser", "guinness", "corona",
    # Media / toys / retail
    "disney", "pixar", "marvel", "warner", "universal", "paramount", "hulu",
    "espn", "nasa", "lego", "mattel", "hasbro", "nerf", "barbie", "walmart",
    "target", "costco", "ikea", "ebay", "alibaba", "etsy", "shopify",
]


MUSIC = [
    # Bands
    "queen", "beatles", "nirvana", "metallica", "acdc", "ledzeppelin",
    "pinkfloyd", "rollingstones", "radiohead", "coldplay", "imaginedragons",
    "linkinpark", "greenday", "blink182", "paramore", "foofighters",
    "redhotchili", "gunsnroses", "aerosmith", "bonjovi", "ironmaiden",
    "blacksabbath", "slipknot", "systemofadown", "rammstein", "onerepublic",
    "maroon5", "theweeknd", "daftpunk", "gorillaz", "avicii", "kygo",
    "chainsmokers", "calvinharris", "deadmau5", "skrillex", "diplo",
    "marshmello", "zedd", "tiesto", "hardwell", "afrojack", "abba", "kiss",
    # Hip-hop
    "eminem", "drake", "kanye", "jayz", "kendrick", "jcole", "travisscott",
    "asaprocky", "50cent", "snoopdogg", "tupac", "biggie", "nas", "cardi",
    "nickiminaj", "dojacat", "lilwayne", "postmalone", "juicewrld",
    "lildurk", "future", "migos", "offset", "quavo", "takeoff",
    # Pop
    "taylorswift", "beyonce", "rihanna", "adele", "madonna", "ladygaga",
    "katyperry", "arianagrande", "mileycyrus", "selenagomez", "shakira",
    "jlo", "britneyspears", "mariahcarey", "whitneyhouston", "celinedion",
    "justinbieber", "justintimberlake", "brunomars", "edsheeran", "samsmith",
    "harrystyles", "zayn", "billieeilish", "dualipa", "sza", "lizzo",
    "halsey", "charlieputh", "shawnmendes",
    # Rock / legends
    "elvis", "prince", "michaeljackson", "davidbowie", "freddiemercury",
    "eltonjohn", "steviewonder", "bobmarley", "johnnycash", "bobdylan",
    "brucespringsteen", "sting", "philcollins",
    # K-pop
    "blackpink", "straykids", "redvelvet", "itzy", "aespa", "enhypen",
    "seventeen",
]


SPORTS = [
    # NBA teams
    "lakers", "celtics", "warriors", "bulls", "heat", "knicks", "nets",
    "spurs", "mavericks", "rockets", "thunder", "nuggets", "suns",
    "clippers", "bucks", "76ers", "raptors", "pistons", "cavaliers",
    "atlantahawks", "hornets", "orlandomagic", "wizards", "grizzlies",
    "pelicans", "sacramentokings", "timberwolves", "blazers", "utahjazz",
    "pacers",
    # Basketball players
    "jordan", "kobe", "lebron", "curry", "durant", "giannis", "jokic",
    "embiid", "luka", "tatum", "kyrie", "harden", "westbrook", "kawhi",
    "damianlillard", "zion", "ja", "wemby", "shaq", "kareem", "magic",
    "larrybird", "wilt", "duncan",
    # NFL teams
    "patriots", "cowboys", "packers", "steelers", "49ers", "chiefs",
    "seahawks", "ravens", "eagles", "nygiants", "broncos", "saints", "bills",
    "bengals", "larams", "buccaneers", "dolphins", "vikings", "chicagobears",
    "detroitlions", "nyjets", "raiders", "chargers", "texans", "titans",
    "colts", "jaguars", "panthers", "falcons", "commanders",
    # Soccer players
    "messi", "ronaldo", "neymar", "mbappe", "haaland", "benzema", "modric",
    "kroos", "iniesta", "xavi", "salah", "kane", "lewandowski", "vinicius",
    "bellingham", "buffon", "casillas", "ramos", "pique", "suarez", "aguero",
    "rooney", "zidane", "ronaldinho", "kaka", "maradona", "pele",
    # Soccer clubs
    "barcelona", "realmadrid", "chelsea", "arsenal", "liverpool",
    "manchester", "manutd", "mancity", "juventus", "acmilan", "intermilan",
    "napoli", "asroma", "bayern", "dortmund", "psg", "ajax", "benfica",
    "porto", "sevilla", "atletico", "tottenham", "everton", "newcastle",
    # MLB / NHL
    "yankees", "dodgers", "redsox", "chicagocubs", "nymets", "braves",
    "astros", "sfgiants", "cardinals", "canadiens", "bruins", "mapleleafs",
    "edmontonoilers", "penguins", "redwings", "nyrangers", "flyers",
    "blackhawks", "avalanche", "lightning",
    # Tennis / combat / olympics
    "federer", "nadal", "djokovic", "murray", "serenawilliams",
    "venuswilliams", "agassi", "sampras", "tyson", "muhammadali",
    "mayweather", "mcgregor", "khabib", "jonjones", "andersonSilva",
    "usainbolt", "michaelphelps", "simonebiles",
]


FAMOUS_PEOPLE = [
    # Scientists / thinkers
    "einstein", "newton", "nikolatesla", "darwin", "hawking", "mariecurie",
    "galileo", "davinci", "edison", "archimedes", "pythagoras", "euclid",
    "nielsbohr", "planck", "enricofermi", "oppenheimer", "alanturing",
    "gracehopper", "feynman", "mendel", "pasteur", "shakespeare",
    "socrates", "plato", "aristotle", "descartes", "leibniz", "kant",
    "copernicus", "kepler",
    # Leaders / historical
    "napoleon", "juliuscaesar", "alexanderthegreat", "genghiskhan",
    "cleopatra", "churchill", "lincoln", "washington", "jefferson",
    "jfk", "roosevelt", "mandela", "gandhi", "martinluther", "augustus",
    "attila", "hannibal", "spartacus", "ramses", "tutankhamun", "nefertiti",
    "hammurabi",
    # Art / literature / music
    "picasso", "vangogh", "monet", "michelangelo", "raphael", "beethoven",
    "mozart", "bach", "chopin", "vivaldi", "handel", "brahms", "tolstoy",
    "dostoevsky", "hemingway", "marktwain", "dickens", "orwell", "tolkien",
    # Modern / celebrity
    "billgates", "stevejobs", "elonmusk", "jeffbezos", "zuckerberg",
    "chaplin", "waltdisney", "hepburn", "marilynmonroe", "elvispresley",
    "johnlennon", "paulmccartney", "tomhanks", "dicaprio", "keanureeves",
]


CONSTELLATIONS = [
    "andromeda", "antlia", "apus", "aquarius", "aquila", "ara", "aries",
    "auriga", "bootes", "caelum", "camelopardalis", "cancer",
    "canesvenatici", "canismajor", "canisminor", "capricornus", "carina",
    "cassiopeia", "centaurus", "cepheus", "cetus", "chamaeleon", "circinus",
    "columba", "comaberenices", "coronaaustralis", "coronaborealis", "corvus",
    "crater", "crux", "cygnus", "delphinus", "dorado", "draco", "equuleus",
    "eridanus", "fornax", "gemini", "grus", "hercules", "horologium", "hydra",
    "hydrus", "indus", "lacerta", "leo", "leominor", "lepus", "libra",
    "lupus", "lynx", "lyra", "mensa", "microscopium", "monoceros", "musca",
    "norma", "octans", "ophiuchus", "orion", "pavo", "pegasus", "perseus",
    "phoenix", "pictor", "pisces", "piscisaustrinus", "puppis", "pyxis",
    "reticulum", "sagitta", "sagittarius", "scorpius", "sculptor", "scutum",
    "serpens", "sextans", "taurus", "telescopium", "triangulum",
    "triangulumaustrale", "tucana", "ursamajor", "ursaminor", "vela",
    "virgo", "volans", "vulpecula",
]

STARS = [
    "sirius", "canopus", "arcturus", "vega", "capella", "rigel", "procyon",
    "betelgeuse", "achernar", "hadar", "altair", "acrux", "aldebaran",
    "antares", "spica", "pollux", "fomalhaut", "deneb", "mimosa", "regulus",
    "bellatrix", "polaris", "dubhe", "merak", "alioth", "mizar", "alcor",
    "alnilam", "alnitak", "mintaka", "saiph", "wezen", "adhara", "mirzam",
    "gacrux", "avior", "aspidiske", "alnair", "peacock", "atria", "shaula",
    "sargas", "rasalhague", "elnath", "alhena", "alphard", "denebola",
    "algieba", "zubeneschamali", "zubenelgenubi", "sadalsuud", "sadalmelik",
    "menkar", "mirach", "alpheratz", "markab", "scheat", "algenib", "hamal",
    "sheratan", "menkalinan", "mirfak", "caph", "schedar", "rukbat", "nunki",
    "thuban",
]

BODIES = [
    "mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus",
    "neptune", "pluto", "ceres", "eris", "haumea", "makemake", "titan",
    "europa", "ganymede", "callisto", "phobos", "deimos", "triton",
    "enceladus", "mimas", "rhea", "titania", "oberon", "charon", "luna",
    "sol", "milkyway", "andromeda", "whirlpool", "sombrero", "crab", "helix",
    "tarantula", "pleiades", "hyades", "magellanic",
]


ELEMENTS = [
    "hydrogen", "helium", "lithium", "beryllium", "boron", "carbon",
    "nitrogen", "oxygen", "fluorine", "neon", "sodium", "magnesium",
    "aluminum", "silicon", "phosphorus", "sulfur", "chlorine", "argon",
    "potassium", "calcium", "scandium", "titanium", "vanadium", "chromium",
    "manganese", "iron", "cobalt", "nickel", "copper", "zinc", "gallium",
    "germanium", "arsenic", "selenium", "bromine", "krypton", "rubidium",
    "strontium", "yttrium", "zirconium", "niobium", "molybdenum",
    "technetium", "ruthenium", "rhodium", "palladium", "silver", "cadmium",
    "indium", "tin", "antimony", "tellurium", "iodine", "xenon", "cesium",
    "barium", "lanthanum", "cerium", "praseodymium", "neodymium",
    "promethium", "samarium", "europium", "gadolinium", "terbium",
    "dysprosium", "holmium", "erbium", "thulium", "ytterbium", "lutetium",
    "hafnium", "tantalum", "tungsten", "rhenium", "osmium", "iridium",
    "platinum", "gold", "thallium", "lead", "bismuth", "polonium", "astatine",
    "radon", "francium", "radium", "actinium", "thorium", "protactinium",
    "uranium", "neptunium", "plutonium", "americium", "curium", "berkelium",
    "californium", "einsteinium", "fermium", "mendelevium", "nobelium",
    "lawrencium", "rutherfordium", "dubnium", "seaborgium", "bohrium",
    "hassium", "meitnerium", "darmstadtium", "roentgenium", "copernicium",
    "nihonium", "flerovium", "moscovium", "livermorium", "tennessine",
    "oganesson",
]

MINERALS = [
    "diamond", "emerald", "ruby", "sapphire", "topaz", "opal", "jade",
    "amethyst", "onyx", "pearl", "garnet", "aquamarine", "turquoise",
    "peridot", "citrine", "obsidian", "quartz", "granite", "marble",
    "basalt", "flint", "mica", "graphite", "malachite", "azurite", "pyrite",
    "hematite", "magnetite", "calcite", "feldspar", "amber", "opal",
]

COMPOUNDS = [
    "ammonia", "methane", "propane", "butane", "ethanol", "methanol",
    "glucose", "fructose", "sucrose", "caffeine", "aspirin", "nicotine",
    "penicillin", "adrenaline", "dopamine", "serotonin", "insulin",
    "collagen", "keratin", "chlorophyll", "hemoglobin", "protein", "enzyme",
    "peptide", "polymer", "plastic", "teflon", "nylon", "kevlar", "polyester",
]


MINECRAFT_ECOSYSTEM = [
    # Hypixel / major network games
    "hypixel", "skyblock", "bedwars", "skywars", "skyclash", "warlords",
    "buildbattle", "party games", "speeduhc", "crazywalls", "smashheroes",
    "quakecraft", "paintball", "vampirez", "creeperattack", "blockingdead",
    "galaxywars", "murder mystery", "minestrike", "copsandcrims", "megawalls",
    "blitzsg", "uhc", "duels", "housing", "arcade", "tntgames", "tntrun",
    "tnttag", "bowspleef", "spleef", "walls",
    # Server software / ecosystem
    "mineplex", "cubecraft", "wynncraft", "2b2t", "anarchy", "lifesteal",
    "purpur", "spigot", "bukkit", "sponge", "fabric", "forge", "velocity",
    "waterfall", "bungeecord", "essentials", "worldedit", "luckperms",
    "protocollib", "viaversion", "sodium", "lithium", "optifine",
    # Gamemodes / tropes
    "survivalgames", "hungergames", "factions", "prison", "towny", "kitpvp",
    "practice", "oneblock", "acidisland", "caveblock", "skygrid", "parkour",
    "dropper", "hideandseek", "pvp", "siege", "capture", "battle royale",
    "hardcore", "spectator",
    # Redstone / technical
    "redstone", "repeater", "comparator", "observer", "piston", "sticky",
    "dispenser", "dropper", "hopper", "minecart", "poweredrail",
    "detectorrail", "activatorrail", "redstonetorch", "daylightdetector",
    "noteblock", "jukebox", "commandblock", "structureblock", "barrier",
    "beacon", "conduit", "sculk", "sculksensor", "tripwirehook",
    "lightningrod", "crafter", "chiseled",
    # Commands
    "gamemode", "teleport", "summon", "execute", "enchant", "whitelist",
    "difficulty", "gamerule", "scoreboard", "particle", "playsound",
    "spawnpoint", "locate", "clone", "setblock",
    # Community / creators
    "herobrine", "technoblade", "notch", "dinnerbone", "grumm", "dream",
    "deadmau5",
]


def build_category(raw_names, exclude: set[str], seen: set[str]) -> list[str]:
    """Fold -> validate -> drop already-covered and already-emitted names."""
    out: set[str] = set()
    for raw in raw_names:
        if not raw:
            continue
        for name in fold(raw):
            if not is_valid(name):
                continue
            if name in exclude or name in seen:
                continue
            out.add(name)
    result = sorted(out, key=lambda w: (len(w), w))
    seen.update(result)
    return result


def write_list(filename: str, names: list[str]) -> int:
    path = WORDLIST_DIR / filename
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for name in names:
            f.write(name + "\n")
    print(f"{filename:28} {len(names):>6} names")
    return len(names)


def main():
    parser = argparse.ArgumentParser(description="Generate extra proper-noun word lists.")
    parser.add_argument("--offline", action="store_true",
                        help="Skip live API fetches (Pokemon/LoL/Valorant/Overwatch).")
    args = parser.parse_args()

    WORDLIST_DIR.mkdir(parents=True, exist_ok=True)
    output_files = {
        "franchise_characters.txt", "minecraft_ecosystem.txt", "brands.txt",
        "music_artists.txt", "sports.txt", "famous_people.txt",
        "astronomy.txt", "chemistry.txt",
    }
    exclude = _existing_names(exclude=output_files)
    print(f"existing names to exclude: {len(exclude)}")

    pokemon, lol, valorant, overwatch = [], [], [], []
    if not args.offline:
        for label, fn, bucket in [
            ("pokemon", fetch_pokemon, "pokemon"),
            ("lol", fetch_lol_champions, "lol"),
            ("valorant", fetch_valorant, "valorant"),
            ("overwatch", fetch_overwatch, "overwatch"),
        ]:
            try:
                data = fn()
                print(f"fetched {label}: {len(data)}")
                if bucket == "pokemon":
                    pokemon = data
                elif bucket == "lol":
                    lol = data
                elif bucket == "valorant":
                    valorant = data
                else:
                    overwatch = data
            except Exception as e:
                print(f"WARNING: fetch {label} failed: {e}")

    franchise = pokemon + lol + valorant + overwatch + ANIME_CHARACTERS
    astronomy = CONSTELLATIONS + STARS + BODIES
    chemistry = ELEMENTS + MINERALS + COMPOUNDS

    seen: set[str] = set()
    categories = [
        ("franchise_characters.txt", franchise),
        ("minecraft_ecosystem.txt", MINECRAFT_ECOSYSTEM),
        ("brands.txt", BRANDS),
        ("music_artists.txt", MUSIC),
        ("sports.txt", SPORTS),
        ("famous_people.txt", FAMOUS_PEOPLE),
        ("astronomy.txt", astronomy),
        ("chemistry.txt", chemistry),
    ]
    total = 0
    for filename, raw in categories:
        names = build_category(raw, exclude, seen)
        total += write_list(filename, names)
    print(f"TOTAL: {total} names across {len(categories)} files")


if __name__ == "__main__":
    main()
