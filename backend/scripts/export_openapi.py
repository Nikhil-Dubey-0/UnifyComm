"""Write the OpenAPI schema to frontend/openapi.json (ARCHITECTURE §10).

uv run python -m scripts.export_openapi
"""

import json

from app.config import REPO_ROOT
from app.main import create_app

OUTPUT = REPO_ROOT / "frontend" / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
