"""Synthetic training sentences for gaps in veri/birlesik_veri.csv, and held-out sentences to check them.

1. Identity bias. In the training split 91 % of the messages that mention "gay" are harmful (88 % for "muslims",
   78 % for "woman"; 22 % overall), so a model learns that the word itself is harmful and flags
   "my teacher is gay". identity_sentences() writes neutral sentences that use these words in ordinary contexts,
   labelled harmless, until each word is at most about half harmful (at most CAP per word). v3 adds compound
   identities in everyday and achievement contexts ("the first black woman to lead the lab").
2. Threats. Only ~480 messages are threats, all found by the keyword rules in kategoriler.py, so phrasings like
   "i'll break your legs" never appear. threat_sentences() writes threats, labelled harmful, category threat.
   benign_frame_sentences() writes as many harmless sentences in the same frames ("after school i'll help you
   with your homework"): without them a trial model learned that "tomorrow" or "after school" means a threat and
   blocked "see you tomorrow". With both, only the harmful verb tells the two apart.
3. Profanity and aim (v3). In the data a listed word almost always means harmful, so the model scored "holy shit,
   that was insane" 0.72: yellow on the school profile, while the team's evaluation set expects swearing that
   attacks nobody to be green (censored, word points only). profanity_sentences() writes swearing at things and
   situations, labelled harmless, and as many insults aimed at the reader in the same words, labelled harmful
   (category insult): the aim, not the word, tells them apart.
4. Victims and personal insults (v3). "the boys in my class call me ugly" is a child asking for help, not an
   insult; "why are you so ugly" is one. personal_sentences() writes both, with harmless sentences in the aimed
   frames ("why are you so funny").
5. Innocent words (v3). Letters of a slur inside an ordinary word ("snigger", "scunthorpe"), double meanings
   ("tennis balls", "jerk chicken"), topic words ("our school started an anti bullying club") and game words in
   everyday use: innocent_sentences(), harmless. karistirilabilir_kelimeler.csv's own example sentences are the
   check (measure.py) and are never trained on.

The HELDOUT_* sentences are never trained on and use other templates and words (no "legs" or "face" in the
training threats, no "proud" or "best friend" in the training identity sentences, no "lol" after the insults), so
train.py measures whether the models generalize, not whether they memorized the templates. The PDF example is only
in HELDOUT_THREATS. build() also drops every sentence of the team's evaluation set (degerlendirme_seti.csv), the
test split and YouTube, and the templates avoid that set's frames: it stays a fair check.
"""
import itertools
import random
import re

import pandas as pd

import temizlik

CAP = 600              # at most this many neutral sentences per identity word
BIASED_ABOVE = 0.55    # only words whose messages are more often harmful than this get sentences
THREATS = 900          # synthetic threats (and as many harmless sentences in the same frames) for 150k rows
COMPOUNDS = 1200       # compound identities in context (v3)
PROFANITY = 900        # swearing at things (and as many aimed insults with the same words) (v3)
PERSONAL = 600         # victims' accounts, aimed personal insults and their harmless frames, each (v3)
INNOCENT = 480         # innocent words in everyday sentences (v3)
FULL_TRAINING = 150_000

# --- Identity words, by how they are used in a sentence ------------------------------------------------
ADJECTIVES = ["gay", "muslim", "christian", "black", "white", "trans", "transgender", "queer", "lesbian", "hindu",
              "female", "feminist"]
NOUNS = ["woman", "girl", "muslim", "christian", "hindu", "feminist", "lesbian"]
PLURALS = ["muslims", "christians", "women", "girls", "feminists", "lesbians", "mexicans", "asians"]
PROPER = ["islam"]

_REL = ["cousin", "teacher", "coach", "classmate", "boss", "doctor", "roommate", "brother", "sister", "dentist",
        "manager", "lab partner", "landlord", "uncle", "aunt", "professor"]
