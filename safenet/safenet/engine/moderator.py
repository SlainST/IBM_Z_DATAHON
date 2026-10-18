"""PDF step 9: one message in, the CheckResponse out (docs/API.md)."""
from collections import Counter
from datetime import datetime

from .. import settings
from ..ml.models import Models
from ..state.store import utcnow
from . import points as pts
from .analysis import Analyzer
from .decision import judge


class Moderator:
    def __init__(self, store, models: Models | None = None):
        self.store = store
        self.models = models or Models()
        self.analyzer = Analyzer(self.models)

    def check(self, platform: str, req: dict, now: datetime | None = None) -> dict:
        """now: when the message was sent, for replaying a conversation (simulate.py); the clock when None."""
        sender, recipient = req["sender_id"], req.get("recipient_id")
        group = req.get("group_id") or "general"
        message_id = req.get("message_id")
        text = req["text"]
        a = settings.for_platform(platform, settings.CHANNEL_1TO1 if recipient else settings.CHANNEL_GROUP)
        m = a["mesaj"]
        analysis = self.analyzer.analyze(text, m["oyun_dili_serbest"], a["karistirilabilir"]["baglam_ipucu_sayisi"],
                                         m["alinti_korumasi"])

        with self.store.message(platform, group, sender, recipient, message_id) as tx:
            if tx.replay is not None:
                stored, replayed = tx.replay, True
            else:
                stored, replayed = self._decide(analysis, a, tx, now or utcnow()), False
        if replayed:
            self.store.count(platform, group, Counter({"replayed": 1}))
        return self._answer(text, analysis, stored, platform, group, sender, recipient, message_id, replayed)

    def _decide(self, analysis, a: dict, tx, now: datetime) -> dict:
        user, rel = tx.user, tx.relation
        verdict = judge(analysis, a)
        decision, reason = verdict.decision, verdict.reason
        suggested, change, rel_change = None, 0.0, 0.0

        if pts.is_restricted(user, now):
            decision, reason = "block", "sender_restricted"          # frozen: no points, no recovery
        else:
            blocked_before = pts.relation_blocked(rel, a)
            event = pts.event_points(analysis, verdict, a)
            change, suggested = pts.score_sender(user, event, verdict.clean, a, now)
            if rel is not None:
                rel_change = pts.score_relation(rel, event, verdict.clean, a)
            if suggested is None and verdict.colour == "yellow" and a["mesaj"]["sari_davranis"] == "teslim_ve_uyari_onerisi":
                suggested = "warn_sender"
            if suggested == "restrict_sender":
                decision, reason = "block", reason if decision == "block" else "sender_restricted"
            elif blocked_before:
                decision, reason = "block", "relation_blocked"

        worst = verdict.worst
        if worst is None and analysis.sentences:
            worst = max(range(len(analysis.sentences)), key=lambda i: analysis.sentences[i].harm)
        s = analysis.sentences[worst]
        harmful = verdict.colour in ("yellow", "red")
        stored = {
            "decision": decision, "reason": reason, "colour": verdict.colour, "worst": worst,
            "harm": s.harm, "wordless_harm": s.wordless, "category": s.category if harmful else None,
            "sender_standing": {"level": pts.level(user, a, now), "change": change, "restrictions": user["restrictions"],
                                "restricted_until": user["restricted_until"].isoformat() if user["restricted_until"] else None},
            "relation": None if rel is None else {"blocked": pts.relation_blocked(rel, a), "change": rel_change},
            "suggested_action": suggested,
        }
        counters = Counter({"messages": 1, f"decision:{decision}": 1})
        if harmful:
            counters["harmful"] += 1
            if stored["category"]:
                counters[f"category:{stored['category']}"] += 1
        if reason:
            counters[f"reason:{reason}"] += 1
        if suggested == "warn_sender":
            counters["warnings"] += 1
        elif suggested == "restrict_sender":
            counters["restrictions"] += 1
        tx.save(user, rel, stored, counters)
        return stored

    @staticmethod
    def _answer(text, analysis, stored, platform, group, sender, recipient, message_id, replayed) -> dict:
        decision = stored["decision"]
        worst = analysis.sentences[stored["worst"]] if stored["worst"] is not None and stored["worst"] < len(analysis.sentences) else None
        harmful = stored["colour"] in ("yellow", "red")
        return {
            "key": f"{platform}/{group}/{sender}",
            "platform": platform, "group": group, "sender": sender, "recipient": recipient,
            "message_id": message_id,
            "decision": decision,
            "recipient_sees": text if decision == "allow" else analysis.censored_text if decision == "censor" else None,
            "reason": stored["reason"],
            "worst_sentence": analysis.censored_text[worst.start:worst.end] if worst and decision != "allow" else None,
            "harm": stored["harm"],
            "wordless_harm": stored["wordless_harm"],
            "category": stored["category"],
            "key_words": worst.key_words if worst and harmful else [],
            "censored": [{"start": h.start, "end": h.end} for h in analysis.hits],
            "hidden_profanity": [{"written": h.written, "word": h.word} for h in analysis.hits if h.hidden],
            "possible_typos": [t for s in analysis.sentences for t in s.typos],
            "sender_standing": stored["sender_standing"],
            "relation": stored["relation"],
            "suggested_action": stored["suggested_action"],
            "replayed": replayed,
        }
