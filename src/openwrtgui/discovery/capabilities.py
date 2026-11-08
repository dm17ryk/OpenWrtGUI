"""The capability map (spec 5, 7.8): each capability in the image, added after flashing, or missing.

A capability needs programs (found by name in the PATH directories) and kernel modules.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.discovery.overlay import OverlayDiff
from openwrtgui.images.profile import PATH_DIRS, Profile


@dataclass(frozen=True)
class CapabilityNeed:
    name: str
    programs: tuple[str, ...]
    modules: tuple[str, ...] = ()


CAPABILITIES = (
    CapabilityNeed("Switch", ("swconfig",)),
    CapabilityNeed("LTE", ("uqmi",)),
    CapabilityNeed("Capture", ("tcpdump",)),
    CapabilityNeed("netem", ("tc",), ("sch_netem.ko",)),
    CapabilityNeed("Firewall", ("fw4",)),
    CapabilityNeed("Monitor mode", ("iw",)),
    CapabilityNeed("Throughput", ("iperf3",)),
    CapabilityNeed("Traffic generator", ("socat",)),
    CapabilityNeed("Connections", ("conntrack",)),
)


class CapabilityRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    state: Literal["in image", "added after flashing", "missing"]
    reason: str | None = None


def _names(paths: list[str] | tuple[str, ...]) -> set[str]:
    return {posixpath.basename(p) for p in paths if posixpath.dirname(p) in PATH_DIRS}


def capability_map(profile: Profile, overlay: OverlayDiff) -> tuple[CapabilityRow, ...]:
    image = _names(profile.programs) | set(profile.modules)
    added = _names([e.path for e in overlay.added]) | {
        posixpath.basename(e.path) for e in overlay.added if e.path.endswith(".ko")
    }
    rows: list[CapabilityRow] = []
    for need in CAPABILITIES:
        wanted = [*need.programs, *need.modules]
        if all(w in image for w in wanted):
            rows.append(CapabilityRow(name=need.name, state="in image"))
        elif all(w in image | added for w in wanted):
            rows.append(CapabilityRow(name=need.name, state="added after flashing"))
        else:
            first = next(w for w in wanted if w not in image | added)
            rows.append(CapabilityRow(name=need.name, state="missing", reason=f"needs {first}"))
    return tuple(rows)