_PERSON = ["guy", "student", "artist", "writer", "engineer", "nurse", "musician", "chef", "pilot", "volunteer"]
_PLACE = ["library", "park", "concert", "conference", "gym", "cafe", "museum", "airport", "bookstore", "market",
          "train station", "science fair"]
_GROUP = ["club", "team", "choir", "class", "company", "book club", "chess club", "study group"]
_JOB = ["nurse", "teacher", "programmer", "lawyer", "baker", "firefighter", "designer", "scientist", "mechanic"]
_NAME = ["sam", "alex", "maria", "omar", "lena", "david", "aisha", "tom", "priya", "lucas", "emma", "yusuf"]
_TIME = ["last week", "yesterday", "this morning", "last summer", "on monday", "after lunch"]
_HOBBY = ["painting", "hiking", "cooking", "football", "chess", "reading", "running", "baking"]
_TOPIC = ["music", "football", "the weather", "our homework", "a new movie", "travel", "science"]

_ADJ_TEMPLATES = [
    "my {rel} is {w} and really funny",
    "i met a {w} {person} at the {place} {time}",
    "our {group} has a few {w} members",
    "{name} is {w} and works as a {job}",
    "my {rel} is {w} and helps everyone at work",
    "a {w} {person} gave a great talk at the {place}",
    "{name} told me she is {w} and we kept talking about {topic}",
    "there is a {w} {person} in my {group} who loves {hobby}",
    "my {rel} who is {w} invited us for dinner {time}",
    "the {w} {person} next door helped me carry boxes {time}",
]
_NOUN_TEMPLATES = [
    "my {rel} is a {w} who loves {hobby}",
    "i talked with a {w} about {topic} at the {place}",
    "as a {w}, {name} enjoys {hobby} on weekends",
    "a {w} from my {group} won the prize {time}",
    "{name} is a {w} and a great {job}",
    "a {w} sat next to me at the {place} and we talked about {topic}",
]
_PLURAL_TEMPLATES = [
    "many {w} came to the {place} {time}",
    "there are {w} in my {group} and we get along well",
    "{w} and their families celebrated together at the {place}",
    "our {group} welcomes {w} and everyone else",
    "i learned a lot about {topic} from {w} at the {place}",
    "{w} in our town organized a charity run {time}",
]
_PROPER_TEMPLATES = [
    "{w} is one of the major world religions",
    "{name} wrote a school report about the history of {w}",
    "we visited an exhibition about art and {w} at the {place} {time}",
    "my {rel} teaches a course on {w} and philosophy",
]

# --- Threats ------------------------------------------------------------------------------------------
_HURT = ["break", "snap", "crack", "twist", "bust", "smash up"]
_PART = ["arms", "neck", "nose", "jaw", "ribs", "fingers", "teeth", "wrist", "skull", "knees", "back"]   # no legs, no face
_ACT = ["hurt", "stab", "shoot", "strangle", "punch", "hit", "kill", "choke", "drown", "beat up", "end", "jump"]
_INTRO = ["", "if you come back ", "if you tell anyone ", "after school ", "tomorrow ", "one more word and ",
          "if i see you again ", "if you do that again ", "next time ", "listen to me, "]
_AFTER = ["", " after school", " tomorrow", " tonight", " when you least expect it", " i promise", " this weekend",
          " and nobody will help you"]
_FAMILY = ["family", "little brother", "mom", "dog", "friends"]
_THREAT_TEMPLATES = [
    "{intro}i'll {hurt} your {part}{after}",
    "{intro}i'm going to {hurt} your {part}{after}",
    "{intro}i will {act} you{after}",
    "{intro}i'm gonna {act} you{after}",
    "{intro}i'm going to {act} you{after}",
    "{intro}you better watch your back{after}",
    "{intro}i know where you live and i'll {act} you{after}",
    "{intro}i'll find you and {act} you{after}",
    "{intro}i'm going to hurt your {family}{after}",
    "{intro}you won't make it home{after}",
    "{intro}i'll make you pay for this{after}",
    "{intro}i'm coming for you{after}",
    "{intro}i swear i'll hunt you down{after}",
    "{intro}say that again and i'll {hurt} your {part}",
]
# The same frames, harmless (no "find you", "watch", "high score" or "break a leg": those are held out)
_KIND = ["help you with your homework", "call you", "bring you some cookies", "pick you up", "text you",
         "lend you my charger", "show you the new game", "carry your bag", "save you a seat", "send you the notes",
         "teach you the song", "meet you at the park", "wait for you at the gate", "cheer for you at the game",
         "buy you a coffee"]
