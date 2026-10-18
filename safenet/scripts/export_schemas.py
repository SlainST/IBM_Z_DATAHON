"""Write the JSON Schema of every request and response body to schemas/: python scripts/export_schemas.py

The bodies are the pydantic models in safenet/api/schemas.py. tests/test_api.py checks every kind of answer
against them and that these files are up to date, so an adapter in any language can validate against them.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safenet.api import schemas  # noqa: E402

MODELS = [schemas.CheckRequest, schemas.BatchRequest, schemas.CheckResponse, schemas.BatchResponse,
          schemas.UserView, schemas.RelationView, schemas.Stats, schemas.Groups, schemas.Error]


def rendered(model) -> str:
    return json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n"


def main():
    out = ROOT / "schemas"
    out.mkdir(exist_ok=True)
    for model in MODELS:
        path = out / f"{model.__name__}.schema.json"
        path.write_text(rendered(model), encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
