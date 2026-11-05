from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.luci_bridge.pages import page_views
from openwrtgui.luci_bridge.session import (
    create_command,
    destroy_command,
    grant_commands,
    page_groups,
    set_command,
)
from openwrtgui.probe import commands as c
from openwrtgui.probe.describe import _json_blocks
from openwrtgui.probe.luci_menu import LuciPage, parse_acl, parse_menu

AP2 = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "ap2" / "commands.json").read_text("utf-8")
)
MENUS = _json_blocks(AP2[c.LUCI_MENU]["stdout"])
ACL = parse_acl(_json_blocks(AP2[c.LUCI_ACL]["stdout"]))


def test_menu_pages_from_ap2_recording() -> None:
    pages = parse_menu(MENUS)
    wireless = next(p for p in pages if p.path == "admin/network/wireless")
    assert wireless == LuciPage(
        "admin/network/wireless",
        "Wireless",
        "luci-mod-network",
        ("luci-mod-network-config",),
        ("wireless",),
        (),
        "Network",
    )
    assert len(pages) == 42 and [p.path for p in pages] == sorted(p.path for p in pages)
    untitled = next(p for p in pages if p.path == "admin/status/nftables/iptables")
    assert untitled.title == "iptables"


def test_pages_carry_their_menu_section() -> None:
    by_path = {p.path: p for p in parse_menu(MENUS)}
    assert by_path["admin/network/dhcp"].section == "Network"
    assert by_path["admin/network/firewall/zones"].section == "Network › Firewall"
    assert by_path["admin/status/realtime/wireless"].section == "Status › Realtime Graphs"


def test_page_labels_tell_same_titled_pages_apart() -> None:
    views = {v.path: v for v in page_views(parse_menu(MENUS))}
    assert views["admin/network/routes"].label == "Network › Routing"
    assert views["admin/status/realtime/wireless"].label == "Status › Realtime Graphs › Wireless"
    assert views["admin/status/iptables"].label == "Status › Firewall (iptables)"
    assert views["admin/status/nftables"].label == "Status › Firewall (nftables)"
    labels = [v.label for v in views.values()]
    assert len(labels) == len(set(labels))


def test_acl_groups_merge_across_files() -> None:
    assert {"luci-base", "luci-mod-network-config", "luci-app-firewall"} <= set(ACL)
    assert ACL["luci-mod-network-config"]["write"]["ubus"]["hostapd.*"] == ["del_client"]


def test_a_group_defined_in_two_files_keeps_both_parts() -> None:
    # AP2: `unauthenticated` is in luci-base.json (luci getFeatures) and unauthenticated.json (session login)
    ubus = ACL["unauthenticated"]["read"]["ubus"]
    assert "getFeatures" in ubus["luci"] and "login" in ubus["session"]
    dhcp = next(p for p in parse_menu(MENUS) if p.path == "admin/network/dhcp")
    grants = " ".join(grant_commands("s1", page_groups(dhcp, ACL), ACL, "read"))
    assert '["luci","getFeatures"]' in grants


def test_merge_unions_lists_and_methods() -> None:
    merged = parse_acl(
        {
            "a": {"g": {"read": {"ubus": {"x": ["m1"]}, "uci": ["one"]}}},
            "b": {
                "g": {
                    "read": {"ubus": {"x": ["m2", "m1"], "y": ["n"]}, "uci": ["two"]},
                    "write": {"uci": ["one"]},
                }
            },
        }
    )
    assert merged["g"] == {
        "read": {"ubus": {"x": ["m1", "m2"], "y": ["n"]}, "uci": ["one", "two"]},
        "write": {"uci": ["one"]},
    }


def test_page_views_mark_native() -> None:
    views = {v.path: v for v in page_views(parse_menu(MENUS))}
    assert views["admin/network/wireless"].native == "wifi"
    assert views["admin/status/overview"].native == "dashboard"
    assert views["admin/network/dhcp"].native is None


def test_page_groups_fall_back_to_the_package() -> None:
    pages = {p.path: p for p in parse_menu(MENUS)}
    assert page_groups(pages["admin/network/wireless"], ACL)[0] == "luci-mod-network-config"
    assert page_groups(pages["admin/network/firewall/zones"], ACL)[0] == "luci-app-firewall"
    assert "luci-base" in page_groups(pages["admin/network/wireless"], ACL)


def _grants(access: str) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for cmd in grant_commands("S1D", ["luci-mod-network-config"], ACL, access):  # type: ignore[arg-type]
        args = json.loads(cmd.split(" ", 4)[4].strip("'"))
        assert cmd.startswith("ubus call session grant ") and args["ubus_rpc_session"] == "S1D"
        out[args["scope"]] = args["objects"]
    return out


def test_grant_commands_expand_read_only() -> None:
    read = _grants("read")
    assert ["luci-mod-network-config", "read"] in read["access-group"]
    assert ["iwinfo", "assoclist"] in read["ubus"]
    assert ["hostapd.*", "del_client"] not in read["ubus"]
    assert ["wireless", "read"] in read["uci"] and ["wireless", "write"] not in read["uci"]


def test_grant_commands_with_write() -> None:
    write = _grants("write")
    assert ["luci-mod-network-config", "write"] in write["access-group"]
    assert ["hostapd.*", "del_client"] in write["ubus"] and ["iwinfo", "assoclist"] in write["ubus"]
    assert ["wireless", "write"] in write["uci"]


def test_session_commands() -> None:
    assert create_command() == "ubus call session create '{\"timeout\":300}'"
    assert set_command("S1D", "T0K") == (
        'ubus call session set \'{"ubus_rpc_session":"S1D","values":{"token":"T0K","username":"root"}}\''
    )
    assert destroy_command("S1D") == 'ubus call session destroy \'{"ubus_rpc_session":"S1D"}\''
