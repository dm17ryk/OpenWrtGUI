from __future__ import annotations

from pathlib import Path

import pytest
from fwenv import FwEnv, build


@pytest.fixture
async def env(tmp_path: Path) -> FwEnv:
    return await build(tmp_path)
