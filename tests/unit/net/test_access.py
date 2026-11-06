"""Wi-Fi access by MAC: the policy per SSID, and blocking a device now, for N s, or saved (ap1 is on air)."""

from __future__ import annotations

import pytest
from netenv import NetEnv

from openwrtgui.net.access import AccessChange, AccessState, SsidAccess, compile_access, read_access
from openwrtgui.net.service import radio_results
from openwrtgui.transport.base import CommandResult
from openwrtgui.uci import UciOp, parse_uci_show
from openwrtgui.wifi.service import ApplyResult, Check, PreviewChanged

PANEL = "f4:12:fa:f3:57:68"
OTHER = "aa:bb:cc:dd:ee:01"
DEL_CLIENT = (
    'ubus call hostapd.phy0-ap0 del_client \'{{"addr":"{mac}","ban_time":{ms},"deauth":true,"reason":3}}\''
)


async def test_state_lists_ssids_with_policy_and_interface(net: NetEnv) -> None:
    state = await net.service.access("ap1")
    (ssid,) = state.ssids
    assert (ssid.section, ssid.ssid, ssid.radio, ssid.ifname, ssid.policy) == (
        "default_radio0",
        "OpenWrt",
        "radio0",
        "phy0-ap0",
        "everyone",
    )
    parked = (await net.service.access("ap2")).ssids[0]
    assert parked.ifname is None


async def test_policy_block_listed_plan(net: NetEnv) -> None:
    plan = await net.service.plan_access("ap1", AccessChange("policy", ("default_radio0",), policy="deny"))
    assert "uci set wireless.default_radio0.macfilter='deny'" in plan.lines
    assert "wifi down radio0; wifi up radio0" in plan.lines


async def test_only_listed_with_empty_list_refused(net: NetEnv) -> None:
    with pytest.raises(
        ValueError,
        match="before choosing Only listed: an empty list keeps every device off OpenWrt",
    ):
        await net.service.plan_access("ap1", AccessChange("policy", ("default_radio0",), policy="allow"))


async def test_saved_block_from_everyone_switches_policy_with_warning(net: NetEnv) -> None:
    change = AccessChange("block", ("default_radio0",), mac=OTHER.upper(), method="saved")
    plan = await net.service.plan_access("ap1", change)
    assert "uci set wireless.default_radio0.macfilter='deny'" in plan.lines
    assert f"uci add_list wireless.default_radio0.maclist='{OTHER}'" in plan.lines
    assert "OpenWrt changes from Everyone to Block listed." in plan.warnings
    result = await net.service.apply_access("ap1", change, plan.digest)
    assert result.applied and result.verified, result
    state = await net.service.access("ap1")
    assert state.ssids[0].policy == "deny" and state.ssids[0].maclist == (OTHER,)
    assert next(d for d in state.devices if d.mac == OTHER).saved_in == ("default_radio0",)
    assert any(e.screen == "Network" and e.command == "verify radio0" for e in net.audit.query())


async def test_block_now_uses_deny_acl_and_verifies(net: NetEnv) -> None:
    change = AccessChange("block", ("default_radio0",), mac=PANEL, method="now")
    plan = await net.service.plan_access("ap1", change)
    assert plan.lines == (f"hostapd_cli -i phy0-ap0 deny_acl ADD_MAC {PANEL}",)
    result = await net.service.apply_access("ap1", change, plan.digest)
    assert result.verified and [c.name for c in result.checks] == ["runtime list phy0-ap0"]
    panel = next(d for d in (await net.service.access("ap1")).devices if d.mac == PANEL)
    assert panel.blocked_now_on == ("phy0-ap0",) and panel.name == "panel"
    unblock = await net.service.apply_access(
        "ap1", AccessChange("unblock", ("default_radio0",), mac=PANEL, method="now")
    )
    assert unblock.verified


async def test_block_now_on_allow_policy_removes_from_accept_list_and_deauths(net: NetEnv) -> None:
    await net.service.apply_access(
        "ap1", AccessChange("block", ("default_radio0",), mac=OTHER, method="saved")
    )
    sim = await net.sim("ap1")
    script = "set -e\nuci set wireless.default_radio0.macfilter='allow'\nuci commit wireless"
    assert (await sim.run(script)).ok and (await sim.run("wifi down radio0; wifi up radio0")).ok
    plan = await net.service.plan_access(
        "ap1", AccessChange("block", ("default_radio0",), mac=PANEL, method="now")
    )
    assert plan.lines == (
        f"hostapd_cli -i phy0-ap0 accept_acl DEL_MAC {PANEL}",
        DEL_CLIENT.format(mac=PANEL, ms=0),
    )


