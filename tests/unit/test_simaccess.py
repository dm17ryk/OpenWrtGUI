"""simaccess.py through the whole simulator (v0.6c plan Task 5): dropbear's port, authorized_keys, LEDs,
uhttpd's listeners, the password digest, a restore and a reset to defaults."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from openwrtgui.simulator import SimConnector, sim_commands
from openwrtgui.system import commands as s
from openwrtgui.system.access import parse_listeners
from openwrtgui.system.leds import parse_leds
from openwrtgui.system.mounts import parse_df, parse_mounts
from openwrtgui.system.parse import parse_board
from openwrtgui.system.sshkeys import parse_authorized_keys
from openwrtgui.transport.base import Unreachable
from openwrtgui.transport.fake import ReplayTransport

SIM_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sim"
AP2 = "192.168.1.2"
KEY = [Path("unused-key")]  # ap2 trusts any key (routers.json auth "key")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _sim(clock: Clock) -> tuple[SimConnector, ReplayTransport]:
    connector = SimConnector(SIM_DIR, clock)
    return connector, ReplayTransport(sim_commands(SIM_DIR, "ap2"), state=connector.state(AP2))


async def _out(t: ReplayTransport, command: str) -> str:
    result = await t.run(command)
    assert result.exit_status == 0, (command, result.stderr)
    return result.stdout


async def _apply(t: ReplayTransport, *lines: str, rollback: bool = True) -> None:
    sid = "0123456789abcdef0123456789abcdef"
    for line in lines:
        assert (await t.run(f"uci -P /var/run/rpcd/uci-{sid} {line}")).ok, line
    args = {"rollback": rollback, "timeout": 60, "ubus_rpc_session": sid}
    assert (await t.run(f"ubus call uci apply '{json.dumps(args)}'")).ok


async def test_sim_dropbear_port_moves_the_listener() -> None:
    clock = Clock()
    connector, t = _sim(clock)
    assert (AP2, 22) in {(AP2, p) for _, p in parse_listeners(await _out(t, s.LISTENERS))}
    await _apply(t, "set dropbear.main.Port='2222'")
    ports = {p for _, p in parse_listeners(await _out(t, s.LISTENERS))}
    assert 2222 in ports and 22 not in ports
    with pytest.raises(Unreachable):
        await connector.connect(AP2, 22, password=None, key_paths=KEY)
    moved = await connector.connect(AP2, 2222, password=None, key_paths=KEY)
    assert (await moved.run("true")).ok
    clock.now += 61  # no confirm: rpcd puts the old config back and dropbear follows
    ports = {p for _, p in parse_listeners(await _out(t, s.LISTENERS))}
    assert 22 in ports and 2222 not in ports


async def test_sim_a_blocked_port_is_refused() -> None:
    connector, t = _sim(Clock())
    await _apply(t, "set dropbear.main.Port='2222'")
    state = connector.state(AP2)
    assert state.access is not None
    state.access.blocked_ports.add(2222)  # as a firewall that does not let the new port in
    with pytest.raises(Unreachable):
        await connector.connect(AP2, 2222, password=None, key_paths=KEY)


async def test_sim_authorized_keys_round_trip() -> None:
    _, t = _sim(Clock())
    keys = parse_authorized_keys(await _out(t, s.KEYS_READ))
    assert [k.comment for k in keys if k.type] == ["bench@lab"]
    text = "# kept\n" + keys[0].text + "\n"
    assert (await t.run(s.write_file("/etc/dropbear/authorized_keys", text))).ok
    assert await _out(t, s.KEYS_READ) == text


async def test_sim_led_restart_sets_the_trigger() -> None:
    _, t = _sim(Clock())
    lan = {led.sysfs: led for led in parse_leds(await _out(t, s.LEDS))}["green:lan"]
    assert lan.active == "switch0" and "netdev" in lan.triggers
    script = (
        "set -e\nuci set system.led_lan.trigger='none'\nuci set system.led_lan.default='1'\nuci commit system"
    )
    assert (await t.run(script)).ok
    assert {x.sysfs: x for x in parse_leds(await _out(t, s.LEDS))}["green:lan"].active == "switch0"
    assert (await t.run("/etc/init.d/led restart")).ok
    lan = {led.sysfs: led for led in parse_leds(await _out(t, s.LEDS))}["green:lan"]
    assert (lan.active, lan.brightness) == ("none", 1)


async def test_sim_uhttpd_restart_moves_listeners() -> None:
    _, t = _sim(Clock())
    listening = parse_listeners(await _out(t, s.LISTENERS))
    assert ("0.0.0.0", 80) in listening
    assert not any(port == 443 for _, port in listening)  # AP2 serves no HTTPS (no certificate)
    script = (
        "set -e\nuci delete uhttpd.main.listen_http\n"
        "uci add_list uhttpd.main.listen_http='127.0.0.1:80'\n"
        "uci add_list uhttpd.main.listen_http='[::1]:80'\n"
        "uci commit uhttpd"
    )
    assert (await t.run(script)).ok
    assert ("0.0.0.0", 80) in parse_listeners(await _out(t, s.LISTENERS))  # until uhttpd restarts
    assert (await t.run("/etc/init.d/uhttpd restart")).ok
    web = {a for a, p in parse_listeners(await _out(t, s.LISTENERS)) if p == 80}
    assert web == {"127.0.0.1", "::1"}


async def test_sim_passwd_changes_the_digest() -> None:
    _, t = _sim(Clock())
    before = (await _out(t, s.PASSWORD_DIGEST)).split()[0]
    assert before != s.EMPTY_DIGEST  # the simulated router has a password
    assert (await t.run_stdin(s.PASSWD, "n3w-Pass\nn3w-Pass\n")).ok
    after = (await _out(t, s.PASSWORD_DIGEST)).split()[0]
    assert after not in (before, s.EMPTY_DIGEST)


async def test_sim_digest_comes_back_with_the_password() -> None:
    """The D3 hardware test's put-back, simulated: the same password gives the same digest again."""
    _, t = _sim(Clock())
    assert t.state is not None and t.state.root_password
    found = t.state.root_password
    before = (await _out(t, s.PASSWORD_DIGEST)).split()[0]
    assert (await t.run_stdin(s.PASSWD, "0ther-Pass\n0ther-Pass\n")).ok
    assert (await _out(t, s.PASSWORD_DIGEST)).split()[0] != before
    assert (await t.run_stdin(s.PASSWD, f"{found}\n{found}\n")).ok
    assert (await _out(t, s.PASSWORD_DIGEST)).split()[0] == before


