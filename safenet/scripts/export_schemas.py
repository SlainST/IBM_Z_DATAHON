"""Write the request JSON Schemas from the API's own pydantic models: python scripts/export_schemas.py

schemas/check_request.schema.json and batch_request.schema.json come from safenet/api/schemas.py, so they
always match what the API accepts (tests/test_schemas.py fails when they are stale). The response schemas
are written by hand from docs/API.md and checked against real answers by the same test.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safenet.api.schemas import BatchRequest, CheckRequest  # noqa: E402

OUT = ROOT / "schemas"
GENERATED = {"check_request.schema.json": CheckRequest, "batch_request.schema.json": BatchRequest}


def render(model) -> str:
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **model.model_json_schema()}
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, model in GENERATED.items():
        (OUT / name).write_text(render(model), encoding="utf-8")
        print(f"wrote schemas/{name}")
