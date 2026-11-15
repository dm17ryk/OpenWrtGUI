from __future__ import annotations

from pathlib import Path

import pytest
from bridgeenv import BridgeEnv, build


@pytest.fixture
async def bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BridgeEnv:
    return await build(tmp_path, monkeypatch)
