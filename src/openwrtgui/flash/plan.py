"""The flash preview (v0.5 plan, "Flash rules"): every check before anything is sent, then the exact steps.

The image goes to /tmp/owg on the router, is checked there (sha256, validate_firmware_image, sysupgrade -T),
and sysupgrade is started by the router-side timer 2 s later, so the app's own exec returns and is audited.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from openwrtgui.discovery import commands as cmd
from openwrtgui.discovery.overlay import parse_ls_ldn
from openwrtgui.guard.writes import upload_line
from openwrtgui.images.profile import Profile
from openwrtgui.net.state import NetworkState
from openwrtgui.timer import arm_command
from openwrtgui.transport.base import Transport, ubus_command

KEEP_LINE = "grep -qx /etc/owg/ /etc/sysupgrade.conf || echo /etc/owg/ >> /etc/sysupgrade.conf"
MARGIN = 4 * 2**20
TIMER = "flash"


class FlashRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    board: str
    revision: str
    sha256: str
    keep_settings: bool = True
    isolated: bool = False


@dataclass(frozen=True)
class FlashFacts:
    board_name: str
    revision: str
    mem_available_kb: int
    tmp_free_kb: int
    owg_dir: bool
    dhcp_on_own: str | None


@dataclass(frozen=True)
class FlashPlan:
    lines: tuple[str, ...]
    warnings: tuple[str, ...]
    upload_command: str
    digest: str


def fw_path(sha256: str) -> str:
    return f"/tmp/owg/fw-{sha256[:12]}.bin"


def _kb(text: str, key: str) -> int:
    for line in text.splitlines():
        if line.startswith(key):
            words = line.split()
            if len(words) >= 2 and words[1].isdigit():
                return int(words[1])
    return 0


def _df_free(text: str) -> int:
    lines = [ln.split() for ln in text.splitlines()[1:] if ln.split()]
    return int(lines[-1][3]) if lines and len(lines[-1]) > 3 and lines[-1][3].isdigit() else 0


async def read_facts(t: Transport, board_name: str, revision: str, net: NetworkState) -> FlashFacts:
    """RAM and /tmp free, whether the app saved files under /etc/owg, and DHCP on the app's interface."""
    mem = _kb((await t.run(cmd.MEMINFO)).stdout, "MemAvailable:")
    tmp = _df_free((await t.run(cmd.DF_TMP)).stdout)
    entries, _ = parse_ls_ldn((await t.run(cmd.OVERLAY_LS)).stdout, "/overlay/upper")
    owg = any(e.path.startswith("/etc/owg/") for e in entries)
    own = net.own_interface
    dhcp = own if own and any(d.interface == own and d.enabled for d in net.dhcp) else None
    return FlashFacts(board_name, revision, mem, tmp, owg, dhcp)


def flash_plan(
    router_name: str, profile: Profile, image: bytes, req: FlashRequest, facts: FlashFacts
) -> FlashPlan:
    if profile.source != "image":
        raise ValueError("Flash needs the image file: import it in Settings › Images")
    if hashlib.sha256(image).hexdigest() != profile.key.sha256:
        raise ValueError(f"{profile.image_name} changed on disk since it was imported; import it again")
    if not profile.boards:
        raise ValueError(
            "The image does not say which boards it is for; flash it with LuCI or sysupgrade -F by hand"
        )
    if facts.board_name not in profile.boards:
        raise ValueError(
            f"This image is for {', '.join(profile.boards)}; {router_name} is {facts.board_name}"
        )
    if not req.keep_settings and not req.isolated:
        raise ValueError(f"Confirm that {router_name} is isolated from the bench LAN first")
    needs = len(image) + MARGIN
    free = min(facts.mem_available_kb, facts.tmp_free_kb) * 1024
    if facts.mem_available_kb * 1024 < needs or facts.tmp_free_kb * 1024 < len(image):
        raise ValueError(
            f"{router_name} has {free // 2**20} MB of RAM free; "
            f"the image needs {math.ceil(needs / 2**20)} MB in /tmp"
        )
    path = fw_path(profile.key.sha256)
    upload = f"cat > {path}"
    lines = [
        "mkdir -p /tmp/owg",
        upload_line(upload, profile.image_name or "image.bin", image),
        f"sha256sum {path}",
        ubus_command("system", "validate_firmware_image", {"path": path}),
        f"sysupgrade -T {path}",
    ]
    if req.keep_settings and facts.owg_dir:
        lines.append(KEEP_LINE)
    lines.append(arm_command(TIMER, 2, [f"sysupgrade {'' if req.keep_settings else '-n '}{path}"]))
    warnings = [
        f"{router_name} reboots and is off the network for about 3 minutes. "
        "Once sysupgrade starts it cannot be stopped."
    ]
    if facts.dhcp_on_own:
        warnings.append(
            f"{router_name} hands out addresses on {facts.dhcp_on_own}. "
            "Devices there get no new address while it flashes (about 3 minutes)."
        )
    if not req.keep_settings:
        warnings.append(
            f"Without settings {router_name} comes back as 192.168.1.1 with no password. "
            "Connect it alone to this PC, then add it again."
        )
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
    return FlashPlan(tuple(lines), tuple(warnings), upload, digest)