_YOUR = ["fix your bike", "check your essay", "read your story", "clean your desk", "water your plants",
         "feed your cat", "return your book", "charge your phone", "sign your birthday card", "fill your water bottle"]
_OTHER = ["beat my record", "beat this level", "beat the boss in this game", "take a break", "break the news to her",
          "finish the project", "bake a cake", "learn the song", "clean my room", "see the match"]
_BENIGN_TEMPLATES = [
    "{intro}i'll {kind}{after}",
    "{intro}i'm going to {kind}{after}",
    "{intro}i will {your}{after}",
    "{intro}i'm gonna {other}{after}",
    "{intro}i'm going to {other}{after}",
    "{intro}you better bring a jacket{after}",
    "{intro}i'm coming to your party{after}",
    "{intro}i'll {your} for you{after}",
]

# --- Compound identities in context (v3; no "first ... to win": that frame is in the evaluation set) ---------
_COMPOUND = ["black woman", "black man", "black girl", "black student", "white woman", "asian man", "asian woman",
             "muslim woman", "muslim girl", "muslim family", "jewish family", "jewish student", "gay couple",
             "lesbian couple", "trans woman", "trans man", "mexican family", "arab student", "hindu family",
             "christian girl", "immigrant family", "latina woman", "gay teacher", "black family"]
_DOES = ["leads the science lab", "opened a bakery on our street", "coaches our basketball team",
         "teaches piano at the music school", "runs the community garden", "fixed my bike for free",
         "organized the charity run", "designed the new library", "started a reading club for kids",
         "works night shifts at the hospital"]
_COMPOUND_TEMPLATES = [
    "a {c} {does}",
    "the {c} who {does} is my {rel}",
    "{name} is a {c} who {does}",
    "we watched a documentary about a {c} who {does}",
    "the {c} next door brought us soup when i was sick",
    "a {c} helped me find my lost dog {time}",
    "i interviewed a {c} for the school newspaper {time}",
    "the {c} at the {place} recommended a great book",
]

# --- Profanity and aim (v3; no "missed the bus", "bus is late" or "pain in the ass": those are evaluated) ----
_EXCLAIM = ["holy shit", "oh shit", "holy crap", "oh crap", "damn", "oh damn", "fuck yeah", "hell yeah", "holy fuck"]
_GOOD = ["that concert was unreal", "this view is incredible", "we actually won the game", "the cake turned out perfect",
         "my exam went great", "the fireworks were beautiful", "this song is a masterpiece", "that trick was clean",
         "the new level looks amazing"]
_THING = ["this pizza", "the new album", "this hike", "the sunset tonight", "that roller coaster", "this soup",
          "the final episode", "her painting", "the new phone", "this beach"]
_INTENS = ["fucking", "so fucking", "damn", "so damn", "fuckin"]
_NICE = ["good", "amazing", "beautiful", "delicious", "awesome", "hard", "fun", "huge", "cold", "loud"]
_MISHAP = ["i forgot my charger at home", "i dropped my phone in the sink", "i spilled coffee on my shirt",
           "i locked myself out again", "my laptop just froze", "i burned the toast", "i slept through my alarm",
           "the printer jammed again", "i left my umbrella at school", "the battery died"]
_ANNOY = ["the wifi", "this printer", "the traffic", "the weather", "my old laptop", "this queue", "the train schedule",
          "the heating"]
