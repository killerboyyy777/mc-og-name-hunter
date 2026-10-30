# What the Minecraft username community agrees on about name rarity

Research date **2026-10-30**; all URLs accessed the same day.

Goal: find what the username-trading community actually agrees on when it rates a Java
username as "rare"/"OG"/valuable, so `_base_rarity_points()` in `src/models.py` can be
replaced by something defensible. Method: read the numeric source the repo already cites
(mcindex.gg) end to end, then cross-check every class boundary against where players argue —
Hypixel threads (2019–2024), BuiltByBit sales, r/Minecraft, and the Minecraft Wiki's account
mechanics. Snippet-only evidence is marked **UNVERIFIED**.

Evidence-base warning: there is **no canonical authority**. mcindex.gg is one site's rubric,
not a standards body; Hypixel threads are a decade of unresolved amateur debate; prices are
almost all unverifiable. What repeats across independent sources is the **ordering** of name
classes. The **numbers attached to them are one site's invention.** That distinction drives
everything below.

---

## 1. Consensus summary

**High confidence**

- **Class, not length, determines rarity.** Every source rates `Dog` > `Xqz` > `Qzvk`. mcindex:
  *"A name is classified by its structure … and by its meaning … The higher class counts."*
- **Base form beats inflected form.** `Dog` > `Dogs`, `Run` > `Running`. mcindex encodes it as
  60 vs 35; Choo lists `Doggings` as not OG; DoctorWhere: OG is *"non-plural, non-adverb,
  non-past-tense"*.
- **A word only counts when it is the whole name.** mcindex: *"A word counts only when it is
  the whole name."* Hypixel rejects `Superman1`, `xxOperatorxx`, `CS_GO` likewise.
- **Digits/underscores demote to a separate lower class**, not a small penalty. `Shadow7` = 3,
  not a weakened `Shadow`. mcindex: *"Capitalisation, digits and underscores around a word do
  not make a name rarer."*
- **Sub-3-character names top the scale** because supply is permanently fixed (3-char minimum;
  renaming a 1–2 char name destroys it — Minecraft Wiki).
- **Rarity is a step function over discrete classes**, not a continuous score. Nobody computes
  a name's value; they place it in a bucket and argue about the bucket.

**Medium confidence**

- **Class order:** very common short word > common word ≈ popular first name > 3L pronounceable
  > 3L random ≈ 3 digits > 3-char mixed > second-tier word > 4L pronounceable > 4L random >
  4-char mixed > clean > nothing. Agreed at top and bottom; the middle is where sources split.
- **3L random and 3 digits are level** (mcindex: both 45). Choo lumps `000`, `______` into
  "Repeater OG" rather than a separate value tier.
- **Compounds are a "minor feature"** — below base words, above random strings (12). Contested
  in practice; they sell well on BuiltByBit (see §4).
- **Pronounceability is weak and deliberately generous** — *"Our rule is generous, so the
  points are set low"*; *"Pronounceability is a rough rule."* It separates 3L/4L sub-classes
  only, never promotes a non-word.
- **First names are their own axis**, roughly equal to a common word (`Daniel` = 60; r/Minecraft:
  *"Ryan is an OG username. Ryan1995 is not."*).

**Low confidence**

- **The point values themselves.** 80/60/52/45/40/35/20/12/8/5/3/0 is mcindex's rubric with no
  external validation. No second source publishes numbers.
- **Market prices.** Every anchor found was snippet-only or SEO-grade.
- **Whether 4L pronounceable (20) belongs below second-tier word (35).** mcindex says yes; some
  Hypixel posters call 4L "semi-OG", which is 35 in mcindex terms.

---

## 2. Name classes: published values

mcindex publishes 18 classes with fixed points; tiers are its own thresholds (**Notable ≥15,
Collectible ≥35, Rare ≥60, Unique ≥85**), capped at 90.

