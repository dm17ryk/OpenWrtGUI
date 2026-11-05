from __future__ import annotations

import pytest

from conftest import WifiEnv
from openwrtgui.wifi.compile import render_uci
from openwrtgui.wifi.options import OptionEdit, compile_edits, editor_for


async def test_rows_cover_every_validate_option(env: WifiEnv) -> None:
    rows = await env.service.options("ap2", "radio0")
    assert sum(r.group == "device" for r in rows) == 155
    assert sum(r.group == "interface" for r in rows) == 289
    assert {r.section for r in rows if r.group == "interface"} == {"default_radio0"}


async def test_controls_writers_and_values(env: WifiEnv) -> None:
    rows = {(r.section, r.name): r for r in await env.service.options("ap2", "radio0")}
    htmode = rows[("radio0", "htmode")]
    assert htmode.control == "Modes" and htmode.value == "HT40" and htmode.set_in_config
    assert rows[("radio0", "disabled")].control == "Channels (None = parked)"
    assert rows[("radio0", "cell_density")].writer == "dima_night"
    assert (
        rows[("radio0", "beacon_int")].editor == "number" and not rows[("radio0", "beacon_int")].set_in_config
    )
    assert rows[("radio0", "channels")].editor == "list"
    assert rows[("radio0", "type")].editor == "readonly"
    key = rows[("default_radio0", "key")]
    assert (
        key.editor == "secret"
        and key.value is None
        and key.set_in_config
        and key.control == "Security (hidden)"
    )
    assert rows[("default_radio0", "maclist")].control == "Network & DHCP › Wi-Fi access by MAC"


def test_editor_for() -> None:
    assert editor_for("noscan", "bool") == "switch"
    assert editor_for("rts", "uinteger") == "number"
    assert editor_for("maclist", "list(string)") == "list"
    assert editor_for("key", "<hidden>") == "secret"
    assert editor_for("sae_password", "string") == "secret"
    assert editor_for("path", "string") == "readonly"
    assert editor_for("server", "host") == "text"


async def test_compile_edits(env: WifiEnv) -> None:
    rows = await env.service.options("ap2", "radio0")
    ops, secrets = compile_edits(
        [
            OptionEdit("radio0", "beacon_int", "200"),
            OptionEdit("radio0", "channels", ["1", "6", "11"]),
            OptionEdit("radio0", "rts", None),
            OptionEdit("radio0", "noscan", "1"),
            OptionEdit("default_radio0", "key", "new-lab-key"),
        ],
        rows,
    )
    assert render_uci(ops) == [
        "uci set wireless.radio0.beacon_int='200'",
        "uci -q delete wireless.radio0.channels",
        "uci add_list wireless.radio0.channels='1'",
        "uci add_list wireless.radio0.channels='6'",
        "uci add_list wireless.radio0.channels='11'",
        "uci -q delete wireless.radio0.rts",
        "uci set wireless.radio0.noscan='1'",
        "uci set wireless.default_radio0.key='new-lab-key'",
    ]
    assert secrets == ["new-lab-key"]


async def test_refusals(env: WifiEnv) -> None:
    rows = await env.service.options("ap2", "radio0")
    cases = [
        (OptionEdit("radio0", "nope", "1"), "nope is not an option of radio0"),
        (OptionEdit("radio0", "path", "x"), "path is read-only"),
        (OptionEdit("radio0", "beacon_int", "fast"), "beacon_int takes a whole number"),
        (OptionEdit("radio0", "noscan", "yes"), "noscan is on or off"),
    ]
    for edit, message in cases:
        with pytest.raises(ValueError, match=message):
            compile_edits([edit], rows)


async def test_plan_and_apply_options_run_reload_and_verify_radio(env: WifiEnv) -> None:
    edits = [OptionEdit("radio0", "beacon_int", "200")]
    plan = await env.service.plan_options("ap1", "radio0", edits)
    assert list(plan.lines) == [
        "set -e",
        "uci set wireless.radio0.beacon_int='200'",
        "uci commit wireless",
        "wifi down radio0; wifi up radio0",
    ]  # AP1's modes are set outside the selector, so no TX mask goes with them
    result = await env.service.apply_options("ap1", "radio0", edits)
    assert result.applied and result.verified
    assert [c.name for c in result.checks] == ["radio", "channel", "width", "TX power"]
    shown = (await (await env.sim("ap1")).run("uci -q show wireless")).stdout
    assert "wireless.radio0.beacon_int='200'" in shown


async def test_secret_option_is_hidden_in_the_preview(env: WifiEnv) -> None:
    plan = await env.service.plan_options(
        "ap1", "radio0", [OptionEdit("default_radio0", "key", "x'y-lab-key")]
    )
    assert plan.lines[1] == "uci set wireless.default_radio0.key='<hidden>'"
