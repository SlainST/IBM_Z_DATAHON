"""The 1:1 chat simulation through the engine: are the right senders restricted, and does a bullied recipient stop
getting the bully's messages? (SafeNet_Model_Tasarimi.pdf, section 9.)

    python simulate.py                                 # every demo platform: per user type, then the targets
    python simulate.py --platform demo_okul --users    # also one line per user
    python simulate.py --csv veri/simulation_users.csv # one row per platform and user

Input: veri/sohbetler/birebir.csv and kullanicilar.csv, written by sohbet_simulasyonu.py: 40 conversations
(normal, bullying, fights, escalating, repentant, friendly swearing, disguised swearing) between 80 users whose
behaviour is known, so the hidden points can be checked: trolls, bullies, escalating, disguising and
swearing-with-friends users should be restricted (no banter discount, PDF decision); normal users, victims and
the repentant should not. The messages come from the test split, so the models never saw them.

Each conversation is replayed in order on its own clock (zaman_sn): a 5-minute restriction ends 5 simulated
minutes later. Memory store only: nothing on the server or in Postgres is touched. The models in models/ are
used (the fallback rules without them).
"""
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import kimlik

from safenet.engine.moderator import Moderator
from safenet.ml.models import Models
from safenet.state.store import MemoryStore

ROOT = Path(__file__).resolve().parent
CHATS = ROOT / "veri" / "sohbetler" / "birebir.csv"
USERS = ROOT / "veri" / "sohbetler" / "kullanicilar.csv"
PLATFORMS = ("demo_sosyal", "demo_okul", "demo_oyun")
GROUP = "simulation"
START = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
# PDF section 9: at least 90 % of the users who should be restricted are, at most 5 % of the others, and in every
# bullying conversation the victim stops receiving the bully's messages.
SHOULD_AT_LEAST, SHOULD_NOT_AT_MOST = 0.90, 0.05
# Who should be restricted: the user types of sohbet_simulasyonu.py, and anyone who sent a threat (the data's label)
# or a slur (kimlik.py's list). Normal users and victims get 2 % harmful messages at random and a repentant user
# starts with two, sometimes a threat or a slur; one such message restricts its sender by the design's points
# (red 25 + targeted identity 30 x 1.5 in 1:1). The user types alone are reported too (persona_*).
_SLUR = re.compile(r"\b(?:" + "|".join(kimlik.HAKARETLER.values()) + r")\b")


def severe(m) -> bool:
    return m.zararli == 1 and (m.tur == "tehdit" or bool(_SLUR.search(str(m.metin).lower())))


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    chats = pd.read_csv(CHATS).sort_values(["sohbet_id", "sira"])
    users = pd.read_csv(USERS)
    return chats, users[users["kanal"] == "birebir"]


def replay(chats: pd.DataFrame, users: pd.DataFrame, platform: str, models: Models) -> tuple[pd.DataFrame, list]:
    """Returns (one row per user, one row per bullying conversation)."""
    store = MemoryStore()
    store.open()
    mod = Moderator(store, models=models)
    seen = {u: {"blocked": 0, "warned": False, "protected_at": None, "harmful_sent": False, "first_restriction": None,
                "severe": False}
            for u in users["gonderen"]}
    bullies = set(users.loc[users["kullanici_tipi"] == "zorba", "gonderen"])
    exposure = {}                 # bully -> harmful messages the victim still got before the protection began
    for m in chats.itertuples():
        r = mod.check(platform, {"sender_id": m.gonderen, "recipient_id": m.alici, "group_id": GROUP,
                                 "message_id": f"{m.sohbet_id}_{m.sira}", "text": m.metin},
                      now=START + timedelta(seconds=float(m.zaman_sn)))
        u = seen[m.gonderen]
        u["harmful_sent"] |= m.zararli == 1
        u["severe"] |= severe(m)
        if r["suggested_action"] == "restrict_sender" and u["first_restriction"] is None:
            u["first_restriction"] = "after a harmful message" if u["harmful_sent"] else "harmless messages only"
        u["blocked"] += r["decision"] == "block"
        u["warned"] |= r["sender_standing"]["level"] != "normal"
        if m.gonderen in bullies:
            protected = (r["relation"] or {}).get("blocked") or r["sender_standing"]["level"] == "restricted"
            if protected and u["protected_at"] is None:
                u["protected_at"] = int(m.sira)
            if u["protected_at"] is None and m.zararli == 1 and r["decision"] in ("allow", "censor"):
                exposure[m.gonderen] = exposure.get(m.gonderen, 0) + 1
    rows = []
    for u in users.itertuples():
        state = store.user(platform, GROUP, u.gonderen)
        rows.append({"platform": platform, "user": u.gonderen, "conversation": u.sohbet_id, "type": u.kullanici_tipi,
                     "should_restrict": bool(u.susturulmali) or seen[u.gonderen]["severe"],
                     "persona_should": bool(u.susturulmali), "messages": int(u.mesaj_sayisi),
                     "harmful": int(u.zararli_mesaj), "restricted": state["restrictions"] > 0,
                     "restrictions": state["restrictions"], "warned": seen[u.gonderen]["warned"],
                     "first_restriction": seen[u.gonderen]["first_restriction"],
                     "blocked": seen[u.gonderen]["blocked"], "final_points": state["points"]})
    bullying = [{"conversation": u.sohbet_id, "bully": u.gonderen,
                 "protected": seen[u.gonderen]["protected_at"] is not None,
                 "protected_at_message": seen[u.gonderen]["protected_at"],
                 "harmful_delivered_before": exposure.get(u.gonderen, 0)}
                for u in users[users["kullanici_tipi"] == "zorba"].itertuples()]
    return pd.DataFrame(rows), bullying


