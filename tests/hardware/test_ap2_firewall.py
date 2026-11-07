"""AP2 firewall window: firewall changes applied the way the app applies them, on the real router, and undone.

uv run pytest -m hardware tests/hardware/test_ap2_firewall.py tests/hardware/test_ap2_faults.py \
    --router 192.168.1.2 --identity <key> --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window the owner approved and the txctl session was told of: fw4 reloads, and the unpinned
change leaves AP2 unanswering for up to about 75 s while it rolls back. Each test undoes its change through
the app; the `fw_window` fixture then checks that the firewall config, the nft tables, the qdiscs, /tmp/owg,
the switch ports and the parked radio are as found.
"""

from __future__ import annotations

import time

import pytest

from conftest import FwWindow
from openwrtgui.fw.compile import ModelRequest
from openwrtgui.fw.sections import RuleRequest
from openwrtgui.fw.tables import ChainEdit, TableRequest
from openwrtgui.net.apply import NetApplyResult

pytestmark = pytest.mark.hardware

AP2 = "ap2"


def _proven(result: NetApplyResult) -> None:
    failed = [f"{c.name}: {c.detail}" for c in result.checks if c.ok is not True]
    assert result.applied and result.verified, failed or result.error


async def _model(w: FwWindow, req: ModelRequest) -> NetApplyResult:
    plan = await w.fw.plan_model(AP2, req)
    started = time.monotonic()
    result = await w.fw.apply_model(AP2, req, plan.digest)
    print(f"\n{dict(req.cells)} pins_removed={set(req.pins_removed)}: {time.monotonic() - started:.1f} s")
    print([(c.name, c.ok, c.detail) for c in result.checks])
    return result


async def test_block_all_on_lan_input_with_ssh_pin_confirms(fw_window: FwWindow) -> None:
    blocked = await _model(fw_window, ModelRequest({"lan.input": "REJECT"}))
    try:
        _proven(blocked)
        names = {c.name for c in blocked.checks}
        assert {"confirmed", "zone lan input", "rule Allow SSH from this PC"} <= names, names
    finally:
        back = await _model(fw_window, ModelRequest({"lan.input": "ACCEPT"}, frozenset({"ssh"})))
    _proven(back)


async def test_unpinned_block_all_rolls_back(fw_window: FwWindow) -> None:
    cut = await _model(fw_window, ModelRequest({"lan.input": "DROP"}, frozenset({"ssh"})))
    assert not cut.applied, cut
    checks = {c.name: c.ok for c in cut.checks}
    assert checks.get("reconnected") is False and checks.get("restored") is True, cut.checks


async def test_rule_add_and_delete(fw_window: FwWindow) -> None:
    rule = RuleRequest(None, "owg-hw-test", "wan", None, "tcp", dest_port="9", target="DROP")
    plan = await fw_window.fw.plan_sections(AP2, "rule", [rule], [])
    added = await fw_window.fw.apply_sections(AP2, "rule", [rule], [], plan.digest)
    section = next(
        (r.conf.section for r in (await fw_window.fw.state(AP2)).rules if r.conf.name == "owg-hw-test"), None
    )
    assert section is not None, f"the rule was not saved: {added}"
    try:
        _proven(added)
        assert "!fw4: owg-hw-test" in await fw_window.fw.ruleset_text(AP2)
    finally:
        plan = await fw_window.fw.plan_sections(AP2, "rule", [], [section])
        gone = await fw_window.fw.apply_sections(AP2, "rule", [], [section], plan.digest)
    _proven(gone)
    assert "!fw4: owg-hw-test" not in await fw_window.fw.ruleset_text(AP2)


async def _table(w: FwWindow, req: TableRequest) -> NetApplyResult:
    plan = await w.fw.plan_table(AP2, req)
    result = await w.fw.apply_table(AP2, req, plan.digest)
    print(f"\ntable {req.action}: {[(c.name, c.ok, c.detail) for c in result.checks]}")
    return result


async def test_app_table_add_edit_delete(fw_window: FwWindow) -> None:
    chain = ChainEdit("c", "type filter hook input priority 10; policy accept;")
    added = await _table(
        fw_window,
        TableRequest(
            "", "add", family="inet", name="hwtest", chains=(chain,), rules=(("c", "tcp dport 9 counter"),)
        ),
    )
    try:
        _proven(added)
        # nft lists rules its own way: the check counts chains and rules (final review, Important 2)
        edited = await _table(
            fw_window,
            TableRequest(
                "inet owg_hwtest",
                "edit",
                rules=(("c", "tcp dport { 9,10 } counter"), ("c", "ip saddr 10.9.9.9/32 drop")),
            ),
        )
        _proven(edited)
    finally:
        gone = await _table(fw_window, TableRequest("inet owg_hwtest", "delete"))
    _proven(gone)
    assert "owg_hwtest" not in await fw_window.fw.ruleset_text(AP2)
