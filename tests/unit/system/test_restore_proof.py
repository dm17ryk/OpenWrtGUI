"""The restore's proof (v0.6c D11) as AP2 taught it on 2026-11-13 (HW-3), and as PR #61's review sharpened it:
a uci-defaults script the first boot consumed is not a difference (one still there must match), and a config
is proven by its settings: options exactly, lists by every item of the backup (the boot may add items)."""

from __future__ import annotations

import hashlib
import io
import tarfile

import pytest

from openwrtgui.system import commands as s
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
DISABLE_PATH = "/etc/uci-defaults/10_disable_services"
KEYS_PATH = "/etc/dropbear/authorized_keys"


def _archive(files: dict[str, str]) -> ArchiveInfo:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return read_archive(raw.getvalue())


def _ok(out: str) -> CommandResult:
    return CommandResult("", out, "", 0)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


INFO = _archive(
    {
        "etc/config/firewall": FIREWALL,
        "etc/config/system": SYSTEM,
        "etc/dropbear/authorized_keys": KEYS,
        "etc/uci-defaults/10_disable_services": DISABLE,
    }
)
FILES_CMD = s.file_digests([KEYS_PATH, DISABLE_PATH])  # the archive's order
WAN = "firewall.@zone[1]=zone\nfirewall.@zone[1].name='wan'\nfirewall.@zone[1].network={}\n"
LAN = "firewall.@zone[0]=zone\nfirewall.@zone[0].name='lan'\nfirewall.@zone[0].network='lan'\n"


def _system(hostname: str) -> dict[str, CommandResult]:
    shown = f"system.@system[0]=system\nsystem.@system[0].hostname={hostname}\n"
    return {s.uci_show_config("system"): _ok(shown)}


def _firewall(network: str) -> dict[str, CommandResult]:
    return {s.uci_show_config("firewall"): _ok(LAN + WAN.format(network))}


def test_the_proof_takes_configs_by_settings_and_every_other_file_by_sha256() -> None:
    assert [f.path for f in provable(INFO)] == [KEYS_PATH, DISABLE_PATH]
    assert [name for name, _ in proven_configs(INFO)] == ["firewall", "system"]


def test_the_config_read_is_a_catalog_command() -> None:
    assert s.uci_show_config("firewall") == "uci -X show firewall"
    with pytest.raises(ValueError):
        s.uci_show_config("firewall; reboot")


async def test_a_consumed_uci_defaults_script_is_not_a_difference() -> None:
    """The first boot ran 10_disable_services and deleted it (AP2, HW-3): sha256sum says it is gone."""
    files = {
        FILES_CMD: CommandResult(
            FILES_CMD,
            f"{_digest(KEYS)}  {KEYS_PATH}\n",
            f"sha256sum: {DISABLE_PATH}: No such file or directory\n",
            1,
        )
    }
    t = ReplayTransport(files | _firewall("'wan' 'wan6' 'lte' 'lte'") | _system("'OpenWrt'"))
    assert await differing(t, provable(INFO), proven_configs(INFO)) == []


async def test_a_uci_defaults_script_still_there_must_match() -> None:
    """OpenWrt keeps a script that failed: one still there is proven like any other file."""
    files = {FILES_CMD: _ok(f"{_digest('changed')}  {DISABLE_PATH}\n{_digest(KEYS)}  {KEYS_PATH}\n")}
    t = ReplayTransport(files | _firewall("'wan' 'wan6' 'lte'") | _system("'OpenWrt'"))
    assert await differing(t, provable(INFO), proven_configs(INFO)) == [DISABLE_PATH]


async def test_another_missing_file_still_differs() -> None:
    gone = f"sha256sum: {KEYS_PATH}: No such file or directory\n"
    files = {FILES_CMD: CommandResult(FILES_CMD, f"{_digest(DISABLE)}  {DISABLE_PATH}\n", gone, 1)}
    t = ReplayTransport(files | _firewall("'wan' 'wan6' 'lte'") | _system("'OpenWrt'"))
    assert await differing(t, provable(INFO), proven_configs(INFO)) == [KEYS_PATH]


@pytest.mark.parametrize(
    ("network", "holds"),
    [
        ("'wan' 'wan6' 'lte' 'lte'", True),  # the boot staged one more lte, uci-defaults' uci commit kept it
        ("'lte' 'wan6' 'wan'", True),  # the same items in another order
        ("'wan' 'wan6'", False),  # an item of the backup is missing
        ("'wan' 'wan6' 'lte6'", False),
    ],
)
async def test_a_list_holds_when_every_backup_item_is_there(network: str, holds: bool) -> None:
    firewall = _archive({"etc/config/firewall": FIREWALL})
    t = ReplayTransport(_firewall(network))
    assert await differing(t, [], proven_configs(firewall)) == ([] if holds else ["/etc/config/firewall"])


@pytest.mark.parametrize(
    ("backup", "router", "holds"),
    [
        ("'OpenWrt'", "'OpenWrt'", True),
        ("'OpenWrt'", "'OpenWrt lab'", False),  # an extra word is another value
        ("'OpenWrt'", "'changed'", False),
        ("''", "''", True),
        ("''", "'set'", False),  # an empty option is not "anything"
        ("'OpenWrt'", "'OpenWrt' 'OpenWrt2'", False),  # an option that became a list
    ],
)
async def test_an_option_must_match_exactly(backup: str, router: str, holds: bool) -> None:
    system = _archive({"etc/config/system": f"config system\n\toption hostname {backup}\n"})
    t = ReplayTransport(_system(router))
    assert await differing(t, [], proven_configs(system)) == ([] if holds else ["/etc/config/system"])


async def test_libuci_section_names_read_as_uci_show_names() -> None:
    """`uci -X show` (the catalog command, and the simulator) names an unnamed section cfgXXXXXX."""
    system = _archive({"etc/config/system": SYSTEM})
    shown = "system.cfg01e48a=system\nsystem.cfg01e48a.hostname='OpenWrt'\n"
    answer = {s.uci_show_config("system"): _ok(shown)}
    assert await differing(ReplayTransport(answer), [], proven_configs(system)) == []


async def test_a_config_missing_on_the_router_differs() -> None:
    """Any failed read counts as missing: uci answers "Entry not found" with a non-zero exit."""
    system = _archive({"etc/config/system": SYSTEM})
    answer = {s.uci_show_config("system"): CommandResult("", "", "uci: Entry not found\n", 1)}
    assert await differing(ReplayTransport(answer), [], proven_configs(system)) == ["/etc/config/system"]


def test_a_config_name_uci_cannot_take_is_proven_by_its_sha256() -> None:
    odd = _archive({"etc/config/my.conf": "config x\n"})
    assert proven_configs(odd) == ()
    assert [f.path for f in provable(odd)] == ["/etc/config/my.conf"]
