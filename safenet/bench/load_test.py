"""Load test for the SafeNet API: latency p50/p95/p99 and messages per second.

Standard library only, so it runs on the server or on a PC through the tunnel.

    python bench/load_test.py --key "$KEY" --seconds 30 --concurrency 16
    python bench/load_test.py --path /v1/moderate          # the older endpoint, no key

Each request gets a unique message_id, so no request is answered as a replay. Results are printed
and written to bench/results/<timestamp>.json. Do not run it while a model is training on the
server: there are only 3 vCPUs and both numbers would be wrong.
"""
import argparse
import http.client
import json
import os
import random
import socket
import statistics
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

TEXTS = [
    "see you tomorrow at school",
    "great match yesterday, well played",
    "can you send me the homework for monday",
    "you are such an idiot, nobody likes you",
    "yarın derste görüşürüz",
    "bu oyunu çok sevdim, tekrar oynayalım",
    "sen tam bir salaksın",
    "if you show up on friday I'll break your legs",
    "lol that was so funny",
    "kimse seni sevmiyor, git buradan",
    "my number is 0532 123 45 67 call me",
    "gg ez noob uninstall",
]


def payload(path: str, wid: int, i: int) -> dict:
    text = random.choice(TEXTS)
    if path.startswith("/v1/moderate"):
        return {"text": text, "user_id": f"bench_u{wid}"}
    return {
        "sender_id": f"bench_u{random.randint(1, 5000)}",
        "recipient_id": f"bench_u{random.randint(5001, 10000)}",
        "group_id": f"bench_g{random.randint(1, 50)}",
        "message_id": f"bench_{os.getpid()}_{wid}_{i}_{time.time_ns()}",
        "text": text,
    }


class Run:
    def __init__(self):
        self.lock = threading.Lock()
        self.client_ms: list[float] = []
        self.server_ms: list[float] = []
        self.statuses: Counter = Counter()


def connect(url):
    u = urlparse(url)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=10)
    conn.connect()
    # Without this, Nagle + delayed ACK add ~40 ms to every keep-alive request.
    conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return conn


def worker(args, wid: int, stop: float, run: Run) -> None:
    conn = None
    headers = {"content-type": "application/json"}
    if args.key:
        headers["X-API-Key"] = args.key
    client, server, statuses, i = [], [], Counter(), 0
    while time.perf_counter() < stop:
        body = json.dumps(payload(args.path, wid, i))
        t0 = time.perf_counter()
        try:
            conn = conn or connect(args.url)
            conn.request("POST", args.path, body=body.encode(), headers=headers)
            resp = conn.getresponse()
            data, status = resp.read(), resp.status
        except Exception as e:
            data, status = b"", type(e).__name__
            if conn:
                conn.close()
            conn = None
            time.sleep(0.05)
        client.append((time.perf_counter() - t0) * 1000)
        statuses[status] += 1
        if status == 200:
            try:
                ms = json.loads(data).get("latency_ms")
                if ms is not None:
                    server.append(float(ms))
            except ValueError:
                pass
        i += 1
    with run.lock:
        run.client_ms += client
        run.server_ms += server
        run.statuses.update(statuses)


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p * len(s)))], 3)


def health(url: str) -> dict:
    try:
        c = connect(url)
        c.request("GET", "/health")
        return json.loads(c.getresponse().read())
    except Exception as e:
        return {"error": str(e)}


def blast(args, seconds: float, concurrency: int) -> tuple[Run, float]:
    run = Run()
    start = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(args, w, start + seconds, run)) for w in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return run, time.perf_counter() - start


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.getenv("SAFENET_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--key", default=os.getenv("SAFENET_KEY"))
    ap.add_argument("--path", default="/v1/check")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--warmup", type=float, default=3)
    ap.add_argument("--label", default="", help="saved with the result, e.g. 'workers=2 pool=5'")
    args = ap.parse_args()

    h = health(args.url)
    print("health:", json.dumps(h, ensure_ascii=False))
    if args.warmup > 0:
        blast(args, args.warmup, min(4, args.concurrency))

    run, elapsed = blast(args, args.seconds, args.concurrency)
    ok = run.statuses.get(200, 0)
    lat = run.client_ms
    result = {
        "label": args.label,
        "url": args.url, "path": args.path,
        "concurrency": args.concurrency, "seconds": round(elapsed, 2),
        "requests": sum(run.statuses.values()), "ok": ok,
        "statuses": {str(k): v for k, v in run.statuses.items()},
        "msg_per_s": round(ok / elapsed, 1),
        "client_ms": {"p50": pct(lat, .50), "p95": pct(lat, .95), "p99": pct(lat, .99),
                      "mean": round(statistics.fmean(lat), 3) if lat else None},
        "server_ms": {"p50": pct(run.server_ms, .50), "p95": pct(run.server_ms, .95), "p99": pct(run.server_ms, .99)},
        "health": h,
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    (out / f"{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
