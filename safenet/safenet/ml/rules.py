"""Precise phrase rules on top of the two models, and the insult cap.

Model 1 gives the probability that a sentence is harmful, learned from ~150k public comments. Three things it
cannot do well on its own:

1. Rare kinds of harm. The data has ~480 threats and almost no sexual requests to a child, blackmail or
   "everyone would be happier if you disappeared", so phrasings it never saw score low. A sentence matching
   one of the rules below gets at least that rule's floor and its category, whatever the models say.
2. Severity. A probability is not a severity: "you are an idiot" is harmful almost surely (0.99), but it is an
   insult, and the team's evaluation set (degerlendirme_seti.csv) expects insults to be yellow (0.60-0.75),
   not blocked as "very harmful". A sentence Model 2 calls an insult, that matches no rule and attacks no
   identity, gets at most INSULT_CAP: yellow on every profile, never red by itself.
3. Identity words and words that name a harm. In the data 91 % of the messages with "gay" are harmful, so the
   model still scores "i'm gay i love men" 0.68 and "she's the first black woman to win that award" 0.93; it
   blocked "Racism has no place in sports." When a sentence only mentions an identity (no slur, no "you muslim",
   no claim about the whole group, no hostile word, no rule, no listed word), or names a harm without being
   addressed to the reader ("racism", "bullying": "i was bullied at school"; "some kids keep calling me fat and
   ugly"), it is scored once more without those words and keeps the lower score: the mere mention of an identity
   adds nothing (ayarlar.toml), talking about bullying is not bullying, and an attack keeps its score.

Every pattern was checked on veri/birlesik_veri.csv: precision on the training split (share of matched messages
that are labelled harmful) and how often it fires on harmless messages (models/README.md, "Rules"). Patterns
that also matched ordinary sentences ("i'll shoot you an email", "go back to your room", "send me a pic of
you in paris") were narrowed or left out. They run on temizlik.temizle() output: lower case, disguises decoded
("kys" -> "kill yourself", "f*ck" -> "fuck").
"""
import re
from dataclasses import dataclass
from functools import lru_cache

import kimlik

THREAT_FLOOR = 0.95    # explicit threats, self-harm encouragement, blackmail: red on every profile (tehdit_esigi <= 0.70)
SEVERE_FLOOR = 0.92    # severe bullying, sexual requests, xenophobia: red on every profile (cok_kotu_esigi <= 0.90)
INSULT_CAP = 0.72      # plain insults: yellow everywhere (sari_esigi <= 0.60), below every cok_kotu_esigi (>= 0.75)


@dataclass(frozen=True, slots=True)
class Rule:
    kind: str          # threat | self_harm | blackmail | bullying | sexual | xenophobia | dehumanizing
    category: str      # the API category it gives the sentence
    floor: float
    pattern: re.Pattern


@dataclass(frozen=True, slots=True)
class Match:
    rule: Rule
    phrase: str        # the words that matched, first in key_words


_YOU = r"(you|u|ya|yourself|urself|ur family|your family|your mom|your kids)"
# "i'll", "i'm going to"... and up to two more words, none of them a negation ("i will never hurt you")
_FIRST = (r"(i'?ll|i will|i'?m going to|im going to|i am going to|i'?m gonna|im gonna)\s+"
          r"((?!not\b|never\b|no\b)\w+\s+){0,2}")
_OR_ELSE = r"\bor\s+(else\s+)?(i'?ll|i will|i'?m gonna|im gonna|i'?m going to|im going to)\s+"