def summary(users: pd.DataFrame, bullying: list) -> dict:
    should, should_not = users[users["should_restrict"]], users[~users["should_restrict"]]
    persona, persona_not = users[users["persona_should"]], users[~users["persona_should"]]
    return {
        "persona_restricted_of_should": round(float(persona["restricted"].mean()), 3),
        "persona_restricted_of_should_not": round(float(persona_not["restricted"].mean()), 3),
        "users": len(users),
        "restricted_of_should": round(float(should["restricted"].mean()), 3),
        "restricted_of_should_not": round(float(should_not["restricted"].mean()), 3),
        # The simulation draws its 2 % harmful messages for normal users and victims at random, some of them racist
        # slurs: restricting their sender is right. Wrongful are the restrictions earned by harmless messages alone.
        "restricted_of_should_not_without_a_harmful_message": round(float(
            (should_not["first_restriction"] == "harmless messages only").mean()), 3),
        "bullying_conversations_protected": f"{sum(b['protected'] for b in bullying)} of {len(bullying)}",
        "bullying_all_protected": all(b["protected"] for b in bullying),
        "harmful_delivered_to_victims_before_protection": sum(b["harmful_delivered_before"] for b in bullying),
        "targets_met": bool(should["restricted"].mean() >= SHOULD_AT_LEAST
                            and should_not["restricted"].mean() <= SHOULD_NOT_AT_MOST
                            and all(b["protected"] for b in bullying)),
        "per_type": {t: {"users": len(g), "restricted": round(float(g["restricted"].mean()), 3),
                         "warned": round(float(g["warned"].mean()), 3),
                         "mean_final_points": round(float(g["final_points"].mean()), 1)}
                     for t, g in users.groupby("type")},
        "bullying": bullying,
    }


def run(models: Models | None = None, platforms=PLATFORMS) -> dict:
    """Every platform: {platform: summary}. measure.py calls this."""
    models = models or Models()
    chats, users = load()
    out = {}
    for p in platforms:
        rows, bullying = replay(chats, users, p, models)
        out[p] = summary(rows, bullying) | {"_rows": rows}
    return out


def _print(platform: str, s: dict, show_users: bool):
    rows = s["_rows"]
    print(f"\n{platform}: {s['users']} users")
    print(f"  {'type':10} {'should':>7} {'users':>6} {'restricted':>11} {'warned':>7} {'points':>7}")
    for t, v in s["per_type"].items():
        should = bool(rows.loc[rows["type"] == t, "should_restrict"].iloc[0])
        print(f"  {t:10} {'yes' if should else 'no':>7} {v['users']:>6} {v['restricted']:>10.0%} {v['warned']:>7.0%}"
              f" {v['mean_final_points']:>7.1f}")
    ok = lambda b: "OK " if b else "NO "  # noqa: E731
    print(f"  {ok(s['restricted_of_should'] >= SHOULD_AT_LEAST)}restricted, of those who should be: "
          f"{s['restricted_of_should']:.0%} (target >= {SHOULD_AT_LEAST:.0%})")
    print(f"  {ok(s['restricted_of_should_not'] <= SHOULD_NOT_AT_MOST)}restricted, of the others: "
          f"{s['restricted_of_should_not']:.0%} (target <= {SHOULD_NOT_AT_MOST:.0%}); by harmless messages alone: "
          f"{s['restricted_of_should_not_without_a_harmful_message']:.0%}")
    print(f"  {ok(s['bullying_all_protected'])}bullying conversations where the victim stops getting the bully's "
          f"messages: {s['bullying_conversations_protected']}; harmful messages that reached a victim before: "
          f"{s['harmful_delivered_to_victims_before_protection']}")
    if show_users:
        for r in rows.sort_values(["type", "user"]).itertuples():
            print(f"    {r.user:9} {r.type:10} should={'yes' if r.should_restrict else 'no ':3} "
                  f"restricted={r.restrictions} warned={'yes' if r.warned else 'no '} blocked={r.blocked:>2}/"
                  f"{r.messages:<3} harmful={r.harmful:>2} points={r.final_points}"
                  + (f"  (first restriction: {r.first_restriction})" if r.first_restriction else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--platform", choices=PLATFORMS, help="only this platform")
    ap.add_argument("--users", action="store_true", help="one line per user")
    ap.add_argument("--csv", type=Path, help="write one row per platform and user")
    args = ap.parse_args()

    models = Models()
    print(f"models: {models.status()}")
    results = run(models, [args.platform] if args.platform else PLATFORMS)
    for p, s in results.items():
        _print(p, s, args.users)
    if args.csv:
        pd.concat([s["_rows"] for s in results.values()]).to_csv(args.csv, index=False, encoding="utf-8")
        print(f"\n-> {args.csv}")


if __name__ == "__main__":
    main()
