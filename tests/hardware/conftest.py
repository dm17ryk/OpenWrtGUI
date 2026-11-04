"""Fixtures for `pytest -m hardware`: a read-only SSH connection to AP2 (192.168.1.2), nothing else.

uv run pytest -m hardware --router 192.168.1.2 --identity C:/Essence_SC/home/.ssh/id_rsa -v
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from ro_transport import ReadOnlyTransport

from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key

AP2 = "192.168.1.2"


@pytest.fixture
async def ap2(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[ReadOnlyTransport]:
    router: str = request.config.getoption("--router")
    identity: Path | None = request.config.getoption("--identity")
    if router != AP2 and not request.config.getoption("--allow-other"):
        pytest.fail(f"hardware tests run on AP2 ({AP2}) only; --allow-other to use {router}", pytrace=False)
    if identity is None:
        pytest.skip("pass --identity <private key> that the router accepts")
    state = BenchGuard(GuardWatchList()).check_local()
    if state.live:
        pytest.skip("Bench Guard sees a run: " + "; ".join(r.text for r in state.reasons))
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    info = await fetch_host_key(router)
    print(f"\n{router} host key {info.type} {info.fingerprint} (pinned for this run only)")
    host_keys.pin(router, 22, info)
    transport = await SshTransport.connect(router, 22, "root", host_keys=host_keys, key_paths=[identity])
    try:
        yield ReadOnlyTransport(transport)
    finally:
        await transport.close()