THREAT = [
    _FIRST + r"(kill|murder|stab|strangle|choke|hurt|beat up|punch|rape|burn|drown|end)\s+" + _YOU + r"\b",
    _FIRST + r"(beat|punch|kick|slap)\s+(the )?(crap|shit|hell|fuck|living daylights)\s+out of\s+" + _YOU + r"\b",
    _FIRST + r"(break|snap|smash|crack|bust)\s+(your|ur|ya)\s+"
             r"(legs?|arms?|neck|face|teeth|nose|jaw|skull|bones|ribs|fingers|knees?)\b",
    _FIRST + r"(find|catch|get)\s+(you|u|ya)\s+(and\s+|then\s+)?(\w+\s+)?(kill|murder|stab|hurt|beat|punch|shoot)\b",
    _FIRST + r"(hunt|track)\s+(you|u|ya)\s+down\s+(and\s+|then\s+)?(\w+\s+)?"
             r"(kill|murder|stab|hurt|beat|punch|shoot|rape)\b",
    _FIRST + r"(beat|smack|mess|rough|fuck)\s+(you|u|ya)\s+up\b",
    r"\b(hope|wish)\s+(you|u)\s+(\w+\s+){0,2}(die|dies|get raped|get killed|get cancer|burn|rot|suffer)\b",
    r"\b(you|u)('re| are| r)?\s*(gonna|going to|will)\s+(get|be)\s+(raped|killed|shot|stabbed|beaten|murdered|hurt)\b",
    r"\b(you'?re|you are|ur|u r)\s+(so\s+)?dead\b(?!\s+(wrong|on|right|serious|set|tired|last|center|inside|to me))",
    r"\b(go die|die in a fire|watch your back|i know where you live|dead meat)\b",
    r"\bdrop dead\b(?!\s+(gorgeous|beautiful|date|deadline|funny|sexy|hot|serious|simple|easy|good|perfect|fast))",
    # implicit: no violent verb, but something is going to happen to the reader (7 of the 10 training messages they
    # match are labelled harmful, 2 of the other 3 are threats too; "regret" and "see what happens" are not in the data)
    _FIRST + r"make\s+(your|ur)\s+life\s+(a\s+)?(living\s+)?(hell|nightmare|misery|miserable)\b",
    r"\b(you'?ll|you will|you'?re (gonna|going to)|you are (gonna|going to)|ur (gonna|going to))\s+(\w+\s+)?regret\s+"
    r"(coming|saying|messing|talking|crossing|ever|the day|being born|what you)\b",
    r"\b(keep (talking|it up)|say (that|it) again|try me)\b[^.!?]{0,20}\b(and|then)\s+(see|watch)\s+what\s+happens\b",
    r"\b(your|ur)\s+days\s+are\s+numbered\b|\bsleep with one eye open\b|"
    r"\bi\s+know\s+where\s+(you|u)\s+(go to school|work|sleep|study)\b",
]
SELF_HARM = [
    r"\b(kys|kill (your|ur) ?self|kill urself|hang (your|ur) ?self|end (your|ur) life|slit (your|ur) wrists?)\b",
    # the words children use to get past filters: "unalive yourself", "neck yourself", "go drink bleach"
    r"\b(unalive|neck) (your|ur) ?self\b|\b(unalive|neck) urself\b",
    r"\b(go|just|pls|please|you should|u should)\s+(drink|chug)\s+(some\s+)?bleach\b",
    r"\b(you|u)\s+(should|need to|deserve to|ought to)\s+(just\s+)?(die|be dead)\b",
]
BLACKMAIL = [
    _OR_ELSE + r"(\w+\s+)?(post|leak|share|spread|send|show)\s+(\w+\s+){0,2}"
               r"(pics?|photos?|pictures?|nudes|videos?|vids?|secrets?|messages|texts|chats?|dms|screenshots?)\b",
    _OR_ELSE + r"tell\s+(everyone|everybody|the (whole )?(school|class))\b",
]
BULLYING = [
    r"\b(no ?one|nobody)\s+(even\s+)?(likes|loves|wants|cares about|would miss|will miss|misses|needs)\s+(you|u)\b",
    r"\b(every ?one|everybody)\s+(here\s+|at school\s+)?(hates|despises)\s+(you|u)\b",
    r"\b(you'?re|you are|ur|u r|u are)\s+(so\s+|completely\s+|totally\s+|just\s+)?"
    r"(worthless|a waste of (space|air|oxygen|skin)|unlovable)\b",
    r"\b(every ?one|everybody|the world|we|we all|they|people|this (school|class|team|group))\s+(would|will)\s+be\s+"
    r"(so\s+much\s+)?(happier|better off)\s+(if\s+(you|u)\s+(just\s+)?(left|disappeared|died|were gone|were dead|"
    r"never came back|weren'?t here)|without\s+(you|u))\b",
    r"\bif\s+(you|u)\s+(just\s+)?(disappeared|were dead|never existed|were never born|weren'?t born)\b",
    r"\b(you|u)\s+(should|need to|deserve to)\s+(just\s+)?(disappear|not exist|stop existing|never have been born)\b",
]
_CLOTHES = r"(underwear|bra|panties|bikini|boxers|undies|lingerie)"
SEXUAL = [
    r"\bsend\s+(me\s+)?(some\s+|a few\s+|more\s+|your\s+|ur\s+)?"
    r"(nudes|noods|nude (pics?|photos?)|naked (pics?|photos?)|dirty (pics?|photos?)|sexy (pics?|photos?|selfies?))\b",
    r"\b(send|show)\s+(me\s+)?(a\s+|some\s+)?(pics?|pictures?|photos?|selfies?|videos?|vids?)\s+of\s+"
    r"(you|u|yourself|urself|your body|ur body)\s+(in\s+(your|ur|a)\s+" + _CLOTHES + r"|without\s+(clothes|your clothes|"
    r"ur clothes|a shirt|anything on)|naked|nude|topless)\b",
    r"\b(show|send)\s+(me\s+)?(your|ur)\s+(boobs|tits|titties|breasts|nipples|dick|cock|penis|pussy|privates|"
    r"private parts|naked body)\b",
    r"\b(take\s+off|remove)\s+(your|ur)\s+(clothes|shirt|top|bra|pants|underwear|panties)\s+(for me|on cam|on camera|"
    r"and send)\b",
]
_ELSEWHERE = (r"(your|ur) (own )?(country|homeland|home country|land)|where (you|u) (came|come) from|africa|asia|"
              r"china|mexico|india|pakistan|syria|iraq|iran|afghanistan|somalia|nigeria|the middle east|the desert")
