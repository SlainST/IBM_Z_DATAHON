"""A small chat app for the LAN, to show SafeNet: phones and laptops on the same Wi-Fi chat one-to-one, and every
message goes through the live SafeNet API before the other person sees it.

    python chat_lan.py --keys-file C:\\path\\api_keys.env                 # demo_sosyal, port 8700
    python chat_lan.py --keys-file ... --platform demo_okul                # the school profile
    -> open the printed http://<this PC's address>:8700 on each device (same Wi-Fi), pick a name, pick a person

The app plays the platform: it keeps the conversation in memory while it runs (SafeNet itself stores no text) and
shows each side what SafeNet decided. The recipient gets the message, its starred version, or nothing (held for a
moderator, blocked); the sender sees why and their hidden points. The keys stay in this process. Standard library.
"""
import argparse
import json
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "client"))
sys.path.insert(0, str(HERE))
from safenet_client import SafeNet, SafeNetError  # noqa: E402
from demo_web import PLATFORMS, keys, tunnel  # noqa: E402

GROUP = "lan"
PAGE = HERE / "chat_lan.html"
ONLINE_S = 30          # a user who has not polled for this long is not listed


class Room:
    def __init__(self, sn: SafeNet, platform: str):
        self.sn, self.platform = sn, platform
        self.users, self.events, self.lock = {}, [], threading.Lock()

    def join(self, name: str) -> dict:
        name = " ".join(str(name).split())[:24] or "guest"
        uid = f"lan_{secrets.token_hex(3)}"
        with self.lock:
            self.users[uid] = {"name": name, "seen": time.time()}
        return {"id": uid, "name": name, "platform": self.platform}

    def send(self, uid: str, to: str, text: str) -> dict:
        r = self.sn.check(uid, text, recipient=to, group=GROUP)
        try:
            view = self.sn.user(GROUP, uid)
        except (SafeNetError, OSError):
            view = None
        d, standing = r["decision"], r.get("sender_standing") or {}
        event = {"from": uid, "to": to, "text": text, "decision": d, "reason": r.get("reason"),
                 "category": r.get("category"), "harm": r.get("harm"), "words": r.get("key_words") or [],
                 "delivered": r.get("recipient_sees") if d in ("allow", "censor") else None,
                 "change": standing.get("change"), "level": standing.get("level"),
                 "restricted_until": standing.get("restricted_until"), "suggested": r.get("suggested_action"),
                 "relation_blocked": (r.get("relation") or {}).get("blocked"),
                 "points": view["points"] if view else None, "ms": r.get("latency_ms"), "time": time.time()}
        with self.lock:
            event["seq"] = len(self.events) + 1
            self.events.append(event)
        return event

    def poll(self, uid: str, since: int) -> dict:
        """The people online and the events this user may see: their own messages with SafeNet's answer, and the
        messages to them as delivered (never the original of a starred or stopped message)."""
        now = time.time()
        with self.lock:
            if uid in self.users:
                self.users[uid]["seen"] = now
            people = [{"id": k, "name": v["name"]} for k, v in self.users.items() if k != uid and now - v["seen"] < ONLINE_S]
            names = {k: v["name"] for k, v in self.users.items()}
            mine = []
            for e in self.events[max(0, since):]:
                if e["from"] == uid:
                    mine.append(e)
                elif e["to"] == uid and e["delivered"] is not None:
                    mine.append({k: e[k] for k in ("seq", "from", "to", "delivered", "decision", "time")})
            return {"people": people, "names": names, "events": mine, "last": len(self.events)}


def handler(room: Room, machine: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code: int, body, kind: str = "application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self.reply(200, PAGE.read_bytes(), "text/html")
            if url.path == "/api/info":
                return self.reply(200, {"platform": room.platform, "machine": machine})
            if url.path == "/api/poll":
                q = parse_qs(url.query)
                return self.reply(200, room.poll(q.get("id", [""])[0], int(q.get("since", ["0"])[0] or 0)))
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
            if self.path == "/api/join":
                return self.reply(200, room.join(body.get("name", "")))
            if self.path == "/api/send":
                uid, to, text = body.get("id"), body.get("to"), str(body.get("text", "")).strip()[:2000]
                if uid not in room.users or to not in room.users or not text:
                    return self.reply(400, {"error": "join first, pick a person, write something"})
                try:
                    return self.reply(200, room.send(uid, to, text))
                except (SafeNetError, OSError) as e:
                    return self.reply(502, {"error": f"SafeNet: {e}"})
            self.reply(404, {"error": "not found"})

    return Handler


def lan_address() -> str:
    """This PC's address on the LAN (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keys-file", type=Path, help="a file with SAFENET_KEY_DEMO_SOSYAL=... lines")
    ap.add_argument("--platform", choices=PLATFORMS, default="demo_sosyal")
    ap.add_argument("--url", help="SafeNet's URL (default: an SSH tunnel on --tunnel-port)")
    ap.add_argument("--tunnel-port", type=int, default=8012)
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0: every device on the LAN")
    args = ap.parse_args()

    key = keys(args.keys_file).get(args.platform)
    if not key:
        sys.exit(f"No key for {args.platform}: pass --keys-file or set SAFENET_KEY_{args.platform.upper()}.")
    proc = None if args.url else tunnel(args.tunnel_port)
    sn = SafeNet(args.url or f"http://127.0.0.1:{args.tunnel_port}", key=key, timeout=5)
    try:
        h = sn.health()
        machine = {k: h.get(k) for k in ("arch", "generation", "nnpa", "workers")} | {
            "trained": (h.get("model_version") or {}).get("trained")}
    except OSError:
        machine = {}
    server = ThreadingHTTPServer((args.host, args.port), handler(Room(sn, args.platform), machine))
    print(f"SafeNet chat ({args.platform}) on http://{lan_address()}:{args.port}  - open it on every device on this "
          "Wi-Fi (allow Python through the firewall if Windows asks). Ctrl+C stops.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
