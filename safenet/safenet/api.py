"""SafeNet HTTP + WebSocket API."""

import threading
from collections import Counter, deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config
from .classifier import ToxicityClassifier
from .lexicon import Lexicon
from .moderator import Moderator, Result

ProfileName = Literal["under13", "teen", "adult"]


class ModerateRequest(BaseModel):
    text: str = Field(max_length=config.MAX_TEXT_LEN)
    user_id: str | None = None
    profile: ProfileName = config.DEFAULT_PROFILE


class BatchRequest(BaseModel):
    items: list[ModerateRequest] = Field(max_length=500)


class Metrics:
    def __init__(self):
        self.actions: Counter[str] = Counter()
        self.latencies: deque[float] = deque(maxlen=10_000)
        self._lock = threading.Lock()

    def record(self, r: Result):
        with self._lock:
            self.actions[r.action.value] += 1
            self.latencies.append(r.latency_ms)

    def snapshot(self) -> dict:
        with self._lock:
            lat = sorted(self.latencies)
            actions = dict(self.actions)
        pct = lambda p: round(lat[min(len(lat) - 1, int(p * len(lat)))], 3) if lat else None
        return {"messages": sum(actions.values()), "actions": actions,
                "latency_ms": {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99)}}


state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["moderator"] = Moderator(Lexicon.from_dir(config.LEXICON_DIR), ToxicityClassifier(config.MODEL_PATH))
    state["metrics"] = Metrics()
    state["rooms"] = {}
    yield


app = FastAPI(title="SafeNet", version="0.1.0", lifespan=lifespan)


def run(req: ModerateRequest) -> dict:
    result = state["moderator"].moderate(req.text, req.profile, req.user_id)
    state["metrics"].record(result)
    return asdict(result)


@app.post("/v1/moderate")
def moderate(req: ModerateRequest) -> dict:
    return run(req)


@app.post("/v1/moderate/batch")
def moderate_batch(req: BatchRequest) -> dict:
    return {"results": [run(item) for item in req.items]}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ml_model": state["moderator"].classifier.available}


@app.get("/metrics")
def metrics() -> dict:
    return state["metrics"].snapshot()


@app.websocket("/v1/chat/{room}")
async def chat(ws: WebSocket, room: str):
    """Demo chat room: every message is moderated before anyone else sees it.

    Client sends {"user_id": "...", "text": "...", "profile": "teen"}.
    Sender gets the full moderation result; everyone else gets only the filtered text.
    """
    await ws.accept()
    members: set[WebSocket] = state["rooms"].setdefault(room, set())
    members.add(ws)
    try:
        while True:
            req = ModerateRequest(**await ws.receive_json())
            result = run(req)
            await ws.send_json({"type": "result", **result})
            if result["action"] != "block":
                msg = {"type": "message", "user_id": req.user_id, "text": result["text"]}
                for other in list(members - {ws}):
                    await other.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        members.discard(ws)


@app.get("/")
def demo_page():
    return FileResponse(Path(__file__).parent / "static" / "demo.html")