| Class | Pts | Tier | Definition | Repo |
|---|---|---|---|---|
| 1–2 characters | **90** | Unique | *"cannot be registered again. Renaming the account loses the name for good."* | **missing** |
| Chars no longer allowed | **85** | Unique | *"special characters or more than 16 characters … not issued any more."* | **missing** |
| Very common short word | **80** | Rare | *"most frequent English words with six letters at most"* (Dog, Dream, Water) | 80 |
| Common word | **60** | Rare | *"base form with up to ten letters, popular first names and well-known gaming terms"* (Fox, Harbor, Daniel) | 60 |
| 3L pronounceable | **52** | Collectible | *"Three letters that read like a word"* (Zor, Yew, Ran) | 52 |
| 3L random | **45** | Collectible | *"Three letters that cannot be pronounced"* (Xqz, Kvr, Bzt) | 45 |
| 3 digits | **45** | Collectible | *"Three digits. There are exactly a thousand of them"* (482, 777) | 45 |
| 3 chars mixed | **40** | Collectible | *"at least one digit or underscore"* (q7x, a_7) | 40 |
| Word, second tier | **35** | Collectible | *"rare or inflected English words … eleven letters or more, and German words"* (Wandered, Schatten) | 35 |
| 4L pronounceable | **20** | Notable | *"Four letters that read like a word. Our rule is generous, so the points are set low"* (Vexo, Zaza) | 20 |
| Minor name feature | **12** | Standard | *"Compound words, leet spellings, very rare words and rare first names"* (IronWolf, Sh4dow) | 12 |
| 4L random | **8** | Standard | *"Four letters that cannot be pronounced"* (Qzvk, Xkrt) | 8 |
| 4 chars mixed | **5** | Standard | *"at least one digit or underscore"* (Ab3x, Fox_, K9_z) | 5 |
| Clean name | **3** | Standard | *"readable name that is not a word, or a word followed by up to two digits"* (Velmora, Shadow7) | 3 |
| Nothing special | **0** | Standard | *"xX frame, long digit tails, barcode patterns"* | 0 |
| Brand / well-known person; offensive; being taken away | not rated | — | Mojang can reclaim; slurs; forced-change flags | — |

Source for the table: <https://mcindex.gg/names>.

**Cross-check against community vocabulary.** Choo's 2019 Hypixel taxonomy maps almost exactly
onto these classes — strong evidence the *classes* are real even if the *points* are not:

| Community term | Choo's definition | mcindex |
|---|---|---|
| OG | *"original forms of words and common definitions/slangs"* | 80 / 60 |
| Semi-OG | *"added prefix/suffix or uncommon word"* (`Dogs`, `CounterStrike`, `720`) | 35 / 12 |
| 3-letter | *"All 3 character names are taken now as of Nov 2019"* | 52 / 45 / 40 |
| 4-letter | *"semi og sometimes"*; *"not og, there's still tons of them available"* | 20 / 8 |
| Repeater OG | `000`, `______` | 45 / 40 |
| Meme/Culture OG | `Facebook`, `Roblox` | **not rated** |
| Invalid | pre-2015 special chars | 85 |

One genuine disagreement: `Meme/Culture OG` is valued by Choo and *refused* by mcindex — i.e.
does a name Mojang can reclaim have value? Community answer: yes, with risk.

**Gaps in the repo** (`src/models.py`):

1. Both top classes are absent — the repo's ceiling is 80, mcindex's is 90, so `Zq`/`a_` score
   as mere "top words".
2. `3 digits` and `3L random` are collapsed to 45 (matches mcindex, loses `777` vs `482`).
3. **No within-class term at all** — two names in one bucket are indistinguishable. Biggest gap.

---

## 3. Within-class factors

mcindex is the only source publishing a within-class sub-score, and the only source giving
evidence of *ordering*. It uses a position in [0.10, 0.90] = 0.10 start + a "how common" term +
a length term:

