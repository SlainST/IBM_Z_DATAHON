"""FastAPI app: every endpoint of docs/API.md. Run: uvicorn safenet.api:app (deploy/linuxone/run_api.sh)."""
import logging
import os
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .. import config, ibmz, settings
from ..engine import points as pts
from ..engine.moderator import Moderator
from ..state.store import StoreUnavailable, make_store, utcnow
from .auth import KEYS, require_platform
from .schemas import (BatchRequest, BatchResponse, CheckRequest, CheckResponse, Error, Groups, RelationView, Stats,
                      UserView)

log = logging.getLogger("safenet")
BUCKETS_MS = (0.5, 1, 2, 5, 10, 25, 50, 100, 250, 1000)
KEYED = {401: {"model": Error, "description": "X-API-Key missing or unknown"},
         403: {"model": Error, "description": "the key's platform has no [platform.<id>] block in ayarlar.toml"}}
WRITES = {**KEYED, 503: {"model": Error, "description": "points store unavailable: retry with the same message_id"}}


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.decisions: Counter = Counter()
        self.buckets: Counter = Counter()
        self.count, self.total_ms = 0, 0.0

    def record(self, platform: str, decision: str, ms: float):
        with self.lock:
            self.decisions[(platform, decision)] += 1
            self.count += 1
            self.total_ms += ms
            self.buckets[next((b for b in BUCKETS_MS if ms <= b), "inf")] += 1

    def snapshot(self) -> dict:
        with self.lock:
            per = {}
            for (p, d), n in self.decisions.items():
                per.setdefault(p, {})[d] = n
            return {"pid": os.getpid(), "messages": self.count, "decisions": per,
                    "latency_ms_buckets": {str(b): self.buckets.get(b, 0) for b in (*BUCKETS_MS, "inf")},
                    "latency_ms_mean": round(self.total_ms / self.count, 3) if self.count else None}


state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if config.DEV_KEYS:
        log.warning("SAFENET_DEV_KEYS=1: dev-<platform> keys are accepted. Never on a server others can reach.")
    store = make_store(config.DATABASE_URL, config.DB_POOL_SIZE, config.DB_TIMEOUT_S)
    store.open()
    for p in settings.platforms():
        settings.for_platform(p)          # a wrong value in ayarlar.toml stops the start here
    state.update(store=store, moderator=Moderator(store), metrics=Metrics())
    yield
    store.close()


app = FastAPI(title="SafeNet", version="1.0.0", lifespan=lifespan,
              description="Message security API on IBM LinuxONE. See docs/API.md.")


@app.exception_handler(StoreUnavailable)
async def _unavailable(_: Request, exc: StoreUnavailable):
    log.warning("store unavailable: %s", exc)
    return JSONResponse({"detail": "points store unavailable, retry with the same message_id"}, status_code=503,
                        headers={"Retry-After": "1"})


def _check(platform: str, req: CheckRequest) -> dict:
    t0 = time.perf_counter()
    answer = state["moderator"].check(platform, req.model_dump())
    ms = round((time.perf_counter() - t0) * 1000, 3)
    answer["latency_ms"] = ms
    state["metrics"].record(platform, answer["decision"], ms)
    return answer


@app.post("/v1/check", responses={200: {"model": CheckResponse}, **WRITES})
def check(req: CheckRequest, platform: str = Depends(require_platform)) -> dict:
    return _check(platform, req)


@app.post("/v1/check/batch", responses={200: {"model": BatchResponse}, **WRITES})
def check_batch(req: BatchRequest, platform: str = Depends(require_platform)) -> dict:
    return {"results": [_check(platform, m) for m in req.messages]}


@app.get("/v1/groups/{group}/users/{user}", responses={200: {"model": UserView}, **KEYED})
def user_points(group: str, user: str, platform: str = Depends(require_platform)) -> dict:
    a = settings.for_platform(platform)
    return {"key": f"{platform}/{group}/{user}", **pts.public(state["store"].user(platform, group, user), a, utcnow())}


@app.get("/v1/relations/{sender}/{recipient}", responses={200: {"model": RelationView}, **KEYED})
def relation(sender: str, recipient: str, platform: str = Depends(require_platform)) -> dict:
    a = settings.for_platform(platform)
    r = state["store"].relation(platform, sender, recipient)
    out = pts.public(r, a, utcnow())
    return {"platform": platform, "sender": sender, "recipient": recipient, "points": out["points"],
            "blocked": pts.relation_blocked(r, a), "recent_clean": out["recent_clean"],
            "recent_messages": out["recent_messages"], "messages": out["messages"]}


@app.get("/v1/stats", responses={200: {"model": Stats}, **KEYED})
def stats(platform: str = Depends(require_platform)) -> dict:
    return {"platform": platform, **state["store"].stats(platform)}


@app.get("/v1/groups/{group}/stats", responses={200: {"model": Stats}, **KEYED})
def group_stats(group: str, platform: str = Depends(require_platform)) -> dict:
    return {"platform": platform, "group": group, **state["store"].stats(platform, group)}


@app.get("/v1/groups", responses={200: {"model": Groups}, **KEYED})
def groups(limit: int = Query(50, ge=1, le=500), platform: str = Depends(require_platform)) -> dict:
    return {"platform": platform, "groups": state["store"].groups(platform, limit)}


@app.get("/v1/settings", responses=KEYED)
def platform_settings(platform: str = Depends(require_platform)) -> dict:
    return {"platform": platform, **settings.public(platform)}


@app.get("/health")
def health():
    store = state["store"]
    writable = store.writable()
    workers = os.getenv("SAFENET_WORKERS", "1")
    models = state["moderator"].models
    body = {"status": "ok" if writable else "degraded", **ibmz.info(), "pid": os.getpid(),
            "workers": int(workers) if workers.isdigit() else workers, "models": models.status(),
            "model_version": models.version(),
            "store": {"kind": store.kind, "writable": writable}, "platforms": list(settings.platforms()),
            "api_keys": len(KEYS), "dev_keys": config.DEV_KEYS}
    return JSONResponse(body, status_code=200 if writable else 503)


@app.get("/metrics")
def metrics() -> dict:
    return state["metrics"].snapshot()


@app.get("/metrics/prometheus", response_class=PlainTextResponse)
def metrics_prometheus() -> str:
    snap, pid = state["metrics"].snapshot(), os.getpid()
    lines = ["# TYPE safenet_messages_total counter"]
    for p, ds in snap["decisions"].items():
        for d, n in ds.items():
            lines.append(f'safenet_messages_total{{platform="{p}",decision="{d}",pid="{pid}"}} {n}')
    lines.append("# TYPE safenet_latency_ms histogram")
    running = 0
    for b, n in snap["latency_ms_buckets"].items():
        running += n
        le = "+Inf" if b == "inf" else b
        lines.append(f'safenet_latency_ms_bucket{{le="{le}",pid="{pid}"}} {running}')
    return "\n".join(lines) + "\n"
