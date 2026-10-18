"""The demo: SafeNet deciding what a recipient sees, live from IBM LinuxONE, through the real API.

    python demo.py --keys-file C:\\path\\api_keys.env      # lines like SAFENET_KEY_DEMO_SOSYAL=...
    SAFENET_KEY_DEMO_SOSYAL=... SAFENET_KEY_DEMO_OKUL=... python demo.py --url http://127.0.0.1:8000

Run deploy/linuxone/tunnel.sh first (or run it on the server). Five parts:
1. The machine: /health a few times: s390x, the IBM Z generation, NNPA, the models, and different worker pids.
2. The same messages on a social app (demo_sosyal) and a school app (demo_okul), from the team's evaluation set:
   all four decisions, and the school app holding what the social app only censors.
3. The PDF example: a threat in the second sentence blocks the whole message and adds +48 hidden points.
4. Recipient protection: after A threatens B, A's next friendly message to B is blocked; to C it is delivered.
5. What the platform's moderators see: the sender's points, the A -> B relation, the platform's counters.
Every run uses new ids, so it can be repeated; its messages count in the stats under the group "demo".
Keys come from the environment or the keys file and are never printed.
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "client"))
from safenet_client import SafeNet, SafeNetError  # noqa: E402

PLATFORMS = ("demo_sosyal", "demo_okul")
MESSAGES = [  # (text, what it shows)
    ("see you tomorrow at practice", "an ordinary message"),
    ("f*ck, I missed the bus again", "swearing at nobody: starred, no harm"),
    ("I fed the fuck at the lake", "a likely typo for 'duck': starred, no points"),
    ("I'm a proud Muslim and I fast during Ramadan", "an identity named, not attacked"),
    ("you are an idiot", "an insult: yellow"),
    ('He told me "I will kill you tomorrow".', "a reported threat: a moderator looks"),
    ("nobody likes you, just leave the group chat", "bullying with no listed word"),
    ("send me a pic of you in your underwear", "a sexual request"),
]
PDF_TEXT = "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."
COLOURS = {"allow": "32", "censor": "33", "hold": "35", "block": "31"}


def keys(path: Path | None) -> dict[str, str]:
    found = {}
    if path:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.strip().partition("=")
            if name and not name.startswith("#") and value:
                found[name.strip()] = value.strip().strip("'\"")
    found.update({k: v for k, v in os.environ.items() if k.startswith("SAFENET_KEY_")})
    return {p: found[f"SAFENET_KEY_{p.upper()}"] for p in PLATFORMS if f"SAFENET_KEY_{p.upper()}" in found}


def paint(decision: str) -> str:
    if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
        return f"{decision:6}"
    return f"\033[{COLOURS.get(decision, '0')}m{decision:6}\033[0m"


def title(text: str):
    print(f"\n== {text} " + "=" * max(0, 96 - len(text)))


def machine(sn: SafeNet):
    title("1. The machine")
    pids, h = set(), {}
    for _ in range(8):
        h = sn.health()
        pids.add(h.get("pid"))
    print(f"   arch {h.get('arch')}, IBM Z {h.get('generation') or '-'} (machine type {h.get('machine_type') or '-'}), "
          f"NNPA {'yes' if h.get('nnpa') else 'no'}")
    version = h.get("model_version") or {}
    print(f"   models {h.get('models')}" + (f", trained {version.get('trained')} on {version.get('machine')}"
                                            if version else ""))
    print(f"   store {h.get('store')}, workers {h.get('workers')}, pids answering: {sorted(p for p in pids if p)}")


def decisions(clients: dict[str, SafeNet], run: str):
    title("2. Same message, two platforms: what the recipient sees")
    print(f"   {'message':46} " + "  ".join(f"{p:24}" for p in clients))
    for i, (text, why) in enumerate(MESSAGES):
        cells = []
        for p, sn in clients.items():
            a = sn.check(f"{run}_s{i}", text, recipient=f"{run}_r{i}", group="demo")
            cells.append(f"{paint(a['decision'])} {str(a['reason'] or ''):17}")
        print(f"   {text[:46]:46} " + "  ".join(cells) + f"  {why}")


def pdf_example(sn: SafeNet, run: str):
    title("3. The PDF example (demo_sosyal)")
    a = sn.check(f"{run}_A", PDF_TEXT, recipient=f"{run}_B", group="demo")
    print(f"   {PDF_TEXT}")
    print(f"   -> {paint(a['decision'])} reason {a['reason']}, category {a['category']}, harm {a['harm']} "
          f"(without its listed words {a['wordless_harm']})")
    print(f"   worst sentence: {a['worst_sentence']}")
    print(f"   key words {a['key_words']}, disguised {[h['written'] for h in a['hidden_profanity']]}")
    s = a["sender_standing"]
    print(f"   sender: {s['change']:+.0f} points, now {s['level']}; suggested action: {a['suggested_action']}; "
          f"A -> B blocked: {a['relation']['blocked']}")


def protection(sn: SafeNet, run: str):
    title("4. Recipient protection")
    to_b = sn.check(f"{run}_A", "sorry about earlier, see you tomorrow", recipient=f"{run}_B", group="demo")
    to_c = sn.check(f"{run}_A", "sorry about earlier, see you tomorrow", recipient=f"{run}_C", group="demo")
    print(f"   A -> B: {paint(to_b['decision'])} {to_b['reason']}   (B no longer receives A's messages)")
    print(f"   A -> C: {paint(to_c['decision'])} {to_c['reason'] or ''}   (everyone else still does)")


def moderators(sn: SafeNet, run: str):
    title("5. What moderators see")
    u = sn.user("demo", f"{run}_A")
    r = sn.relation(f"{run}_A", f"{run}_B")
    s = sn.stats()
    print(f"   sender A in group demo: {u['points']} points, {u['level']}, {u['messages']} messages")
    print(f"   A -> B: {r['points']} points, blocked {r['blocked']}")
    print(f"   platform: {s['messages']} messages, {s['harmful_rate']:.1%} harmful, decisions {s['decisions']}, "
          f"categories {s['categories']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=os.getenv("SAFENET_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--keys-file", type=Path, help="a file with SAFENET_KEY_DEMO_SOSYAL=... lines")
    args = ap.parse_args()
    found = keys(args.keys_file)
    if "demo_sosyal" not in found:
        sys.exit("no key for demo_sosyal: set SAFENET_KEY_DEMO_SOSYAL or pass --keys-file")
    clients = {p: SafeNet(args.url, key=k, timeout=5) for p, k in found.items()}
    run = f"demo_{time.strftime('%H%M%S')}"
    try:
        machine(clients["demo_sosyal"])
        decisions(clients, run)
        pdf_example(clients["demo_sosyal"], run)
        protection(clients["demo_sosyal"], run)
        moderators(clients["demo_sosyal"], run)
    except SafeNetError as e:
        sys.exit(f"SafeNet refused: {e}")
    except ConnectionError as e:
        sys.exit(f"{e}\nIs the API running and the tunnel open (deploy/linuxone/tunnel.sh)?")


if __name__ == "__main__":
    main()