_BAD = ["is shit today", "is crap", "is so fucking slow", "is a damn mess", "is bullshit"]
_PROFANE_HARMLESS = ["{exclaim}, {good}", "{thing} is {intens} {nice}", "{exclaim}, {mishap}", "ugh, {annoy} {bad}",
                     "{annoy} {bad} again", "{exclaim} {thing} is {intens} {nice}"]
_INSULT = ["idiot", "loser", "joke", "clown", "moron", "creep", "failure", "bitch", "asshole", "dumbass"]
_AIMED_PROFANE = ["stop texting me you {intens} {insult}", "{name}, you {intens} {insult}, leave me alone",
                  "what a {intens} {insult} you are", "get lost you {intens} {insult}", "screw you {name}, you {insult}",
                  "fuck off {name}, you {insult}", "go to hell {name}, you {insult}", "{exclaim}, you are a {insult}"]

# --- Victims and personal insults (v3; no "keep calling me", no "lol" after an insult: evaluated) -------------
_WHO = ["the boys in my class", "a girl on my team", "people on the bus", "the older kids", "my classmates",
        "two guys from my school", "someone in the group chat", "the kids next door"]
_CALLED = ["ugly", "fat", "stupid", "a loser", "a freak", "weird", "a nerd", "useless"]
_FEEL = ["and i cried", "and i don't want to go back", "and i feel awful", "and nobody helped me",
         "and i didn't know what to say", "and it really hurt", "every single day", "again today"]
_VICTIM_TEMPLATES = ["{who} call me {called} {feel}", "{who} called me {called} {feel}",
                     "{who} laughed at me and called me {called}", "i got called {called} by {who} {feel}",
                     "{who} told everyone i'm {called} {feel}", "should i tell my teacher that {who} call me {called}?"]
_LOOKS = ["ugly", "fat", "disgusting", "gross", "annoying", "pathetic", "weird", "dumb", "stupid", "useless", "lazy",
          "smelly", "creepy", "boring"]
_KINDLY = ["funny", "kind", "smart", "brave", "helpful", "talented", "cheerful", "patient", "generous", "creative",
           "strong", "honest", "sweet", "clever"]
