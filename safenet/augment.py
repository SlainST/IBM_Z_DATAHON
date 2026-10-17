"""Synthetic training sentences for two gaps in veri/birlesik_veri.csv, and held-out sentences to check them.

1. Identity bias. In the training split 91 % of the messages that mention "gay" are harmful (88 % for "muslims",
   78 % for "woman"; 22 % overall), so a model learns that the word itself is harmful and flags
   "my teacher is gay". identity_sentences() writes neutral sentences that use these words in ordinary contexts,
   labelled harmless, until each word is at most about half harmful (at most CAP per word).
2. Threats. Only ~480 messages are threats, all found by the keyword rules in kategoriler.py, so phrasings like
   "i'll break your legs" never appear. threat_sentences() writes threats, labelled harmful, category threat.
   benign_frame_sentences() writes as many harmless sentences in the same frames ("after school i'll help you
   with your homework"): without them a trial model learned that "tomorrow" or "after school" means a threat and
   blocked "see you tomorrow". With both, only the harmful verb tells the two apart.

The HELDOUT_* sentences are never trained on and use other templates and words (no "legs" or "face" in the
training threats, no "proud" or "best friend" in the training identity sentences), so train.py measures whether
the models generalize, not whether they memorized the templates. The PDF example is only in HELDOUT_THREATS.
"""
import itertools
import random
import re

import pandas as pd

import temizlik

CAP = 600              # at most this many neutral sentences per identity word
BIASED_ABOVE = 0.55    # only words whose messages are more often harmful than this get sentences
THREATS = 900          # synthetic threats (and as many harmless sentences in the same frames) for 150k rows
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


def build(train: pd.DataFrame, avoid: set[str], text_col: str, harmful_col: str) -> tuple[pd.DataFrame, dict]:
    """All synthetic rows, cleaned like the real data. Sentences equal to a message in `avoid` (test, YouTube)
    are dropped so nothing evaluated is trained on. Threat and frame counts scale with the training size."""
    neutral, counts = identity_sentences(train, text_col, harmful_col)
    n = max(50, round(THREATS * len(train) / FULL_TRAINING))
    rows = ([(temizlik.temizle(s), 0, None, "identity") for s in neutral]
            + [(temizlik.temizle(s), 1, "threat", "threat") for s in threat_sentences(n)]
            + [(temizlik.temizle(s), 0, None, "frame") for s in benign_frame_sentences(n)])
    df = pd.DataFrame(rows, columns=[text_col, harmful_col, "category", "kind"]).drop_duplicates(text_col)
    df = df[~df[text_col].isin(avoid)].reset_index(drop=True)
    sizes = df["kind"].value_counts().to_dict()
    return df.drop(columns="kind"), {"identity_sentences": int(sizes.get("identity", 0)), "per_word": counts,
                                     "threat_sentences": int(sizes.get("threat", 0)),
                                     "benign_frame_sentences": int(sizes.get("frame", 0))}
