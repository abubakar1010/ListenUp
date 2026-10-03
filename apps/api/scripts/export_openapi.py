"""Write the API's OpenAPI schema to apps/web/src/api/openapi.json.

The web client generates its TypeScript types from that file (`pnpm api:generate`);
CI fails if either file is out of date.
"""

import json
from pathlib import Path

from listenup.main import app

OUT = Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "openapi.json"

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {OUT}")
