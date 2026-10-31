"""Generate the word lists the coverage audit found missing.

The audit (see README, "Word-list coverage") compared every enumerated shape
space and a set of probe categories against ``data/word_lists``.  Five gaps
remained:

* **leet spellings** -- the compound class advertises leet, but no list fed it
* **underscore shapes** -- ``_name``, ``name_``, ``a_b_c`` were absent
* **repeaters / sequences** -- ``aaaaa``, ``ababab``, ``abc123`` were absent
* **esports orgs and streamers** -- recognised gaming names, partially present
* **18 Latin-script languages** -- only 33 language files shipped

This script writes the missing lists and records class hints in
``rarity_overrides.tsv`` so generation, filtering, storage, display and the
auditor agree on the same score.  Multilingual words are semi-OG (35, i.e. the
350 band) exactly like the existing ``og_multilingual_*`` files; esports orgs
and streamers are OG (60, the 600 band) because they are recognised gaming
names.  Leet and underscore shapes are left to the base model -- it already
places them (compound / 3-char mixed / clean handle), and a hint would promote
them above what the class table allows.

Usage::

    python generate_missing_wordlists.py
    python generate_missing_wordlists.py --offline
    python generate_missing_wordlists.py --output-dir data/word_lists
"""

from __future__ import annotations

import argparse
import re
import urllib.request
from pathlib import Path

try:
    from unidecode import unidecode
except Exception:  # pragma: no cover - dependency is in requirements.txt
    unidecode = None

try:
    from wordfreq import iter_wordlist
except Exception:  # pragma: no cover - dependency is in requirements.txt
    iter_wordlist = None

from generate_custom_wordlists import is_banned
from src.rarity import score as rarity_score


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "word_lists"
CACHE_DIR = REPO_ROOT / "data" / "themed_cache"

VALID = re.compile(r"^[A-Za-z0-9_]{3,16}$")

# FrequencyWords (OpenSubtitles 2018) has these; wordfreq has no data for the
# rest, so those are curated below.
FREQUENCY_LANGUAGES = [
    "ca", "gl", "eu", "is", "et", "lv", "lt", "sq", "bs", "eo", "br",
]

