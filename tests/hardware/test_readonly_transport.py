"""The hardware tests' transport wrapper: every probe passes it, and writes never reach the router.

These run in CI on the recorded AP2 output (no hardware marker).
"""

from __future__ import annotations

import pytest
from ro_transport import LuciSessionTransport, ReadOnlyTransport, write_refusal

from openwrtgui.luci_bridge.session import create_command, destroy_command, grant_commands, set_command
from openwrtgui.probe.describe import describe_router
from openwrtgui.probe.status import read_status
from openwrtgui.transport.base import Forwarder, LocalForward
from openwrtgui.transport.fake import ReplayTransport


async def test_probes_pass_the_read_only_wrapper(ap2_transport: ReplayTransport) -> None:
    ro = ReadOnlyTransport(ap2_transport)
    described = await describe_router(ro)
    status = await read_status(ro)
    assert described.identity.board_name == "dlink,dwr-921-c3-uboot"
    assert status.interfaces
    assert len(ro.commands) >= 8


async def test_wrapper_refuses_writes_before_they_run(ap2_transport: ReplayTransport) -> None:
    ro = ReadOnlyTransport(ap2_transport)
    with pytest.raises(AssertionError, match="not read-only"):
        await ro.run("uci set wireless.radio0.disabled=1")
    with pytest.raises(AssertionError, match="stdin"):
        await ro.run_stdin("passwd root", "x\nx\n")
    with pytest.raises(AssertionError, match="shell"):
        await ro.open_shell(80, 24)
    assert ro.commands == []


def test_writes_need_ap2_and_both_flags() -> None:
    assert write_refusal("192.168.1.2", allow_writes=True, txctl_told=True) is None
    assert "--allow-writes" in str(write_refusal("192.168.1.2", allow_writes=False, txctl_told=True))
    assert "--txctl-told" in str(write_refusal("192.168.1.2", allow_writes=True, txctl_told=False))
    # --allow-other never unlocks writes on another router
    assert "AP2 (192.168.1.2) only" in str(write_refusal("192.168.1.1", allow_writes=True, txctl_told=True))


class _Forwarding(ReplayTransport):
    async def forward_local(self, remote_host: str, remote_port: int) -> LocalForward:
        async def close() -> None:
            return None

        return LocalForward(50080, close)


async def test_luci_session_wrapper_allows_session_calls_and_the_forward(
    ap2_transport: ReplayTransport,
) -> None:
    inner = _Forwarding({}, ap2_transport.state)
    t = LuciSessionTransport(inner)
    acl = {"luci-base": {"read": {"ubus": {"luci": ["getFeatures"]}}}}
    for command in [
        create_command(),
        *grant_commands("s1", ["luci-base"], acl, "read"),
        set_command("s1", "t"),
        destroy_command("s1"),
        'ubus call session list \'{"ubus_rpc_session":"s1"}\'',
        "uci show",
    ]:
        await t.run(command)
    assert isinstance(t, Forwarder) and (await t.forward_local("127.0.0.1", 80)).port == 50080
    with pytest.raises(AssertionError, match="not read-only"):
        await t.run("uci set wireless.radio0.disabled=1")
    with pytest.raises(AssertionError, match="not read-only"):
        await t.run("ubus call session grant '{}'; uci commit")
    assert t.commands[-1] == "uci show"
