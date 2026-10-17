"""Sentences, possible typos, game words, quotes and spam: the small text rules around the models."""
import csv
import re
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
def _game_words() -> re.Pattern:
    words = sorted({r["kelime"] for r in confusables() if r["kategori"] == "oyun_dili"}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")(?:s|d|ed|ing|er|ers)?\b", re.I)


def without_game_words(sentence: str) -> str:
    """oyun_dili_serbest: 'kill / die / destroy' are taken out before the models score the sentence."""
    return _game_words().sub(" ", sentence)


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


def spam(text: str) -> bool:
    """3 or more links, or one word repeated at least 8 times making up more than 60 % of the words."""
    if len(_LINK.findall(text)) >= 3:
        return True
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 8:
        return False
    top = max(words.count(w) for w in set(words))
    return top >= 8 and top / len(words) > 0.6