# Languages with neither wordfreq nor FrequencyWords coverage.  Curated from
# everyday vocabulary: numbers, colours, family, nature, animals, food, verbs.
CURATED_LANGUAGES: dict[str, str] = {
    "sw": """
        moja mbili tatu nne tano sita saba nane tisa kumi
        simba chui tembo twiga kifaru nyati swala tumbili paa ndovu
        maji moto hewa ardhi mbingu jua mwezi nyota mvua upepo
        nyumba mlango dirisha kitanda meza kiti chakula
        mama baba kaka dada babu bibi mtoto mume mke rafiki
        furaha upendo amani nguvu akili moyo mkono mguu jicho sikio
        kichwa uso kinywa meno ulimi tumbo mgongo
        simba sanifu
        moja mbili tatu nne tano sita saba nane tisa kumi
        akiba bahari barabara bustani chuo duka elimu familia
        farasi gari hadithi hospitali hundi ndege jiko kahawa
        kalamu karibu kibanda kijiji kilima kisu kitabu
        kizuri kofia kuku kuni kuta ladha langua majani
        makazi maneno matunda mboga mchele mchanga mfumo
        miaka mji mkate mlango mlima mnyama mshipa msumari
        mti mtihani mtoto mwaka mwalimu mwanzo mwili mzigo
        nchi ndani ndoa neema nguo nyama nyasi nyumba
        pesa picha pua pwani radi sahani sauti shamba
        shule sindano sukari soko stesheni sumu tabibu
        tamu tanga tofauti tumbo udevu uhuru uma umri
        unga uso uwanja uzima viatu vitabu wakati wimbo
        windo yadi zabibu zao zawadi zito
    """,
    "cy": """
        un dau tri pedwar pump chwech saith wyth naw deg
        llew teigr eliffant ceffyl ci cath aderyn pysgodyn
        dŵr tân awyr daear awyr haul lleuad seren glaw gwynt
        tŷ drws ffenestr gwely bwrdd cadair bwyd
        mam tad brawd chwaer taid nain plentyn gŵr gwraig ffrind
        hapus cariad heddwch nerth meddwl calon llaw troed llygad clust
        pen wyneb genau dant tafod bola cefn
        mynydd afon mor llyn coedwig gardd ffordd siop ysgol
        llyfr pensil car pedair awr munud wythnos mis blwyddyn
        bore noswaith prynhawn heddiw yfory ddoe amser
        bara caws llaeth siwgr halen te coffi afal oren
        ci bach mawr hir byr newydd hen da drwg
        cerdded rhedeg nofio canu dawnsio siarad gwrando darllen
        ysgrifennu bwyta yfed cysgu deffro gweithio chwarae
        dysgu helpu caru casáu chwerthin crio
    """,
    "ga": """
        aon dó trí ceathair cúig sé seacht ocht naoi deich
        leon tíogar eilifint capall madra cat éan iasc
        uisce tine aer talamh spéir grian gealach réalta báisteach gaoth
        teach doras fuinneog leaba bord cathaoir bia
        máthair athair deartháir deirfiúr seanathair seanmháthair páiste fear bean cara
        sona grá síocháin neart smaoineamh croí lámh cos súil cluas
        ceann aghaidh béal fiacail teanga bolg droim
        sliabh abhainn farraige loch coill garraí bóthar siopa scoil
        leabhar peann carr uair nóiméad seachtain mí bliain
        maidin oíche tráthnóna inniu amárach inné am
        arán cáis bainne siúcra salann tae caife úll oráiste
        mór beag fada gearr nua sean maith olc
        siúil rith snámh can damhsa labhair éist léamh scríobh
        ithe ól codail dúisigh oibriú imir foghlaim cabhair grá
        gáire caoin
    """,
    "mt": """
        wieħed tnejn tlieta erbgħa ħamsa sitta sebgħa tmienja disgħa għaxra
        iljun tigra iljunfant żiemel kelb qattus għasfur ħuta
        ilma nar arja art sema xemx qamar stilla xita riħ
        dar bieb tieqa sodda mejda siġġu ikel
        omm missier ħu oħt nannu nanna tifel raġel mara ħabib
        kuntent imħabba paċi saħħa moħħ qalb id sieq għajn widna
        ras wiċċ ħalq sinna lsien żaqq dahar
        muntanja xmara baħar għadira foresta ġnien triq ħanut skola
        ktieb pinna karozza siegħa minuta ġimgħa xahar sena
        filgħodu bil-lejl waranofsinhar illum għada ilbieraħ żmien
        ħobż ġobon ħalib zokkor melħ te kafè tuffieħa larinġa
        kbir żgħir twil qasir ġdid qadim tajjeb ħażin
        imxi iġri għum kanta żfin tkellem isma aqra ikteb
        ieklu ixrob norqod qum aħdem ilgħab tgħallem għin ħobb
        daħak beka
    """,
    "az": """
        bir iki üç dörd beş altı yeddi səkkiz doqquz on
        aslan pələng fil at it pişik quş balıq
        su od hava torpaq göy günəş ay ulduz yağış külək
        ev qapı pəncərə çarpayı masa stul yemək
        ana ata qardaş bacı baba nənə uşaq kişi qadın dost
        xoşbəxt sevgi sülh güc ağıl ürək əl ayaq göz qulaq
        baş üz ağız diş dil qarın bel
        dağ çay dəniz göl meşə bağ yol mağaza məktəb
        kitab qələm maşın saat dəqiqə həftə ay il
        səhər gecə axşam bugün sabah dünən vaxt
        çörək pendir süd şəkər duz çay qəhvə alma portağal
        böyük kiçik uzun qısa yeni köhnə yaxşı pis
        getmək qaçmaq üzmək oxumaq rəqs danışmaq dinləmək yazmaq
        yemək içmək yatmaq durmaq işləmək oynamaq öyrənmək kömək etmək
        gülmək ağlamaq
    """,
    "uz": """
        bir ikki uch tort besh olti yetti sakkiz toqqiz on
        sher arslon fil ot it mushuk qush baliq
        suv olov havo tuproq osmon quyosh oy yulduz yomgir shamol
        uy eshik deraza karavot stol stul ovqat
        ona ota aka opa buva buvi bola erkak ayol do'st
        baxtli sevgi tinchlik kuch aql yurak qo'l oyoq ko'z quloq
        bosh yuz og'iz tish til qorin bel
        tog' daryo dengiz ko'l o'rmon bog' yo'l do'kon maktab
        kitob qalam mashina soat daqiqa hafta oy yil
        ertalab kech oqshom bugun ertaga kecha vaqt
        non pishloq sut shakar tuz choy qahva olma apelsin
        katta kichik uzun qisqa yangi eski yaxshi yomon
        yurmoq yugurmoq suzmoq kuylamoq raqs gapirmoq tinglamoq yozmoq
        yemoq ichmoq uxlamoq turmoq ishlamoq o'ynamoq o'rganmoq yordam
        kulmoq yig'lamoq
    """,
}