> *"Inside a class a name sits between 0.10 and 0.90: the shorter and more common, the higher.
> The position only decides between two classes of the same rank; it never changes the
> points."* — `/how-it-works`

The last clause matters: **the sub-score is cosmetic on mcindex.** It cannot be lifted
wholesale as a scoring term.

Published components (fetched per name page):

| Name | Zipf | Len | "How common" | Length | Position |
|---|---|---|---|---|---|
| Dog | 5.30 | 3 | +0.43 | +0.15 | 0.68 |
| Fox | 4.35 | 3 | +0.68 | +0.15 | 0.90 (sum 0.93, clamped) |
| Harbor | 4.05 | 6 | +0.44 | +0.05 | 0.59 |
| Daniel | 4.72 | 6 | +0.65 | +0.05 | 0.80 |
| Teacher | 4.76 | 7 | +0.80 | +0.00 | 0.90 |
| Water | 5.36 | 5 | +0.46 | +0.10 | 0.66 |

**This sub-score is not reproducible; do not copy it.** Sorted by Zipf, the "commonness" bonus
is non-monotonic: Harbor 4.05→+0.44, Fox 4.35→+0.68, Daniel 4.72→+0.65, Teacher 4.76→+0.80,
Water 5.36→+0.46. The documented rule is *"the more common, the higher"*; the published values
say the opposite for Water vs Teacher and Harbor vs Fox. The length bonus is also inconsistent
(two 5-letter names: +0.05 and +0.10). Take the *direction* as evidence, the *magnitudes* as
noise.

| Factor | Direction | Weight evidence | Sources |
|---|---|---|---|
| Supply scarcity | fewer possible → higher | Hard class boundary, not a bonus: 17,576 3L; 456,976 4L; sub-3L extinct. 2-char→3L is a 38–45 pt jump. | mcindex `/names`, 3L guide; Wiki |
| Is a dictionary word | word ≫ non-word | Largest jump in the scale: 45→60 (+15) to common word, 45→80 (+35) to top word. | mcindex; all Hypixel threads |
| Base vs inflected | base ≫ inflected | 60→35 (−25), biggest *penalty*. `Doggings` not OG. | mcindex; Hypixel 2017834, 5890011 |
| Length within word classes | shorter → higher | Acts as class gate first (≤6 for 80, ≤10 for 60, ≥11 → 35), tiebreak second (bonus 0.00–0.15). | mcindex `/names`, `/how-it-works` |
| Frequency / recognizability | more recognizable → higher | Gate at top: top word Zipf ≥4.5 & ≤6 chars; OG ≥3.5 & ≤10; semi ≥2.5. Within a class, small and inconsistent. | mcindex guides |
| Pronounceability | pronounceable → higher | Only 52 vs 45 (3L) and 20 vs 8 (4L). Rule: *"a vowel, no three consonants or vowels in a row and a usual start and end"*; 4,598/17,576 (26%) of 3L and 70,635/456,976 (15%) of 4L pass. | mcindex 3L guide |
| Pure letters vs digit/underscore | pure → higher | `Shadow7` 3 vs `Shadow` 60; `Fox_` 5. Demotion to another class, not a deduction. | mcindex; Hypixel 2017834 |
| Compound | above random, below base word | 12 pts — above 4L random (8), below second-tier (35). Contested; sells as premium. | mcindex; BuiltByBit 597650 |
| Proper noun / first name | ≈ common word | Folded into 60 (`Daniel`). mcindex: *"Proper nouns count as ordinary words. Cities and countries … are rated like English words."* | mcindex |
| Language | English ≈ German > all else | German allowed at 35; *"English and German only."* Non-English words misclassify as non-words. | mcindex |
| Leet / obfuscation | penalty | `Sh4dow` 12 vs `Shadow` 60. Never promotes. | mcindex |
| Repeater pattern | bonus within digit/char classes | `000`, `777`, `______` a distinct desirable sub-type to Choo; mcindex flat 45. | Hypixel 2017834 |
| Semantic / cultural weight | bonus, unquantified | Choo's Meme/Culture OG; circulated lists include `100`, `666`, `555`, `777`, `wp`. | Hypixel 2017834, 3223559 |
| Brand / reclaimable | negative, or refused | mcindex refuses; Choo rates OG. Real disagreement. | mcindex; Hypixel 2017834 |

