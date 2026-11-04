from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sshserver import SshServer, start_server


@pytest.fixture
async def ssh_server() -> AsyncIterator[SshServer]:
    srv = await start_server()
    yield srv
    srv.server.close()
    await srv.server.wait_closed()