XENOPHOBIA = [
    r"(^|[,.!?;:]\s*|\b(you|u|they|them)\s+(should|need to|must|better)\s+|\bjust\s+)go\s+back\s+to\s+"
    r"(" + _ELSEWHERE + r")\b",
]
_LOWER = (r"criminals|rapists|terrorists|animals|vermin|parasites|savages|thieves|subhuman|inferior|scum|filth|"
          r"a disease|a plague|cockroaches|rats|trash")
_REMOVE = (r"be deported|be sent back|go back|get out|leave (our|this) country|be banned|be killed|die|be shot|"
           r"be gassed|be exterminated")


@lru_cache(maxsize=1)
def rules() -> tuple[Rule, ...]:
    """In priority order: the first rule that matches a sentence decides its category."""
    out = []

    def add(kind, category, floor, patterns):
        out.extend(Rule(kind, category, floor, re.compile(p)) for p in patterns)

    add("threat", "threat", THREAT_FLOOR, THREAT)
    add("self_harm", "threat", THREAT_FLOOR, SELF_HARM)
    add("blackmail", "threat", THREAT_FLOOR, BLACKMAIL)
    add("xenophobia", "race", SEVERE_FLOOR, XENOPHOBIA)
    for group, category in (("irk", "race"), ("din", "religion"), ("cinsiyet", "gender")):
        words = kimlik.GRUPLAR[group]
        add("dehumanizing", category, SEVERE_FLOOR, [
            rf"\b(all\s+)?(?:{words})\s+(are|r)\s+(all\s+)?(just\s+)?({_LOWER})\b",
            rf"\b(?:{words})\s+(should|must|need to)\s+(all\s+)?({_REMOVE})\b"])
    add("sexual", "sexual", SEVERE_FLOOR, SEXUAL)
    add("bullying", "insult", SEVERE_FLOOR, BULLYING)
    return tuple(out)


