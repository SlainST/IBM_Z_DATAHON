"""schemas/: the request schemas match the API's pydantic models, and real answers match the response schemas."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import export_schemas  # noqa: E402

import degerlendir  # noqa: E402

KEY = {"X-API-Key": "dev-demo_sosyal"}


def load(name):
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def validator(name):
    jsonschema = pytest.importorskip("jsonschema")
    from referencing import Registry, Resource   # comes with jsonschema
    registry = Registry().with_resources(
        (p.name, Resource.from_contents(json.loads(p.read_text(encoding="utf-8"))))
        for p in (ROOT / "schemas").glob("*.schema.json"))
    return jsonschema.Draft202012Validator(load(name), registry=registry)


@pytest.mark.parametrize("name", export_schemas.GENERATED)
def test_request_schemas_are_current(name):
    assert (ROOT / "schemas" / name).read_text(encoding="utf-8") == export_schemas.render(export_schemas.GENERATED[name]), \
        "run python scripts/export_schemas.py"


def test_every_evaluation_answer_matches_the_schema(mod, uid):
    v = validator("check_response.schema.json")
    for row in degerlendir.oku():
        for platform in degerlendir.PLATFORMLAR:
            answer = mod.check(platform, {"sender_id": uid("s"), "recipient_id": uid("r"), "text": row["metin"]})
            v.validate(json.loads(json.dumps(answer)))


def test_http_answers_match_the_schemas(client):
    jsonschema = pytest.importorskip("jsonschema")
    body = {"sender_id": "u_4821", "recipient_id": "u_1093", "group_id": "t_77", "message_id": "m_s1",
            "text": "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."}
    jsonschema.validate(body, load("check_request.schema.json"))
    validator("check_response.schema.json").validate(client.post("/v1/check", headers=KEY, json=body).json())
    batch = {"messages": [{"sender_id": "b1", "text": "see you tomorrow"}, {"sender_id": "b1", "text": "you idiot"}]}
    jsonschema.validate(batch, load("batch_request.schema.json"))
    validator("batch_response.schema.json").validate(client.post("/v1/check/batch", headers=KEY, json=batch).json())