---

## 4. Contested points

1. **Random 3L value.** mcindex 45 ("Collectible" — a tradeable asset). BuiltByBit: *"chearful
   sells random 3 letters for 5$"*, *"3 random letter names … are not really worth anything"*,
   *"Random 3 chars make up most 3 chars and they look bad normally."* Yet Hypixel: *"All 3
   character names are taken now as of Nov 2019"* — supply fixed at 17,576. Resolution: the
   *class* is scarce, the *individual name* is not. 45 badly overstates the median random 3L.
2. **Three-digit names.** Flat 45 for all 1,000 cannot express `777` ≫ `482`, yet `100`, `666`,
   `555`, `777` appear on circulated OG lists and Choo names `000` a "Repeater OG". Clearest
   case where a within-class term is mandatory.
3. **Compounds.** mcindex 12 ("minor feature"); BuiltByBit sells them as premium (597650,
   `HydroCarbon`); Hypixel's semi-OG explicitly includes *"added prefix/suffix"*. 12 too low,
   35 too high — unresolved, and it affects many real names.
4. **Non-English words.** *"English and German only."* A good Spanish, Portuguese or Indonesian
   word scores as a non-word — a large silent error class given those player populations.
5. **First names vs nouns.** mcindex folds both into 60. Hypixel posters tend to rate a noun
   (`Dog`) above a first name (`Daniel`). `Daniel` = `Fox` is defensible by supply, not by feel.
6. **4-letter names.** 20 pronounceable / 8 random on mcindex; Hypixel: *"4 letter is semi og
   sometimes"* but *"4 letter is not og, there's still tons of them available."* With 456,976
   possible and many free, the supply case for 20 is weak.
7. **Underscores.** mcindex demotes `_Shadow` to 12 and `Fox_` to 5; some lists treat edge
   underscores as aesthetic. No consensus; mcindex is the only published rule.
8. **Brand names.** mcindex refuses to rate (`Hypixel`, `MrBeast`); Choo rates them OG. Is a
   reclaimable name valuable? No answer.
9. **What "OG" means.** Choo (*"original forms of words and common definitions/slangs"*) vs
   DoctorWhere (*"common English words not invented after 2010"*) vs mcindex's Zipf thresholds —
   all different, none measurable. Treat "OG" as a *label derived from points*, which
   `rarity_label()` already does.
10. **Price anchors — all UNVERIFIED** (snippet-only or SEO-grade): 1-letter `G` asking $10k /
    refusing $8k; "high tier OG shop $3k–15k"; EpicNPC 3-char $150; PlayerUp 3L $100; and
    howmuchisitworth.app (3L $200–$2,000+, 4L $50–$500, one-word English $100–$2,000+, OG first
    names $200–$1,500, semi-OG $50–$300 — no stated methodology). Do not calibrate to these.

---

## 5. Proposed ordered scoring dimensions

No code — the design to implement. Structural insight: **the community reasons class-first,
then tiebreaks.** A weighted sum of independent factors does not reproduce that, because a
3L random name does not become "almost a word" by being short. Use an ordered pipeline where
each dimension only applies within the band the previous one selected.

- **D1 — Supply class (hard gate, dominant).** Bucket by what is *possible*, not by appearance:
  sub-3-char/invalid > word classes > 3L > 3-char mixed > 4L > 4-char mixed > clean > nothing.
  Only dimension with a defensible numeric gap (38–45 pts on mcindex). *Evidence: high.*
