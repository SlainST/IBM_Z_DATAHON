"""Model 1 (harm 0-1 per sentence) and Model 2 (category), with fallback rules until they are trained.

Both are scikit-learn pipelines saved with joblib in models/ (model1.joblib, model2.joblib), trained on
the server by the team. They get the sentence as temizlik.temizle() returns it, exactly as in training.
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
        return [round(float(p), 4) for p in self.model1.predict_proba(texts)[:, 1]]

    def profanity_harm(self, severities: list[int]) -> float:
        """Fallback only: listed words raise harm a little (so "f*ck, I missed the bus" stays green)."""
        if self.model1 is not None:
            return 0.0
        return _combine(0.04 * s for s in severities)

    def category(self, text: str) -> str:
        if self.model2 is None:
            return fallback_category(text)
        label = str(self.model2.predict([text])[0])
        return CATEGORY.get(label, label if label in CATEGORIES else "insult")
