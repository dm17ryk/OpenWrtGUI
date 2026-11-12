"""The chained step-through preview and the radio hold on WifiService (v0.7 plan Task 10, D3, D8)."""

from __future__ import annotations

import pytest

from conftest import WifiEnv
from openwrtgui.uci import UciOp
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest
from openwrtgui.wifi.service import RadioBusy
from openwrtgui.wifi.state import read_uci
from openwrtgui.wifi.steps import StepRequest, expand_steps, saved_ops, saved_options, step_request

DISABLED_0 = "uci set wireless.radio0.disabled='0'"
DISABLED_1 = "uci set wireless.radio0.disabled='1'"


async def test_plan_sequence_chains(env: WifiEnv) -> None:
    state = await env.service.state("ap2")
    [radio] = [r for r in state.radios if r.name == "radio0"]
    assert not radio.up
    steps = expand_steps(StepRequest("radio0", ("b",), (1, 6)), radio.limits)
    uci = await read_uci(await env.sim("ap2"))
    tail = saved_ops("radio0", saved_options(uci, "radio0"))
    plans, restore = await env.service.plan_sequence(
        "ap2", "radio0", [step_request(s, "radio0") for s in steps], tail
    )
    assert len(plans) == 2
    assert DISABLED_0 in plans[0].lines and DISABLED_0 not in plans[1].lines
    assert "uci set wireless.radio0.channel='6'" in plans[1].lines
    assert "uci set wireless.radio0.htmode='NOHT'" not in plans[1].lines  # step 1 set it already
    assert DISABLED_1 in restore.lines


async def test_a_step_that_changes_nothing_is_kept(env: WifiEnv) -> None:
    state = await env.service.state("ap2")
    [radio] = [r for r in state.radios if r.name == "radio0"]
    steps = expand_steps(StepRequest("radio0", ("b",), (6,)), radio.limits)
    req = step_request(steps[0], "radio0")
    plans, _ = await env.service.plan_sequence("ap2", "radio0", [req, req], [])
    assert plans[1].script == "" and all(" set bitrates " in line for line in plans[1].lines)


async def test_change_lines_drop_the_mask(env: WifiEnv) -> None:
    req = RadioRequest(radio="radio0", modes=ModeSelection.of("g"), channels=ChannelSelection.of(6))
    plan = await env.service.plan("ap2", req)
    assert any(" set bitrates " in line for line in plan.lines)
    assert not any(" set bitrates " in line for line in plan.change_lines)
    assert plan.change_lines == tuple(line for line in plan.lines if " set bitrates " not in line)


async def test_apply_refused_while_held(env: WifiEnv) -> None:
    token = env.service.hold_radio("ap1", "radio0", "A step-through")
    req = RadioRequest(radio="radio0", channels=ChannelSelection.of(11))
    before = len(env.audit_lines())
    with pytest.raises(RadioBusy, match="^A step-through runs on AP1 · bench radio0"):
        await env.service.apply("ap1", req)
    assert len(env.audit_lines()) == before
    env.service.release_radio(token)


async def test_apply_ops_refused_while_held(env: WifiEnv) -> None:
    env.service.hold_radio("ap1", "radio0", "A step-through")
    ops = [UciOp("set", "wireless.radio0.txpower", "10")]
    with pytest.raises(RadioBusy):  # Network & DHCP's saved MAC lists go through apply_ops
        await env.service.apply_ops("ap1", "radio0", ops, screen="Network & DHCP")
    with pytest.raises(RadioBusy):
        env.service.hold_radio("ap1", "radio0", "Another step-through")


async def test_holder_may_apply(env: WifiEnv) -> None:
    token = env.service.hold_radio("ap1", "radio0", "A step-through")
    result = await env.service.apply(
        "ap1", RadioRequest(radio="radio0", channels=ChannelSelection.of(11)), holder=token
    )
    assert result.applied
    env.service.release_radio(token)
    assert (
        await env.service.apply("ap1", RadioRequest(radio="radio0", channels=ChannelSelection.of(1)))
    ).applied