# "not all muslims are terrorists", "they never said women are inferior": a claim about a group right after a
# negation is not the claim.
_NEGATED = re.compile(r"\b(not|never|no|isn'?t|aren'?t|don'?t|doesn'?t)\s+(\w+\s+)?$")
_NEGATABLE = ("xenophobia", "dehumanizing")


def find(clean: str) -> Match | None:
    """The first rule matching the sentence (temizlik.temizle() output), or None."""
    for rule in rules():
        for m in rule.pattern.finditer(clean):
            if rule.kind in _NEGATABLE and _NEGATED.search(clean[:m.start()]):
                continue
            return Match(rule, m.group(0).strip(" ,.!?;:"))
    return None


def explicit_threat(clean: str) -> bool:
    """A threat, self-harm encouragement or blackmail: a threat with harm at least THREAT_FLOOR."""
    found = find(clean)
    return found is not None and found.rule.category == "threat"


def identity_attack(identity: dict) -> bool:
    """kimlik.kimlik_analizi() found an identity attacked: aimed at the reader, generalized, or a slur."""
    return identity["bicim"] in ("hedefli", "genelleme") or identity["hakaret_kelimesi"]


# ---- identity mentions -------------------------------------------------------------------------------------
_IDENTITY = re.compile(r"\b(?:" + "|".join(f"(?:{v})" for v in kimlik.GRUPLAR.values()) + r")\b")
# "you muslim", "u flippin homosexual", "you're such a girl", "you are gay", "your just a homosexual": the identity
# as a label for the reader
_LABEL = re.compile(r"\b(you|u|ya)\s+((fucking|fuckin|flipping|flippin|freaking|freakin|frigging|friggin|bloody|damn|"
                    r"damned|little)\s+)?(?:" + _IDENTITY.pattern + r")|\b(you'?re|youre|you are|ur|u r)\s+"
                    r"(a\s+|an\s+|such\s+a\s+|so\s+|such\s+|just\s+a\s+)?(\w+\s+)?(?:" + _IDENTITY.pattern + r")"
                    r"|\byour\s+(just\s+)?(a|an|such a)\s+(\w+\s+)?(?:" + _IDENTITY.pattern + r")")
# "women will never...", "muslims always...", "gays should...": a claim about a whole group
_CLAIM = re.compile(r"(?:" + _IDENTITY.pattern + r")\s+(will|won'?t|wont|can|cannot|can'?t|cant|do|does|don'?t|dont|"
                    r"doesn'?t|get|want|wants|have|has|belong|ruin|deserve|are|r|should|must|always|never|need|needs)\b")
