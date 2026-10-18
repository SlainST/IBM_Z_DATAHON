"""WhatsApp adapter: replays an exported chat ("Export chat", without media) through SafeNet and shows what each
recipient would have seen.

    SAFENET_KEY=... python client/whatsapp_chat.py chat.txt                 # through tunnel.sh on localhost:8000
    python client/whatsapp_chat.py chat.txt --only-flagged --url http://127.0.0.1:8000

A chat with two people is one-to-one: every message goes to the other person, so the recipient protection
(A -> B) and the x1.5 identity points apply. With more people it is a group chat: messages are scored for their
sender only. Names are turned into pseudonymous ids (wa_<hash>) before they leave this PC; message ids come from
the file and the line, so running the same file again gets the same decisions back ("replayed") and counts
nothing twice. --fresh scores it as new messages.

Android ("17/10/2026, 21:15 - Ali: hi") and iOS ("[17.10.26, 21:15:03] Ali: hi") exports are read; lines without
a timestamp continue the message above, system lines and "<Media omitted>" are skipped.
"""
import argparse
import hashlib
import os
import re
import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safenet_client import UNAVAILABLE, SafeNet  # noqa: E402

STAMP = (r"^\u200e?\[?(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),?\s+"
         r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?\s*(?:-\s+)?")
LINE = re.compile(STAMP + r"(?P<name>[^:]{1,60}?):\s(?P<text>.*)$")
SYSTEM = re.compile(STAMP)          # a stamp without "name: " ("Ali added Veli", "Messages are end-to-end encrypted")
SKIP = re.compile(r"^\u200e?(<media omitted>|<medya dahil edilmedi>|image omitted|video omitted|sticker omitted|"
                  r"audio omitted|gif omitted|this message was deleted|bu mesaj silindi)", re.I)


def parse(raw: str) -> list[dict]:
    """[{"name", "time", "text", "line"}]: one entry per message, multi-line messages joined."""
    messages = []
    for i, line in enumerate(raw.splitlines(), 1):
        m = LINE.match(line)
        if m:
            messages.append({"name": m["name"].strip(), "time": f"{m['date']} {m['time']}", "text": m["text"],
                             "line": i})
        elif SYSTEM.match(line):
            continue
        elif messages and line.strip():
            messages[-1]["text"] += "\n" + line
    return [m for m in messages if m["text"].strip() and not SKIP.match(m["text"].strip())]


def pseudonym(name: str) -> str:
    return "wa_" + hashlib.sha256(name.encode()).hexdigest()[:12]


def replay(sn: SafeNet, messages: list[dict], chat: str, fresh: bool):
    people = list(dict.fromkeys(m["name"] for m in messages))
    one_to_one = len(people) == 2
    group = "wa_" + hashlib.sha256(chat.encode()).hexdigest()[:10]
    for m in messages:
        recipient = next(p for p in people if p != m["name"]) if one_to_one else None
        message_id = uuid.uuid4().hex if fresh else f"{group}_{m['line']}"
        answer = sn.check(pseudonym(m["name"]), m["text"][:2000], recipient=pseudonym(recipient) if recipient else None,
                          group=group, message_id=message_id)
        yield m, recipient, answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("chat", type=Path, help="the exported .txt file")
    ap.add_argument("--url", default=os.getenv("SAFENET_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--only-flagged", action="store_true", help="print only messages not delivered as written")
    ap.add_argument("--fresh", action="store_true", help="new message ids: score the chat again from zero")
    args = ap.parse_args()
    key = os.getenv("SAFENET_KEY")
    if not key:
        sys.exit("set SAFENET_KEY to the platform's API key (it is never printed)")

    messages = parse(args.chat.read_text(encoding="utf-8-sig", errors="replace"))
    if not messages:
        sys.exit("no messages found: is this a WhatsApp export?")
    sn = SafeNet(args.url, key=key)
    decisions, senders = Counter(), {}
    for m, recipient, a in replay(sn, messages, args.chat.name, args.fresh):
        decisions[a["decision"]] += 1
        senders[m["name"]] = a.get("sender_standing", {}).get("level", senders.get(m["name"], "?"))
        if args.only_flagged and a["decision"] == "allow":
            continue
        shown = a["recipient_sees"] if a["decision"] in ("allow", "censor") else f"[{a['decision']}: {a['reason']}]"
        to = f" -> {recipient}" if recipient else ""
        print(f"{m['time']}  {m['name']}{to}: {shown}")
        if a["reason"] == UNAVAILABLE:
            print("   (SafeNet did not answer: the message is held)")
    print(f"\n{len(messages)} messages: " + ", ".join(f"{d} {n}" for d, n in decisions.most_common()))
    for name, level in senders.items():
        print(f"  {name}: {level}")


if __name__ == "__main__":
    main()
