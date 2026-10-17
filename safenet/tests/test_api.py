"""HTTP layer: keys, validation, every endpoint (memory store, dev keys)."""
KEY = {"X-API-Key": "dev-demo_sosyal"}


def test_health_needs_no_key(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert {"arch", "machine_type", "nnpa", "pid", "models", "store"} <= body.keys()
    assert body["store"] == {"kind": "memory", "writable": True}


def test_keys(client):
    body = {"sender_id": "u1", "text": "hi"}
    assert client.post("/v1/check", json=body).status_code == 401
    assert client.post("/v1/check", json=body, headers={"X-API-Key": "nope"}).status_code == 401
    assert client.post("/v1/check", json=body, headers={"X-API-Key": "dev-not_a_platform"}).status_code == 403
    assert client.post("/v1/check", json=body, headers=KEY).status_code == 200


def test_validation(client):
    assert client.post("/v1/check", json={"sender_id": "u1", "text": "hi", "profile": "x"}, headers=KEY).status_code == 422
    assert client.post("/v1/check", json={"sender_id": "u/1", "text": "hi"}, headers=KEY).status_code == 422
    assert client.post("/v1/check", json={"sender_id": "u1", "text": ""}, headers=KEY).status_code == 422
    assert client.post("/v1/check", json={"sender_id": "u1", "text": "x" * 2001}, headers=KEY).status_code == 422


def test_check_answer_shape(client):
    r = client.post("/v1/check", headers=KEY, json={
        "sender_id": "u_4821", "recipient_id": "u_1093", "group_id": "t_77", "message_id": "m_000123",
        "text": "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."}).json()
    assert r["key"] == "demo_sosyal/t_77/u_4821" and r["decision"] == "block"
    assert r["latency_ms"] >= 0 and r["replayed"] is False


def test_batch_in_order(client):
    r = client.post("/v1/check/batch", headers=KEY, json={"messages": [
        {"sender_id": "b1", "text": "see you tomorrow"}, {"sender_id": "b1", "text": "you are an idiot"}]})
    assert [x["decision"] for x in r.json()["results"]] == ["allow", "censor"]


def test_moderator_endpoints(client):
    client.post("/v1/check", headers=KEY, json={"sender_id": "s1", "recipient_id": "s2", "group_id": "7b",
                                                 "text": "you are an idiot"})
    u = client.get("/v1/groups/7b/users/s1", headers=KEY).json()
    assert u["key"] == "demo_sosyal/7b/s1" and u["points"] == 10.0 and u["messages"] == 1
    rel = client.get("/v1/relations/s1/s2", headers=KEY).json()
    assert rel["points"] == 10.0 and rel["blocked"] is False
    nobody = client.get("/v1/groups/7b/users/nobody", headers=KEY).json()
    assert nobody["points"] == 0.0
    stats = client.get("/v1/stats", headers=KEY).json()
    assert stats["messages"] >= 1 and "decisions" in stats
    assert client.get("/v1/groups/7b/stats", headers=KEY).json()["group"] == "7b"
    assert any(g["group"] == "7b" for g in client.get("/v1/groups?limit=10", headers=KEY).json()["groups"])
    assert client.get("/v1/settings", headers=KEY).json()["secim"]["profil"] == "sosyal_medya"
    assert client.get("/metrics").json()["messages"] >= 1
