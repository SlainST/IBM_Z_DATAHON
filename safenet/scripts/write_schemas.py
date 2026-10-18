"""Writes schemas/*.schema.json, the JSON Schema of every request and answer body (docs/API.md), from the classes
in safenet/api/schemas.py. Run it after changing them: tests/test_api.py fails while the files are out of date.

    python scripts/write_schemas.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safenet.api.schemas import SCHEMAS, SCHEMAS_DIR, schema_text  # noqa: E402

SCHEMAS_DIR.mkdir(exist_ok=True)
for name, model in SCHEMAS.items():
    (SCHEMAS_DIR / f"{name}.schema.json").write_text(schema_text(model), encoding="utf-8")
    print(f"schemas/{name}.schema.json")
