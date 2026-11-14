"""Which LuCI pages have a screen in the app (spec section 8); the rest open as fallback pages."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from openwrtgui.luci_bridge.depends import Facts, why_hidden
from openwrtgui.probe.luci_menu import SECTION_SEP, LuciPage

# LuCI page → the app screen that replaces it. Grows as native screens arrive (the roadmap's parity).
NATIVE: dict[str, str] = {
    "admin/network/wireless": "wifi",
    "admin/status/overview": "dashboard",
    "admin/network/network": "network",
    "admin/network/dhcp": "network",
    "admin/network/dns": "network",
    "admin/network/routes": "network",
    "admin/status/routes": "network",
    "admin/status/routesj": "network",  # the JSON variant; LuCI shows one of the two
    "admin/network/switch": "ports",
    "admin/network/firewall": "firewall",
    "admin/network/firewall/zones": "firewall",
    "admin/network/firewall/forwards": "firewall",
    "admin/network/firewall/rules": "firewall",
    "admin/network/firewall/snats": "firewall",
    "admin/network/firewall/ipsets": "firewall",
    "admin/network/firewall/custom": "firewall",
    "admin/status/nftables": "firewall",
    # v0.6b D11: the System screen; v0.6c D1: Administration and LEDs too (Mount points stays LuCI's: its page
    # needs block-mount, D8)
    "admin/system/admin": "system",
    "admin/system/admin/password": "system",
    "admin/system/admin/pwpolicy": "system",
    "admin/system/admin/dropbear": "system",
    "admin/system/admin/sshkeys": "system",
    "admin/system/admin/uhttpd": "system",
    "admin/system/admin/repokeys": "system",
    "admin/system/leds": "system",
    "admin/status/logs": "system",
    "admin/status/logs/syslog": "system",
    "admin/status/logs/dmesg": "system",
    "admin/status/processes": "system",
    "admin/status/realtime": "system",
    "admin/status/realtime/load": "system",
    "admin/status/realtime/bandwidth": "system",
    "admin/status/realtime/connections": "system",
    "admin/system/system": "system",
    "admin/system/startup": "system",
    "admin/system/crontab": "system",
    "admin/system/reboot": "system",
    "admin/system/flash": "system",
    "admin/network/diagnostics": "system",
    # v0.7 D13: Status › Channel analysis is RF live's channel analysis
    "admin/status/channel_analysis": "rf",
    # v1.0a1 D5: Status › Realtime Graphs › Wireless is RF live (rates, signal and noise, live)
    "admin/status/realtime/wireless": "rf",
}


@dataclass(frozen=True)
class PageView:
    path: str
    title: str
    package: str
    native: str | None
    section: str = ""
    label: str = ""  # unique on the router: "Status › Firewall (nftables)"
    available: bool = True  # LuCI shows it on this router (v1.0a1 D4)
    missing: str | None = None  # why LuCI does not: "needs /sbin/block"
    checked: bool = True  # False: the router's facts could not be read, so nothing is hidden (D3)


def _label(p: LuciPage) -> str:
    return f"{p.section}{SECTION_SEP}{p.title}" if p.section else p.title


def page_views(pages: Sequence[LuciPage], facts: Facts | None = None) -> list[PageView]:
    # LuCI hides one of two same-titled pages by its dependencies; the label tells them apart either way.
    counts = Counter(_label(p) for p in pages)
    views = []
    for p in pages:
        missing = why_hidden(p, facts) if facts is not None else None
        views.append(
            PageView(
                p.path,
                p.title,
                p.package,
                NATIVE.get(p.path),
                p.section,
                _label(p) if counts[_label(p)] == 1 else f"{_label(p)} ({p.path.rsplit('/', 1)[-1]})",
                available=missing is None,
                missing=missing,
                checked=facts.checked if facts is not None else True,
            )
        )
    return views


def fallback_pages(pages: Sequence[LuciPage]) -> list[LuciPage]:
    return [p for p in pages if p.path not in NATIVE]
