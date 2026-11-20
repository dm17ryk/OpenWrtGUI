"""The capability map's needs (v1.2a Task 1): Air survey, Port statistics, and Connections needs the table."""

from __future__ import annotations

from openwrtgui.discovery.capabilities import CAPABILITIES, capability_map
from openwrtgui.discovery.overlay import OverlayDiff
from openwrtgui.images.profile import Profile

ORDER = [
    "Switch",
    "LTE",
    "Capture",
    "netem",
    "Firewall",
    "Monitor mode",
    "Air survey",
    "Throughput",
    "Traffic generator",
    "Connections",
    "Port statistics",
]


def _profile(programs: tuple[str, ...], modules: tuple[str, ...] = ()) -> Profile:
    return Profile.model_construct(programs=programs, modules=modules)


NONE_ADDED = OverlayDiff.model_construct(added=())


def test_new_needs_and_connections_reads_the_table() -> None:
    assert [n.name for n in CAPABILITIES] == ORDER
    needs = {n.name: n for n in CAPABILITIES}
    assert (needs["Air survey"].programs, needs["Air survey"].modules) == (("iw",), ())
    assert (needs["Port statistics"].programs, needs["Port statistics"].modules) == (("swconfig",), ())
    assert (needs["Connections"].programs, needs["Connections"].modules) == ((), ("nf_conntrack.ko",))


def test_connections_needs_the_module_not_the_program() -> None:
    rows = {r.name: r for r in capability_map(_profile(("/usr/sbin/iw",), ("nf_conntrack.ko",)), NONE_ADDED)}
    assert rows["Connections"].state == "in image"
    assert rows["Air survey"].state == "in image"
    missing = {r.name: r for r in capability_map(_profile(()), NONE_ADDED)}
    assert (missing["Connections"].state, missing["Connections"].reason) == (
        "missing",
        "needs nf_conntrack.ko",
    )
    assert missing["Port statistics"].reason == "needs swconfig"