ESPORTS_ORGS = """
cloud9 fnatic astralis g2esports karmine teamliquid navi vitality
faze liquid geng t1 dplus drx gen.g edg rng invictus ig
sktelecom skt samsung ktrolster griffin damwon dwg
nigma og secret alliance nip mibr imperial godsent complexity
col optic envytsm 100thieves sentinels geng esports
virtuspro vp gambit forze heroic big mouz mousesports
north astralis dignitas rogue excel misfits schalke
splyce vikings clg imt flyquest golden guardians
evilempire evil geniuses eg clg dignitas
natusvincere navi gambit vega spirit
newbee vici lgd psg.lgd teamsecret eg alliance
fnatic nrg clg tsm immersive
genting bilibili weibo jdg blg wbg lng tes
""".split()

#: Leet spellings the community actually uses.  Generated variants below only
#: cover one substitution per word, so the memorable double-substitution
#: forms are curated here.
LEET_CURATED = """
n00b tr0ll h4x h4cker sk1ll gh0st ph4ntom sn1per n1nja 0wn3d g4m3r sh4dow
l33t pr0 pr0s n00bs 1337 3lit3 h4x0r h4xx0r sk1llz sn1p3r n1nj4
m4st3r m4st3r 0wn4g3 pwn3d pwn4g3 r3kt r3kted l4g l4gz
z3r0 h3r0 4ng3l d3m0n 4w3s0m3 l3g3nd ch4mp ch4mp10n
w1z4rd w4rr10r h4ck3r h4ck3d h4x0rz 3l1t3 k1ll4 k1ll3r
bl4z3 ph33r sn0w d4rk d4rkn3ss l1ght l1ghtn1ng
c0d3 g4m3 g4m3s g4m3z pl4y3r pl4y4 pl4y3rz
sk8 sk8er n0sc0p3 0p3n s3cr3t s3rv3r cl4n
""".split()

STREAMERS = """
pokimane sodapoppin summit1g timthetatman drdisrespect
kaicenat adinross jynxzi ishowspeed xqc trainwreckstv asmongold
mizkif shroud ninja tfue myth lupo cloak
sypherpk nickmercs doc disney dobre brothers bellarina
botez pokimane valkyrae sykkuno corpse husband toast
ludwig qtcinderella hasan ab gymshark moistcritikal penguinz0
techsupport tyler1 trick2g boxbox
philza technoblade dream georgenotfound sapnap karljacobs
quackity tommyinnit tubbo ranboo wilbursoot jschlatt
captainsparklez antvenom skydoesminecraft ssundee
""".split()


def clean_word(raw: str) -> str:
    """Fold a raw dictionary spelling into a valid ASCII username shape."""
    word = raw.strip().lower()
    if not word or word.startswith("#"):
        return ""
    if unidecode is not None:
        word = unidecode(word)
    word = re.sub(r"[^a-z0-9_]", "", word)
    if not VALID.match(word) or is_banned(word):
        return ""
    return word


