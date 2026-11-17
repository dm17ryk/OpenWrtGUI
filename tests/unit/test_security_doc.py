"""SECURITY.md lists every folder the app keeps in its data folder, and its known limits (v1.0b1 D11)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")


def test_every_data_folder_is_in_the_table() -> None:
    paths_py = (ROOT / "src" / "openwrtgui" / "paths.py").read_text(encoding="utf-8")
    named = set(re.findall(r'root / "([a-z_.-]+)"', paths_py)) | {"backups", "exports"}
    for name in named:  # a folder is written `name\`, a file `name`
        assert re.search(rf"`{re.escape(name)}\\?`", SECURITY), f"{name} is missing from SECURITY.md's table"


def test_known_limits_name_each_open_item() -> None:
    limits = SECURITY.split("## Known limits", 1)[1]
    for item in ("Authenticode", "rotat", "HTTPS", "flash", "Bench Guard", "AP1", "GitHub Action"):
        assert item in limits, item
