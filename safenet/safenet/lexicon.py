"""Lexicon matching on token skeletons.

Lexicon files are tab-separated: ``term<TAB>severity<TAB>mode``.
  severity: 1 = profanity, 2 = insult / harassment, 3 = threat / self-harm / hate
  mode:     exact (default) or prefix (catches Turkish suffixes: salak -> salaklar)
Multi-word terms ("kill yourself") are matched as phrases.
"""

from dataclasses import dataclass
from pathlib import Path

from .normalize import Token, skeleton

EMBEDDED_MIN_LEN = 5  # long terms are also found inside glued words ("sengerizekalisin")


@dataclass(frozen=True, slots=True)
class Hit:
    start: int
    end: int
    term: str
    severity: int


class Lexicon:
    def __init__(self, entries: list[tuple[str, int, str]]):
        self.exact: dict[str, int] = {}
        self.prefix: dict[str, int] = {}
        self.phrases: dict[tuple[str, ...], int] = {}
        for term, severity, mode in entries:
            words = tuple(w for w in (skeleton(p) for p in term.split()) if w)
            if len(words) > 1:
                self.phrases[words] = max(severity, self.phrases.get(words, 0))
            elif words:
                table = self.prefix if mode == "prefix" else self.exact
                table[words[0]] = max(severity, table.get(words[0], 0))
        self.embedded = {t: s for t, s in {**self.exact, **self.prefix}.items() if len(t) >= EMBEDDED_MIN_LEN}
        self.min_prefix = min(map(len, self.prefix), default=1)

    @classmethod
    def from_dir(cls, directory: Path) -> "Lexicon":
        entries = []
        for path in sorted(directory.glob("*.tsv")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.split("\t")
                mode = parts[2].strip() if len(parts) > 2 else "exact"
                entries.append((parts[0].strip(), int(parts[1]), mode))
        return cls(entries)

    def _match_word(self, word: str) -> tuple[str, int] | None:
        if word in self.exact:
            return word, self.exact[word]
        for i in range(len(word), self.min_prefix - 1, -1):
            if word[:i] in self.prefix:
                return word[:i], self.prefix[word[:i]]
        for term, severity in self.embedded.items():
            if term in word:
                return term, severity
        return None

    def scan(self, tokens: list[Token]) -> list[Hit]:
        hits: list[Hit] = []
        for tok in tokens:
            if tok.skeleton and (m := self._match_word(tok.skeleton)):
                hits.append(Hit(tok.start, tok.end, m[0], m[1]))
        hits += self._scan_phrases(tokens)
        hits += self._scan_spaced_letters(tokens)
        return hits

    def _scan_phrases(self, tokens: list[Token]) -> list[Hit]:
        words = [t.skeleton for t in tokens]
        hits = []
        for phrase, severity in self.phrases.items():
            n = len(phrase)
            for i in range(len(words) - n + 1):
                if tuple(words[i:i + n]) == phrase:
                    hits.append(Hit(tokens[i].start, tokens[i + n - 1].end, " ".join(phrase), severity))
        return hits

    def _scan_spaced_letters(self, tokens: list[Token]) -> list[Hit]:
        """Catch "s a l a k" by joining runs of single-letter tokens."""
        hits, run = [], []
        for tok in [*tokens, None]:
            if tok is not None and len(tok.skeleton) == 1:
                run.append(tok)
                continue
            if len(run) >= 3 and (m := self._match_word(skeleton("".join(t.skeleton for t in run)))):
                hits.append(Hit(run[0].start, run[-1].end, m[0], m[1]))
            run = []
        return hits
