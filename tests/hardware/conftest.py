"""Fixtures for `pytest -m hardware`: an SSH connection to AP2 (192.168.1.2), nothing else.

uv run pytest -m hardware --router 192.168.1.2 --identity C:/Essence_SC/home/.ssh/id_rsa -v

`ap2` only reads. `ap2_luci` also makes the LuCI bridge's in-memory rpcd sessions and its SSH forward.
`ap2_rw` changes AP2 (and the test restores it); it runs only with --allow-writes --txctl-told:

uv run pytest -m hardware tests/hardware/test_ap2_wifi.py --router 192.168.1.2 --identity <key> \
    --allow-writes --txctl-told -v
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from ro_transport import LuciSessionTransport, ReadOnlyTransport, write_refusal

from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key

AP2 = "192.168.1.2"


async def _connect(request: pytest.FixtureRequest, tmp_path: Path) -> SshTransport:
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
    return await SshTransport.connect(router, 22, "root", host_keys=host_keys, key_paths=[identity])


@pytest.fixture
async def ap2(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[ReadOnlyTransport]:
    transport = await _connect(request, tmp_path)
    try:
        yield ReadOnlyTransport(transport)
    finally:
        await transport.close()


@pytest.fixture
async def ap2_luci(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[LuciSessionTransport]:
    transport = await _connect(request, tmp_path)
    try:
        yield LuciSessionTransport(transport)
    finally:
        await transport.close()


@pytest.fixture
async def ap2_rw(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[SshTransport]:
    refusal = write_refusal(
        request.config.getoption("--router"),
        allow_writes=request.config.getoption("--allow-writes"),
        txctl_told=request.config.getoption("--txctl-told"),
    )
    if refusal:
        pytest.skip(refusal)
    transport = await _connect(request, tmp_path)
    try:
        yield transport
    finally:
        await transport.close()