async def test_block_now_refused_when_radio_down(net: NetEnv) -> None:
    with pytest.raises(
        ValueError, match="OpenWrt is not on air; a block now needs the radio up. Use For N s or Saved."
    ):
        await net.service.plan_access(
            "ap2", AccessChange("block", ("default_radio0",), mac=PANEL, method="now")
        )


async def test_timed_block_uses_ban_time(net: NetEnv) -> None:
    change = AccessChange("block", ("default_radio0",), mac=PANEL, method="timed", seconds=60)
    plan = await net.service.plan_access("ap1", change)
    assert plan.lines == (DEL_CLIENT.format(mac=PANEL, ms=60000),)
    with pytest.raises(ValueError, match="Block for 10 to 3600 seconds"):
        await net.service.plan_access(
            "ap1", AccessChange("block", ("default_radio0",), mac=PANEL, method="timed", seconds=5)
        )


class Idle:
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        return CommandResult(command, "", "", 0)


async def test_only_access_point_ssids_are_listed() -> None:
    """A client (sta) or mesh interface admits no stations: it is not an SSID here (Codex review, PR #23)."""
    uci = parse_uci_show(
        "wireless.default_radio0=wifi-iface\nwireless.default_radio0.device='radio0'\n"
        "wireless.default_radio0.mode='ap'\nwireless.default_radio0.ssid='OpenWrt'\n"
        "wireless.wwan=wifi-iface\nwireless.wwan.device='radio0'\nwireless.wwan.mode='sta'\n"
        "wireless.wwan.ssid='uplink'\n"
        "wireless.mesh0=wifi-iface\nwireless.mesh0.device='radio0'\nwireless.mesh0.mode='mesh'\n"
    )
    state = await read_access(Idle(), uci, {}, {})  # type: ignore[arg-type]
    assert [s.section for s in state.ssids] == ["default_radio0"]


def test_saved_unblock_under_everyone_removes_a_listed_mac() -> None:
    """Everyone leaves the old maclist in place; Saved → Unblock must still take a MAC off it, or the entry
    comes back the day a list policy is chosen (Codex review, PR #23)."""
    ssid = SsidAccess("default_radio0", "OpenWrt", "radio0", "phy0-ap0", "everyone", (OTHER,), ())
    change = AccessChange("unblock", ("default_radio0",), mac=OTHER, method="saved")
    ops, commands, warnings = compile_access(change, AccessState((ssid,), ()), "AP1 · bench")
    assert ops == [UciOp("del_list", "wireless.default_radio0.maclist", OTHER)]
    assert commands == [] and warnings == []


def test_a_partial_multi_radio_apply_says_what_changed() -> None:
    """Saved access changes go radio by radio: when one radio takes the change and the next refuses it, the
    result must not claim nothing was applied (Codex review, PR #23)."""
    took = ApplyResult("ap1", "radio0", True, True, (Check("radio", True, "on air"),), None)
    refused = ApplyResult("ap1", "radio1", False, False, (), "dima_night.py started 21:04 (PID 18244)")
    result = radio_results("ap1", "192.168.1.1", [took, refused], ["radio2"])
    assert result.applied and not result.verified
    assert result.error == (
        "Applied on radio0 only. radio1: dima_night.py started 21:04 (PID 18244). radio2: not tried"
    )
    single = radio_results("ap1", "192.168.1.1", [took], [])
    assert single.applied and single.verified and single.error is None


async def test_unknown_ssid_and_bad_mac_refused(net: NetEnv) -> None:
    with pytest.raises(ValueError, match="nosuch is not an SSID of AP1 · bench"):
        await net.service.plan_access("ap1", AccessChange("policy", ("nosuch",), policy="deny"))
    with pytest.raises(ValueError, match="f4:12 is not a MAC address"):
        await net.service.plan_access(
            "ap1", AccessChange("block", ("default_radio0",), mac="f4:12", method="now")
        )


async def test_access_saved_checks_digest_under_lock(net: NetEnv) -> None:
    """#32: a saved access change is planned and its digest checked while the write lock is held, and the
    Wi-Fi apply then runs under that same hold."""
    seen: list[bool] = []
    plan_ops = net.wifi.plan_ops

    async def watched(*args, **kw):  # type: ignore[no-untyped-def]
        seen.append(net.pool.write_lock("ap1").locked())
        return await plan_ops(*args, **kw)

    net.wifi.plan_ops = watched  # type: ignore[method-assign]
    change = AccessChange("block", ("default_radio0",), mac=OTHER, method="saved")
    with pytest.raises(PreviewChanged):
        await net.service.apply_access("ap1", change, "0000000000000000")
    assert seen == [True]
    assert not any("uci add_list wireless" in line for line in net.audit_lines())
    plan = await net.service.plan_access("ap1", change)
    result = await net.service.apply_access("ap1", change, plan.digest)
    assert result.applied and result.verified, result
