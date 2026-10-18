"""Sentences, possible typos, game words, quotes and spam: the small text rules around the models."""
import csv
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

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
def _game_words() -> tuple[re.Pattern, dict]:
    rows = [r for r in confusables() if r["kategori"] == "oyun_dili"]
    words = sorted({r["kelime"] for r in rows}, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")(?:s|d|ed|ing|er|ers)?\b", re.I)
    return pattern, {r["kelime"]: r["clues"] for r in rows}


def without_game_words(sentence: str, offset: int = 0, hits=()) -> str:
    """oyun_dili_serbest: 'kill / die / destroy' are taken out before the models score the sentence, but only
    with one of the word's game clues (match, round, gg...) within CLUE_DISTANCE words, and never inside a
    listed phrase ('kill yourself'). 'I hope you die in a fire' keeps its 'die'."""
    pattern, clues = _game_words()
    words = [(m.start(), m.group(0).lower()) for m in _WORD.finditer(sentence)]
    out, at = [], 0
    for m in pattern.finditer(sentence):
        if any(h.start - offset < m.end() and m.start() < h.end - offset for h in hits):
            continue
        i = next((k for k, (pos, _) in enumerate(words) if pos >= m.start()), len(words))
        near = {w for _, w in words[max(0, i - CLUE_DISTANCE):i + CLUE_DISTANCE + 1]}
        if near & clues.get(m.group(1).lower(), set()):
            out.append(sentence[at:m.start()] + " ")
            at = m.end()
    out.append(sentence[at:])
    return "".join(out)


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


SPAM_REPEATS = 8       # a word or phrase repeated at least this many times ...
SPAM_SHARE = 0.6       # ... making up more than this share of the words
SPAM_PHRASE = 3        # phrases of up to this many words ("follow me" x 8)


def _repeated(words: list[str], n: int) -> bool:
    """Is one n-word phrase repeated SPAM_REPEATS times without overlapping, covering more than SPAM_SHARE?"""
    need = max(SPAM_REPEATS, int(SPAM_SHARE * len(words) / n) + 1)
    grams = Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1))
    for gram, seen in grams.items():
        if seen < need:
            continue
        count = i = 0
        while i <= len(words) - n:
            if tuple(words[i:i + n]) == gram:
                count, i = count + 1, i + n
            else:
                i += 1
        if count >= need:
            return True
    return False


def spam(text: str) -> bool:
    """3 or more links, or one word or short phrase repeated at least 8 times making up more than 60 % of the
    words."""
    if len(_LINK.findall(text)) >= 3:
        return True
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < SPAM_REPEATS:
        return False
    return any(_repeated(words, n) for n in range(1, SPAM_PHRASE + 1))
