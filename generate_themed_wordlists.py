"""Generate themed OG / semi-OG word lists for mc-og-name-hunter.

Most of the core lists are English-centric: they come from an English
frequency model, so a perfectly good foreign word such as ``perro``,
``sakura`` or ``zhongguo`` scores near zero.  This script builds
supplemental lists from:

* ``wordfreq`` multilingual frequency data (offline),
* public first-name / surname / country / Wordle datasets (cached under
  ``data/themed_cache``; pass ``--offline`` to use the cache only),
* curated geography, nature, mythology, Latin, tech, food, music, sports,
  space, Minecraft, brand and compound-name collections.

It writes one ``*.txt`` file per theme and a single
``rarity_overrides.tsv`` mapping every generated word to its intended
points.  ``src.models.rarity_points`` reads that file and uses the higher
of the English score and the curated tier, so the rest of the program
(generation, filtering, storage, display and auditing) automatically
agrees on the value.

Usage::

    python generate_themed_wordlists.py
    python generate_themed_wordlists.py --offline
    python generate_themed_wordlists.py --output-dir data/word_lists
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import urllib.request
from pathlib import Path

try:
    from unidecode import unidecode
except Exception:  # pragma: no cover - dependency is in requirements.txt
    unidecode = None

try:
    from wordfreq import iter_wordlist, zipf_frequency
except Exception:  # pragma: no cover - wordfreq is required by the project
    iter_wordlist = None
    zipf_frequency = None

from generate_custom_wordlists import is_banned


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "word_lists"
CACHE_DIR = REPO_ROOT / "data" / "themed_cache"

# Files produced by this script.  They are excluded from the "already in the
# corpus" set so the script can be rerun and refreshed in place.
GENERATED_NAMES = {"rare_names.txt", "semi_names.txt"}
GENERATED_PREFIXES = ("og_", "semi_")

# Language, number of valid words to keep, points.  Most are OG (60); short
# words are promoted to TOP (80) by _record(short_top=True).
MULTILINGUAL = [
    ("es", 3000, 60), ("fr", 3000, 60), ("de", 3000, 60),
    ("it", 2500, 60), ("pt", 2500, 60), ("nl", 2200, 60),
    ("sv", 2000, 60), ("no", 2000, 60), ("da", 2000, 60),
    ("fi", 1800, 60), ("pl", 2200, 60), ("cs", 1800, 60),
    ("sk", 1500, 60), ("hu", 1800, 60), ("ro", 1800, 60),
    ("tr", 2200, 60), ("id", 2200, 60), ("ms", 1800, 60),
    ("vi", 1800, 60), ("tl", 1800, 60),
    ("af", 1500, 60), ("hr", 1500, 60), ("sr", 1500, 60),
    ("bg", 1500, 60), ("uk", 1800, 60), ("ru", 2200, 60),
    ("el", 1500, 60), ("ar", 1800, 35), ("fa", 1500, 35),
    ("hi", 1500, 35), ("ja", 1200, 35), ("ko", 1200, 35),
    ("zh", 1200, 35),
]


US_STATES = """
alabama alaska arizona arkansas california colorado connecticut delaware
florida georgia hawaii idaho illinois indiana iowa kansas kentucky louisiana
maine maryland massachusetts michigan minnesota mississippi missouri montana
nebraska nevada newhampshire newjersey newmexico newyork northcarolina
northdakota ohio oklahoma oregon pennsylvania rhodeisland southcarolina
southdakota tennessee texas utah vermont virginia washington westvirginia
wisconsin wyoming
""".split()

CA_PROVINCES = """
alberta britishcolumbia manitoba newbrunswick newfoundland labrador
novascotia ontario princeedwardisland quebec saskatchewan northwestterritories
nunavut yukon
""".split()

CITIES = """
amsterdam athens atlanta auckland baghdad bangkok barcelona beijing beirut
belfast belgrade berlin bern bogota boston brasilia bratislava brussels
bucharest budapest buenosaires cairo calgary canberra capeTown caracas
casablanca chicago copenhagen dakar damascus delhi denver dhaka doha dubai
dublin edinburgh frankfurt geneva glasgow guatemala hamburg hanoi havana
helsinki hongkong honolulu houston istanbul jakarta jerusalem johannesburg
kabul karachi kathmandu kiev kingston kualalumpur kuwait lagos lasvegas lima
lisbon london losangeles luanda luxembourg lyon madrid manila maputo marseille
medellin melbourne mexico miami milan minsk monaco montreal moscow mumbai
munich nairobi naples newdelhi neworleans newyork oslo ottawa paris perth
philadelphia phoenix prague pretoria quebec quito rabat reykjavik rio riga
riyadh rome sanfrancisco santiago santoDomingo saopaulo seattle seoul
singapore sofia stockholm sydney taipei tallinn tehran telaviv tokyo toronto
tunis vancouver venice vienna warsaw washington wellington zurich
""".split()

LANDMARKS = """
acropolis alhambra alps amazon andes angkor arcadia atlantis avalon babylon
bigben borobudur brooklyn bridge colosseum everest eiffel fjord forbidden
giza golden gate grandcanyon hadrian hagia sophia hollywood kilimanjaro
kremlin louvre machu picchu matterhorn metropolis mont saint michel
mountfuji niagara notredame olympus parthenon petra pyramids redsquare
sahara sphinx stonehenge taj mahal tiananmen tower bridge uluru versaille
westminster yellowstone
""".split()


ANIMALS = """
aardvark albatross alligator alpaca anaconda ant anteater antelope armadillo
baboon badger barracuda bat bear beaver bee beetle bison boar bobcat buffalo
butterfly camel capybara caribou cat caterpillar cattle chameleon cheetah
chicken chimp chimpanzee chinchilla chipmunk cobra cockatoo condor cougar cow
coyote crab crane crocodile crow cuckoo deer dingo dog dolphin donkey dove
dragonfly duck eagle eel elephant elk emu falcon ferret finch firefly fish
flamingo fly fox frog gazelle gecko gerbil gibbon giraffe goat goose gopher
gorilla grasshopper grouse guppy hamster hare hawk hedgehog heron hippo
hippopotamus hog horse hummingbird hyena ibex iguana impala jackal jaguar
jellyfish kangaroo koala koi ladybug lamb lemur leopard lion lizard llama
lobster lynx macaw magpie mammal manatee mandrill mantis marmot marten meerkat
mink mole mongoose monkey moose mosquito moth mouse mule mussel newt
nightingale ocelot octopus okapi opossum orangutan orca ostrich otter owl ox
panda panther parrot peacock pelican penguin pheasant pig pigeon piranha
platypus pony porcupine porpoise possum prawn puffin puma python quail rabbit
raccoon ram rat raven ray reindeer reptile rhino rhinoceros robin rooster
salamander salmon sardine scorpion seahorse seal shark sheep shrew shrimp
skunk sloth snail snake sparrow spider sponge squid squirrel stag starfish
stingray stork swan swordfish tadpole tapir tarantula termite tiger toad
tortoise toucan trout tuna turkey turtle viper vulture walrus warthog wasp
weasel whale wolf wolverine wombat woodpecker worm yak zebra zebu
""".split()

BIRDS = """
avocet bittern blackbird bluebird bluejay buzzard cardinal chaffinch chickadee
coot cormorant curlew dodo dunlin egret falcon finch flamingo goldfinch
grackle grebe grouse guillemot gull harrier hawk heron hoopoe hummingbird ibis
jay kestrel kingfisher kite kiwi lapwing lark loon magpie martin merlin
mockingbird murre nightjar nuthatch oriole osprey owl parakeet parrot partridge
peacock pelican penguin petrel pheasant pigeon pipit plover puffin quail raven
redwing roadrunner robin rook sandpiper shrike skylark snipe sparrow starling
stork swallow swan swift teal tern thrush toucan towhee turkey vulture warbler
waxwing whippoorwill wigeon woodcock woodpecker wren yellowhammer
""".split()

FISH = """
anchovy angelfish bass barb betta bloater bluefish bream carp catfish char cod
conger dace dorado eel flounder gar goldfish gourami grayling grouper guppy
haddock hake halibut herring ide jackfish koi lamprey lingcod loach mackerel
mahi marlin minnow molly monkfish mullet perch pike pilchard plaice pollock
puffer ray roach salmon sardine saury sawfish scad seabass shark skate smelt
snapper sole sprat stingray sturgeon sunfish swordfish tarpon tench tetra trout
tuna turbot wahoo walleye wrasse yellowtail zebrafish
""".split()

PLANTS = """
acacia alder almond amaryllis anemone apple ash aspen aster azalea balsa baobab
beech begonia bellflower birch bluebell boxwood buttercup camellia carnation
cedar chamomile cherry chestnut chrysanthemum clover columbine crocus cypress
daffodil dahlia daisy dandelion delphinium dogwood ebony elm eucalyptus fig fir
foxglove freesia gardenia geranium gladiolus hazel hemlock hibiscus hickory
hollyhock hornbeam hyacinth hydrangea iris ironwood jasmine juniper kale
larch laurel lavender lemon lilac lily lime linden lotus lupine magnolia
mahogany maple marigold mesquite milkweed mimosa narcissus nasturtium oak
olive orange orchid palm pansy peach pear pecan peony petunia phlox pine
poinsettia poppy poplar primrose redwood rose rowan sequoia snapdragon
snowdrop spruce sunflower sweetpea sycamore teak tulip violet walnut willow
wisteria yew zinnia
""".split()

DINOSAURS = """
allosaurus ankylosaurus apatosaurus archaeopteryx baryonyx brachiosaurus
brontosaurus carnotaurus ceratosaurus coelophysis compsognathus deinonychus
dilophosaurus diplodocus dromaeosaurus gallimimus gigantosaurus hadrosaur
iguanodon kronosaurus lambeosaurus maiasaura megalodon megalosaurus
mosasaurus pachycephalosaurus parasaurolophus plesiosaur pteranodon
pterodactyl raptor sauropod spinosaurus stegosaurus styracosaurus
therizinosaurus triceratops trex tyrannosaurus velociraptor vulcanodon
""".split()


MYTHOLOGY = """
achilles adonis aesir agni amaterasu amun anu anubis aphrodite apollo ares
ariadne artemis asgard atlas balder banshee bastet behemoth brahma bragi
brigid cassandra centaur cerberus cernunnos chaos charon chimera chiron cronus
cyclops daedalus dagda danu demeter dionysus dragon dryad durga dwarf echo
elf enki enlil eros eurydice fairy fenrir freya freyr frigg fury gaia galatea
ganesha gargoyle geb giant gilgamesh gnome goblin golem griffin hades hanuman
harpy hecate heimdall hel helios hera hercules hermes hestia hippolyta horus
hydra hypnos icarus idun imp indra inari iris ishtar isis izanagi izanami
janus jason jormungandr juno jupiter kali kerberos khonsu kirin kitsune
kraken krishna lakshmi leviathan lich lugh maat marduk medusa mermaid merman
midgard mimir minerva minotaur morpheus morrigan nemesis neptune nephthys
nike njord nuada nymph nyx odin oedipus ogre olympus oni orc orion orpheus
osiris pan pandora parvati pegasus persephone perseus phoenix pixie pluto
poseidon prometheus psyche ptah ra ragnarok raijin rama satyr seer selene set
shiva siren sisyphus sita sobek sphinx spirit susanoo surya tengu thanatos
theseus thoth thor tiamat titan triton troll tsukuyomi tuatha tyr unicorn
valhalla valkyrie vampire vidar vishnu vulcan werewolf wyvern yama yeti ymir
zeus zombie
""".split()

LATIN = """
acedia adulescens aeger aevum agricola albus altus amicitia amor anima animus
annus aqua aquila ara arbor arcus argentum ars artemis articulus asinus asper
atrium auris aurum avaritia avis basilica bellum bestia bonus bos brevis
butyrum caelum calor candidus canis capra captivus caput caritas caro caseus
castellum castrum catena causa cavea celer cena charta cinis circus civitas
clarus clavis coelum coquus cor corpus corvus crinis crocodilus crux cubiculum
culina culpa cura custos daemon dea dens deus dextera dies digitus dives dolor
domina dominus domus donum dormire dux ebrietas ecclesia ego eheu ens equus
ergo errata esse etiam evangelium exilium faber fabula feles felix fera ferrum
fides filia filius finis fiumen flamma flavus flos flumen focus fons forma
fortis fortuna forum frater frigus fructus fuga fumus fundus furor gens gemma
glacies gladiator gloria gradus gratia gravis gula gustus harena hereditas
historia homo honor hora hortus hostia humilis humilitas iaculum ianua ignis
imperium inanis infernus infans iniuria insula invidia ira iter iudex ius
iuvenis labes labor lac lacrima lacus laetus lapis latro laus lectus legio
leo lex liber liberi libertas lingua littera locus longus luna lupus lux
magister magnus mare margarita mater matrona medicus mel memoria mens mensa
mercator meridies meta miles militia minerva minister mirabilis miser modus
mola momentum mons monstrum mors mortuus mulier mundus murus mus musica mutus
narratio natura nauta navis necessitas nebula niger nix nobilis nox numerus
nuntius nutrix oceanus oculus oleum opus orbis ordo origo os ostium ovum
pabulum panis papa paratus parens parvus passio pastor pater patientia pax
peccatum pellis penna pera periculum pes piscis pistor planitia plenus plumbum
pluvia poena poeta populus porta portus potestas prex princeps proelium
profeta promissum propheta puer puella pulcher purpura quaestio quies radix
rama rapina regina regio regnum rex rhetor ridere ritus rosa ruber rubor rudis
ruina rumor rupes sacer sacerdos saeculum sal salus sanguis sanus sapiens
sapientia saxum scaena scientia scintilla scriptor scutum secunda sedes
semita senex senatus sermo serpens servitus servus signum silentium silva
simulacrum sitis sol solacium somnium somnus sonus sors spatium species
spectaculum spes spiritus splendor stannum statua stella stilla stirps
studium stultus suavitas subita summa superbia surdus susurrus taberna
tabula taedium talis tandem templum tempestas templum tempus tenebrae terra
testis thermae thesaurus thymus tigris timor titulus tolerantia tormentum
totus tractus trinitas tristis triumphus tropaeum truncus tuba tueri turba
turpis turris tutela umbra unctio unguis unitas universum unus urbs ursus
usus uva vacatio vapor varius vas vastus vehiculum velum venator venenum
venia ventus ver veritas verbum vermis vestis vetus via victima victoria
vicus vinum vir virgo virtus vis visio vita vitium vivus vox vulgus vulpes
vulnus
""".split()


TECH = """
python java rust golang swift kotlin scala ruby perl php javascript typescript
nodejs react angular vue svelte nextjs nuxt django flask fastapi spring rails
laravel express graphql rest grpc docker kubernetes terraform ansible jenkins
gitlab github bitbucket linux ubuntu debian fedora arch centos alpine bash zsh
fish powershell vim neovim emacs nano tmux screen ssh scp rsync curl wget grep
sed awk find xargs tar gzip zip unzip make cmake gcc clang llvm gdb valgrind
strace lsof netstat iptables nginx apache caddy haproxy redis memcached mysql
postgres sqlite mongodb cassandra elasticsearch kafka rabbitmq zookeeper etcd
consul vault nomad prometheus grafana kibana logstash jaeger zipkin
opentelemetry datadog splunk sentry cloudflare akamai fastly aws azure gcp
digitalocean linode heroku vercel netlify render railway flyio supabase
firebase auth0 okta keycloak oauth jwt saml ldap kerberos tls ssl https http
tcp udp ipv4 ipv6 dns dhcp bgp ospf vpn nat cdn api sdk cli gui ide vscode
jetbrains eclipse intellij pycharm webstorm android ios flutter reactnative
xamarin unity unreal godot blender figma sketch photoshop illustrator canva
jira confluence slack discord teams zoom notion trello asana monday clickup
git svn mercurial npm yarn pnpm pip poetry conda maven gradle cargo nuget
composer bundler webpack vite babel eslint prettier jest mocha pytest junit
selenium cypress playwright postman swagger openapi protobuf avro parquet
hadoop spark flink airflow dbt snowflake databricks bigquery redshift
clickhouse druid presto trino luigi dagster prefect mlflow kubeflow sagemaker
tensorflow pytorch keras sklearn numpy pandas scipy matplotlib seaborn plotly
jupyter anaconda colab opencv nltk spacy huggingface transformers langchain
llamaindex chroma pinecone weaviate milvus faiss ollama llama gpt bert
diffusion gan cnn rnn lstm svm kmeans pca xgboost lightgbm catboost
""".split()

FOOD = """
apple apricot avocado banana blackberry blueberry boysenberry cherry cranberry
currant date dragonfruit durian elderberry fig grape grapefruit guava honeydew
huckleberry jackfruit kiwi kumquat lemon lime lychee mango melon mulberry
nectarine orange papaya passionfruit peach pear persimmon pineapple plum
pomegranate pomelo quince raspberry strawberry tangerine watermelon almond
cashew chestnut hazelnut macadamia peanut pecan pistachio walnut artichoke
asparagus beet bellpepper broccoli cabbage carrot cauliflower celery chard
chickpea chili chive corn cucumber eggplant endive fennel garlic ginger kale
kohlrabi leek lentil lettuce mushroom mustard okra olive onion parsley parsnip
pea pepper potato pumpkin radish rhubarb rutabaga scallion shallot spinach
squash tomato turnip zucchini basil bay cardamom cayenne cilantro cinnamon
clove coriander cumin dill fenugreek mint nutmeg oregano paprika rosemary
saffron sage tarragon thyme turmeric vanilla bread bagel baguette biscuit
brioche brownie cake cookie croissant donut muffin pancake pretzel scone waffle
pasta pizza lasagna ravioli risotto spaghetti ramen sushi taco burrito
quesadilla nachos paella curry biryani kebab falafel hummus pita samosa
dumpling noodle rice quinoa oats cereal granola honey jam jelly butter cheese
yogurt cream milk cocoa chocolate caramel toffee fudge syrup sugar salt
vinegar oil ketchup mustard mayo salsa guacamole pesto marinara alfredo gravy
soup stew salad sandwich burger steak bacon sausage ham chicken turkey duck
lamb beef pork fish shrimp lobster crab oyster clam mussel scallop squid
octopus caviar tofu tempeh seitan egg omelet coffee espresso latte cappuccino
mocha matcha tea chai soda cola lemonade juice smoothie milkshake wine beer
cider mead sake vodka whiskey rum gin tequila brandy champagne cocktail
mocktail
""".split()

MUSIC = """
guitar piano violin viola cello bass drums drum flute clarinet oboe bassoon
saxophone trumpet trombone tuba horn harp banjo mandolin ukulele sitar tabla
lute lyre accordion harmonica organ synthesizer keyboard xylophone marimba
vibraphone timpani cymbal snare tom conga bongo djembe tambourine triangle gong
bell chime melody harmony rhythm tempo beat note chord scale key octave pitch
tone timbre crescendo decrescendo staccato legato vibrato tremolo arpeggio
cadence sonata symphony concerto opera ballet jazz blues rock pop hiphop rap
country folk metal punk reggae ska funk soul gospel disco techno house trance
dubstep ambient classical baroque romantic choir chorus verse bridge hook riff
solo duet trio quartet quintet orchestra band ensemble conductor composer
maestro virtuoso ballad anthem lullaby serenade requiem overture prelude fugue
etude nocturne waltz tango salsa samba rumba flamenco bossa swing groove
""".split()

SPORTS = """
soccer football basketball baseball tennis golf hockey cricket rugby boxing
wrestling swimming cycling running marathon sprint hurdle relay gymnastics
athletics archery fencing judo karate taekwondo kungfu aikido sumo rowing
sailing surfing skateboarding snowboarding skiing biathlon triathlon decathlon
pentathlon polo lacrosse squash badminton tabletennis volleyball handball
netball dodgeball kickball softball rounders bowls curling bobsled luge
skeleton climbing bouldering hiking camping fishing hunting shooting
equestrian dressage showjumping racing rally drifting karting motocross
formula nascar indycar motogp esports gaming speedrun parkour freerunning
calisthenics weightlifting bodybuilding powerlifting crossfit yoga pilates
aerobics zumba mma ufc wwe aew kabaddi hurling camogie shinty bandy floorball
futsal sevens wicket striker goalkeeper defender midfielder forward winger
quarterback runningback receiver linebacker cornerback safety pitcher catcher
batter bowler batsman fielder umpire referee coach captain mascot trophy medal
podium olympics paralympics commonwealth worldcup playoff final semifinal
quarterfinal derby rivalry stadium arena court pitch field track pool rink
ring cage mat net goal basket touchdown homerun ace birdie eagle bogey par
hattrick knockout submission decision draw tie overtime penalty foul offside
dribble pass shoot serve volley smash spike block tackle dunk slamdunk
freethrow wicketkeeper
""".split()

COSMOS = """
space cosmos universe galaxy nebula star sun moon planet asteroid comet meteor
meteorite meteoroid quasar pulsar blackhole wormhole supernova nova
constellation orbit gravity vacuum void celestial astronomy astrology telescope
observatory satellite rocket shuttle launchpad astronaut cosmonaut taikonaut
spacesuit spacewalk mission apollo artemis gemini mercury venus earth mars
jupiter saturn uranus neptune pluto ceres eris haumea makemake charon titan
europa ganymede callisto io enceladus triton phobos deimos miranda ariel
titania oberon pandora prometheus atlas calypso helios selene lunar solar
stellar galactic cosmic interstellar intergalactic exoplanet habitable
goldilocks redshift blueshift lightyear parsec hubble webb kepler spitzer
chandra voyager pioneer cassini galileo juno newhorizons perseverance curiosity
opportunity spirit sojourner rosetta philae hayabusa osiris bennu ryugu itokawa
vesta pallas hygiea psyche trojan kuiper oort heliopause magnetosphere
ionosphere exosphere thermosphere stratosphere mesosphere troposphere
atmosphere aurora borealis australis eclipse solstice equinox zodiac aries
taurus cancer leo virgo libra scorpio sagittarius capricorn aquarius pisces
orion andromeda pegasus cassiopeia cygnus lyra draco hydra phoenix centaurus
pavo tucana octans mensa norma circinus musca chamaeleon apus volans dorado
reticle telescopium microscopium indus grus scutum vulpecula sagitta delphinus
equuleus lacerta lynx camelopardalis auriga perseus triangulum corvus crater
sextans antlia pyxis puppis vela carina columba lepus canis monoceros
""".split()

COLORS = """
red blue green yellow orange purple violet indigo cyan magenta pink brown
black white gray grey silver gold bronze copper brass steel iron ruby emerald
sapphire diamond pearl opal topaz amber jade onyx coral turquoise aqua teal
navy maroon crimson scarlet vermilion burgundy wine rose blush peach apricot
tangerine lemon lime mint olive sage forest hunter moss fern pine seafoam
aquamarine cerulean azure cobalt ultramarine lavender lilac plum mauve orchid
fuchsia salmon melon sand beige tan khaki ivory cream vanilla champagne
caramel chocolate coffee mocha chestnut mahogany walnut oak ebony charcoal
slate ash smoke fog cloud snow frost ice sky ocean sea midnight twilight dawn
dusk sunset sunrise rainbow prism spectrum neon pastel vivid bright dark light
pale deep
""".split()

MC_CREATORS = """
dream georgenotfound sapnap karljacobs quackity tommyinnit tubbo ranboo wilbur
philza technoblade skeppy badboyhalo hannahxxrose wallibear purpled punz ponk
fundy nihachu jacksepticeye markiplier pewdiepie dantdm captainsparklez
antvenom skydoesminecraft stampylonghead iballisticsquid ldshadowlady
smallishbeans geminitay fwhip joeygraceffa laurenzside aphmau prestonplayz
bajancanadian vikkstar lazarbeam muselk alia jeromeasf huskymudkipz skythekidrs
yogscast simon lewis sips hatfilms totalbiscuit ethoslab docm77 xisumavoid
mumbo grian iskall rendog falsesymmetry impulsesv tangotek scar bdubs keralis
stressmonster vintagebeef zombcleo joehills cleo martyn inthelittlewood
orionsound smajor jimmy solidarity lizzie joel pixlriffs wattles systemzee
""".split()

MC_META = """
hardcore survival creative adventure spectator peaceful easy normal hard smp
lifesteal manhunt speedrun oneblock skyblock bedwars skywars uhc pvp griefing
anarchy factions prison kitpvp duels mcc hermitcraft empires dreamsmp originsmp
afterlife dsmp qsmp osmp smpearth smplive mcpvp hypixel mineplex cubecraft hive
wynncraft donutsmp
""".split()

BRANDS = """
nike adidas puma reebok underarmour newbalance asics converse vans timberland
gucci prada versace armani chanel dior hermes louisvuitton burberry givenchy
balenciaga fendi rolex omega cartier tagheuer patek audemars breitling fossil
casio seiko citizen apple samsung google microsoft amazon meta tesla spacex
nvidia amd intel qualcomm sony nintendo xbox playstation sega atari steam
epicgames riotgames blizzard ubisoft rockstar bethesda valve mojang roblox
minecraft fortnite callofduty battlefield overwatch valorant leagueoflegends
dota csgo apex pubg fifa nba2k madden gtav reddead witcher eldenring darksouls
zelda mario pokemon sonic kirby metroid halo doom quake wolfenstein
assassinscreed farcry watchdogs tombraider uncharted lastofus godofwar
spiderman batman superman marvel disney pixar starwars startrek harrypotter
lordoftherings gameofthrones strangerthings breakingbad friends office
simpsons futurama rickandmorty southpark familyguy spongebob yugioh naruto
onepiece dragonball attackontitan demonslayer jujutsu myhero swordart bleach
deathnote evangelion ghibli totoro digimon beyblade bakugan transformers
barbie bratz lego playmobil nerf hotwheels matchbox funko monopoly scrabble
uno jenga rubik slinky litebrite spirograph squishmallow carebears
mylittlepony littlestpet pollypocket buildabear toyota honda ford chevrolet
dodge chrysler jeep bmw audi mercedes porsche ferrari lamborghini maserati
bugatti bentley rollsroyce astonmartin jaguar landrover mini volvo saab subaru
mazda nissan infiniti lexus acura hyundai kia genesis mitsubishi suzuki
peugeot citroen renault fiat alfaromeo lancia seat skoda opel vauxhall
volkswagen koenigsegg pagani mclaren lotus caterham morgan
""".split()

GAMES = """
minecraft roblox fortnite terraria stardew pokemon zelda mario sonic kirby
metroid halo doom quake portal halflife counterstrike overwatch valorant
leagueoflegends dota apex pubg rust ark factorio rimworld simcity civilization
ageofempires starcraft warcraft diablo elder scrolls skyrim fallout witcher
cyberpunk gta reddead assassinscreed farcry watchdogs hitman splintercell
tombraider uncharted lastofus godofwar spiderman batman eldenring darksouls
sekiro bloodborne nioh monsterhunter finalfantasy dragonquest persona xenoblade
fireemblem smash tekken streetfighter mortalkombat soulcalibur killerinstinct
guiltygear blazblue skullgirls undertale deltarune hollowknight celeste ori
cuphead shovelknight deadcells hades bastion transistor journey flower limbo
inside braid fez superhot witness myst riven monkeyisland samandmax
brokensword grimfandango dayofthetentacle thimbleweed deponia runescape
maplestory wow everquest guildwars eso ffxiv osrs albion blackdesert lostark
newworld
""".split()

FOREIGN_ICONS = """
sakura samurai ninja sensei senpai anime manga karaoke sushi ramen tempura
wasabi matcha origami kimono katana shogun ronin haiku zen koi bonsai geisha
sumo aikido judo karate ninjutsu dojo tatami futon sake tofu miso udon soba
yakuza kawaii arigato sayonara konnichiwa ohayo genki kami kaiju mecha otaku
bento ramune mikado tanuki kitsune yokai tengu oni kanji hiragana katakana
shinobi gundam akihabara shibuya harajuku kyoto osaka nagoya sapporo okinawa
hokkaido honshu fuji kamikaze tsunami tycoon karoshi hikikomori waifu husbando
kohai baka sugoi neko inu tora usagi kuma onigiri mochi dango taiyaki takoyaki
okonomiyaki yakitori teriyaki edamame natto nori kombu dashi umami
kungfu taichi qigong wushu shaolin wuxia xianxia jianghu yin yang qi chi tao
dao feng shui hongkong taipei beijing shanghai shenzhen guangzhou hangzhou
chengdu chongqing xian nanjing suzhou wuhan tianjin macau canton mandarin
cantonese panda dragon tiger phoenix lotus jade silk tea dimsum dumpling wonton
baozi chowmein chopsticks wok soy ginger ginseng mahjong weiqi xiangqi
seoul busan incheon daegu daejeon gwangju ulsan jeju hangang hanbok kimchi
bibimbap bulgogi tteokbokki soju makgeolli taekwondo hapkido taekkyeon kpop
kdrama hangul hangeul chaebol oppa unni noona hyung maknae daebak sarang
hwaiting manhwa webtoon naver kakao lotte goryeo joseon silla baekje goguryeo
hwarang sejong dokdo halla seorak namsan hanok ondol jjimjilbang norae
habibi habibti inshallah mashallah alhamdulillah bismillah salam shalom yalla
wallah haram halal jihad sheikh sultan sahara aladdin genie bazaar harem hijab
niqab kaaba mecca medina quran islam muslim arab persia iran iraq syria lebanon
jordan egypt cairo nile sphinx pyramid pharaoh cleopatra nefertiti tutankhamun
anubis osiris isis horus ra set thoth sobek bastet sekhmet hathor ptah amun
aten scarab ankh obelisk mummy sarcophagus papyrus hieroglyph oasis bedouin emir
caliph vizier souk falafel hummus pita kebab shawarma baklava halva tahini
couscous tagine saffron cumin sumac zaatar hookah shisha henna kohl attar oud
amber musk sandalwood jasmine lotus cedar olive fig date pomegranate apricot
quince melon watermelon grape wine raki arak ouzo
yoga guru karma dharma moksha nirvana samsara mantra tantra chakra kundalini
ayurveda dosha veda upanishad bhagavad gita ramayana mahabharata om aum namaste
shanti ahimsa satya maya lila bhakti shakti prana chai masala curry naan roti
samosa pakora biryani tandoori tikka paneer ghee lassi raita chutney papad dal
raj maharaja maharani raja rani thug jungle bungalow veranda pyjama shampoo
khaki cashmere calico bandana dinghy loot juggernaut avatar sutra ashram swami
yogi sadhu brahmin kshatriya vaishya shudra hindi urdu sanskrit tamil telugu
bengali marathi gujarati punjabi rajasthan delhi mumbai kolkata chennai
bangalore hyderabad goa taj mahal ganges ganga yamuna himalaya everest kashmir
nepal tibet buddha buddhism hindu sikh jain
amigo amiga amor casa gato perro loco fiesta siesta manana hola adios bueno
grande pequeno rojo azul verde blanco negro sol luna estrella cielo mar tierra
fuego agua viento noche dia vida muerte paz guerra rey reina dios diablo angel
demonio fantasma sombra luz oscuridad corazon alma sangre hueso acero piedra
oro plata cobre hierro jade rubi perla coral ambar hielo tormenta rayo trueno
lluvia nieve nube niebla amanecer atardecer
bonjour bonsoir merci salut amour maison chat chien roi reine dieu diable ange
demon fantome ombre lumiere nuit jour vie mort paix guerre ciel mer terre feu
eau vent etoile lune soleil or argent cuivre fer jade rubis perle corail ambre
glace tempete tonnerre pluie neige nuage brouillard aube crepuscule
ciao amore casa gatto cane re regina dio diavolo angelo demone fantasma ombra
luce notte giorno vita morte pace guerra cielo mare terra fuoco acqua vento
stella luna sole oro argento rame ferro giada rubino perla corallo ambra
ghiaccio tempesta tuono pioggia neve nuvola nebbia alba tramonto
ola amor casa gato cao rei rainha deus diabo anjo demonio fantasma sombra luz
noite dia vida morte paz guerra ceu mar terra fogo agua vento estrela lua sol
ouro prata cobre ferro jade rubi perola coral ambar gelo tempestade trovao
chuva neve nuvem neblina amanhecer anoitecer
hallo liebe haus hund katze konig konigin gott teufel engel damon geist schatten
licht nacht tag leben tod frieden krieg himmel meer erde feuer wasser wind stern
mond sonne gold silber kupfer eisen jade rubin perle koralle bernstein eis sturm
donner regen schnee wolke nebel morgen abend
hola liefde huis hond kat koning koningin god duivel engel demon geest schaduw
licht nacht dag leven dood vrede oorlog hemel zee aarde vuur water wind ster maan
zon goud zilver koper ijzer jade robijn parel koraal barnsteen ijs storm donder
regen sneeuw wolk mist ochtend avond
""".split()

COMPOUND_ROOTS = """
iron frost storm fire ice void night star moon sun dark light wild swift raven
wolf fox hawk bear lion tiger dragon phoenix blade arrow spear shield crown
king queen lord saint knight mage wizard rogue ranger hunter sniper ghost demon
angel spirit soul heart blood bone steel stone gold silver copper bronze jade
ruby onyx opal pearl coral amber ember blaze thunder lightning rain snow wind
cloud mist fog dawn dusk eclipse cosmic astro nova orbit comet meteor galaxy
nebula quasar pulsar zenith apex alpha omega origin vertex cyber neon pixel
byte code data logic matrix vector cipher enigma paradox rune sigil totem relic
artifact legend myth fable saga epic hero villain titan god deity oracle
prophet seer witch warlock druid shaman monk paladin cleric bard assassin thief
pirate ninja samurai viking spartan gladiator centurion emperor empress pharaoh
sultan shah czar kaiser regent noble royal rebel outlaw bandit mercenary
crusader templar sentinel guardian warden keeper watcher seeker wanderer
traveler explorer pioneer voyager nomad exile stranger phantom wraith specter
banshee revenant lich ghoul zombie vampire werewolf golem gargoyle griffin
wyvern kraken leviathan hydra chimera sphinx unicorn pegasus fairy pixie sprite
nymph dryad elf dwarf gnome goblin orc troll ogre giant
""".split()

COMPOUND_SUFFIXES = """
blade arrow spear shield crown king queen lord saint knight mage wizard rogue
ranger hunter sniper ghost demon angel spirit soul heart blood bone steel stone
fang claw wing feather scale horn tail eye gaze storm frost fire ice wind rain
snow cloud mist shadow light dark dawn dusk night day star moon sun sky sea
ocean river lake mountain forest wood field rock iron gold silver flame ember
spark bolt thunder lightning wave tide vortex void abyss peak ridge vale glen
moor fen marsh isle coast shore bay reef cave crypt tomb ruin tower keep fort
gate bridge road path trail way run walker runner rider flyer born child kin
mind song tale lore myth saga
""".split()


def clean_word(raw: str) -> str:
    """Lowercase, transliterate and restrict to a legal ASCII username core."""
    text = raw.strip().lower()
    if not text:
        return ""
    if unidecode is not None:
        text = unidecode(text)
    text = re.sub(r"[^a-z]", "", text)
    if not (3 <= len(text) <= 16):
        return ""
    # Transliterations that dropped every vowel (e.g. Arabic "bdhlk") are
    # not usable handles; require at least one vowel letter.
    if not any(char in "aeiouy" for char in text):
        return ""
    if is_banned(text):
        return ""
    return text


def read_existing(out_dir: Path) -> set[str]:
    """Read the core corpus, ignoring files this script generates."""
    existing: set[str] = set()
    for path in sorted(out_dir.glob("*.txt")):
        if path.name in GENERATED_NAMES or path.name.startswith(GENERATED_PREFIXES):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            word = line.split("\t")[0].strip().lower()
            if word:
                existing.add(word)
    return existing


def fetch(url: str, filename: str, offline: bool) -> str:
    """Fetch a remote dataset, caching it under data/themed_cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / filename
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")
    if offline:
        print(f"  ! {filename}: not cached (offline)")
        return ""
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "mc-og-name-hunter/1.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read().decode("utf-8", errors="ignore")
        cache_path.write_text(data, encoding="utf-8")
        return data
    except Exception as exc:
        print(f"  ! {filename}: {exc}")
        return ""