def _archive(files: dict[str, str]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return raw.getvalue()


async def test_sim_restore_applies_the_hostname_after_reboot() -> None:
    clock = Clock()
    connector, t = _sim(clock)
    system = (
        "config system\n\toption hostname 'restored'\n\toption zonename 'UTC'\n\toption timezone 'GMT0'\n"
    )
    data = _archive({"etc/config/system": system, "etc/rc.local": "exit 0\n"})
    assert (await t.upload(s.UPLOAD_RESTORE, data)).ok
    assert (await _out(t, s.LIST_RESTORE)).split() == ["etc/config/system", "etc/rc.local"]
    assert (await t.run(s.RESTORE)).ok
    digests = await _out(t, s.file_digests(["/etc/config/system", "/etc/rc.local"]))
    assert digests.split()[0] == hashlib.sha256(system.encode()).hexdigest()
    assert digests.split()[2] == hashlib.sha256(b"exit 0\n").hexdigest()
    assert (await t.run("reboot")).ok
    clock.now += 30
    back = await connector.connect(AP2, 22, password=None, key_paths=KEY)
    board = parse_board(await _out(back, s.BOARD))  # type: ignore[arg-type]
    assert board is not None and board.hostname == "restored"


async def test_sim_firstboot_takes_the_router_away() -> None:
    clock = Clock()
    connector, t = _sim(clock)
    assert (await t.run(s.firstboot_command())).ok
    clock.now += 3
    with pytest.raises(Unreachable):
        await t.run("true")
    with pytest.raises(Unreachable):
        await connector.connect(AP2, 22, password=None, key_paths=KEY)


async def test_sim_access_reads() -> None:
    _, t = _sim(Clock())
    assert (await _out(t, s.APK_KEYS)).split() == ["openwrt-snapshots.pem", "public-key.pem"]
    assert not (await t.run(s.OPKG_KEYS)).ok
    assert (await t.run(s.HAS_BLOCK)).exit_status == 1
    assert {m.target for m in parse_mounts(await _out(t, s.MOUNTS))} >= {"/", "/rom", "/tmp", "/overlay"}
    assert [u.target for u in parse_df(await _out(t, s.DF))][:2] == ["/rom", "/tmp"]
    assert "br-lan" in (await _out(t, s.NET_DEVICES)).split()
    kept = await _out(t, s.KEPT)  # the image's own file (it owns sysupgrade.conf)
    assert kept.startswith("## This file contains files and directories")
    assert (await t.run(s.write_file("/etc/sysupgrade.conf", kept + "/etc/owg-test.conf\n"))).ok
    assert await _out(t, s.KEPT) == kept + "/etc/owg-test.conf\n"
    assert "/etc/config/dropbear" in (await _out(t, s.BACKUP_LIST)).split()
    shown = await _out(t, s.UCI_DROPBEAR)
    assert "dropbear.main.Port='22'" in shown
    assert "uhttpd.main.redirect_https='0'" in await _out(t, s.UCI_UHTTPD)
