"""The uci layer every config shares: rendering, only-changes, script order, `uci show` parsing."""

from __future__ import annotations

from openwrtgui.uci import UciOp, after, drop_unchanged, order_for_script, parse_uci_show, render_uci


def test_add_renders_a_shell_variable() -> None:
    ops = [UciOp("add", "dhcp.$h1", "host"), UciOp("set", "dhcp.$h1.mac", "f4:12:fa:f3:57:68")]
    assert render_uci(ops) == ["h1=$(uci add dhcp host)", "uci set dhcp.$h1.mac='f4:12:fa:f3:57:68'"]


def test_savedir_prefix() -> None:
    ops = [UciOp("set", "network.lan.ipaddr", "192.168.1.12/24"), UciOp("add", "network.$r1", "route")]
    assert render_uci(ops, savedir="/var/run/rpcd/uci-S") == [
        "uci -P /var/run/rpcd/uci-S set network.lan.ipaddr='192.168.1.12/24'",
        "r1=$(uci -P /var/run/rpcd/uci-S add network route)",
    ]


def test_lists_render_add_and_del() -> None:
    ops = [UciOp("add_list", "wireless.w.maclist", "aa:bb"), UciOp("del_list", "wireless.w.maclist", "cc:dd")]
    assert render_uci(ops) == [
        "uci add_list wireless.w.maclist='aa:bb'",
        "uci del_list wireless.w.maclist='cc:dd'",
    ]


def test_deletes_run_last_in_descending_position() -> None:
    current = parse_uci_show(
        "dhcp.cfg01=host\ndhcp.cfg01.mac='a'\ndhcp.cfg02=host\ndhcp.cfg02.mac='b'\ndhcp.lan=dhcp\n"
    )
    ops = [UciOp("delete", "dhcp.cfg01"), UciOp("set", "dhcp.lan.start", "50"), UciOp("delete", "dhcp.cfg02")]
    assert [o.path for o in order_for_script(ops, current)] == ["dhcp.lan.start", "dhcp.cfg02", "dhcp.cfg01"]


def test_option_deletes_keep_their_place() -> None:
    current = parse_uci_show("network.lan=interface\nnetwork.lan.netmask='255.255.255.0'\n")
    ops = [UciOp("set", "network.lan.ipaddr", "10.0.0.1/24"), UciOp("delete", "network.lan.netmask")]
    assert order_for_script(ops, current) == ops


def test_del_list_dropped_when_absent() -> None:
    current = {"wireless.w.maclist": "11:22:33:44:55:66"}
    assert drop_unchanged([UciOp("del_list", "wireless.w.maclist", "aa:bb:cc:dd:ee:ff")], current) == []
    kept = [UciOp("del_list", "wireless.w.maclist", "11:22:33:44:55:66")]
    assert drop_unchanged(kept, current) == kept


def test_new_section_ops_are_never_dropped() -> None:
    ops = [UciOp("add", "dhcp.$h1", "host"), UciOp("set", "dhcp.$h1.name", "panel")]
    assert drop_unchanged(ops, {}) == ops


def test_after_applies_ops_and_ignores_new_sections() -> None:
    current = {"wireless.w.maclist": "a b", "wireless.w.macfilter": "deny"}
    ops = [
        UciOp("del_list", "wireless.w.maclist", "a"),
        UciOp("add_list", "wireless.w.maclist", "c"),
        UciOp("delete", "wireless.w.macfilter"),
        UciOp("set", "dhcp.$h1.name", "panel"),
    ]
    assert after(current, ops) == {"wireless.w.maclist": "b c"}