class Builder:
    def __init__(self, out_dir: Path, existing: set[str]):
        self.out_dir = out_dir
        self.existing = existing
        self.lists: dict[str, set[str]] = {}
        self.points: dict[str, int] = {}
        self.new_count = 0
        self.override_count = 0

    def add(self, filename: str, raw: str, points: int, *, short_top: bool = False) -> bool:
        word = clean_word(raw)
        if not word:
            return False
        if short_top and points >= 60 and len(word) <= 4:
            points = 80
        points = max(0, min(80, points))
        previous = self.points.get(word)
        if previous is None:
            self.override_count += 1
        if previous is None or points > previous:
            self.points[word] = points
        if word in self.existing:
            return False
        bucket = self.lists.setdefault(filename, set())
        if word not in bucket:
            bucket.add(word)
            self.new_count += 1
            return True
        return False

    def write(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for filename, words in sorted(self.lists.items()):
            ordered = sorted(words, key=lambda w: (len(w), w))
            (self.out_dir / filename).write_text(
                "\n".join(ordered) + ("\n" if ordered else ""), encoding="utf-8"
            )
            counts[filename] = len(ordered)

        rare = sorted(
            (w for w, p in self.points.items() if p >= 60 and w not in self.existing),
            key=lambda w: (len(w), w),
        )
        semi = sorted(
            (w for w, p in self.points.items() if p < 60 and w not in self.existing),
            key=lambda w: (len(w), w),
        )
        (self.out_dir / "rare_names.txt").write_text(
            "\n".join(rare) + ("\n" if rare else ""), encoding="utf-8"
        )
        (self.out_dir / "semi_names.txt").write_text(
            "\n".join(semi) + ("\n" if semi else ""), encoding="utf-8"
        )
        counts["rare_names.txt"] = len(rare)
        counts["semi_names.txt"] = len(semi)

        overrides = sorted(self.points.items())
        (self.out_dir / "rarity_overrides.tsv").write_text(
            "".join(f"{word}\t{points}\n" for word, points in overrides),
            encoding="utf-8",
        )
        counts["rarity_overrides.tsv"] = len(overrides)
        return counts


def add_curated(builder: Builder) -> None:
    groups = [
        ("og_geo.txt", 60, True, (US_STATES, CA_PROVINCES, CITIES, LANDMARKS)),
        ("og_nature_animals.txt", 60, True, (ANIMALS,)),
        ("og_nature_birds.txt", 60, True, (BIRDS,)),
        ("og_nature_fish.txt", 60, True, (FISH,)),
        ("og_nature_plants.txt", 60, True, (PLANTS,)),
        ("og_nature_dinosaurs.txt", 60, True, (DINOSAURS,)),
        ("og_mythology.txt", 60, True, (MYTHOLOGY, LATIN)),
        ("og_tech.txt", 60, False, (TECH,)),
        ("og_food.txt", 60, False, (FOOD,)),
        ("og_music.txt", 60, False, (MUSIC,)),
        ("og_sports.txt", 60, False, (SPORTS,)),
        ("og_cosmos.txt", 60, True, (COSMOS, COLORS)),
        ("og_mc_creators.txt", 60, False, (MC_CREATORS,)),
        ("og_mc_meta.txt", 60, True, (MC_META,)),
        ("og_brands.txt", 60, False, (BRANDS, GAMES)),
        ("og_foreign_icons.txt", 60, True, (FOREIGN_ICONS,)),
    ]
    for filename, points, short_top, word_groups in groups:
        before = len(builder.lists.get(filename, ()))
        for group in word_groups:
            for word in group:
                builder.add(filename, word, points, short_top=short_top)
        after = len(builder.lists.get(filename, ()))
        print(f"  {filename}: {after - before} new")


def add_multilingual(builder: Builder) -> None:
    if iter_wordlist is None:
        print("  ! wordfreq unavailable; skipping multilingual lists")
        return
    if unidecode is None:
        print("  ! unidecode unavailable; non-Latin words will be skipped")
    for language, limit, points in MULTILINGUAL:
        valid = scanned = 0
        try:
            for raw in iter_wordlist(language, wordlist="best"):
                scanned += 1
                if valid >= limit or scanned > limit * 8:
                    break
                word = clean_word(raw)
                if not word or len(word) > 12:
                    continue
                builder.add(f"og_multilingual_{language}.txt", word, points, short_top=True)
                valid += 1
        except Exception as exc:
            print(f"  ! {language}: {exc}")
            continue
        print(f"  {language}: {valid} valid (scanned {scanned})")


def add_public_names(builder: Builder, offline: bool) -> None:
    first = fetch(
        "https://raw.githubusercontent.com/dominictarr/random-name/master/first-names.txt",
        "first-names.txt",
        offline,
    )
    if first:
        added = 0
        for line in first.splitlines():
            word = clean_word(line)
            if not word:
                continue
            points = 60 if len(word) <= 8 else 35
            if builder.add("og_names_first.txt", word, points):
                added += 1
        print(f"  og_names_first.txt: {added} new")

    surnames = fetch(
        "https://raw.githubusercontent.com/fivethirtyeight/data/master/"
        "most-common-name/surnames.csv",
        "surnames.csv",
        offline,
    )
    if surnames:
        added = 0
        try:
            reader = csv.DictReader(io.StringIO(surnames.lstrip("\ufeff")))
            fields = reader.fieldnames or []
            name_key = "name" if "name" in fields else fields[0]
            count_key = "count" if "count" in fields else None
            rows = []
            for row in reader:
                name = row.get(name_key, "")
                try:
                    count = int(row.get(count_key, "0")) if count_key else 0
                except (TypeError, ValueError):
                    count = 0
                rows.append((count, name))
            rows.sort(reverse=True)
            for _, name in rows[:15000]:
                word = clean_word(name)
                if not word:
                    continue
                points = 60 if len(word) <= 8 else 35
                if builder.add("og_names_surnames.txt", word, points):
                    added += 1
        except Exception as exc:
            print(f"  ! surnames.csv: {exc}")
        print(f"  og_names_surnames.txt: {added} new")


def add_countries(builder: Builder, offline: bool) -> None:
    payload = fetch(
        "https://raw.githubusercontent.com/mledoze/countries/master/countries.json",
        "countries.json",
        offline,
    )
    if not payload:
        return
    added = 0
    try:
        countries = json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"  ! countries.json: {exc}")
        return
    if isinstance(countries, dict):
        countries = countries.get("data") or []
    if not isinstance(countries, list):
        print("  ! countries.json: unexpected format")
        return
    for item in countries:
        if not isinstance(item, dict):
            continue
        names = []
        common = item.get("name", {}).get("common", "")
        if common:
            names.append(common)
        names.extend(item.get("altSpellings", []) or [])
        names.extend(item.get("capital", []) or [])
        names.extend([item.get("cca2", ""), item.get("cca3", "")])
        for name in names:
            if builder.add("og_geo.txt", name, 60, short_top=True):
                added += 1
    print(f"  og_geo.txt: {added} new from REST Countries")


