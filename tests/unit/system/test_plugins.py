"""System › Plugins (v1.0a2 D4): plugin headers from their JS, the state from luci_plugins, the uci ops."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.system.plugins import (
    PluginChange,
    PluginHeader,
    parse_header,
    plugin_ops,
    plugin_state,
    read_plugin_command,
)
from openwrtgui.uci import UciOp, parse_uci_show

LATER = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "sim" / "later" / "ap4.json").read_text("utf-8")
)
CSP_ID = "c0ffee2cf63e160c091224d95d69cdff"
GONE_ID = "0123456789abcdef0123456789abcdef"
CSP = parse_header(CSP_ID, LATER["plugins"][f"{CSP_ID}.js"])
UCI = parse_uci_show(
    f"""luci_plugins.global=global
luci_plugins.global.enabled='1'
luci_plugins.global.http_headers_enabled='1'
luci_plugins.{CSP_ID}=http_headers
luci_plugins.{CSP_ID}.name='Content-Security-Policy'
luci_plugins.{CSP_ID}.enabled='0'
luci_plugins.{CSP_ID}.mode='strict'
luci_plugins.{GONE_ID}=auth_login
luci_plugins.{GONE_ID}.name='Gone plugin'
luci_plugins.{GONE_ID}.enabled='0'
"""
)


def test_plugin_header_from_luci_csp_plugin() -> None:
    assert (
        PluginHeader(
            id=CSP_ID,
            class_name="http",
            type_name="headers",
            name="Content-Security-Policy",
            title="Content Security Policy",
            description="Sets the Content-Security-Policy header on every LuCI response.",
        )
        == CSP
    )


def test_plugin_header_tolerates_other_shapes() -> None:
    text = (
        'return baseclass.extend({ class: "auth", type: "login", name: "TOTP", title: `Two ${x}`, '
        'description: _("Codes %s").format(n) });'
    )
    header = parse_header(GONE_ID, text)
    assert header is not None
    assert (header.class_name, header.type_name, header.name, header.title, header.description) == (
        "auth",
        "login",
        "TOTP",
        "",
        "Codes %s",
    )
    assert parse_header(GONE_ID, "return baseclass.extend({ class: 'http' });") is None  # no type: no group


def test_state_joins_files_and_sections() -> None:
    assert CSP is not None
    state = plugin_state(UCI, [CSP])
    assert state.enabled and state.global_section
    assert [(g.key, g.enabled) for g in state.groups] == [("auth_login", False), ("http_headers", True)]
    by = {p.id: p for p in state.plugins}
    # LuCI runs a header plugin whatever its `enabled` holds, even '0' (run_plugins tests it for truth)
    assert (by[CSP_ID].installed, by[CSP_ID].configured, by[CSP_ID].enabled) == (True, True, True)
    assert by[CSP_ID].options == {"mode": "strict"}
    assert (by[GONE_ID].installed, by[GONE_ID].enabled, by[GONE_ID].name) == (False, False, "Gone plugin")


def test_off_deletes_and_on_creates_the_section() -> None:
    assert CSP is not None
    fresh = plugin_state({"luci_plugins.global": "global"}, [CSP])
    ops = plugin_ops(fresh, PluginChange(enabled=True, groups={"http_headers": True}, plugins={CSP_ID: True}))
    assert ops == [
        UciOp("set", "luci_plugins.global.enabled", "1"),
        UciOp("set", "luci_plugins.global.http_headers_enabled", "1"),
        UciOp("set", f"luci_plugins.{CSP_ID}", "http_headers"),
        UciOp("set", f"luci_plugins.{CSP_ID}.name", "Content-Security-Policy"),
        UciOp("set", f"luci_plugins.{CSP_ID}.enabled", "1"),
    ]
    off = plugin_ops(plugin_state(UCI, [CSP]), PluginChange(plugins={CSP_ID: False}))
    assert off == [UciOp("delete", f"luci_plugins.{CSP_ID}.enabled")]


def test_the_global_section_is_made_when_missing() -> None:
    ops = plugin_ops(plugin_state({}, []), PluginChange(enabled=True))
    assert ops == [
        UciOp("set", "luci_plugins.global", "global"),
        UciOp("set", "luci_plugins.global.enabled", "1"),
    ]


def test_a_present_file_whose_header_cannot_be_read_is_not_gone() -> None:
    """final review Important 4: installed means the plugin's file is there; its header may be unreadable."""
    state = plugin_state(UCI, [], files={CSP_ID})  # CSP's file is listed, its header did not parse
    by = {p.id: p for p in state.plugins}
    assert (by[CSP_ID].installed, by[CSP_ID].readable, by[CSP_ID].group) == (True, False, "http_headers")
    assert (by[GONE_ID].installed, by[GONE_ID].readable) == (False, False)
    with pytest.raises(ValueError, match="file is gone"):
        plugin_ops(state, PluginChange(remove=[CSP_ID]))
    assert plugin_ops(state, PluginChange(plugins={CSP_ID: False})) == [
        UciOp("delete", f"luci_plugins.{CSP_ID}.enabled")
    ]
    lone = "a" * 32  # a file with an unreadable header and no section: listed, but no group to switch
    bare = plugin_state({"luci_plugins.global": "global"}, [], files={lone})
    assert [(p.id, p.installed, p.group) for p in bare.plugins] == [(lone, True, "")]
    with pytest.raises(ValueError, match="configure it in LuCI"):
        plugin_ops(bare, PluginChange(plugins={lone: True}))


