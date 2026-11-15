"""v1.0a2 D10b: LuCI checks each menu node's acl on the way down (dispatcher.uc), so a page's bridge session
gets its ancestors' groups too. Before, a page whose own entry names none got only its package's."""

from __future__ import annotations

from openwrtgui.luci_bridge.session import page_groups
from openwrtgui.probe.luci_menu import LuciPage

ACL = {"luci-base": {}, "luci-mod-status-firewall": {}, "luci-app-firewall": {}}


def test_a_pages_session_gets_its_ancestors_groups() -> None:
    # Status › Firewall › iptables (fw4's sub-route): no depends of its own, its parent needs the firewall ACL
    sub = LuciPage(
        "admin/status/nftables/iptables",
        "",
        "luci-mod-status",
        (),
        (),
        (),
        requires=({"acl": ["luci-mod-status-firewall"], "fs": {"/usr/sbin/nft": "executable"}},),
    )
    assert "luci-mod-status-firewall" in page_groups(sub, ACL)


def test_a_page_without_its_own_groups_keeps_its_package_group() -> None:
    """final review (re-graded): D10b must not drop the package fallback a page had before v1.0a2."""
    acl = {**ACL, "luci-app-sqm": {}}
    page = LuciPage(
        "admin/network/sqm/extra",
        "Extra",
        "luci-app-sqm",
        (),
        (),
        (),
        requires=({"acl": ["luci-mod-status-firewall"]},),
    )
    groups = page_groups(page, acl)
    assert "luci-app-sqm" in groups and "luci-mod-status-firewall" in groups


def test_groups_the_router_lacks_are_left_out() -> None:
    page = LuciPage(
        "admin/x/y",
        "Y",
        "pkg",
        ("luci-app-firewall",),
        (),
        (),
        requires=({"acl": ["gone"]}, {"acl": ["luci-app-firewall"]}),
    )
    groups = page_groups(page, ACL)
    assert "gone" not in groups and groups[0] == "luci-app-firewall"
