"""One shared monitor interface per router (v0.7 plan D11): counted holders, re-added after a reload."""

from __future__ import annotations

import pytest

from openwrtgui.transport.base import CommandResult
from openwrtgui.wifi.monitor import DEL, INFO, MONITOR, MonitorLeases, add_command

PHY = "phy0"


class _Router:
    """What the leases send, and whether owgmon0 exists on the 'router'."""

    def __init__(self, *, add_fails: bool = False, del_fails: int = 0) -> None:
        self.sent: list[tuple[str, bool]] = []
        self.exists = False
        self.add_fails = add_fails
        self.del_fails = del_fails  # how many removals the router refuses, keeping the interface

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        assert command == INFO  # the only read the leases make on their own
        if self.exists:
            return CommandResult(command, "Interface owgmon0\n", "", 0)
        return CommandResult(command, "", "No such device (-19)", 237)

    async def audited(self, command: str, require_guard: bool) -> CommandResult:
        self.sent.append((command, require_guard))
        if "interface add" in command:
            if self.add_fails:
                return CommandResult(command, "", "command failed: Device or resource busy (-16)", 240)
            self.exists = True
        elif command == DEL:
            if not self.exists:
                return CommandResult(command, "", "command failed: No such device (-19)", 237)
            if self.del_fails:
                self.del_fails -= 1
                return CommandResult(command, "", "command failed: Device or resource busy (-16)", 240)
            self.exists = False
        return CommandResult(command, "", "", 0)


async def test_first_holder_adds_last_removes() -> None:
    router, leases = _Router(), MonitorLeases()
    async with leases.hold("ap2", "capture", PHY, router, router.audited):  # type: ignore[arg-type]
        async with leases.hold("ap2", "beacon check", PHY, router, router.audited):  # type: ignore[arg-type]
            assert leases.holders("ap2") == ("capture", "beacon check")
        assert router.exists and leases.holders("ap2") == ("capture",)
    assert not router.exists and leases.holders("ap2") == ()
    assert router.sent == [(add_command(PHY, clear_leftover=True), True), (DEL, False)]


async def test_monitor_added_again_after_a_reload() -> None:
    router, leases = _Router(), MonitorLeases()
    async with leases.hold("ap2", "frames", PHY, router, router.audited):  # type: ignore[arg-type]
        router.exists = False  # a Wi-Fi reload removed every interface on the phy
        assert await leases.ensure("ap2", PHY, router, router.audited) is True  # type: ignore[arg-type]
        assert router.exists
        assert await leases.ensure("ap2", PHY, router, router.audited) is False  # type: ignore[arg-type]
    assert router.sent[1] == (add_command(PHY, clear_leftover=False), True)
    assert "del 2>/dev/null" not in router.sent[1][0]


async def test_last_holder_removes_it_during_a_run() -> None:
    router, leases = _Router(), MonitorLeases()
    async with leases.hold("ap2", "frames", PHY, router, router.audited):  # type: ignore[arg-type]
        pass
    assert router.sent[-1] == (DEL, False)  # cleanup goes even while Bench Guard is live


async def test_failed_add_leaves_no_holder() -> None:
    router, leases = _Router(add_fails=True), MonitorLeases()
    with pytest.raises(ValueError, match="Device or resource busy"):
        async with leases.hold("ap2", "frames", PHY, router, router.audited):  # type: ignore[arg-type]
            pass
    assert leases.holders("ap2") == ()
    router.add_fails = False
    async with leases.hold("ap2", "frames", PHY, router, router.audited):  # type: ignore[arg-type]
        assert router.exists


async def test_a_refused_removal_is_tried_again() -> None:
    """PR #59 review: a nonzero `iw dev owgmon0 del` is not success; it is checked and tried once more."""
    router, leases = _Router(del_fails=1), MonitorLeases()
    await leases.acquire("ap2", "frames", PHY, router, router.audited)  # type: ignore[arg-type]
    removed = await leases.release("ap2", "frames", router.audited, router)  # type: ignore[arg-type]
    assert removed is not None and removed.ok and not router.exists
    assert [c for c, _ in router.sent].count(DEL) == 2


async def test_a_monitor_that_stays_is_reported() -> None:
    router, leases = _Router(del_fails=2), MonitorLeases()
    await leases.acquire("ap2", "frames", PHY, router, router.audited)  # type: ignore[arg-type]
    removed = await leases.release("ap2", "frames", router.audited, router)  # type: ignore[arg-type]
    assert removed is not None and not removed.ok and "busy" in removed.stderr
    assert router.exists and [c for c, _ in router.sent].count(DEL) == 2


async def test_a_monitor_a_reload_removed_counts_as_removed() -> None:
    router, leases = _Router(), MonitorLeases()
    await leases.acquire("ap2", "frames", PHY, router, router.audited)  # type: ignore[arg-type]
    router.exists = False  # a Wi-Fi reload took it first
    removed = await leases.release("ap2", "frames", router.audited, router)  # type: ignore[arg-type]
    assert removed is not None and removed.ok
    assert [c for c, _ in router.sent].count(DEL) == 1


def test_add_command_matches_todays() -> None:
    assert add_command(PHY, clear_leftover=True) == (
        f"iw dev {MONITOR} del 2>/dev/null; iw phy phy0 interface add {MONITOR} type monitor && "
        f"ip link set {MONITOR} up"
    )
