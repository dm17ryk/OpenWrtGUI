from __future__ import annotations

from pathlib import Path

import pytest
from netenv import NetEnv, build


@pytest.fixture
async def net(tmp_path: Path) -> NetEnv:
    return await build(tmp_path)