class Writer:
    """Collects new words per list and records class hints."""

    def __init__(self, output_dir: Path, offline: bool = False):
        self.output_dir = output_dir
        self.offline = offline
        self.lists: dict[str, set[str]] = {}
        self.hints: dict[str, int] = {}

    def add(self, filename: str, word: str, hint: int = 0) -> bool:
        word = clean_word(word)
        if not word:
            return False
        bucket = self.lists.setdefault(filename, set())
        if word in bucket:
            return False
        bucket.add(word)
        if hint:
            self.hints.setdefault(word, hint)
        return True

    # -- sources ---------------------------------------------------------

    def fetch(self, url: str, filename: str) -> str:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CACHE_DIR / filename
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="ignore")
        if self.offline:
            print(f"  ! {filename}: not cached (offline)")
            return ""
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "mc-og-name-hunter/2.1"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read().decode("utf-8", errors="ignore")
            cache_path.write_text(data, encoding="utf-8")
            return data
        except Exception as exc:
            print(f"  ! {filename}: {exc}")
            return ""

    def add_leet(self) -> None:
        """Leet spellings of common English words (one substitution each)."""
        if iter_wordlist is None:
            print("  ! wordfreq unavailable; skipping leet list")
            return
        subs = [
            ("o", "0"), ("i", "1"), ("l", "1"), ("e", "3"), ("a", "4"),
            ("s", "5"), ("t", "7"), ("b", "8"), ("g", "9"), ("z", "2"),
        ]
        added = 0
        seen = 0
        for word in iter_wordlist("en", wordlist="best"):
            if seen >= 400:
                break
            cleaned = clean_word(word)
            if not cleaned or not cleaned.isalpha() or not 4 <= len(cleaned) <= 8:
                continue
            seen += 1
            for index, char in enumerate(cleaned):
                for source, target in subs:
                    if char != source:
                        continue
                    variant = cleaned[:index] + target + cleaned[index + 1:]
                    if self.add("leet.txt", variant):
                        added += 1
                    # Two substitutions keep the memorable forms (n00b, gh0st)
                    # for short words; longer ones get unreadable.
                    if len(cleaned) <= 5:
                        for other in range(index + 1, len(cleaned)):
                            if cleaned[other] != source:
                                continue
                            double = (
                                cleaned[:index] + target
                                + cleaned[index + 1:other] + target
                                + cleaned[other + 1:]
                            )
                            if self.add("leet.txt", double):
                                added += 1
                if cleaned[index] in "aeiost":
                    variant = cleaned[:index] + "@" + cleaned[index:]
                    self.add("leet.txt", variant)
        for word in LEET_CURATED:
            added += self.add("leet.txt", word)
        print(f"  leet.txt: {len(self.lists.get('leet.txt', ()))} words ({added} new)")

    def add_underscore_shapes(self) -> None:
        """Prefix/suffix underscores and short a_b_c shapes."""
        if iter_wordlist is None:
            print("  ! wordfreq unavailable; skipping underscore list")
            return
        added = 0
        for word in iter_wordlist("en", wordlist="best"):
            cleaned = clean_word(word)
            if not cleaned or not cleaned.isalpha() or not 3 <= len(cleaned) <= 12:
                continue
            for shape in (f"_{cleaned}", f"{cleaned}_", f"__{cleaned}", f"{cleaned}__"):
                if self.add("underscore_shapes.txt", shape):
                    added += 1
            for letter in "xyzqj":
                self.add("underscore_shapes.txt", f"{letter}_{cleaned}")
                self.add("underscore_shapes.txt", f"{cleaned}_{letter}")
            if len(self.lists.get("underscore_shapes.txt", ())) >= 3000:
                break
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        for first in alphabet:
            for second in alphabet:
                self.add("underscore_shapes.txt", f"_{first}{second}")
                self.add("underscore_shapes.txt", f"{first}{second}_")
        for letter in alphabet:
            self.add("underscore_shapes.txt", f"__{letter}")
            self.add("underscore_shapes.txt", f"{letter}__")
            self.add("underscore_shapes.txt", f"___{letter}")
            self.add("underscore_shapes.txt", f"{letter}___")
        for first in alphabet:
            for second in alphabet:
                self.add("underscore_shapes.txt", f"__{first}{second}")
                self.add("underscore_shapes.txt", f"{first}{second}__")
        # a_b_c is the one 5-char underscore shape worth enumerating in full
        # (17,576 names, ~105 KB).
        for first in alphabet:
            for middle in alphabet:
                for last in alphabet:
                    self.add("underscore_shapes.txt", f"{first}_{middle}_{last}")
        print(f"  underscore_shapes.txt: {len(self.lists.get('underscore_shapes.txt', ()))}")

    def add_repeaters(self) -> None:
        """Runs, alternating pairs and numeric sequences."""
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        added = 0
        for letter in alphabet:
            for length in range(3, 17):
                added += self.add("repeaters.txt", letter * length)
        for a in alphabet:
            for b in alphabet:
                if a == b:
                    continue
                for reps in (2, 3):
                    added += self.add("repeaters.txt", (a + b) * reps)
                for reps in (2, 3):
                    added += self.add("repeaters.txt", (a + b + "c") * reps)
        for start in range(0, 10):
            for length in range(3, 7):
                digits = "".join(str((start + i) % 10) for i in range(length))
                added += self.add("repeaters.txt", digits)
                added += self.add("repeaters.txt", digits * 2)
        for word in ("abc", "xyz", "ace", "bad", "cat", "dog", "top", "one",
                     "two", "six", "zen", "max", "pro", "gg", "ez", "og"):
            for digits in ("123", "1234", "321", "007", "777", "666", "420"):
                self.add("repeaters.txt", f"{word}{digits}")
                self.add("repeaters.txt", f"{digits}{word}")
            for extra in ("xp", "z", "hq", "tv", "gg"):
                self.add("repeaters.txt", f"{word}{extra}")
        print(f"  repeaters.txt: {len(self.lists.get('repeaters.txt', ()))} ({added} new)")

    def add_creators(self) -> None:
        added = 0
        for word in ESPORTS_ORGS:
            added += self.add("og_esports_orgs.txt", word, hint=60)
        for word in STREAMERS:
            added += self.add("og_streamers.txt", word, hint=60)
        print(f"  og_esports_orgs.txt: {len(self.lists.get('og_esports_orgs.txt', ()))}")
        print(f"  og_streamers.txt: {len(self.lists.get('og_streamers.txt', ()))}")

    def add_languages(self) -> None:
        for language in FREQUENCY_LANGUAGES:
            filename = f"og_multilingual_{language}.txt"
            # The repo names some languages with the full-corpus file.
            stem = f"{language}_50k" if language not in ("eo", "br") else f"{language}_full"
            url = (
                "https://raw.githubusercontent.com/hermitdave/FrequencyWords/"
                f"master/content/2018/{language}/{stem}.txt"
            )
            data = self.fetch(url, f"frequency_{language}.txt")
            if not data:
                continue
            valid = 0
            for line in data.splitlines():
                raw = line.split()[0] if line.split() else ""
                if valid >= 2000:
                    break
                if self.add(filename, raw, hint=35):
                    valid += 1
            print(f"  {filename}: {valid} words")

        for language, blob in CURATED_LANGUAGES.items():
            filename = f"og_multilingual_{language}.txt"
            valid = 0
            for raw in blob.split():
                if self.add(filename, raw, hint=35):
                    valid += 1
            print(f"  {filename}: {valid} words (curated)")

    # -- output ----------------------------------------------------------

    def write(self) -> None:
        for filename, words in sorted(self.lists.items()):
            if not words:
                continue
            path = self.output_dir / filename
            ordered = sorted(words, key=lambda w: (len(w), w))
            path.write_text("\n".join(ordered) + "\n", encoding="utf-8")
        self.write_hints()
        self.write_rare_names()

    def write_rare_names(self) -> None:
        """Rebuild ``rare_names.txt`` (top-class words across every list).

        The file shipped empty even though the README describes it as the
        supplemental 600+ set; regenerating it from the corpus keeps the two
        consistent.
        """
        path = self.output_dir / "rare_names.txt"
        valid = re.compile(r"[A-Za-z0-9_]{3,16}")
        names: set[str] = set()
        for list_path in self.output_dir.glob("*.txt"):
            if list_path.name in ("rare_names.txt", "semi_names.txt"):
                continue
            try:
                text = list_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                word = line.split("\t")[0].strip().lower()
                if valid.fullmatch(word):
                    names.add(word)
        rare = sorted(
            (word for word in names if rarity_score(word) >= 600),
            key=lambda w: (-rarity_score(w), len(w), w),
        )
        path.write_text("\n".join(rare) + ("\n" if rare else ""), encoding="utf-8")
        print(f"  rare_names.txt: {len(rare):,} words at 600+")

    def write_hints(self) -> None:
        path = self.output_dir / "rarity_overrides.tsv"
        existing: dict[str, int] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].strip():
                    try:
                        existing[parts[0].strip().lower()] = int(parts[1])
                    except ValueError:
                        continue
        new = {w: h for w, h in self.hints.items() if w not in existing}
        if not new:
            print("  rarity_overrides.tsv: no new hints")
            return
        with open(path, "a", encoding="utf-8") as handle:
            for word in sorted(new):
                handle.write(f"{word}\t{new[word]}\n")
        print(f"  rarity_overrides.tsv: +{len(new)} hints")


def restore_enumeration_files(output_dir: Path) -> None:
    """Bring back the two cheap exhaustive lists kept out of the bundle."""
    scratch = REPO_ROOT / "data" / "scratch"
    for name in ("digits_all_4.txt", "alnum_mixed_3.txt"):
        source = scratch / name
        target = output_dir / name
        if source.exists() and not target.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  restored {name} ({len(target.read_text(encoding='utf-8').splitlines()):,} names)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--offline", action="store_true",
                        help="use only cached downloads")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Restoring exhaustive enumeration lists")
    restore_enumeration_files(output_dir)

    writer = Writer(output_dir, offline=args.offline)
    print("Generating leet spellings")
    writer.add_leet()
    print("Generating underscore shapes")
    writer.add_underscore_shapes()
    print("Generating repeaters and sequences")
    writer.add_repeaters()
    print("Generating esports and streamer names")
    writer.add_creators()
    print("Generating missing language lists")
    writer.add_languages()
    print("Writing")
    writer.write()

    total = sum(len(words) for words in writer.lists.values())
    print(f"\nWrote {len(writer.lists)} lists, {total:,} names "
          f"({len(writer.hints):,} class hints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
