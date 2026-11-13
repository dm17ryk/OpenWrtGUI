"""The restore's proof (v0.6c D11) as AP2 taught it on 2026-11-13 (HW-3): OpenWrt's own uci-defaults are
consumed at the first boot, and a config is proven by its settings, which the boot may add to."""

from __future__ import annotations

import hashlib
import io
import tarfile

from openwrtgui.system.archive import ArchiveInfo, read_archive
from openwrtgui.system.restore import differing, provable, proven_configs
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport

FIREWALL = (
    "config zone\n\toption name 'lan'\n\tlist network 'lan'\n"
    "config zone\n\toption name 'wan'\n\tlist network 'wan'\n\tlist network 'wan6'\n\tlist network 'lte'\n"
)
SYSTEM = "config system\n\toption hostname 'OpenWrt'\n"
KEYS = "ssh-ed25519 AAAAexample test@example\n"
DISABLE = "/etc/init.d/sysntpd disable\nexit 0\n"


def _archive(files: dict[str, str]) -> ArchiveInfo:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return read_archive(raw.getvalue())


def _ok(command: str, out: str) -> CommandResult:
    return CommandResult(command, out, "", 0)


INFO = _archive(
    {
        "etc/config/firewall": FIREWALL,
        "etc/config/system": SYSTEM,
        "etc/dropbear/authorized_keys": KEYS,
        "etc/uci-defaults/10_disable_services": DISABLE,
    }
)


def test_uci_defaults_are_not_proven_and_configs_go_by_their_settings() -> None:
    """sysupgrade -b adds 10_disable_services; the first boot runs and deletes it (HW-3: it "differed")."""
    assert [f.path for f in provable(INFO)] == ["/etc/dropbear/authorized_keys"]
    assert [name for name, _ in proven_configs(INFO)] == ["firewall", "system"]


async def test_a_config_holds_when_the_boot_added_to_it() -> None:
    """AP2 after the restore: the boot staged `network+='lte'` and uci-defaults' `uci commit` kept it."""
    digest = hashlib.sha256(KEYS.encode()).hexdigest()
    t = ReplayTransport(
        {
            "sha256sum '/etc/dropbear/authorized_keys'": _ok(
                "", f"{digest}  /etc/dropbear/authorized_keys\n"
            ),
            "uci -q show firewall": _ok(
                "",
                "firewall.@zone[0]=zone\nfirewall.@zone[0].name='lan'\nfirewall.@zone[0].network='lan'\n"
                "firewall.@zone[1]=zone\nfirewall.@zone[1].name='wan'\n"
                "firewall.@zone[1].network='wan' 'wan6' 'lte' 'lte'\nfirewall.@zone[1].input='REJECT'\n",
            ),
            "uci -q show system": _ok("", "system.@system[0]=system\nsystem.@system[0].hostname='OpenWrt'\n"),
        }
    )
    assert await differing(t, provable(INFO), proven_configs(INFO)) == []


async def test_a_setting_that_did_not_take_differs() -> None:
    t = ReplayTransport(
        {
            "uci -q show firewall": _ok(
                "",
                "firewall.@zone[0]=zone\nfirewall.@zone[0].name='lan'\nfirewall.@zone[0].network='lan'\n"
                "firewall.@zone[1]=zone\nfirewall.@zone[1].name='wan'\nfirewall.@zone[1].network='wan'\n",
            ),
            "uci -q show system": _ok("", "system.@system[0]=system\nsystem.@system[0].hostname='changed'\n"),
        }
    )
    assert await differing(t, [], proven_configs(INFO)) == ["/etc/config/firewall", "/etc/config/system"]


async def test_libuci_section_names_read_as_uci_show_names() -> None:
    """`uci -X show` (and the simulator) names an unnamed section cfgXXXXXX; `uci show` says @type[n]."""
    system = _archive({"etc/config/system": SYSTEM})
    t = ReplayTransport(
        {"uci -q show system": _ok("", "system.cfg01e48a=system\nsystem.cfg01e48a.hostname='OpenWrt'\n")}
    )
    assert await differing(t, [], proven_configs(system)) == []


async def test_a_config_missing_on_the_router_differs() -> None:
    system = _archive({"etc/config/system": SYSTEM})
    t = ReplayTransport({"uci -q show system": CommandResult("uci -q show system", "", "", 1)})
    assert await differing(t, [], proven_configs(system)) == ["/etc/config/system"]


def test_a_config_name_uci_cannot_take_is_proven_by_its_sha256() -> None:
    odd = _archive({"etc/config/my.conf": "config x\n"})
    assert proven_configs(odd) == ()
    assert [f.path for f in provable(odd)] == ["/etc/config/my.conf"]
