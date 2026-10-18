"""A chat page for the video and the jury: Ali writes to Ayşe and every message goes through the live SafeNet API.

    python demo_web.py --keys-file C:\\path\\api_keys.env      # opens an SSH tunnel to the server ("safenet")
    python demo_web.py --url http://127.0.0.1:8000 --no-tunnel  # the API is already reachable
    -> open http://127.0.0.1:8600

The page shows what the recipient sees (delivered, starred, held for a moderator or blocked), why, the category, the
words that decided, and the sender's hidden points and the Ali -> Ayşe relation after each message. Every message is a
real POST /v1/check on the platform picked on the page (demo_sosyal, demo_okul, demo_oyun), in the group "video";
"New conversation" starts with new user ids. The keys stay in this process: the page never sees them.
Standard library only (plus client/safenet_client.py).
"""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "client"))
from safenet_client import SafeNet, SafeNetError  # noqa: E402

PLATFORMS = ("demo_sosyal", "demo_okul", "demo_oyun")
GROUP = "video"
PAGE = HERE / "demo_web.html"


def keys(path: Path | None) -> dict[str, str]:
    """SAFENET_KEY_DEMO_SOSYAL=... lines from the file, then the environment (as demo.py)."""
    found = {}
    if path:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, _, value = line.strip().partition("=")
            if name and not name.startswith("#") and value:
                found[name.strip()] = value.strip().strip("'\"")
    found.update({k: v for k, v in os.environ.items() if k.startswith("SAFENET_KEY_")})
    return {p: found[f"SAFENET_KEY_{p.upper()}"] for p in PLATFORMS if f"SAFENET_KEY_{p.upper()}" in found}


class Chat:
    def __init__(self, clients: dict[str, SafeNet]):
        self.clients = clients
        self.new()

    def new(self):
        tag = secrets.token_hex(3)
        self.sender, self.recipient = f"ali_{tag}", f"ayse_{tag}"

    def send(self, platform: str, text: str) -> dict:
        c = self.clients[platform]
        r = c.check(self.sender, text, recipient=self.recipient, group=GROUP)
        for name, call in (("user_view", lambda: c.user(GROUP, self.sender)),
                           ("relation_view", lambda: c.relation(self.sender, self.recipient))):
            try:
                r[name] = call()
            except (SafeNetError, OSError):
                r[name] = None
        return r


def handler(chat: Chat):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code: int, body, kind: str = "application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                if self.path in ("/", "/index.html"):
                    return self.reply(200, PAGE.read_bytes(), "text/html")
                if self.path == "/api/health":
                    return self.reply(200, next(iter(chat.clients.values())).health() | {"platforms": list(chat.clients)})
                if self.path.startswith("/api/settings/") and self.path.rsplit("/", 1)[1] in chat.clients:
                    return self.reply(200, chat.clients[self.path.rsplit("/", 1)[1]].settings())
                self.reply(404, {"error": "not found"})
            except (SafeNetError, OSError) as e:
                self.reply(502, {"error": f"SafeNet: {e}"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
            if self.path == "/api/new":
                chat.new()
                return self.reply(200, {"sender": chat.sender, "recipient": chat.recipient})
            if self.path == "/api/check":
                text = str(body.get("text", "")).strip()[:2000]
                if body.get("platform") not in chat.clients or not text:
                    return self.reply(400, {"error": "platform and text needed"})
                return self.reply(200, chat.send(body["platform"], text))
            self.reply(404, {"error": "not found"})

    return Handler


def tunnel(port: int) -> subprocess.Popen:
    """ssh -N -L port:127.0.0.1:8000 safenet, until the port answers."""
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
    sys.exit("The SSH tunnel did not come up. Check `ssh safenet`, or pass --url ... --no-tunnel.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keys-file", type=Path, help="a file with SAFENET_KEY_DEMO_SOSYAL=... lines")
    ap.add_argument("--url", help="SafeNet's URL (default: an SSH tunnel on --tunnel-port)")
    ap.add_argument("--no-tunnel", action="store_true", help="do not open the SSH tunnel")
    ap.add_argument("--tunnel-port", type=int, default=8010)
    ap.add_argument("--port", type=int, default=8600)
    args = ap.parse_args()

    found = keys(args.keys_file)
    if not found:
        sys.exit("No keys: pass --keys-file or set SAFENET_KEY_DEMO_SOSYAL / _OKUL / _OYUN.")
    proc = None if args.no_tunnel or args.url else tunnel(args.tunnel_port)
    url = args.url or f"http://127.0.0.1:{args.tunnel_port}"
    chat = Chat({p: SafeNet(url, key=k, timeout=5) for p, k in found.items()})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(chat))
    print(f"SafeNet demo on http://127.0.0.1:{args.port}  (API {url}, platforms {', '.join(found)}; Ctrl+C stops)")
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
