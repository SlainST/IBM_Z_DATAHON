import os
import uuid

import pytest

from safenet import config
from safenet.engine.moderator import Moderator
from safenet.state.store import MemoryStore, PostgresStore

PG_URL = os.getenv("SAFENET_TEST_DATABASE_URL", "")


@pytest.fixture(params=["memory"] + (["postgres"] if PG_URL else []))
def store(request):
    if request.param == "memory":
        s = MemoryStore()
    else:
        s = PostgresStore(PG_URL, 4, 5)
    s.open()
    yield s
    s.close()


@pytest.fixture
def mod(store):
    return Moderator(store)


@pytest.fixture
def uid():
    """Unique ids per test so Postgres tests don't see each other's points."""
    tag = uuid.uuid4().hex[:8]
    return lambda name: f"{name}_{tag}"


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(config, "DEV_KEYS", True)
    monkeypatch.setattr(config, "DATABASE_URL", "")
    from safenet.api import app
    with TestClient(app) as c:
        yield c
