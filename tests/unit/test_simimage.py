"""simimage.py: the simulated router's image side (/rom, overlay, packages, firmware partition, reflash)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from openwrtgui.discovery.commands import (
    APK_DB,
    CONFIG_LIST,
    MEMINFO,
    OVERLAY_LS,
    PROC_MTD,
    ROM_APK_DB,
    ROM_LS,
    SYSUPGRADE_LIST,
    firmware_hash,
    uci_show,
)
from openwrtgui.discovery.overlay import parse_ls_ldn
from openwrtgui.images.sysupgrade import parse_layout
from openwrtgui.simulator import SimConnector
from openwrtgui.timer import arm_command
from openwrtgui.transport.base import Transport, Unreachable
from openwrtgui.transport.fake import ReplayTransport

ROOT = Path(__file__).resolve().parents[2]
SIM_DIR = ROOT / "tests" / "fixtures" / "sim"
MINI = (ROOT / "tests" / "fixtures" / "images" / "mini-r35692.bin").read_bytes()
NEWER = (ROOT / "tests" / "fixtures" / "images" / "mini-r35700.bin").read_bytes()
KEY = [Path("app_key")]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _mini_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("mini_image", ROOT / "tools" / "mini_image.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mini_image"] = module
    spec.loader.exec_module(module)
    return module


async def _connect(sim: SimConnector, host: str) -> Transport:
    return await sim.connect(host, 22, password=None, key_paths=KEY)


async def test_sim_lists_the_overlay_and_rom() -> None:
    t = await _connect(SimConnector(SIM_DIR, clock=Clock()), "192.168.1.1")
    out = (await t.run(OVERLAY_LS)).stdout
    entries, unreadable = parse_ls_ldn(out, "/overlay/upper")
    assert unreadable == 0
    kinds = {e.path: e.kind for e in entries}
    assert kinds["/usr/sbin/wifi-mirror"] == "file"
    assert kinds["/etc/uci-defaults/20_dwr921_c3_uboot_luci"] == "whiteout"
    assert kinds["/etc/config/dropbear"] == "file"
    assert re.search(r"^c\S+ +\d+ +0 +0 +0, +0 .*/20_dwr921_c3_uboot_luci$", out, re.M)
    assert "dwr921-portctl" in (await t.run(ROM_APK_DB)).stdout
    rom, bad = parse_ls_ldn((await t.run(ROM_LS)).stdout, "/rom")
    assert bad == 0
    assert next(e for e in rom if e.path == "/bin/sh").target == "busybox"


async def test_sim_package_db_and_configs() -> None:
    t = await _connect(SimConnector(SIM_DIR, clock=Clock()), "192.168.1.1")
    assert "P:iperf3" in (await t.run(APK_DB)).stdout
    assert "P:dwr921-portctl" in (await t.run(APK_DB)).stdout
    assert "dropbear.@dropbear[0].Port='2222'" in (await t.run(uci_show("dropbear"))).stdout
    configs = (await t.run(CONFIG_LIST)).stdout.split()
    assert {"dropbear", "dhcp", "network", "wireless", "dwr921-internet-led"} <= set(configs)
    assert "/etc/config/dropbear" in (await t.run(SYSUPGRADE_LIST)).stdout.split()
    assert "MemAvailable:" in (await t.run(MEMINFO)).stdout
    assert '"firmware"' in (await t.run(PROC_MTD)).stdout


async def test_sim_firmware_hash() -> None:
    sim = SimConnector(SIM_DIR, clock=Clock())
    length = parse_layout(MINI, "m").firmware_len
    assert length is not None
    expected = hashlib.sha256(MINI[:length]).hexdigest()
    ap2 = await _connect(sim, "192.168.1.2")
    assert (await ap2.run(firmware_hash(3, length))).stdout.split()[0] == expected
    ap1 = await _connect(sim, "192.168.1.1")
    assert (await ap1.run(firmware_hash(3, length))).stdout.split()[0] != expected


async def test_sim_services_help_and_the_keep_line() -> None:
    t = await _connect(SimConnector(SIM_DIR, clock=Clock()), "192.168.1.1")
    running = 'ubus call service list \'{"name":"wifi-mirror"}\''
    assert json.loads((await t.run(running)).stdout)["wifi-mirror"]["instances"]
    assert (await t.run("/etc/init.d/wifi-mirror stop")).ok
    assert json.loads((await t.run(running)).stdout) == {}
    assert (await t.run("/etc/init.d/wifi-mirror enabled; echo $?")).stdout == "0\n"
    helped = await t.run("timeout 5 /usr/sbin/wifi-mirror --help 2>&1 | head -c 8192")
    assert helped.stdout.startswith("Usage: wifi-mirror {start|stop|status}")
    led = await t.run("timeout 5 /usr/sbin/dwr921-internet-led --help 2>&1 | head -c 8192")
    assert (led.stdout, led.exit_status) == ("", 0)
    keep = "grep -qx /etc/owg/ /etc/sysupgrade.conf || echo /etc/owg/ >> /etc/sysupgrade.conf"
    assert (await t.run(keep)).ok
    assert "/etc/owg/" in (await t.run("cat /etc/sysupgrade.conf")).stdout.split()


async def _flash(sim: SimConnector, clock: Clock, host: str, image: bytes, keep: bool) -> str:
    t = await _connect(sim, host)
    path = f"/tmp/owg/fw-{hashlib.sha256(image).hexdigest()[:12]}.bin"
    assert isinstance(t, ReplayTransport)
    assert (await t.upload(f"cat > {path}", image)).ok
    assert (await t.run(f"sha256sum {path}")).stdout.split()[0] == hashlib.sha256(image).hexdigest()
    validate = await t.run(f'ubus call system validate_firmware_image \'{{"path":"{path}"}}\'')
    assert json.loads(validate.stdout)["valid"] is True
    assert (await t.run(f"sysupgrade -T {path}")).ok
    assert (await t.run(arm_command("flash", 2, [f"sysupgrade {'' if keep else '-n '}{path}"]))).ok
    clock.t += 3
    with pytest.raises(Unreachable):
        await t.run("cat /etc/openwrt_release")  # the timer fired: the router is rebooting
    with pytest.raises(Unreachable):
        await _connect(sim, host)
    clock.t += 25
    return path


async def test_sim_flash_keep_settings_reboots_into_the_new_revision() -> None:
    clock = Clock()
    sim = SimConnector(SIM_DIR, clock=clock)
    await _flash(sim, clock, "192.168.1.2", NEWER, keep=True)
    t = await _connect(sim, "192.168.1.2")
    assert "DISTRIB_REVISION='r35700-0c0ffee000'" in (await t.run("cat /etc/openwrt_release")).stdout
    assert (
        json.loads((await t.run("ubus call system board")).stdout)["release"]["revision"]
        == "r35700-0c0ffee000"
    )
    assert float((await t.run("cat /proc/uptime")).stdout.split()[0]) < 10
    listing = (await t.run(OVERLAY_LS)).stdout
    assert "/root/notes.txt" not in listing
    assert "dropbear.@dropbear[0].RootPasswordAuth='off'" in (await t.run(uci_show("dropbear"))).stdout
    assert "P:dwr921-portctl\nV:3\n" in (await t.run(APK_DB)).stdout  # dwr921-portctl 3 comes with r35700


async def test_sim_flash_without_settings_changes_the_host_key() -> None:
    clock = Clock()
    sim = SimConnector(SIM_DIR, clock=clock)
    before = await sim.fetch_host_key("192.168.1.1")
    await _flash(sim, clock, "192.168.1.1", NEWER, keep=False)
    after = await sim.fetch_host_key("192.168.1.1")
    assert after.fingerprint != before.fingerprint
    state = sim.state("192.168.1.1")
    assert state.root_password is None
    assert state.authorized_keys == []
    t = await sim.connect("192.168.1.1", 22, password=None, key_paths=[])
    assert (await t.run(OVERLAY_LS)).stdout == ""


async def test_sim_refuses_an_image_for_another_board() -> None:
    mini = _mini_module()
    meta = mini.metadata("r35700-0c0ffee000")
    meta["supported_devices"] = ["other,board"]
    other = mini.build_sysupgrade(mini.mini_root("r35700-0c0ffee000"), kernel=b"K" * 4096, metadata=meta)
    t = await _connect(SimConnector(SIM_DIR, clock=Clock()), "192.168.1.2")
    assert isinstance(t, ReplayTransport)
    await t.upload("cat > /tmp/owg/fw-other.bin", other)
    answer = json.loads(
        (await t.run('ubus call system validate_firmware_image \'{"path":"/tmp/owg/fw-other.bin"}\'')).stdout
    )
    assert answer["valid"] is False
    assert answer["tests"]["fwtool_device_match"] is False
    refused = await t.run("sysupgrade -T /tmp/owg/fw-other.bin")
    assert refused.exit_status == 1
    assert (await t.run("rm -f /tmp/owg/fw-other.bin")).ok
    assert (await t.run("sha256sum /tmp/owg/fw-other.bin")).exit_status == 1
