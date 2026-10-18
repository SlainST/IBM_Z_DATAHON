"""Sentences, possible typos, game words, quotes and spam: the small text rules around the models."""
import csv
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import kimlik

from ..config import ROOT

CLUE_DISTANCE = 6   # a context clue counts within this many words of the listed word

# A sentence ends at . ! ? followed by whitespace, or at a line break. "f.u.c.k" stays one word.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int


def sentences(text: str) -> list[Span]:
    spans, start = [], 0
    for m in _BOUNDARY.finditer(text):
        spans.append(Span(start, m.start()))
        start = m.end()
    spans.append(Span(start, len(text)))
    out = []
    for s in spans:
        chunk = text[s.start:s.end]
        if chunk.strip():
            lead = len(chunk) - len(chunk.lstrip())
            out.append(Span(s.start + lead, s.start + len(chunk.rstrip())))
    return out or [Span(0, len(text))]


@lru_cache(maxsize=1)
def confusables() -> list[dict]:
    path = ROOT / "karistirilabilir_kelimeler.csv"
    if not path.exists():
        path = ROOT / "data" / "karistirilabilir_kelimeler.csv"
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["clues"] = {c.strip().lower() for c in r.get("baglam_ipuclari", "").split("|") if c.strip()}
    return rows


def possible_typo(sentence: str, offset: int, hit, min_clues: int) -> dict | None:
    """'I fed the fuck at the lake': a listed word next to clues of an innocent word one key away."""
    candidates = [r for r in confusables() if r["karistirilan"] == hit.word and r["clues"]]
    if not candidates:
        return None
    words = [(m.start() + offset, m.group(0).lower()) for m in _WORD.finditer(sentence)]
    at = next((i for i, (pos, _) in enumerate(words) if pos >= hit.start), None)
    if at is None:
        return None
    near = {w for _, w in words[max(0, at - CLUE_DISTANCE):at + CLUE_DISTANCE + 1]}
    for r in candidates:
        if len(near & r["clues"]) >= min_clues:
            return {"word": hit.word, "suggestion": r["kelime"]}
    return None


@lru_cache(maxsize=1)
def _game_words() -> list[tuple[re.Pattern, frozenset, tuple]]:
    """The oyun_dili rows: the word with its endings, its context clues that are words, and those that are not (😂)."""
    out = []
    for r in confusables():
        if r["kategori"] != "oyun_dili":
            continue
        words = frozenset(c for c in r["clues"] if _WORD.fullmatch(c))
        signs = tuple(c for c in r["clues"] if not _WORD.fullmatch(c))
        out.append((re.compile(rf"\b{re.escape(r['kelime'])}(?:s|d|ed|ing|er|ers)?\b", re.I), words, signs))
    return out


def without_game_words(sentence: str, message: str) -> str:
    """oyun_dili_serbest: a game word ('kill', 'die', 'destroy') is taken out before the models score the
    sentence when the message has one of that word's context clues (karistirilabilir_kelimeler.csv: 'match',
    'round', 'gg'...). "gg, I will kill you next round" is game talk; "I will kill you and your whole family"
    keeps its words and is judged like on any other platform."""
    lowered = message.lower()
    words = set(_WORD.findall(lowered))
    for pattern, clues, signs in _game_words():
        if words & clues or any(s in lowered for s in signs):
            sentence = pattern.sub(" ", sentence)
    return sentence


@lru_cache(maxsize=1)
def _slur_carriers() -> re.Pattern | None:
    """The kelime_icinde_kufur rows whose hidden word is one of kimlik.py's slurs: "snigger", "raccoon", "spicy"."""
    slur = re.compile(r"^(?:" + "|".join(kimlik.HAKARETLER.values()) + r")$")
    words = [r["kelime"] for r in confusables()
             if r["kategori"] == "kelime_icinde_kufur" and slur.match(r["karistirilan"])]
    return re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\w*", re.I) if words else None


def for_models(clean: str) -> str:
    """What the models read. Character n-grams can't tell "snigger" from the slur inside it (Model 1: 0.66 for
    "the kids began to snigger at the joke", 0.08 without the word), so an ordinary word that carries a slur is
    taken out; the rules and the identity analysis still read the sentence as written."""
    carriers = _slur_carriers()
    return re.sub(r"\s+", " ", carriers.sub(" ", clean)).strip() if carriers else clean


_QUOTED = re.compile(r"[\"“”«»„]([^\"“”«»„]{3,})[\"“”«»„]")
_REPORTED = re.compile(
    r"\b(he|she|they|someone|somebody|my \w+|this (guy|girl|kid|boy)|a (guy|girl|kid|boy))\s+"
    r"(told|tells|said|says|keeps saying|kept saying|wrote|writes|texted|texts|messaged|threatened|sent)\b"
    r"|\b(o|biri|birisi)\s+(bana\s+)?(dedi|diyor|yazdı|yazıyor|söyledi)\b", re.I)


def quoted(text: str, span: Span, previous: Span | None) -> bool:
    """A threat passed on ('he told me ...') or inside quotes: held for a moderator, not blocked."""
    for m in _QUOTED.finditer(text):
        if m.start(1) <= span.start + 1 and span.end <= m.end(1) + 1:
            return True
    if _REPORTED.search(text[span.start:span.end]):
        return True
    return bool(previous and _REPORTED.search(text[previous.start:previous.end]))


_LINK = re.compile(r"https?://|www\.", re.I)
SPAM_LINKS = 3          # this many links make a message spam
SPAM_REPEATS = 8        # a word or phrase repeated at least this many times...
SPAM_SHARE = 0.6        # ...making up more than this share of the words
SPAM_PHRASE_WORDS = 4   # phrases of up to this many words ("follow me" x 8)


def _repeats(words: list[str], n: int) -> int:
    """How many times the most frequent run of n words occurs, without overlapping itself."""
    gram = Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1)).most_common(1)[0][0]
    count, i = 0, 0
    while i <= len(words) - n:
        if tuple(words[i:i + n]) == gram:
            count, i = count + 1, i + n
        else:
            i += 1
    return count


def spam(text: str) -> bool:
    """3 or more links, or one word or phrase of up to 4 words repeated at least 8 times and making up more
    than 60 % of the words: "lol" x 10, "follow me" x 8."""
    if len(_LINK.findall(text)) >= SPAM_LINKS:
        return True
    words = [w.lower() for w in _WORD.findall(text)]
    for n in range(1, SPAM_PHRASE_WORDS + 1):
        if len(words) < SPAM_REPEATS * n:
            break
        count = _repeats(words, n)
        if count >= SPAM_REPEATS and count * n / len(words) > SPAM_SHARE:
            return True
    return False
