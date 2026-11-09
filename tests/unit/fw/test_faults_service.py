"""Faults armed, proven, held by a router-side timer and cleared, against the simulated routers."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import cast

import pytest
from fwenv import FwEnv

from openwrtgui.faults.model import FaultRequest, FaultTarget, NetemParams, TargetRef
from openwrtgui.faults.service import FaultsService, caps_from
from openwrtgui.fw.nft import parse_ruleset_json
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.net.apply import NetCheck
from openwrtgui.probe.status import read_status
from openwrtgui.simfw import SimFirewall
from openwrtgui.transport.base import CommandResult, Transport

PANEL = TargetRef(None, "192.168.1.30")
FAR = TargetRef("02:00:00:00:00:01", "192.168.1.250")


def _faults(env: FwEnv) -> FaultsService:
    return FaultsService(
        pool=env.pool,
        routers=env.routers,
        guard=env.guard,
        audit=env.audit,
        settings=env.settings,
        descriptions=env.descriptions,
        runner=env.runner,
        clock=env.clock.now,
        sleep=env.clock.sleep,
    )


async def _arm(env: FwEnv, faults: FaultsService, router_id: str, req: FaultRequest):  # type: ignore[no-untyped-def]
    plan = await faults.plan_fault(router_id, req)
    return plan, await faults.apply_fault(router_id, req, plan.digest)


async def test_state_ap1(env: FwEnv) -> None:
    state = await _faults(env).state("ap1")
    assert (state.caps.family, state.caps.ifb, state.caps.conntrack) == ("netdev", True, True)
    assert state.caps.distributions == frozenset({"normal", "pareto", "paretonormal"})
    assert state.armed == () and state.unavailable == {}
    assert [(w.ifname, w.up) for w in state.wifi] == [("phy0-ap0", True)]
    assert any(t.ip == "192.168.1.30" for t in state.targets)


async def test_apply_l3_verified_in_sim(env: FwEnv) -> None:
    faults = _faults(env)
    plan, result = await _arm(env, faults, "ap1", FaultRequest("block", PANEL, flow="rtp_in", loss=30))
    assert "nft -f /dev/stdin <<'OWG'" in plan.lines and "add table netdev benchfault" in plan.lines
    assert any(line.startswith("printf '%s\"armed_at\":%s}\\n' ") for line in plan.lines)
    assert result.applied and result.verified, result
    (armed,) = (await faults.state("ap1")).armed
    assert {c.name for c in result.checks} >= {f"fault {armed.id}", "record"}
    assert armed.kind == "block" and armed.until is None and "rtp_in" in armed.summary
    t = await env.sim("ap1")
    rules = parse_ruleset_json((await t.run("nft -j list table netdev benchfault")).stdout).rules
    assert len(rules) == 1 and rules[0].comment == f"owg:{armed.id}"


async def test_held_fault_cleared_by_router_timer_in_sim(env: FwEnv) -> None:
    faults = _faults(env)
    _, result = await _arm(env, faults, "ap1", FaultRequest("isolate", PANEL, hold_s=60))
    assert result.verified and ("timer", True) in [(c.name, c.ok) for c in result.checks]
    (armed,) = (await faults.state("ap1")).armed
    assert armed.until is not None and armed.until - env.clock.now() == timedelta(seconds=60)
    env.clock.t += timedelta(seconds=61)
    assert (await faults.state("ap1")).armed == ()
    t = await env.sim("ap1")
    assert not (await t.run("nft list table netdev benchfault")).ok  # the last fault took the table along


async def test_armed_listed_after_app_restart(env: FwEnv) -> None:
    _, result = await _arm(env, _faults(env), "ap1", FaultRequest("block", PANEL, flow="all_in", hold_s=600))
    assert result.verified
    env.clock.t += timedelta(seconds=100)
    (armed,) = (await _faults(env).state("ap1")).armed  # a new service: nothing in memory
    assert armed.until is not None and armed.until - env.clock.now() == timedelta(seconds=500)


async def test_netem_and_ap_down_in_sim(env: FwEnv) -> None:
    faults = _faults(env)
    _, netem = await _arm(
        env, faults, "ap1", FaultRequest("netem", PANEL, netem=NetemParams(delay_ms=100, loss_pct=1))
    )
    assert netem.verified, netem
    assert ("netem phy0-ap0", True) in [(c.name, c.ok) for c in netem.checks]
    _, down = await _arm(env, faults, "ap1", FaultRequest("ap_down", PANEL))
    assert down.verified and ("ap down phy0-ap0", True) in [(c.name, c.ok) for c in down.checks]
    t = await env.sim("ap1")
    plan = await faults.plan_clear("ap1", None)
    assert (await faults.apply_clear("ap1", None, plan.digest)).verified
    assert "state=ENABLED" in (await t.run("hostapd_cli -i phy0-ap0 status")).stdout


async def test_link_down_held_in_sim(env: FwEnv) -> None:
    faults = _faults(env)
    _, result = await _arm(env, faults, "ap2", FaultRequest("link_down", FAR, port=2, hold_s=10))
    assert result.verified, result
    t = await env.sim("ap2")
    shown = (await t.run("swconfig dev switch0 show")).stdout
    assert "enable: 0" in shown.split("Port 2:")[1].split("Port 3:")[0]
    env.clock.t += timedelta(seconds=11)
    shown = (await t.run("swconfig dev switch0 show")).stdout
    assert "enable: 1" in shown.split("Port 2:")[1].split("Port 3:")[0]


async def test_clear_everything_removes_table_ifb_and_records(env: FwEnv) -> None:
    faults = _faults(env)
    await _arm(env, faults, "ap1", FaultRequest("block", PANEL, flow="all_out"))
    _, ifb = await _arm(
        env, faults, "ap1", FaultRequest("netem", PANEL, netem=NetemParams(delay_ms=50, direction="from"))
    )
    assert ifb.verified, ifb
    plan = await faults.plan_clear("ap1", None)
    assert "nft delete table netdev benchfault" in plan.lines
    result = await faults.apply_clear("ap1", None, plan.digest)
    assert result.applied and result.verified, result
    t = await env.sim("ap1")
    assert not (await t.run("nft list table netdev benchfault")).ok
    assert "owgifb0" not in (await t.run("tc qdisc show")).stdout
    assert (await faults.state("ap1")).armed == ()


async def test_clear_allowed_while_guard_live(env: FwEnv) -> None:
    faults = _faults(env)
    await _arm(env, faults, "ap1", FaultRequest("isolate", PANEL))
    env.go_live()
    plan = await faults.plan_clear("ap1", None)
    result = await faults.apply_clear("ap1", None, plan.digest)
    assert result.applied
    assert result.error is not None and result.error.startswith(
        "Cleared although Bench Guard is live (dima_night.py"
    )


async def test_arm_refused_while_guard_live(env: FwEnv) -> None:
    faults = _faults(env)
    plan = await faults.plan_fault("ap1", FaultRequest("isolate", PANEL))
    env.go_live()
    with pytest.raises(GuardLocked):
        await faults.apply_fault("ap1", FaultRequest("isolate", PANEL), plan.digest)


async def test_status_counts_armed_faults(env: FwEnv) -> None:
    await _arm(env, _faults(env), "ap1", FaultRequest("isolate", PANEL, hold_s=600))
    assert (await read_status(await env.sim("ap1"))).faults_armed == 1
    assert (await read_status(await env.sim("ap2"))).faults_armed == 0


def test_caps_from_module_files_and_built_ins() -> None:
    files = "\n".join(["ifb.ko", "sch_ets.ko", "sch_netem.ko", "modules.builtin"])
    caps = caps_from("bridge", "", files, "/usr/sbin/conntrack")
    assert (caps.band, caps.netem, caps.ifb, caps.conntrack) == ("ets", True, True, True)
    built_in = files + "\nkernel/net/sched/sch_prio.ko"
    assert caps_from("bridge", "", built_in, "").band == "prio"
    bare = caps_from(None, "", "ifb.ko", "")
    assert (bare.band, bare.netem, bare.ifb, bare.conntrack) == (None, False, True, False)


async def test_ap2_in_the_sim_is_the_recorded_ap2(env: FwEnv) -> None:
    caps = (await _faults(env).state("ap2")).caps
    assert (caps.family, caps.band, caps.netem, caps.distributions) == ("bridge", "ets", True, frozenset())


async def test_clear_works_when_the_fault_is_already_gone(env: FwEnv) -> None:
    faults = _faults(env)
    _, result = await _arm(env, faults, "ap1", FaultRequest("isolate", PANEL))
    assert result.verified
    (armed,) = (await faults.state("ap1")).armed
    t = await env.sim("ap1")
    assert (await t.run("nft delete table netdev benchfault")).ok  # gone behind the app's back
    plan = await faults.plan_clear("ap1", [armed.id])
    cleared = await faults.apply_clear("ap1", [armed.id], plan.digest)
    assert cleared.applied and cleared.verified, cleared
    assert (await faults.state("ap1")).armed == ()


async def test_a_ban_cleared_early_is_lifted_and_its_timer_sends_nothing(env: FwEnv) -> None:
    faults = _faults(env)
    plan, result = await _arm(env, faults, "ap1", FaultRequest("ban", PANEL, ban_s=600))
    assert result.applied, result
    arm = next(line for line in plan.lines if "start-stop-daemon -S" in line)
    assert "del_client" not in arm  # on time hostapd lifts the ban itself
    t = await env.sim("ap1")
    assert "f4:12:fa:f3:57:68" in (await t.run("ubus call hostapd.phy0-ap0 list_bans")).stdout
    (armed,) = (await faults.state("ap1")).armed
    cleared = await faults.apply_clear("ap1", [armed.id], (await faults.plan_clear("ap1", [armed.id])).digest)
    assert cleared.verified, cleared
    assert "f4:12:fa:f3:57:68" not in (await t.run("ubus call hostapd.phy0-ap0 list_bans")).stdout
    assert (await faults.state("ap1")).armed == ()


class _Rejoining:
    """AP2, 2026-11-09: right after a deauth hostapd still lists the phone, no longer associated, and the
    phone is associated again by the next look a second later."""

    def __init__(self, mac: str) -> None:
        self.mac, self.looks = mac, 0

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.looks += 1
        assoc = self.looks > 1
        flags = {"auth": assoc, "assoc": assoc, "authorized": assoc}
        return CommandResult(command, json.dumps({"freq": 2437, "clients": {self.mac.upper(): flags}}), "", 0)


async def test_deauth_counts_a_station_listed_but_no_longer_associated(env: FwEnv) -> None:
    target = FaultTarget(None, "f4:12:fa:f3:57:68", None, "phy0-ap0", "phy0-ap0")
    t = cast(Transport, _Rejoining("f4:12:fa:f3:57:68"))
    check = await _faults(env)._client_check(t, target, banned=False)
    assert check == NetCheck("deauth", True, "f4:12:fa:f3:57:68 left phy0-ap0")


async def test_a_fault_that_fails_to_clear_stays_listed(env: FwEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    real = SimFirewall._tc

    def no_delete(self: SimFirewall, p: str) -> CommandResult | None:
        if p.startswith("tc qdisc del"):
            return CommandResult(p, "", "RTNETLINK answers: Operation not permitted", 2)
        return real(self, p)

    faults = _faults(env)
    _, result = await _arm(env, faults, "ap2", FaultRequest("netem", FAR, netem=NetemParams(delay_ms=100)))
    assert result.verified, result
    (armed,) = (await faults.state("ap2")).armed
    monkeypatch.setattr(SimFirewall, "_tc", no_delete)
    failed = await faults.apply_clear("ap2", [armed.id], (await faults.plan_clear("ap2", [armed.id])).digest)
    assert not failed.verified
    assert failed.error is not None and "stays listed" in failed.error, failed
    assert [a.id for a in (await faults.state("ap2")).armed] == [armed.id]  # the record is kept to retry
    monkeypatch.setattr(SimFirewall, "_tc", real)
    again = await faults.apply_clear("ap2", [armed.id], (await faults.plan_clear("ap2", [armed.id])).digest)
    assert again.verified, again
    assert (await faults.state("ap2")).armed == ()


async def test_a_failed_arm_removes_what_had_run(env: FwEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    real = SimFirewall._tc

    def no_filter(self: SimFirewall, p: str) -> CommandResult | None:
        if p.startswith("tc filter add"):
            return CommandResult(p, "", "RTNETLINK answers: Operation not supported", 2)
        return real(self, p)

    monkeypatch.setattr(SimFirewall, "_tc", no_filter)
    faults = _faults(env)
    _, result = await _arm(env, faults, "ap2", FaultRequest("netem", FAR, netem=NetemParams(delay_ms=100)))
    assert not result.verified
    assert result.error is not None and "removed the parts that had run" in result.error
    t = await env.sim("ap2")
    assert "1ee7:" not in (await t.run("tc qdisc show")).stdout
    assert (await faults.state("ap2")).armed == ()