_PIC = ["photo", "video", "dress", "jacket", "picture"]
_PART2 = ["face", "voice", "laugh", "hair", "drawing"]
# --- Innocent words (v3): double meanings, listed words hidden inside words, topic words and game words in
# everyday use. The model scored "The kids began to snigger at the joke." 0.89 and "Racism has no place in
# sports." 0.76. Other sentences than karistirilabilir_kelimeler.csv's, which measure.py uses as the check.
_INNOCENT = [
    "my assistant moved the meeting to friday", "the embassy closed early for the holiday",
    "i love the bass line in this song", "we cut the grass before the rain", "she spoke with real passion about science",
    "the bartender made a fruit cocktail", "a peacock walked across the path at the zoo",
    "the therapist gave my mom good advice", "we picked grapes at the farm", "i got a scrape on my knee",
    "the analysis took all week", "we rode a boat along the canal", "add cucumber to the salad",
    "please sign the document by noon", "under the circumstances we stayed home", "the title of my essay is too long",
    "we signed a petition for a new park", "your attitude in class has improved a lot", "press the red button to start",
    "practice is the only way to build a skill", "we stopped in sussex on our road trip",
    "my aunt lives in essex near the coast", "arsenal scored in the last minute",
    "we are reading great expectations by dickens", "the girls started to snigger during the movie",
    "his niggardly tip annoyed the waiter", "this sauce is too spicy for me", "a raccoon got into our bins last night",
    "the butterfly came out of its cocoon", "we flew to japan to see the cherry blossoms",
    "we sold the old car for scrap", "i lost my left shoe at the beach", "the mixture became homogeneous after stirring",
    "the curtains are made of fire retardant fabric", "the assassin in the novel was never caught",
    "i assume the train leaves at eight", "our math class was cancelled today", "scunthorpe has a small football club",
    "the cock crowed at dawn on my grandpa's farm", "use the hoe to loosen the soil",
    "hell no, i'm not jumping into that cold lake", "the dog chased three tennis balls across the yard",
    "a beaver built a dam on the river", "a blue tit came to our bird feeder", "turn the door knob slowly",
    "he gave the rope a quick jerk", "the food truck sells spicy jerk chicken", "the new vacuum sucks up pet hair easily",
    "the pig rolled in the mud", "the cow had a calf this morning", "a monkey stole a banana from a tourist",
    "take out the trash before dinner", "screw the shelf to the wall", "the nuts and bolts are in the red box",
    "our school started an anti bullying club", "the counselor talked to us about bullying",
    "i was bullied last year but now i have good friends", "we wrote essays about racism in history class",
    "the museum has an exhibition on racism and civil rights", "sexism at work is the topic of my presentation",
    "religion class starts after lunch", "teens need more sleep than adults", "the kid next door learned to ride a bike",
    "report bullying to a teacher you trust", "that joke killed me haha", "i almost died laughing at your story",
    "you killed it on stage tonight", "my phone is dead, i'll text you later", "the photographer will shoot our wedding",
    "the striker shot the ball into the top corner", "this cake is the bomb", "she's a beast at volleyball",
    "my sister destroyed me at chess again", "we beat the traffic this morning", "that comeback was savage haha",
    "the heat is killing my tomato plants", "my brother is a black belt in karate", "the white board needs cleaning",
]
_AROUND = [("", ""), ("", ""), ("btw ", ""), ("so ", ""), ("honestly ", ""), ("", " today"), ("", " again"), ("", "!")]
_AIMED_TEMPLATES = ["why are you so {w}", "you look so {w} in that {pic}", "everything about you is {w}",
                    "honestly you are the most {w} person i know", "your {part2} is so {w}", "{name} you are so {w}",
                    "stop being so {w}, {name}", "god you are {w}", "you are honestly so {w} it hurts",
                    "look at you, so {w}"]

# --- Held out: never trained on --------------------------------------------------------------------------
HELDOUT_THREATS = [
    "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs.",   # PDF section 3
    "i swear i will smash your face in",
    "you are going to regret coming to school tomorrow",
    "i know your address and i am coming over tonight",
    "one more message like that and you are dead meat",
    "keep talking and see what happens to you",
    "i'll make sure you never walk again",
    "i'm gonna beat the crap out of you after class",
]
HELDOUT_BENIGN = [
    "break a leg at your show tonight!",
    "we will destroy them in the next match",
    "that movie killed me lol",
    "i'm going to beat your high score",
    "my legs are killing me after the run",
    "i will find you at the library after class",
    "watch your step, the floor is wet",
]
# v3: harmless (swearing at things, victims, identities in context) and harmful (aimed insults)
HELDOUT_HARMLESS = [
    "damn, this traffic is unreal",
    "what a fucking beautiful sunset",
    "oh crap, the meeting already started",
    "shit, my headphones just broke",
    "the kids on the bus make fun of my shoes and i hate going to school",
    "a girl in my class said i was ugly and i can't stop thinking about it",
    "my gay uncle makes the best pasta in the family",
    "a black scientist from our city got a big grant",
    "two jewish students started a chess club",
]
HELDOUT_AIMED = [
    "fuck off and leave me alone",
    "you are a pathetic little loser",
    "shut up you clown",
    "you look disgusting today",
    "nobody wants your stupid opinion",
]
IDENTITIES_EVAL = ["muslim", "jew", "christian", "atheist", "gay", "lesbian", "trans", "black", "white", "asian",
                   "mexican", "arab", "woman", "girl", "immigrant"]
NEUTRAL_EVAL = ["i am a proud {}", "my best friend is {}", "my neighbor is a {} person", "i am {} and i love my family"]
HATEFUL_EVAL = ["all {}s are disgusting", "i hate {} people", "{} people should die"]


