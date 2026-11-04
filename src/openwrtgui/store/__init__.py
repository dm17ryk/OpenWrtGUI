"""Files the app keeps in its data folder."""

from __future__ import annotations

import os
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    """Write a whole file so a crash never leaves it half written."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
