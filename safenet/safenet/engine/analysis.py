"""PDF steps 2-7: everything about the text itself, before any points. Pure, so each worker caches it."""
import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock

import kimlik
import temizlik

from ..config import ANALYSIS_CACHE
from ..ml import models as ml, rules
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
    rule: str | None = None   # the kind of rules.py rule that set the score: threat, bullying, sexual...
    context: float = 0.0      # the whole message's harm, on its worst sentence only: can make it yellow, never red


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


def _key_words(clean: str, hits, rule: rules.Match | None) -> list[str]:
    """A threat phrase ("break your legs") or the phrase a rule matched, the listed words, insult words."""
    words = [h.word for h in hits]
    threat = next((m.group(0) for p in ml._THREAT if (m := p.search(clean))), None)
    if threat or rule:
        words.insert(0, threat or rule.phrase)
    words += [m.group(0) for m in ml._INSULT.finditer(clean)]
    return list(dict.fromkeys(words))[:8]


def _calibrate(harm: float, wordless: float, found, found_wordless, identity: dict, category_of):
    """rules.py on top of the model scores: a matching rule sets a floor and the category; a plain insult is
    capped at rules.INSULT_CAP. Returns (harm, wordless, category, the rule match)."""
    if found:
        harm = max(harm, found.rule.floor)
    if found_wordless:
        wordless = max(wordless, found_wordless.rule.floor)
    rule = found or found_wordless
    if rule:
        category = rule.rule.category
    elif max(harm, wordless) >= CATEGORY_MIN:
        category = category_of()
    else:
        category = None
    if category == "insult" and rule is None and not rules.identity_attack(identity):
        harm, wordless = min(harm, rules.INSULT_CAP), min(wordless, rules.INSULT_CAP)
    return harm, wordless, category, rule


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
            scored = tx.without_game_words(raw, text) if game_words_free else raw
            wordless_raw = _remove(raw, sp.start, mine)
            if game_words_free:
                wordless_raw = tx.without_game_words(wordless_raw, text)
            clean, clean_wordless = temizlik.temizle(scored), temizlik.temizle(wordless_raw)
            identity = kimlik.kimlik_analizi(clean, hedefli=temizlik.hedefli_mi(raw))
            is_quoted = quote_protection and tx.quoted(text, sp, spans[i - 1] if i else None)
            found, found_wordless = rules.find(clean), rules.find(clean_wordless)
            if is_quoted:
                # what the sender reports someone else said: only threats keep their floor (and are held, not
                # blocked); a quoted "nobody likes you" is judged by the models alone, so a victim isn't silenced
                found = found if found and found.rule.category == "threat" else None
                found_wordless = found_wordless if found_wordless and found_wordless.rule.category == "threat" else None
            texts = [clean, clean_wordless]
            take = (False, False) if found or found_wordless else rules.mentions(clean, identity, bool(mine),
                                                                                 temizlik.hedefli_mi(raw))
            mention = any(take)
            if mention:      # also scored without what it only mentions; the lower score is kept (rules.py, 3.)
                texts += [rules.without(clean, *take), rules.without(clean_wordless, *take)]
            parts.append((sp, raw, mine, typos, clean, identity, is_quoted, found, found_wordless, mention,
                          len(prepared)))
            prepared += texts

        # Model 1 learned from whole messages: harm spread over sentences that each look mild ("you! you blocked
        # me worm why!!") shows only in the whole. Not for a message that quotes someone or has a likely typo.
        whole, whole_at = None, len(prepared)
        if len(parts) > 1 and not any(p[6] or p[3] for p in parts):
            whole = temizlik.temizle(tx.without_game_words(text, text) if game_words_free else text)
            addressed = temizlik.hedefli_mi(text)
            whole_identity = kimlik.kimlik_analizi(whole, hedefli=addressed)
            take = (False, False) if rules.find(whole) else rules.mentions(whole, whole_identity, bool(hits), addressed)
            prepared += [whole] + ([rules.without(whole, *take)] if any(take) else [])

        scores = self.models.harm(prepared)
        context = min(scores[whole_at:]) if whole is not None else 0.0
        sentences = []
        for sp, raw, mine, typos, clean, identity, is_quoted, found, found_wordless, mention, at in parts:
            harm, wordless = scores[at], scores[at + 1]
            if mention:
                harm, wordless = min(harm, scores[at + 2]), min(wordless, scores[at + 3])
            typo_words = {t["word"] for t in typos}
            counted = [h for h in mine if h.word not in typo_words]
            harm = round(1 - (1 - harm) * (1 - self.models.profanity_harm([h.severity for h in counted])), 4)
            if typos and len(counted) == 0:
                harm = wordless      # only a likely typo: judged without it (PDF decision 20)
            harm, wordless, category, rule = _calibrate(harm, wordless, found, found_wordless, identity,
                                                        lambda clean=clean: self.models.category(clean))
            sentences.append(Sentence(sp.start, sp.end, harm, wordless, category, mine, typos, identity, is_quoted,
                                      _key_words(clean, counted, rule), rule.rule.kind if rule else None))

        worst = max(sentences, key=lambda s: s.harm, default=None)
        if worst is not None and context > worst.harm:
            if worst.category is None and context >= CATEGORY_MIN:
                worst.category = self.models.category(whole)
            if worst.category == "insult" and worst.rule is None and not rules.identity_attack(worst.identity):
                context = min(context, rules.INSULT_CAP)
            worst.context = context
        return Analysis(sentences, hits, profanity.word_count(text, hits), tx.spam(text), profanity.star(text, hits))