def _fill(templates, word, rng):
    slots = {"rel": _REL, "person": _PERSON, "place": _PLACE, "group": _GROUP, "job": _JOB, "name": _NAME,
             "time": _TIME, "hobby": _HOBBY, "topic": _TOPIC}
    out = set()
    for t in templates:
        keys = [k for k in slots if "{" + k + "}" in t]
        combos = list(itertools.product(*(slots[k] for k in keys)))
        rng.shuffle(combos)
        for combo in combos[:400]:
            out.add(t.format(w=word, **dict(zip(keys, combo))))
    return sorted(out)


def _has_profanity(sentence: str) -> bool:
    return any(w in temizlik.ASIL for w in re.findall(r"[a-z]+", sentence))


def identity_sentences(train: pd.DataFrame, text_col: str, harmful_col: str, seed: int = 42) -> tuple[list[str], dict]:
    """Neutral sentences for every identity word that is mostly harmful in train. Returns (sentences, count per word)."""
    rng = random.Random(seed)
    sentences, counts = [], {}
    for word in sorted(set(ADJECTIVES + NOUNS + PLURALS + PROPER)):
        mask = train[text_col].str.contains(rf"\b{word}\b", regex=True)
        n, harmful = int(mask.sum()), int(train.loc[mask, harmful_col].sum())
        if not n or harmful / n <= BIASED_ABOVE:
            continue
        pool = []
        if word in ADJECTIVES:
            pool += _fill(_ADJ_TEMPLATES, word, rng)
        if word in NOUNS:
            pool += _fill(_NOUN_TEMPLATES, word, rng)
        if word in PLURALS:
            pool += _fill(_PLURAL_TEMPLATES, word, rng)
        if word in PROPER:
            pool += _fill(_PROPER_TEMPLATES, word, rng)
        pool = [s for s in pool if not _has_profanity(s)]
        rng.shuffle(pool)
        take = min(harmful - (n - harmful), CAP, len(pool))
        sentences += pool[:take]
        counts[word] = take
    return sentences, counts


