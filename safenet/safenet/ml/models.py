"""Model 1 (harm 0-1 per sentence) and Model 2 (category), with fallback rules until they are trained.

Both are scikit-learn pipelines saved with joblib in models/ (model1.joblib, model2.joblib), trained on
the server with train.py (models/README.md). They get the sentence as temizlik.temizle() returns it, exactly as in training.
Model 1 must have predict_proba (column 1 = harmful); Model 2 predict() returns one of the training
labels (tehdit, irk, din, cinsiyet, cinsel, genel_hakaret) or the English names.
"""
import logging
import re

import joblib

import kategoriler
import kimlik

from ..config import MODELS_DIR

log = logging.getLogger("safenet.models")

CATEGORY = {"tehdit": "threat", "irk": "race", "din": "religion", "cinsiyet": "gender", "cinsel": "sexual",
            "genel_hakaret": "insult", "hakaret": "insult"}
CATEGORIES = ("insult", "gender", "religion", "race", "sexual", "threat")


def _load(name: str):
    path = MODELS_DIR / name
    if not path.exists():
        return None
    try:
        return joblib.load(path)
    except Exception:
        log.exception("could not load %s; using the fallback rules", path)
        return None


# ---- fallback rules: a few dozen weighted phrases, only until the models exist -----------------------
_THREAT = [re.compile(p) for _, ps in kategoriler.KURALLAR if _ == "tehdit" for p in ps] + [re.compile(p) for p in (
    r"\bbreak (your|ur|ya) (legs?|neck|face|arms?|bones|teeth|nose)\b",
    r"\b(i'?ll|i will|i'?m gonna|im gonna|gonna|going to)\s+(\w+\s+){0,2}(find|get|end|break|smash|destroy|ruin) (you|u|ya)\b",
    r"\b(you'?re|you are|ur|u r) (so )?dead\b",
    r"\bseni (öldür|gebert|bul|döv|kes)\w*",
    r"\b(kafanı|bacaklarını|ağzını|burnunu) (kır|kıra|kırar|kırıcam|kıracağım)\w*",
    r"\b(öl|geber)(sene|esin|in)?\b",
)]
_INSULT = re.compile(
    r"\b(idiot|stupid|moron|loser|dumb|ugly|fat|pathetic|worthless|useless|freak|noob|trash|garbage|"
    r"disgusting|creep|clown|nobody likes you|no one likes you|everyone hates you|shut up|go away|"
    r"uninstall|kill (your|ur) ?self|"
    r"salak\w*|aptal\w*|gerizekal\w*|geri zekal\w*|ezik\w*|şerefsiz\w*|çirkin\w*|şişko\w*|"
    r"kimse seni sevmiyor|herkes senden nefret ediyor|defol\w*|git buradan|sus artık)\b")
_IDENTITY_NEGATIVE = re.compile(
    r"\b(dirty|filthy|disgusting|stupid|terrorists?|animals?|inferior|subhuman|scum|vermin|go back|"
    r"pis|aşağılık|terörist\w*)\b")


# ---- explicit threats: a threat whatever the models say ------------------------------------------------
# The models saw only ~480 real threats (all found by the rules in kategoriler.py), so they miss phrasings they
# never saw, like the PDF's "I'll f*cking break your legs". A sentence matching one of these patterns is a threat
# with harm of at least THREAT_FLOOR. They were picked for precision on the training split: 91 % of the messages
# they match are labelled harmful, and they match 2 in 10,000 harmless ones, most of them threats the labels
# missed ("i will punch you.", "i know where you live, fool"). Broader rules ("shoot you", "kill them") are left
# out: they also match "i'll shoot you an email" and the news.
THREAT_FLOOR = 0.95
_YOU = r"(you|u|ya|yourself|urself|ur family|your family|your mom|your kids)"
_FIRST = r"(i'?ll|i will|i'?m going to|im going to|i'?m gonna|im gonna)\s+(\w+\s+){0,2}"
EXPLICIT_THREATS = [re.compile(p) for p in (
    _FIRST + r"(kill|murder|stab|strangle|choke|hurt|beat up|punch|rape|burn|drown|end)\s+" + _YOU + r"\b",
    _FIRST + r"(beat|punch|kick|slap)\s+(the )?(crap|shit|hell|fuck|living daylights)\s+out of\s+" + _YOU + r"\b",
    _FIRST + r"(break|snap|smash|crack|bust)\s+(your|ur|ya)\s+"
             r"(legs?|arms?|neck|face|teeth|nose|jaw|skull|bones|ribs|fingers|knees?)\b",
    r"\b(hope|wish)\s+(you|u)\s+(\w+\s+){0,2}(die|dies|get raped|get killed|get cancer|burn|rot|suffer)\b",
    r"\b(you|u)('re| are| r)?\s*(gonna|going to|will)\s+(get|be)\s+(raped|killed|shot|stabbed|beaten|murdered|hurt)\b",
    r"\b(you'?re|you are|ur|u r)\s+(so\s+)?dead\b(?!\s+(wrong|on|right|serious|set|tired|last|center|inside|to me))",
    r"\b(kys|kill (your|ur) ?self|kill urself|go die|drop dead|die in a fire|watch your back|i know where you live|"
    r"dead meat|death threat|i'?ll find you and|i will find you and)\b",
)]


def explicit_threat(clean: str) -> bool:
    return any(p.search(clean) for p in EXPLICIT_THREATS)


def _combine(ps) -> float:
    q = 1.0
    for p in ps:
        q *= 1 - p
    return 1 - q


def fallback_harm(clean: str) -> float:
    signals = [0.02]
    if any(p.search(clean) for p in _THREAT):
        signals.append(0.95)
    signals += [0.6] * min(3, len(_INSULT.findall(clean)))
    ident = kimlik.kimlik_analizi(clean, hedefli=False)
    if ident["bicim"] in ("hedefli", "genelleme") and _IDENTITY_NEGATIVE.search(clean):
        signals.append(0.8)
    return round(_combine(signals), 4)


def fallback_category(clean: str) -> str:
    if any(p.search(clean) for p in _THREAT):
        return "threat"
    for name, patterns in kategoriler.KURALLAR:
        if any(re.search(p, clean) for p in patterns):
            return CATEGORY[name]
    return "insult"


# ---- the models ----------------------------------------------------------------------------------
class Models:
    def __init__(self):
        self.model1 = _load("model1.joblib")
        self.model2 = _load("model2.joblib")

    def status(self) -> dict:
        return {"model1": "loaded" if self.model1 is not None else "fallback",
                "model2": "loaded" if self.model2 is not None else "fallback"}

    def harm(self, texts: list[str]) -> list[float]:
        """One call for all sentences of a message (and their wordless versions)."""
        if not texts:
            return []
        if self.model1 is None:
            return [fallback_harm(t) for t in texts]
        return [round(max(float(p), THREAT_FLOOR) if explicit_threat(t) else float(p), 4)
                for p, t in zip(self.model1.predict_proba(texts)[:, 1], texts)]

    def profanity_harm(self, severities: list[int]) -> float:
        """Fallback only: listed words raise harm a little (so "f*ck, I missed the bus" stays green)."""
        if self.model1 is not None:
            return 0.0
        return _combine(0.04 * s for s in severities)

    def category(self, text: str) -> str:
        if explicit_threat(text):
            return "threat"
        if self.model2 is None:
            return fallback_category(text)
        label = str(self.model2.predict([text])[0])
        return CATEGORY.get(label, label if label in CATEGORIES else "insult")