- **D2 — Word status (dominant within non-scarce bands).** base-form word > inflected/rare/
  long/German word > compound > leet > non-word. Order agreed; 60/35/12 spacing is mcindex's
  alone. *Evidence: high on order, low on magnitude.*
- **D3 — Form purity (hard demotion).** pure alpha > trailing digits ≤2 > internal
  digits/underscores > decorative framing (`xX_`, long tails). A gate before D4–D7.
  *Evidence: high (`Shadow7` vs `Shadow`; `Superman1` rejected).*
- **D4 — Length within band (small tiebreak).** Shorter better, but only inside a band length
  already gated. Effect ≲15% of a tier (mcindex uses 0.00–0.15). *Evidence: medium; mcindex's
  own length bonuses are inconsistent at equal length.*
- **D5 — Recognizability (small tiebreak, monotone).** Must be monotonically increasing in
  frequency. mcindex's published sub-score is not, so do not port it — use Zipf with a
  documented monotone mapping. *Evidence: medium on direction, none on magnitude.*
- **D6 — Pronounceability (small tiebreak, 3L/4L only).** Binary and deliberately generous
  (vowel, no 3-consonant/3-vowel run, usual start/end; admits 26% of 3L, 15% of 4L). Separates
  sub-classes only; must not promote a non-word. *Evidence: medium; mcindex calls the rule rough.*
