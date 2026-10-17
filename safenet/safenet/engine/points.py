"""PDF step 8b: hidden points per platform / group / sender, and per sender -> recipient (A -> B).

Points never fall with time. A clean message (green, no listed word) lowers them by iyilesme_orani when at
least iyilesme_esigi of the previous iyilesme_penceresi messages were clean. At uyari_esigi the answer
suggests warn_sender; at susturma_esigi the sender is restricted (5, 60, 1440 minutes...) and the points
drop to susturma_sonrasi_puan. A relation is never restricted: at iliski.engel_esigi A's messages stop
reaching B.
"""
from datetime import datetime, timedelta

import kimlik

from .analysis import Analysis
from .decision import Verdict

ZERO_BELOW = 1.0   # points below this become 0, so a relation row can be deleted


def new_state() -> dict:
    return {"points": 0.0, "recent": "", "restrictions": 0, "restricted_until": None, "messages": 0}


def event_points(analysis: Analysis, verdict: Verdict, a: dict) -> float:
    """What this message adds before any recovery: words, disguises, colour and identity."""
    g, m = a["gizli_puan"], a["mesaj"]
    words = min(sum(h.severity * g["kelime_carpani"] for h in verdict.counted_hits), g["mesaj_basina_ust_sinir"])
    hidden = g["gizli_kufur_ek"] * sum(1 for h in verdict.counted_hits if h.hidden)
    colour = 0
    if verdict.colour == "yellow":
        colour = g["sari_mesaj"]
    elif verdict.colour == "red" and not verdict.quoted:
        colour = {"threat": g["tehdit_mesaj"], "spam": g["spam_mesaj"]}.get(verdict.reason, g["kirmizi_mesaj"])
    identity = max((kimlik.kimlik_puani(s.identity, s.harm >= m["sari_esigi"], a) for s in analysis.sentences), default=0)
    return float(words + hidden + colour + identity)


def _apply(state: dict, points: float, clean: bool, g: dict) -> float:
    """Adds the event or applies recovery; returns the change."""
    before = state["points"]
    window = g["iyilesme_penceresi"]
    if clean:
        if state["recent"].count("1") >= g["iyilesme_esigi"]:
            state["points"] = before * (1 - g["iyilesme_orani"])
    else:
        state["points"] = before + points
    if state["points"] < ZERO_BELOW:
        state["points"] = 0.0
    state["recent"] = (state["recent"] + ("1" if clean else "0"))[-window:]
    state["messages"] += 1
    state["points"] = round(state["points"], 2)
    return round(state["points"] - before, 2)


def is_restricted(state: dict, now: datetime) -> bool:
    return state["restricted_until"] is not None and state["restricted_until"] > now


def level(state: dict, a: dict, now: datetime) -> str:
    if is_restricted(state, now):
        return "restricted"
    return "warned" if state["points"] >= a["gizli_puan"]["uyari_esigi"] else "normal"


def score_sender(state: dict, points: float, clean: bool, a: dict, now: datetime) -> tuple[float, str | None]:
    """Returns (change, suggested_action). change is what the message did, before a restriction resets it."""
    g = a["gizli_puan"]
    before = state["points"]
    change = _apply(state, points, clean, g)
    if state["points"] >= g["susturma_esigi"]:
        state["restrictions"] += 1
        minutes = g["susturma_sureleri_dk"][min(state["restrictions"], len(g["susturma_sureleri_dk"])) - 1]
        state["restricted_until"] = now + timedelta(minutes=minutes)
        state["points"] = float(g["susturma_sonrasi_puan"])
        return change, "restrict_sender"
    if before < g["uyari_esigi"] <= state["points"]:
        return change, "warn_sender"
    return change, None


def score_relation(state: dict, points: float, clean: bool, a: dict) -> float:
    return _apply(state, points, clean, a["gizli_puan"])


def relation_blocked(state: dict | None, a: dict) -> bool:
    return bool(state) and state["points"] >= a["iliski"]["engel_esigi"]


def public(state: dict, a: dict, now: datetime) -> dict:
    """What moderators see from GET /v1/groups/{group}/users/{user} and /v1/relations/..."""
    recent = state["recent"]
    return {"points": state["points"], "level": level(state, a, now), "recent_clean": recent.count("1"),
            "recent_messages": len(recent), "restrictions": state["restrictions"],
            "restricted_until": state["restricted_until"].isoformat() if state["restricted_until"] else None,
            "messages": state["messages"]}