def test_secret_options_are_hidden() -> None:
    """final review (re-graded): LuCI's 2FA plugin keeps root's TOTP key in key_root; it is never shown."""
    totp = "bb4ea47fcffb44ec9bb3d3673c9b4ed2"
    uci = {
        f"luci_plugins.{totp}": "auth_login",
        f"luci_plugins.{totp}.name": "TOTP/HOTP 2FA",
        f"luci_plugins.{totp}.key_root": "JBSWY3DPEHPK3PXP",
        f"luci_plugins.{totp}.type_root": "totp",
        f"luci_plugins.{totp}.priority": "10",
    }
    (row,) = plugin_state(uci, []).plugins
    assert row.options == {"key_root": "<hidden>", "type_root": "totp", "priority": "10"}


def test_run_together_secret_names_are_hidden_too() -> None:
    """v1.0b1 D2: the shared rule keeps the plugin screen's substring match and adds psk and pwd."""
    pid = "bb4ea47fcffb44ec9bb3d3673c9b4ed2"
    uci = {
        f"luci_plugins.{pid}": "auth_login",
        f"luci_plugins.{pid}.apikey": "made-up",
        f"luci_plugins.{pid}.wpa_psk": "made-up",
        f"luci_plugins.{pid}.admin_pwd": "made-up",
        f"luci_plugins.{pid}.priority": "10",
    }
    (row,) = plugin_state(uci, []).plugins
    assert row.options == {
        "apikey": "<hidden>",
        "wpa_psk": "<hidden>",
        "admin_pwd": "<hidden>",
        "priority": "10",
    }


def test_refusals() -> None:
    assert CSP is not None
    state = plugin_state(UCI, [CSP])
    with pytest.raises(ValueError, match="No plugin group foo_bar"):
        plugin_ops(state, PluginChange(groups={"foo_bar": True}))
    with pytest.raises(ValueError, match="installed"):
        plugin_ops(state, PluginChange(plugins={GONE_ID: True}))
    with pytest.raises(ValueError, match="file is gone"):
        plugin_ops(state, PluginChange(remove=[CSP_ID]))
    assert plugin_ops(state, PluginChange(remove=[GONE_ID])) == [UciOp("delete", f"luci_plugins.{GONE_ID}")]
    with pytest.raises(ValueError, match="plugin id"):
        read_plugin_command("../../etc/shadow")
