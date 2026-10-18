"""PDF steps 2-7: everything about the text itself, before any points. Pure, so each worker caches it."""
import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock

import kimlik
import temizlik

from ..config import ANALYSIS_CACHE
from ..ml import models as ml
from ..ml.models import Models
from ..pipeline import profanity, text as tx

CATEGORY_MIN = 0.25   # Model 2 runs only for sentences with harm or wordless harm at least this


@dataclass
class Sentence:
    start: int
    end: int
    harm: float
    wordless: float
    category: str | None
    hits: list           # profanity.Hit inside this sentence
    typos: list          # [{"word", "suggestion"}]
    identity: dict       # kimlik.kimlik_analizi()
    quoted: bool
    key_words: list = field(default_factory=list)


@dataclass
class Analysis:
    sentences: list[Sentence]
    hits: list
    words: int
    spam: bool
    censored_text: str


def _remove(sentence: str, offset: int, hits) -> str:
    out, at = [], 0
    for h in hits:
        out.append(sentence[at:h.start - offset])
        at = h.end - offset
    out.append(sentence[at:])
    return " ".join(out)


def _key_words(clean: str, hits) -> list[str]:
    words = [h.word for h in hits]
    for p in ml._THREAT:
        m = p.search(clean)
        if m:
            words.insert(0, m.group(0))
            break
    words += [m.group(0) for m in ml._INSULT.finditer(clean)]
    return list(dict.fromkeys(words))[:8]


class Analyzer:
    def __init__(self, models: Models):
        self.models = models
        self._cache: OrderedDict = OrderedDict()
        self._lock = Lock()

    def analyze(self, text: str, game_words_free: bool, min_clues: int, quote_protection: bool) -> Analysis:
        key = (hashlib.blake2b(text.encode(), digest_size=16).digest(), game_words_free, min_clues, quote_protection)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._analyze(text, game_words_free, min_clues, quote_protection)
        with self._lock:
            self._cache[key] = result
            if len(self._cache) > ANALYSIS_CACHE:
                self._cache.popitem(last=False)
        return result

    def _analyze(self, text: str, game_words_free: bool, min_clues: int, quote_protection: bool) -> Analysis:
        hits = profanity.find(text)
        spans = tx.sentences(text)
        parts, prepared = [], []
        for i, sp in enumerate(spans):
            raw = text[sp.start:sp.end]
            mine = [h for h in hits if sp.start <= h.start < sp.end]
            typos = [t for h in mine if (t := tx.possible_typo(raw, sp.start, h, min_clues))]
            scored = tx.without_game_words(raw, sp.start, mine) if game_words_free else raw
            wordless_raw = _remove(raw, sp.start, mine)
            if game_words_free:
                wordless_raw = tx.without_game_words(wordless_raw)
            clean, clean_wordless = temizlik.temizle(scored), temizlik.temizle(wordless_raw)
            prepared += [clean, clean_wordless]
            parts.append((sp, raw, mine, typos, clean))

        scores = self.models.harm(prepared)
        sentences = []
        for i, (sp, raw, mine, typos, clean) in enumerate(parts):
            harm, wordless = scores[2 * i], scores[2 * i + 1]
            typo_words = {t["word"] for t in typos}
            counted = [h for h in mine if h.word not in typo_words]
            harm = round(1 - (1 - harm) * (1 - self.models.profanity_harm([h.severity for h in counted])), 4)
            if typos and len(counted) == 0:
                harm = wordless      # only a likely typo: judged without it (PDF decision 20)
            category = self.models.category(clean) if max(harm, wordless) >= CATEGORY_MIN else None
            identity = kimlik.kimlik_analizi(clean, hedefli=temizlik.hedefli_mi(raw))
            is_quoted = quote_protection and tx.quoted(text, sp, spans[i - 1] if i else None)
            sentences.append(Sentence(sp.start, sp.end, harm, wordless, category, mine, typos, identity, is_quoted,
                                      _key_words(clean, counted)))

        return Analysis(sentences, hits, profanity.word_count(text, hits), tx.spam(text), profanity.star(text, hits))