def _frames(templates, n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    pool = set()
    for t in templates:
        for intro, after in itertools.product(_INTRO, _AFTER):
            for _ in range(6):
                pool.add(t.format(intro=intro, after=after, hurt=rng.choice(_HURT), part=rng.choice(_PART),
                                  act=rng.choice(_ACT), family=rng.choice(_FAMILY), kind=rng.choice(_KIND),
                                  your=rng.choice(_YOUR), other=rng.choice(_OTHER)))
    pool = sorted(pool)
    rng.shuffle(pool)
    return pool[:n]


def threat_sentences(n: int = THREATS, seed: int = 42) -> list[str]:
    return _frames(_THREAT_TEMPLATES, n, seed)


def benign_frame_sentences(n: int = THREATS, seed: int = 43) -> list[str]:
    return [s for s in _frames(_BENIGN_TEMPLATES, n, seed) if not _has_profanity(s)]


_SLOTS = {"rel": _REL, "person": _PERSON, "place": _PLACE, "group": _GROUP, "job": _JOB, "name": _NAME,
          "time": _TIME, "hobby": _HOBBY, "topic": _TOPIC, "c": _COMPOUND, "does": _DOES, "exclaim": _EXCLAIM,
          "good": _GOOD, "thing": _THING, "intens": _INTENS, "nice": _NICE, "mishap": _MISHAP, "annoy": _ANNOY,
          "bad": _BAD, "insult": _INSULT, "who": _WHO, "called": _CALLED, "feel": _FEEL, "pic": _PIC, "part2": _PART2}


def _sample(templates, n: int, seed: int, extra: dict | None = None) -> list[str]:
    """Up to n distinct sentences, taken from the templates in turn, slots filled at random."""
    rng = random.Random(seed)
    slots = {**_SLOTS, **(extra or {})}
    pools = []
    for t in templates:
        keys = sorted(set(re.findall(r"{(\w+)}", t)))
        combos = list(itertools.product(*(slots[k] for k in keys)))
        rng.shuffle(combos)
        pools.append([t.format(**dict(zip(keys, c))) for c in combos[:n]])
    out, seen = [], set()
    for row in itertools.zip_longest(*pools):
        for s in row:
            if s is not None and s not in seen:
                seen.add(s)
                out.append(s)
    return out[:n]


def compound_sentences(n: int = COMPOUNDS, seed: int = 44) -> list[str]:
    return [s for s in _sample(_COMPOUND_TEMPLATES, n, seed) if not _has_profanity(s)]


def profanity_sentences(n: int = PROFANITY, seed: int = 45) -> tuple[list[str], list[str]]:
    """(swearing at things: harmless, the same words aimed at the reader: harmful)."""
    return _sample(_PROFANE_HARMLESS, n, seed), _sample(_AIMED_PROFANE, n, seed + 1)


def innocent_sentences(n: int = INNOCENT, seed: int = 50) -> list[str]:
    """Every innocent sentence, with a few harmless words around it, as evenly as n allows."""
    rng = random.Random(seed)
    pools = []
    for s in _INNOCENT:
        around = list(_AROUND)
        rng.shuffle(around)
        pools.append(list(dict.fromkeys(f"{before}{s}{after}" for before, after in around)))
    out = [s for row in itertools.zip_longest(*pools) for s in row if s is not None]
    return out[:n]


def personal_sentences(n: int = PERSONAL, seed: int = 47) -> tuple[list[str], list[str], list[str]]:
    """(victims' accounts: harmless, personal insults aimed at the reader: harmful, the same frames kind: harmless)."""
    kind = [s for s in _sample(_AIMED_TEMPLATES, n, seed + 2, {"w": _KINDLY}) if not _has_profanity(s)]
    return _sample(_VICTIM_TEMPLATES, n, seed), _sample(_AIMED_TEMPLATES, n, seed + 1, {"w": _LOOKS}), kind


def build(train: pd.DataFrame, avoid: set[str], text_col: str, harmful_col: str) -> tuple[pd.DataFrame, dict]:
    """All synthetic rows, cleaned like the real data. Sentences equal to a message in `avoid` (test, YouTube,
    the evaluation set) are dropped so nothing evaluated is trained on. Counts scale with the training size."""
    neutral, counts = identity_sentences(train, text_col, harmful_col)
    k = lambda base: max(50, round(base * len(train) / FULL_TRAINING))  # noqa: E731
    profane, profane_aimed = profanity_sentences(k(PROFANITY))
    victims, aimed, kind_frames = personal_sentences(k(PERSONAL))
    rows = ([(s, 0, None, "identity") for s in neutral]
            + [(s, 1, "threat", "threat") for s in threat_sentences(k(THREATS))]
            + [(s, 0, None, "threat_frame") for s in benign_frame_sentences(k(THREATS))]
            + [(s, 0, None, "compound_identity") for s in compound_sentences(k(COMPOUNDS))]
            + [(s, 0, None, "profanity_at_things") for s in profane]
            + [(s, 1, "insult", "profanity_aimed") for s in profane_aimed]
            + [(s, 0, None, "victim") for s in victims]
            + [(s, 1, "insult", "personal_insult") for s in aimed]
            + [(s, 0, None, "personal_kind") for s in kind_frames]
            + [(s, 0, None, "innocent_words") for s in innocent_sentences(k(INNOCENT))])
    df = pd.DataFrame([(temizlik.temizle(s), y, c, family) for s, y, c, family in rows],
                      columns=[text_col, harmful_col, "category", "kind"]).drop_duplicates(text_col)
    df = df[~df[text_col].isin(avoid)].reset_index(drop=True)
    return df.drop(columns="kind"), {"per_kind": {k: int(v) for k, v in df["kind"].value_counts().items()},
                                     "harmful": int(df[harmful_col].sum()), "per_identity_word": counts}
