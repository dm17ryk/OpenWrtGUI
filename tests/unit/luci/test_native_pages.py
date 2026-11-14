"""LuCI pages with a native screen (spec section 8): v0.7 adds Status › Channel analysis."""

from __future__ import annotations

from openwrtgui.luci_bridge.pages import NATIVE, NATIVE_TAB, page_views
from openwrtgui.probe.luci_menu import LuciPage

# the tab ids of frontend/src/screens/system/SystemScreen.tsx and fw/FirewallScreen.tsx, with v1.0a2's
SCREEN_TABS = {
    "system": {
        "status",
        "logs",
        "processes",
        "diagnostics",
        "settings",
        "access",
        "plugins",
        "services",
        "cron",
        "leds",
        "mounts",
        "backup",
    },
    "firewall": {"zones", "rules", "forwards", "nat", "ipsets", "custom", "tables", "raw", "iptables"},
}


def test_channel_analysis_is_native() -> None:
    assert NATIVE["admin/status/channel_analysis"] == "rf"


def test_realtime_wireless_is_rf_live() -> None:
    """v1.0a1 D5: Status › Realtime Graphs › Wireless is RF live (spec 8: "RF live (wireless)")."""
    assert NATIVE["admin/status/realtime/wireless"] == "rf"


def test_a_native_page_names_its_screens_tab() -> None:
    """v1.0a2 D3: a native page that is one tab of its screen opens that tab."""
    leds = LuciPage("admin/system/leds", "LED Configuration", "luci-mod-system", (), (), ())
    rules = LuciPage("admin/network/firewall/rules", "Traffic Rules", "luci-app-firewall", (), (), ())
    wifi = LuciPage("admin/network/wireless", "Wireless", "luci-mod-network", (), (), ())
    views = {v.path: v for v in page_views([leds, rules, wifi])}
    assert (views["admin/system/leds"].native, views["admin/system/leds"].tab) == ("system", "leds")
    assert views["admin/network/firewall/rules"].tab == "rules"
    assert views["admin/network/wireless"].tab is None  # a screen without tabs


def test_plugins_is_system_plugins() -> None:
    plugins = LuciPage("admin/system/plugins", "Plugins", "luci-mod-system", ("luci-mod-system-plugins",), (), ())
    (view,) = page_views([plugins])
    assert (view.native, view.tab) == ("system", "plugins")


def test_every_tab_is_one_its_screen_has() -> None:
    for path, tab in NATIVE_TAB.items():
        assert path in NATIVE, path
        assert tab in SCREEN_TABS[NATIVE[path]], (path, tab)
