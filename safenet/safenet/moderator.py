"""The moderation pipeline: normalize -> lexicon -> PII -> ML score -> policy -> strikes."""

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

from .classifier import ToxicityClassifier
from .lexicon import Lexicon
from .normalize import tokenize
from .pii import find_pii
from .policy import PROFILES, Profile

SEVERITY_LABELS = {1: "profanity", 2: "insult", 3: "threat_or_hate"}


class Action(str, Enum):
    ALLOW = "allow"
    MASK = "mask"
    BLOCK = "block"


@dataclass
class Result:
    action: Action
    text: str                       # what other users see ("" when blocked)
    categories: list[str]
    max_severity: int
    toxicity_score: float | None
    needs_review: bool
    muted_until: float | None
    latency_ms: float = 0.0
    spans: list[dict] = field(default_factory=list)


class StrikeTracker:
    """Mutes a user after repeated blocked messages. In-memory; swap for Redis when running more than one worker."""

    def __init__(self, max_strikes: int = 3, window_s: float = 300, mute_s: float = 600):
        self.max_strikes, self.window_s, self.mute_s = max_strikes, window_s, mute_s
        self._strikes: dict[str, deque[float]] = defaultdict(deque)
        self._muted: dict[str, float] = {}
        self._lock = threading.Lock()

    def muted_until(self, user_id: str, now: float) -> float | None:
        until = self._muted.get(user_id)
        return until if until and until > now else None

    def strike(self, user_id: str, now: float) -> float | None:
        with self._lock:
            q = self._strikes[user_id]
            q.append(now)
            while q and q[0] < now - self.window_s:
                q.popleft()
            if len(q) >= self.max_strikes:
                q.clear()
                self._muted[user_id] = now + self.mute_s
            return self.muted_until(user_id, now)


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if not chars[i].isspace():
                chars[i] = "#"
    return "".join(chars)


class Moderator:
    def __init__(self, lexicon: Lexicon, classifier: ToxicityClassifier, strikes: StrikeTracker | None = None):
        self.lexicon = lexicon
        self.classifier = classifier
        self.strikes = strikes or StrikeTracker()

    def moderate(self, text: str, profile: str = "teen", user_id: str | None = None) -> Result:
        t0 = time.perf_counter()
        result = self._moderate(text, PROFILES[profile], user_id)
        result.latency_ms = (time.perf_counter() - t0) * 1000
        return result

    def _moderate(self, text: str, profile: Profile, user_id: str | None) -> Result:
        now = time.time()
        if user_id and (until := self.strikes.muted_until(user_id, now)):
            return Result(Action.BLOCK, "", ["muted"], 0, None, False, until)

        hits = self.lexicon.scan(tokenize(text))
        pii = find_pii(text) if profile.mask_pii else []
        score = self.classifier.score(text)

        max_sev = max((h.severity for h in hits), default=0)
        categories = sorted({SEVERITY_LABELS[h.severity] for h in hits} | {f"pii_{p.kind}" for p in pii})
        mask_spans = [(h.start, h.end) for h in hits if h.severity >= profile.mask_severity]
        mask_spans += [(p.start, p.end) for p in pii]
        spans = [{"start": h.start, "end": h.end, "type": SEVERITY_LABELS[h.severity]} for h in hits]
        spans += [{"start": p.start, "end": p.end, "type": f"pii_{p.kind}"} for p in pii]

        blocked = max_sev >= profile.block_severity or (score is not None and score >= profile.block_score)
        needs_review = not hits and score is not None and profile.review_score <= score < profile.block_score
        if blocked and not hits:
            categories.append("ml_toxic")

        muted_until = None
        if blocked:
            action, shown = Action.BLOCK, ""
            if user_id:
                muted_until = self.strikes.strike(user_id, now)
        elif mask_spans:
            action, shown = Action.MASK, _mask(text, mask_spans)
        else:
            action, shown = Action.ALLOW, text

        return Result(action, shown, categories, max_sev, score, needs_review, muted_until, spans=spans)
