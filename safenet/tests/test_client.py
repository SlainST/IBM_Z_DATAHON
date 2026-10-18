"""client/: the Python client, the WhatsApp and YouTube adapters and demo.py, against the real API served by
uvicorn in a thread (memory store, dev keys, fallback rules)."""
import socket
import threading
import time

import pytest

from safenet import config


@pytest.fixture(scope="module")
def api_url():
    import uvicorn
    from safenet.api import app
    patch = pytest.MonkeyPatch()
    patch.setattr(config, "DEV_KEYS", True)
    patch.setattr(config, "DATABASE_URL", "")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    patch.undo()


@pytest.fixture
def sn(api_url):
    from client.safenet_client import SafeNet
    return SafeNet(api_url, key="dev-demo_sosyal")


def test_check_and_the_moderator_calls(sn):
    a = sn.check("c1", "you are an idiot", recipient="c2", group="cg")
    assert (a["decision"], a["reason"]) == ("censor", "harmful") and a["message_id"]
    assert sn.check("c1", "x", message_id=a["message_id"])["replayed"]
    assert sn.user("cg", "c1")["points"] == 10.0 and sn.relation("c1", "c2")["points"] == 10.0
    assert sn.stats()["messages"] >= 1 and sn.stats("cg")["group"] == "cg"
    assert any(g["group"] == "cg" for g in sn.groups()) and sn.settings()["platform"] == "demo_sosyal"
    assert sn.health()["store"]["kind"] == "memory"
    results = sn.check_batch([{"sender_id": "c3", "text": "hi"}, {"sender_id": "c3", "text": "kys"}])
    assert [r["decision"] for r in results] == ["allow", "block"]


def test_ids_with_slashes_are_refused_not_misrouted(sn):
    from client.safenet_client import SafeNetError
    with pytest.raises(SafeNetError) as e:
        sn.check("a/b", "hi")
    assert e.value.status == 422


def test_a_wrong_key_raises(api_url):
    from client.safenet_client import SafeNet, SafeNetError
    with pytest.raises(SafeNetError) as e:
        SafeNet(api_url, key="nope").check("u", "hi")
    assert e.value.status == 401


def test_holds_when_safenet_cannot_answer():
    from client.safenet_client import UNAVAILABLE, SafeNet
    a = SafeNet("http://127.0.0.1:9", key="k", timeout=0.2, retries=1).check("u", "hi", recipient="v")
    assert (a["decision"], a["reason"], a["recipient_sees"]) == ("hold", UNAVAILABLE, None)


ANDROID = """17/10/2026, 21:14 - Messages and calls are end-to-end encrypted. No one outside of this chat can read them.
17/10/2026, 21:15 - Ali: see you tomorrow at practice
17/10/2026, 21:16 - Veli: f*ck, I missed the bus again
and now it's raining
17/10/2026, 21:17 - Veli: <Media omitted>
17/10/2026, 21:18 - Ali: Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs.
17/10/2026, 21:19 - Ali: sorry, see you tomorrow"""
IOS = "[17.10.26, 21:15:03] Ali: hi there\n[17.10.26, 21:16:10] Veli: hello: how are you?"


def test_whatsapp_exports_are_parsed():
    from client.whatsapp_chat import parse
    android = parse(ANDROID)
    assert [m["name"] for m in android] == ["Ali", "Veli", "Ali", "Ali"]
    assert android[1]["text"] == "f*ck, I missed the bus again\nand now it's raining"
    assert [(m["name"], m["text"]) for m in parse(IOS)] == [("Ali", "hi there"), ("Veli", "hello: how are you?")]


def test_whatsapp_chat_through_the_api(sn):
    from client.whatsapp_chat import parse, replay
    answers = [(m["name"], recipient, a["decision"], a["reason"])
               for m, recipient, a in replay(sn, parse(ANDROID), "test_chat.txt", fresh=True)]
    assert answers == [("Ali", "Veli", "allow", None), ("Veli", "Ali", "censor", "profanity"),
                       ("Ali", "Veli", "block", "threat"), ("Ali", "Veli", "block", "relation_blocked")]


def test_youtube_api_json_is_read():
    from client.youtube_comments import from_api
    page = {"items": [{"id": "t1", "snippet": {"topLevelComment": {"id": "c1", "snippet": {
        "authorDisplayName": "Ann", "textOriginal": "great video"}}},
        "replies": {"comments": [{"id": "c2", "snippet": {"authorDisplayName": "Bob", "textOriginal": "kys"}}]}}]}
    assert from_api(page) == [{"id": "c1", "author": "Ann", "text": "great video", "reply_to": None},
                              {"id": "c2", "author": "Bob", "text": "kys", "reply_to": "Ann"}]


def test_demo_runs_end_to_end(api_url, monkeypatch, capsys):
    import demo
    monkeypatch.setenv("SAFENET_KEY_DEMO_SOSYAL", "dev-demo_sosyal")
    monkeypatch.setenv("SAFENET_KEY_DEMO_OKUL", "dev-demo_okul")
    monkeypatch.setattr("sys.argv", ["demo.py", "--url", api_url])
    demo.main()
    out = capsys.readouterr().out
    assert "1. The machine" in out and "5. What moderators see" in out
    assert "relation_blocked" in out and "dev-demo" not in out