def add_wordle(builder: Builder, offline: bool) -> None:
    answers = fetch(
        "https://raw.githubusercontent.com/charlesreid1/five-letter-words/master/sgb-words.txt",
        "wordle-answers.txt",
        offline,
    )
    added = 0
    if answers:
        for line in answers.splitlines():
            if builder.add("og_wordle.txt", line, 60):
                added += 1
    guesses = fetch(
        "https://raw.githubusercontent.com/tabatkins/wordle-list/main/words",
        "wordle-allowed.txt",
        offline,
    )
    if guesses and zipf_frequency is not None:
        for line in guesses.splitlines():
            word = clean_word(line)
            if not word or len(word) != 5:
                continue
            try:
                if zipf_frequency(word, "en") < 2.5:
                    continue
            except Exception:
                continue
            if builder.add("og_wordle.txt", word, 60):
                added += 1
    print(f"  og_wordle.txt: {added} new")


def add_compounds(builder: Builder) -> None:
    roots = [w for w in (clean_word(r) for r in COMPOUND_ROOTS) if w]
    suffixes = [w for w in (clean_word(s) for s in COMPOUND_SUFFIXES) if w]
    combos: set[str] = set()
    for root in roots:
        for suffix in suffixes:
            if root == suffix or root[-1] == suffix[0]:
                continue
            word = root + suffix
            if 6 <= len(word) <= 14:
                combos.add(word)
    added = 0
    for word in sorted(combos, key=lambda w: (len(w), w))[:8000]:
        if builder.add("semi_compounds.txt", word, 35):
            added += 1
    print(f"  semi_compounds.txt: {added} new (from {len(combos):,} combos)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not fetch public datasets; use data/themed_cache only.",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    print(f"Reading existing corpus from {out_dir} ...")
    existing = read_existing(out_dir)
    print(f"  {len(existing):,} existing names")

    builder = Builder(out_dir, existing)
    print("Multilingual (wordfreq) ...")
    add_multilingual(builder)
    print("Public names ...")
    add_public_names(builder, args.offline)
    print("Countries / capitals ...")
    add_countries(builder, args.offline)
    print("Wordle ...")
    add_wordle(builder, args.offline)
    print("Curated themes ...")
    add_curated(builder)
    print("Compound names ...")
    add_compounds(builder)

    print("Writing lists ...")
    counts = builder.write()
    print("\nGenerated files:")
    for name, count in sorted(counts.items()):
        print(f"  {name:32} {count:>7,}")
    unique_new = sum(1 for word in builder.points if word not in existing)
    print(f"\nUnique overrides: {builder.override_count:,}")
    print(f"New list entries (across theme files): {builder.new_count:,}")
    print(f"Unique new names outside the core corpus: {unique_new:,}")
    print(f"Output directory: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
