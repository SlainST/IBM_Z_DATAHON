"""SafeNet on Telegram: a bot that sends every message through the live SafeNet API, in a group or in a private chat.

Setup in Telegram, two minutes:
  1. @BotFather: /newbot -> the bot's token. Then /setprivacy -> your bot -> Disable (so it sees every group message).
  2. Private test: open the bot and write to it; it answers with what the recipient would see.
     Group: add the bot to a group and make it an admin that can delete messages and restrict members.

    python client/telegram_bot.py --token <token> --keys-file C:\\path\\api_keys.env             # demo_sosyal
    python client/telegram_bot.py --token <token> --keys-file ... --platform demo_okul              # school profile

The bot opens an SSH tunnel to the server itself (or give --url). The sender is the Telegram user, the group is
the chat, and a reply is a message to the person replied to (one-to-one: recipient protection). In a group:
  allow    the message stays
  censor   with listed words: deleted and posted again starred ("Ali: f***, I missed the bus"); else a warning reply
  hold     deleted: "held for a moderator";  block  deleted: "blocked (threat)"
  warn_sender: a warning; restrict_sender: the user is muted in the group until the restriction ends.
Only ids go to SafeNet (tg<user id>, tg<chat id>), not names; the token and the keys stay in this process.
Standard library only.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safenet_client import SafeNet  # noqa: E402

PLATFORMS = ("demo_sosyal", "demo_okul", "demo_oyun")
REASON = {"threat": "threat", "hate": "identity attack", "very_harmful": "very harmful", "spam": "spam",
          "profanity_ratio": "mostly profanity", "quoted_threat": "reported threat", "harmful": "harmful",
          "profanity": "profanity", "sender_restricted": "sender restricted",
          "relation_blocked": "this person no longer receives your messages"}
ICON = {"allow": "✅", "censor": "✳️", "hold": "⏳", "block": "⛔"}


class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, **params):
        req = urllib.request.Request(self.base + method, data=json.dumps(params).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = json.loads(e.read() or b"{}")
        if not body.get("ok"):
            raise RuntimeError(f"{method}: {body.get('description', 'failed')}")
        return body["result"]


def keys(path: Path | None) -> dict[str, str]:
    found = {}
    if path:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.strip().partition("=")
            if name and not name.startswith("#") and value:
                found[name.strip()] = value.strip().strip("'\"")
    found.update({k: v for k, v in os.environ.items() if k.startswith("SAFENET_KEY_")})
    return {p: found[f"SAFENET_KEY_{p.upper()}"] for p in PLATFORMS if f"SAFENET_KEY_{p.upper()}" in found}


def verdict(r: dict) -> str:
    """The answer in a private chat: what the recipient would see and why."""
    d = r["decision"]
    lines = [f"{ICON[d]} {d.upper()}" + (f": {REASON.get(r.get('reason'), r.get('reason'))}" if r.get("reason") else "")]
    if d == "censor":
        lines.append(f"the recipient sees: {r.get('recipient_sees')}")
    elif d in ("hold", "block"):
        lines.append("the recipient sees nothing" + (" until a moderator looks" if d == "hold" else ""))
    if r.get("category"):
        lines.append(f"category: {r['category']}, harm {r.get('harm', 0):.2f}")
    if r.get("key_words"):
        lines.append("words: " + ", ".join(r["key_words"]))
    if r.get("possible_typos"):
        lines.append(f"did you mean \"{r['possible_typos'][0]['suggestion']}\"? (no points)")
    s = r.get("sender_standing") or {}
    lines.append(f"hidden points {s.get('change', 0):+g}, level {s.get('level', '?')}"
                 + (f", {r.get('latency_ms', 0):.1f} ms on IBM LinuxONE" if r.get("latency_ms") is not None else ""))
    if r.get("suggested_action") == "warn_sender":
        lines.append("→ the platform would warn you now")
    if r.get("suggested_action") == "restrict_sender":
        lines.append("→ you would be restricted now: your messages reach no one for a while")
    return "\n".join(lines)


def handle(tg: Telegram, sn: SafeNet, msg: dict, log=print):
    text = msg.get("text") or msg.get("caption")
    user, chat = msg.get("from") or {}, msg["chat"]
    if not text or user.get("is_bot") or text.startswith("/"):
        return None
    name = user.get("first_name") or user.get("username") or "someone"
    to = (msg.get("reply_to_message") or {}).get("from") or {}
    recipient = f"tg{to['id']}" if to.get("id") and not to.get("is_bot") and to["id"] != user.get("id") else None
    if chat["type"] == "private":
        recipient = f"tg_test_{chat['id']}"           # a private test: the bot stands for the person you write to
    r = sn.check(f"tg{user['id']}", text, recipient=recipient, group=f"tg{abs(chat['id'])}",
                 message_id=f"tg{chat['id']}_{msg['message_id']}")
    log(f"[{datetime.now():%H:%M:%S}] {chat.get('title') or 'private'} | {name}: {text[:60]!r} -> {r['decision']} "
        f"{r.get('reason') or ''} {r.get('category') or ''}")
    if r.get("reason") == "safenet_unavailable":
        log("   SafeNet unreachable: the message is left alone")
        return r

    def act(method, **params):
        try:
            return tg.call(method, **params)
        except (RuntimeError, OSError) as e:
            log(f"   Telegram: {e}")

    cid, mid = chat["id"], msg["message_id"]
    if chat["type"] == "private":
        act("sendMessage", chat_id=cid, reply_to_message_id=mid, text=verdict(r))
        return r
    d, why = r["decision"], REASON.get(r.get("reason"), r.get("reason") or "")
    if r.get("category") and r["category"] != r.get("reason"):
        why += f", {r['category']}"
    if d == "censor" and r.get("recipient_sees") and r["recipient_sees"] != text:
        act("deleteMessage", chat_id=cid, message_id=mid)
        act("sendMessage", chat_id=cid, text=f"{name}: {r['recipient_sees']}")
    elif d == "censor":
        act("sendMessage", chat_id=cid, reply_to_message_id=mid, text=f"⚠️ {name}, careful: {why}")
    elif d in ("hold", "block"):
        act("deleteMessage", chat_id=cid, message_id=mid)
        act("sendMessage", chat_id=cid, text=f"{ICON[d]} {name}'s message was "
            + ("held for a moderator" if d == "hold" else "blocked") + f" ({why}).")
    if (r.get("suggested_action") == "warn_sender" and d in ("hold", "block")
            and (r.get("sender_standing") or {}).get("level") == "warned"):
        act("sendMessage", chat_id=cid, text=f"⚠️ {name}, this is a warning from SafeNet: keep it respectful.")
    until = (r.get("sender_standing") or {}).get("restricted_until")
    if r.get("suggested_action") == "restrict_sender" and until:
        end = datetime.fromisoformat(until)
        act("restrictChatMember", chat_id=cid, user_id=user["id"], permissions={"can_send_messages": False},
            until_date=int(end.timestamp()))
        act("sendMessage", chat_id=cid, text=f"🔇 {name} is muted until {end.astimezone():%H:%M}.")
    return r


def tunnel(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(["ssh", "-N", "-L", f"{port}:127.0.0.1:8000", "safenet"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return proc
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.25)
    proc.terminate()
    sys.exit("The SSH tunnel did not come up. Check `ssh safenet`, or pass --url.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--token", default=os.getenv("TELEGRAM_TOKEN"), help="the bot's token from @BotFather")
    ap.add_argument("--keys-file", type=Path, help="a file with SAFENET_KEY_DEMO_SOSYAL=... lines")
    ap.add_argument("--platform", choices=PLATFORMS, default="demo_sosyal")
    ap.add_argument("--url", help="SafeNet's URL (default: an SSH tunnel on --tunnel-port)")
    ap.add_argument("--tunnel-port", type=int, default=8011)
    args = ap.parse_args()
    if not args.token:
        sys.exit("Give the bot's token: --token or TELEGRAM_TOKEN (from @BotFather).")
    key = keys(args.keys_file).get(args.platform)
    if not key:
        sys.exit(f"No key for {args.platform}: pass --keys-file or set SAFENET_KEY_{args.platform.upper()}.")
    proc = None if args.url else tunnel(args.tunnel_port)
    sn = SafeNet(args.url or f"http://127.0.0.1:{args.tunnel_port}", key=key, timeout=5)
    tg = Telegram(args.token)
    me = tg.call("getMe")
    print(f"@{me['username']} sends every message through SafeNet ({args.platform}). Write to it, or add it to a group "
          "as an admin (delete messages, restrict members). Ctrl+C stops.")
    started, offset = time.time(), None
    try:
        while True:
            try:
                updates = tg.call("getUpdates", timeout=25, offset=offset, allowed_updates=["message"])
            except (RuntimeError, OSError) as e:
                print(f"Telegram: {e}; retrying")
                time.sleep(3)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message")
                if msg and msg.get("date", 0) >= started - 5:      # nothing sent before the bot started
                    handle(tg, sn, msg)
    except KeyboardInterrupt:
        pass
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
