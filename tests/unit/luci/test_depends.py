"""LuCI's depends rules (dispatcher.uc), checked against facts read from the router (v1.0a1 D2, D3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.luci_bridge.depends import (
    Facts,
    dir_paths,
    files_command,
    fs_paths,
    listing_command,
    missing_paths,
    parse_ls,
    uci_command,
    uci_configs,
    why_hidden,
)
from openwrtgui.probe import commands as c
from openwrtgui.probe.describe import _json_blocks
from openwrtgui.probe.luci_menu import LuciPage, parse_menu

AP2 = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "ap2" / "commands.json").read_text("utf-8")
)
PAGES = {p.path: p for p in parse_menu(_json_blocks(AP2[c.LUCI_MENU]["stdout"]))}
ACL = frozenset({"luci-mod-system-mounts", "luci-mod-network-config", "luci-app-firewall"})


def _page(*requires: dict[str, object]) -> LuciPage:
    return LuciPage("admin/x/y", "Y", "luci-x", (), (), (), "X", requires)


def test_fs_kinds() -> None:
    facts = Facts({"/sbin/block": "executable", "/etc/x": "file", "/sys/class/leds": "directory"}, {}, ACL)
    assert why_hidden(_page({"fs": {"/sbin/block": "executable"}}), facts) is None
    assert why_hidden(_page({"fs": {"/etc/x": "executable"}}), facts) == "needs /etc/x"
    assert why_hidden(_page({"fs": {"/sbin/block": "file"}}), facts) is None  # an executable is a file too
    assert why_hidden(_page({"fs": {"/sys/class/leds": "directory"}}), facts) is None
    assert why_hidden(_page({"fs": {"/usr/sbin/nft": "absent"}}), facts) is None
    assert why_hidden(_page({"fs": {"/sbin/block": "absent"}}), facts) == "is for routers without /sbin/block"


def test_an_empty_directory_is_not_a_directory_to_luci() -> None:
    facts = Facts({"/sys/class/leds": "empty directory"}, {}, ACL)
    assert why_hidden(_page({"fs": {"/sys/class/leds": "directory"}}), facts) == "needs /sys/class/leds"
    assert why_hidden(_page({"fs": {"/sys/class/leds": "absent"}}), facts) is not None  # it exists


def test_fs_alternatives_any_and_paths_all() -> None:
    routes = PAGES["admin/status/routesj"]  # ip-tiny or ip-full executable
    routes_acl = ACL | {"luci-mod-status-routes-json"}
    assert why_hidden(routes, Facts({"/usr/libexec/ip-full": "executable"}, {}, routes_acl)) is None
    both = _page({"fs": {"/usr/sbin/nft": "absent", "/usr/sbin/iptables": "executable"}})
    assert why_hidden(both, Facts({"/usr/sbin/iptables": "executable"}, {}, ACL)) is None
    with_nft = Facts({"/usr/sbin/iptables": "executable", "/usr/sbin/nft": "executable"}, {}, ACL)
    assert why_hidden(both, with_nft) == "is for routers without /usr/sbin/nft"


def test_uci_rules() -> None:
    network = {
        "network.lan": "interface",
        "network.lan.device": "br-lan",
        "network.@device[0]": "device",
        "network.@device[0].name": "br-lan",
        "network.@device[0].type": "bridge",
        "network.@switch[0]": "switch",
        "network.@switch[0].name": "switch0",
    }
    facts = Facts({}, {"network": network}, ACL)
    assert why_hidden(_page({"uci": {"network": True}}), facts) is None
    assert why_hidden(_page({"uci": {"dhcp": True}}), facts) == "needs the dhcp configuration"
    assert why_hidden(_page({"uci": {"network": {"@switch": True}}}), facts) is None
    assert why_hidden(_page({"uci": {"network": {"@device": {"type": "bridge"}}}}), facts) is None
    vlan = PAGES["admin/network/switch-vlan"]
    assert why_hidden(vlan, Facts({}, {"network": network}, ACL)) == (
        "needs a device section in network with type=bridge, name=switch, vlan_filtering=1"
    )
    with_vlan = {**network, "network.@bridge-vlan[0]": "bridge-vlan", "network.@bridge-vlan[0].vlan": "1"}
    assert why_hidden(vlan, Facts({}, {"network": with_vlan}, ACL)) is None
    # a named section: it exists, and a string is its type
    assert why_hidden(_page({"uci": {"network": {"lan": "interface"}}}), facts) is None
    assert why_hidden(_page({"uci": {"network": {"wan": True}}}), facts) == "needs network.wan"


def test_a_list_option_need_only_contain_the_value() -> None:
    network = {"network.@device[0]": "device", "network.@device[0].ports": "lan1 lan2"}
    facts = Facts({}, {"network": network}, ACL)
    assert why_hidden(_page({"uci": {"network": {"@device": {"ports": "lan2"}}}}), facts) is None


def test_acl_groups_must_exist() -> None:
    facts = Facts({"/sbin/block": "executable"}, {}, frozenset())
    assert why_hidden(PAGES["admin/system/mounts"], facts) == (
        "needs LuCI's luci-mod-system-mounts access group"
    )


def test_an_unsatisfied_parent_hides_its_pages() -> None:
    zones = PAGES["admin/network/firewall/zones"]  # its own depends pass; Network › Firewall needs fw3
    facts = Facts({}, {"firewall": {"firewall.@zone[0]": "zone", "firewall.@zone[0].name": "lan"}}, ACL)
    assert why_hidden(zones, facts) == "needs /sbin/fw3"


def test_what_the_router_is_asked() -> None:
    pages = list(PAGES.values())
    assert "/sbin/block" in fs_paths(pages) and "/usr/sbin/nft" in fs_paths(pages)
    assert dir_paths(pages) == ["/sys/class/leds"]
    assert uci_configs(pages) == ["dhcp", "firewall", "network", "wireless"]
    assert files_command(["/sbin/fw3", "/sbin/block"]) == "ls -ldL /sbin/block /sbin/fw3"
    assert listing_command("/sys/class/leds") == "ls -A /sys/class/leds"
    assert uci_command("network") == "uci -q show network"
    with pytest.raises(ValueError):
        uci_command("network; reboot")


def test_paths_are_quoted_and_read_back_whole() -> None:
    assert files_command(["/usr/share/my app/x"]) == "ls -ldL '/usr/share/my app/x'"
    listing = "-rw-r--r--    1 root     root            12 Jan  1  2025 /usr/share/my app/x\n"
    assert parse_ls(listing) == {"/usr/share/my app/x": "file"}


def test_parse_ls_kinds() -> None:
    listing = (
        "-rwxr-xr-x    1 root     root        123456 Aug 13  2024 /sbin/fw3\n"
        "drwxr-xr-x    2 root     root             0 Jan  1 00:00 /sys/class/leds\n"
        "-rw-r--r--    1 root     root           321 Aug 13  2024 /usr/share/fw3/helpers.conf\n"
        "crw-rw-rw-    1 root     root        1,   3 Jan  1 00:00 /dev/null\n"  # a device: two size columns
        "prw-r--r--    1 root     root             0 Jan  1 00:00 /tmp/fifo\n"
    )
    assert parse_ls(listing) == {
        "/sbin/fw3": "executable",
        "/sys/class/leds": "directory",
        "/usr/share/fw3/helpers.conf": "file",
        "/dev/null": "other",
        "/tmp/fifo": "other",
    }


def test_missing_paths_are_the_ones_ls_names() -> None:
    stderr = "ls: /sbin/block: No such file or directory\nls: /usr/sbin/iptables: No such file or directory\n"
    paths = ["/sbin/block", "/sbin/fw3", "/usr/sbin/iptables"]
    assert missing_paths(stderr, paths) == {"/sbin/block", "/usr/sbin/iptables"}
    # a busybox built without -L prints its usage: no path is named, so the listing does not count
    usage = "ls: unrecognized option: L\nUsage: ls [-1AaCxdLHRFplinshrSXvctu] [FILE]...\n"
    assert missing_paths(usage, paths) == set()


def test_a_symlink_counts_as_what_it_points_to() -> None:
    # `ls -ldL` prints the target's mode under the link's own name
    listing = "-rwxr-xr-x    1 root     root        303472 Aug 13  2024 /usr/sbin/iptables\n"
    facts = Facts(parse_ls(listing), {}, frozenset({"luci-mod-status-firewall"}))
    assert why_hidden(_page({"fs": {"/usr/sbin/iptables": "executable"}}), facts) is None


def test_the_reason_names_what_fails() -> None:
    network = {"network.lan": "interface", "network.lan.proto": "static"}
    facts = Facts({}, {"network": network}, ACL)
    assert (
        why_hidden(_page({"uci": {"network": True, "dhcp": True}}), facts) == "needs the dhcp configuration"
    )
    # a menu's empty section spec matches anything: the reason comes from the part that fails, never a crash
    assert why_hidden(_page({"uci": {"network": {}, "dhcp": True}}), facts) == "needs the dhcp configuration"
    assert (
        why_hidden(_page({"uci": {"network": {"lan": "interface", "wan": True}}}), facts)
        == "needs network.wan"
    )
    either = _page({"fs": [{"/usr/sbin/odhcpd": "executable"}, {"/usr/sbin/dnsmasq": "executable"}]})
    assert why_hidden(either, Facts({}, {}, ACL)) == "needs one of /usr/sbin/odhcpd, /usr/sbin/dnsmasq"
    # two alternatives failing the same way give one reason
    iptables = PAGES["admin/status/iptables"]
    nft_only = Facts({"/usr/sbin/nft": "executable"}, {}, frozenset({"luci-mod-status-firewall"}))
    assert why_hidden(iptables, nft_only) == "is for routers without /usr/sbin/nft"


def test_unread_access_groups_hide_nothing() -> None:
    facts = Facts({"/sbin/block": "executable"}, {}, None)
    assert why_hidden(PAGES["admin/system/mounts"], facts) is None