# Hostility: with one of these words the identity keeps its part in the score ("i hate muslims", "lazy mexicans").
# Picked by hand from the words that most separate harmful from harmless identity messages in the training split
# (log-odds, z > 3); topic words of the datasets ("sexist", "jokes", "trump", "kashmir") were left out.
HOSTILE = re.compile(
    r"\b(hate[sd]?|hatred|hating|despise[sd]?|can'?t stand|cant stand|sick of|tired of|disgust\w*|gross|dirty|filth\w*|"
    r"smelly|stinks?|ugly|fat|stupid|dumb|idiots?|morons?|fools?|retard\w*|ignorant|brainwashed|lazy|inferior\w*|"
    r"subhuman|evil|vile\w*|barbar\w*|savages?|primitive|backwards?|violent|violence|animals?|monkeys?|apes?|pigs?|"
    r"dogs|rats|vermin|cockroach\w*|parasites?|scum|trash|garbage|cancer|plague|disease|criminals?|thieves|liars?|"
    r"lying|hypocrit\w*|rapists?|rape\w*|pedophil\w*|paedophil\w*|perverts?|degenerates?|freaks?|abomination\w*|"
    r"terror\w*|extremis\w*|radical\w*|jihad\w*|islamis\w*|invad\w*|invasion|infest\w*|ruin\w*|destroy\w*|genocide|"
    r"slaughter\w*|exterminat\w*|lynch\w*|kill\w*|murder\w*|die|dead|death|deport\w*|ban|banned|get rid of|wipe out|"
    r"go back|go home|not allowed|don'?t belong|not welcome|burn in hell|go to hell|worthless|useless|pathetic|"
    r"shame\w*|worst|sick|crazy|psycho\w*|toxic|losers?|clowns?|weird|creepy|awful|horrible|nasty|wicked|"
    r"expel\w*|outlaw\w*|bigot\w*|hitler|nazi\w*|negro\w*|attack\w*|conquer\w*|so+ gay|too gay|gay ass|"
    r"that'?s gay|thats gay)\b")


# Words that name a harm instead of doing it: "racism has no place in sports", "i was bullied at school", and the
# names a victim reports being called: "some kids keep calling me fat and ugly"
TOPIC = re.compile(r"\b(racism|racist|racists|sexism|sexist|sexists|homophob\w*|transphob\w*|islamophob\w*|"
                   r"antisemit\w*|misogyn\w*|xenophob\w*|discriminat\w*|bully|bullies|bullied|bullying|cyberbully\w*|"
                   r"hate speech|hate crimes?)\b"
                   r"|\b(they|he|she|people|everyone|everybody|kids|some \w+|the \w+|my \w+|other \w+)\s+"
                   r"((keep|keeps|kept|always|still)\s+)?(call|calls|called|calling)\s+me\s+(a\s+|an\s+)?\w+(\s+and\s+\w+)?")
# "i'm not sexist but...", "call me racist, but...": the disclaimer that opens prejudice (116 of the 132 harmful
# test messages a topic-word rescoring let through); with it nothing is taken out of the sentence
DISCLAIMER = re.compile(r"\b(not|n'?t|never|call me|calling me|am i|i'?m no)\s+(\w+\s+)?(a\s+)?"
                        r"(racist|sexist|homophobic|transphobic|islamophobic|bigot|bigoted|misogynist)\b")


def mention_only(clean: str, identity: dict, has_listed_words: bool) -> bool:
    """An identity is mentioned and nothing in the sentence attacks it (3. in the module docstring)."""
    return bool(identity["gruplar"]) and not (identity["hakaret_kelimesi"] or has_listed_words
                                              or kimlik.GENELLEME.search(clean) or _CLAIM.search(clean)
                                              or _LABEL.search(clean) or HOSTILE.search(clean))


def mentions(clean: str, identity: dict, has_listed_words: bool, addressed: bool) -> tuple[bool, bool]:
    """(take out the identity words, take out the harm words) before scoring the sentence once more: the identity
    when it is only mentioned, the harm words when the sentence is not addressed to the reader. Nothing is taken
    out of a sentence with a listed word or with an identity that may be attacked."""
    if has_listed_words or DISCLAIMER.search(clean):
        return False, False
    identity_words = mention_only(clean, identity, False)
    if identity["gruplar"] and not identity_words:
        return False, False
    return identity_words, bool(not addressed and TOPIC.search(clean))


def without(clean: str, identity_words: bool = True, topic_words: bool = False) -> str:
    """The sentence without those words: what the model would say if they were not there."""
    if identity_words:
        clean = _IDENTITY.sub(" ", clean)
    if topic_words:
        clean = TOPIC.sub(" ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def without_identity(clean: str) -> str:
    return without(clean, identity_words=True)
