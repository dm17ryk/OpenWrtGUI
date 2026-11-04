"""Write build/openapi.json (sorted) for the frontend's type generation (npm run gen:api).

uv run python tools/dump_openapi.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from openwrtgui.app import create_app
from openwrtgui.context import build_context
from openwrtgui.paths import DataDir
from openwrtgui.store import keys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    keys.restrict_to_user = lambda path: None  # throwaway key in a temp folder
    with tempfile.TemporaryDirectory() as tmp:
        ctx = build_context(
            DataDir.at(Path(tmp)),
            token="x",
            port=1,
            simulator=ROOT / "tests" / "fixtures" / "sim",
            web_dir=None,
        )
        schema = create_app(ctx).openapi()
    out = ROOT / "build" / "openapi.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
