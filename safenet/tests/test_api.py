"""HTTP layer: keys, validation, every endpoint (memory store, dev keys), and the documented schemas."""
import pytest

from safenet.api import schemas

KEY = {"X-API-Key": "dev-demo_sosyal"}
SCHOOL = {"X-API-Key": "dev-demo_okul"}
PDF_TEXT = "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."


def test_health_needs_no_key(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert {"arch", "machine_type", "nnpa", "pid", "models", "model_version", "store"} <= body.keys()
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


@pytest.mark.parametrize("text", ["see you tomorrow", "f*ck, I missed the bus", "you are an idiot", PDF_TEXT,
                                  'He told me "I will kill you tomorrow".', "I fed the fuck at the lake",
                                  "you dirty muslim"])
def test_every_kind_of_answer_matches_the_schema(client, text):
    for key in (KEY, SCHOOL):
        body = {"sender_id": "schema_a", "recipient_id": "schema_b", "group_id": "g", "message_id": f"m_{text[:9]}",
                "text": text}
        first, again = (client.post("/v1/check", headers=key, json=body).json() for _ in range(2))
        schemas.CheckResponse.model_validate(first)
        schemas.CheckResponse.model_validate(again)
        assert again["replayed"] and again["decision"] == first["decision"]


def test_reads_match_the_schema(client):
    client.post("/v1/check", headers=KEY, json={"sender_id": "r1", "recipient_id": "r2", "group_id": "7c",
                                                 "text": "you are an idiot"})
    schemas.BatchResponse.model_validate(client.post("/v1/check/batch", headers=KEY, json={"messages": [
        {"sender_id": "r1", "text": "hi"}, {"sender_id": "r1", "recipient_id": "r3", "text": "shut up"}]}).json())
    schemas.UserView.model_validate(client.get("/v1/groups/7c/users/r1", headers=KEY).json())
    schemas.RelationView.model_validate(client.get("/v1/relations/r1/r2", headers=KEY).json())
    schemas.Stats.model_validate(client.get("/v1/stats", headers=KEY).json())
    schemas.Stats.model_validate(client.get("/v1/groups/7c/stats", headers=KEY).json())
    schemas.Groups.model_validate(client.get("/v1/groups", headers=KEY).json())
    schemas.Error.model_validate(client.post("/v1/check", json={"sender_id": "x", "text": "hi"}).json())


def test_schema_files_are_up_to_date():
    """schemas/*.schema.json are what scripts/export_schemas.py writes from safenet/api/schemas.py."""
    from scripts import export_schemas
    for model in export_schemas.MODELS:
        path = export_schemas.ROOT / "schemas" / f"{model.__name__}.schema.json"
        assert path.read_text(encoding="utf-8") == export_schemas.rendered(model), f"run scripts/export_schemas.py"