- **D7 — Pattern and culture (small bonus, opt-in).** Repeaters (`777`, `000`, `______`),
  culturally loaded strings (`100`, `666`, `wp`), meme-weighted words. The only way to fix
  flat-45 digits — keep it small and enumerate it as a curated list, not a heuristic.
  *Evidence: medium (Choo's Repeater OG; circulated lists); no published weights.*
- **D8 — Reclaim risk (negative modifier, applied last).** Brands, celebrities, forced-change
  flags. Community disagrees on value; defensible choice is to score but mark, not refuse.
  *Evidence: low / genuinely contested.*

**Why this order.** D1 and D3 are gates because the community treats them as class membership,
not adjustments. D2 dominates within a band. D4–D7 combined must stay under one tier's width,
so no amount of "short + pronounceable + frequent" lifts a random string into the word classes.
D8 is a modifier so it can be surfaced without corrupting the base score.

**Concrete repo changes:**
- Add the two missing top classes (90, 85); the 80 ceiling makes `Zq`/`a_` = `Dog`.
- Keep the integer class bases (they match mcindex and the README's claim), but add a
  **separate documented within-class term** — mcindex explicitly says its position value
  *"never changes the points"*, so the repo cannot claim to follow mcindex while having no
  within-class term at all.
- Make D5 monotone; do not copy mcindex's component values.
- Decide and document the three contested calls (random-3L, compounds, non-English words) —
  each is a policy choice, not a fact.
- Keep `data/word_lists/rarity_overrides.tsv` (~904 KB of curated points) consistent: changing
  the base scale changes what every override means.

---

## 6. Sources

All accessed 2026-10-30.

**Primary numeric rubric — mcindex.gg**
- <https://mcindex.gg/names> — 18 classes, points 90/85/80/60/52/45/45/40/35/20/12/8/5/3/0.
- <https://mcindex.gg/how-it-works> — tiers, weaknesses, position. *"The position only decides
  between two classes of the same rank; it never changes the points."*; *"English and German
  only."*; *"Proper nouns count as ordinary words."*; *"Pronounceability is a rough rule."*
- <https://mcindex.gg/guides/og-minecraft-names> — Zipf thresholds 4.5 / 3.5 / 2.5.
- <https://mcindex.gg/guides/3-letter-minecraft-names> — 17,576 3L; 50,653 3-char; 4,598 (26%)
  pronounceable; 456,976 4L; 70,635 (15%) pronounceable; pronounceability rule.
- Name pages for within-class components: `/names/Dog` (5.30 → 0.68), `/names/Fox`
  (4.35 → 0.90, sum 0.93 clamped), `/names/Harbor` (4.05 → 0.59), `/names/Daniel`
  (4.72 → 0.80), `/names/Teacher` (4.76 → 0.90), `/names/Water` (5.36 → 0.66).

**Community definitions — Hypixel forums**
- Thread 2017834, "OG names and invalid names" —
  <https://hypixel.net/threads/og-names-and-invalid-names.2017834/> — Choo's taxonomy;
  *"original forms of words and common definitions/slangs"*; *"All 3 character names are taken
  now as of Nov 2019"*; Repeater OG and Meme/Culture OG; rejects `Doggings`, `CS_GO`,
  `xxOperatorxx`, `Superman1`.
- Thread 5890011, "What defines a semi-OG Minecraft name?" —
  <https://hypixel.net/threads/what-defines-a-semi-og-minecraft-name.5890011/> — DoctorWhere:
  OG is *"non-plural, non-adverb, non-past-tense, common English words not invented after
  2010"*; *"a semi-og name is either a name with not a lot of letters (4 MAYBE 5) but doesn't
  spell anything coherent"*.
- Thread 2988093, "OG names" — <https://hypixel.net/threads/og-names.2988093/>
- Thread 3223559, "500+ users Hypixel forums OG list" —
  <https://hypixel.net/threads/500-users-hypixel-forums-og-list.3223559/> — includes `100`,
  `666`, `555`, `777`, `8`, `wp`.
- Thread 1538391, "How to get a OG name" —
  <https://hypixel.net/threads/how-to-get-a-og-name.1538391/> — NameMC monthly-searches method.

**Marketplace / trading**
- BuiltByBit 597650 — <https://builtbybit.com/threads/597650/> — compound valuation
  (`HydroCarbon`).
- BuiltByBit 606871 — <https://builtbybit.com/threads/606871/> — *"chearful sells random 3
  letters for 5$"*; *"3 random letter names for example 'jm8' are not really worth anything"*;
  *"Random 3 chars make up most 3 chars and they look bad normally."*
- **UNVERIFIED** (snippet-only): 1-letter `G` $10k ask / $8k refused; "high tier OG account shop
  $3k–15k"; EpicNPC 3-character account $150; PlayerUp 3-letter names $100.
- **UNVERIFIED / low trust** — <https://howmuchisitworth.app/minecraft-account-value> — 3L
  $200–$2,000+; 4L $50–$500; one-word English $100–$2,000+; OG first names $200–$1,500;
  semi-OG $50–$300. No methodology; SEO content, not evidence.

**Mechanics (authoritative)**
- Minecraft Wiki, `Player#Username` — <https://minecraft.wiki/w/Player#Username> — 3–16 chars;
  rename once per 30 days; previous name released after 37 days; 1–2 char names permanently
  unobtainable once changed.
- Minecraft Wiki, `Java Edition account migration` —
  <https://minecraft.wiki/w/Java_Edition_account_migration> — deleted unmigrated accounts'
  usernames *"may or may not be available"*.

**Sentiment**
- r/Minecraft comment via pullpush (reddit.com blocks direct fetches): *"Ryan is an OG username.
  Ryan1995 is not."* — <https://api.pullpush.io/reddit/search/comment/?q=%22OG%20username%22&subreddit=Minecraft>

---

### Residual unknowns (for the repo owner)

1. No source publishes a *validated* point scale. If the README claims a "community model", that
   is stronger than the evidence supports — consider "mcindex.gg's rubric, cross-checked against
   Hypixel usage".
2. mcindex's within-class values cannot be reproduced from its stated formula (non-monotonic in
   Zipf). Do not port them; design a monotone replacement.
3. Flat-45 3-digits and 45-for-random-3L are where the rubric most visibly diverges from market
   behaviour; both are fixable with a small curated pattern list.
4. Price data is effectively unverifiable at this effort level. Any calibration to money is a
   hypothesis, not a finding.
