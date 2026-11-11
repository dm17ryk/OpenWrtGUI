"""AP2 Access window HW-2 (v0.6c plan Task 20, D15): an LED trigger, LuCI off the network and the HTTPS
redirect, a throwaway SSH key, the SSH port followed to 2222, a kept-files line, the policy section, the
password (D3) and a restore, each applied the way the app applies them, on the real router, and put back.

uv run pytest -m hardware tests/hardware/test_ap2_access.py --router 192.168.1.2 --identity <key> \
    --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window the owner approved, with the txctl session told first: the SSH and HTTP(S) changes
restart dropbear and uhttpd. The password test also needs --allow-password and the restore --allow-reboot,
each with the owner's own OK. Each test leaves AP2 as found, compared after it: dropbear, uhttpd, rpcd and
system configs, authorized_keys, /etc/sysupgrade.conf, root's password digest (compared, never printed),
the listeners, each LED's active trigger, /tmp/owg, the parked radio and the app's port (22). A backup holds
AP2's secrets: it lives only in the test's data folder and is removed before the test ends. The SSH key is
made for the test and its private part never leaves memory.
"""

from __future__ import annotations

import asyncio
import secrets
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import asyncssh
import httpx
import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.luci_bridge.service import LuciBridgeService
from openwrtgui.luci_bridge.upstream import Upstream, ssh_upstream
from openwrtgui.net.apply import ApplyRunner, NetApplyResult
from openwrtgui.paths import DataDir
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.store.keys import AppKey
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList, SettingsStore
from openwrtgui.system import commands as s
from openwrtgui.system.access import (
    HttpChange,
    PasswordPolicy,
    SshChange,
    SshInstance,
    SshInstanceIn,
    parse_listeners,
)
from openwrtgui.system.access_service import AccessService
from openwrtgui.system.backup import backup_dir
from openwrtgui.system.leds import LedChange, parse_leds
from openwrtgui.system.service import SystemService
from openwrtgui.system.sshkeys import KeysChange
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.uci import parse_uci_show

pytestmark = pytest.mark.hardware

AP2 = "192.168.1.2"
APP_PORT = 22
TEST_PORT = 2222
KEPT_LINE = "/etc/owg-test.conf"
PAGE = "admin/status/overview"
SETTLE_S = 15  # dropbear and uhttpd listen again within a few seconds of a restart
SHADOW_COPY = "/tmp/owg/shadow.owg"
SHADOW_PID = "/tmp/owg/shadow.pid"
SHADOW_TIMER_S = 120  # D3: AP2 puts its own password back by itself if the test dies


def by_content(text: str) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    """A config's sections as (type, options): libuci names anonymous ones from their content."""
    shown = parse_uci_show(text)
    return sorted(
        (
            shown[name],
            tuple(sorted((k.rsplit(".", 1)[1], v) for k, v in shown.items() if k.startswith(name + "."))),
        )
        for name in (k for k in shown if k.count(".") == 1)
    )


@dataclass(frozen=True)
class Found:
    dropbear: list[tuple[str, tuple[tuple[str, str], ...]]]
    uhttpd: list[tuple[str, tuple[tuple[str, str], ...]]]
    rpcd: list[tuple[str, tuple[tuple[str, str], ...]]]
    system: list[tuple[str, tuple[tuple[str, str], ...]]]
    keys: str
    kept: str
    listeners: tuple[tuple[str, int], ...]
    leds: tuple[tuple[str, str | None], ...]
    owg: str
    radio: str
    digest: str = field(repr=False)  # root's password digest: compared, never printed


async def found(t: Transport) -> Found:
    async def out(command: str) -> str:
        return (await t.run(command)).stdout

    digest = await t.run(s.PASSWORD_DIGEST)
    assert digest.ok, "root's password digest does not read"  # the output is never shown
    return Found(
        dropbear=by_content(await out(s.UCI_DROPBEAR)),
        uhttpd=by_content(await out(s.UCI_UHTTPD)),
        rpcd=by_content(await out(s.UCI_RPCD)),
        system=by_content(await out(s.UCI_SYSTEM)),
        keys=await out(s.KEYS_READ),
        kept=await out(s.KEPT),
        listeners=tuple(sorted(parse_listeners(await out(s.LISTENERS)))),
        leds=tuple((i.sysfs, i.active) for i in parse_leds(await out(s.LEDS) or "{}")),
        owg=await out("ls -A /tmp/owg 2>/dev/null"),
        radio=(await out("uci -q get wireless.radio0.disabled")).strip(),
        digest=digest.stdout,
    )


def differences(now: Found, then: Found) -> list[str]:
    """The parts that differ, by name only (the digest's value is never shown)."""
    return [name for name in Found.__dataclass_fields__ if getattr(now, name) != getattr(then, name)]


@dataclass
class Window:
    access: AccessService
    system: SystemService
    luci: LuciBridgeService
    routers: RouterStore
    raw: Callable[[], Awaitable[Transport]]  # a connection for the test's own setup and put-back steps


def app_key_of(identity: Path) -> AppKey:
    key = asyncssh.read_private_key(str(identity))
    return AppKey(
        private_path=identity,
        public_line=key.export_public_key("openssh").decode("ascii").strip(),
        fingerprint=key.get_fingerprint("sha256"),
    )


async def put_ssh_port_back(w: Window) -> None:
    """A failed port test can leave the app's instance on 2222 (confirmed): move it back to 22."""
    rec = w.routers.get("ap2")
    if rec is None or rec.port == APP_PORT:
        return
    state = await w.access.access("ap2")
    app = next(i for i in state.ssh if i.section == state.app_instance)
    change = SshChange(instances=[_instance(app, APP_PORT)])
    plan = await w.access.plan_ssh("ap2", change)
    await w.access.apply_ssh("ap2", change, plan.digest)


@pytest.fixture
async def window(
    ap2_rw: SshTransport, request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[Window]:
    before = await found(ap2_rw)
    assert before.radio == "1", "AP2's radio must be parked before the window"
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    shutil.copyfile(request.config.getoption("--known-hosts"), host_keys.path)
    identity: Path = request.config.getoption("--identity")

    async def factory(rec: RouterRecord) -> Transport:
        return await SshTransport.connect(AP2, rec.port, "root", host_keys=host_keys, key_paths=[identity])

    async def upstream(_: RouterRecord, t: Transport) -> Upstream:
        return await ssh_upstream(t)

    async def raw() -> Transport:
        return ap2_rw

    data = DataDir.at(tmp_path / "data")
    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(
        RouterRecord(id="ap2", name="AP2", host=AP2, port=APP_PORT, auth="key", added_at=datetime.now())
    )
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    pool = ConnectionPool(factory)
    audit = AuditLog(data.audit_dir)
    runner = ApplyRunner(pool=pool, routers=routers, guard=guard, audit=audit, host_keys=host_keys)
    access = AccessService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        runner=runner,
        settings=SettingsStore(tmp_path / "settings.json"),
        app_key=app_key_of(identity),
    )
    system = SystemService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        runner=runner,
        data=data,
        host_keys=host_keys,
        app_keys=access.app_fingerprints,
    )
    descriptions: dict[str, SelfDescription] = {}
    luci = LuciBridgeService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        descriptions=descriptions,
        upstream_factory=upstream,
    )
    w = Window(access=access, system=system, luci=luci, routers=routers, raw=raw)
    try:
        yield w
    finally:
        shutil.rmtree(backup_dir(data.root, "ap2"), ignore_errors=True)  # AP2's secrets never stay here
        assert not backup_dir(data.root, "ap2").exists(), "a backup of AP2 was not removed"
        await put_ssh_port_back(w)
        await pool.close_all()
        t = await factory(
            RouterRecord(id="ap2", name="AP2", host=AP2, port=APP_PORT, auth="key", added_at=datetime.now())
        )
        try:
            now = await found(t)
            for _ in range(SETTLE_S):
                if now == before:
                    break
                await asyncio.sleep(1.0)
                now = await found(t)
            assert now == before, f"AP2 is not as found: {', '.join(differences(now, before))} differ"
            rec = routers.get("ap2")
            assert rec is not None and rec.port == APP_PORT, "the app's port is not back at 22"
        finally:
            await t.close()


def _instance(i: SshInstance, port: int) -> SshInstanceIn:
    """The app's instance as it is, on `port` (and on: the app's own instance never goes off)."""
    return SshInstanceIn(
        section=i.section,
        enable=True,
        port=port,
        interface=i.interface,
        password_auth=i.password_auth,
        root_password_auth=i.root_password_auth,
        gateway_ports=i.gateway_ports,
    )


def _proven(name: str, result: NetApplyResult, started: float) -> None:
    print(f"\n{name}: {time.monotonic() - started:.1f} s, {result.checks}")
    assert (result.applied, result.verified) == (True, True), result


async def bridged_page(w: Window) -> None:
    """A LuCI page opened through the bridge answers 200 with the app's session (no login form)."""
    view = await w.luci.open("ap2", PAGE)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            page = await client.get(view.url)
        print(f"LuCI {PAGE}: HTTP {page.status_code}, {len(page.text)} bytes")
        assert page.status_code == 200
        assert 'name="luci_password"' not in page.text, "LuCI showed its login form"
    finally:
        await w.luci.close(view.id)


async def test_led_trigger_and_back(window: Window) -> None:
    state = await window.access.leds("ap2")
    lan = next(r for r in state.rows if r.section == "led_lan")
    on = lan.model_copy(update={"trigger": "none", "default": True, "port_mask": None, "speed_mask": None})
    for target in (on, lan):
        change = LedChange(rows=[target if r.section == lan.section else r for r in state.rows])
        plan = await window.access.plan_leds("ap2", change)
        started = time.monotonic()
        result = await window.access.apply_leds("ap2", change, plan.digest)
        _proven(f"LED {lan.sysfs} -> {target.trigger}", result, started)
        assert {c.name: c.ok for c in result.checks}[f"LED {lan.sysfs}"] is True


async def test_luci_off_the_network_and_back(window: Window) -> None:
    http = (await window.access.access("ap2")).http
    if http.luci_on_network is not True:
        pytest.skip(f"AP2's uhttpd keeps its own listen lists ({http.listen_http}): not switched here")
    for on in (False, True):
        change = HttpChange(luci_on_network=on)
        plan = await window.access.plan_http("ap2", change)
        started = time.monotonic()
        result = await window.access.apply_http("ap2", change, plan.digest)
        _proven(f"LuCI on the network: {on}", result, started)
        await bridged_page(window)  # loopback stays: the app's LuCI pages keep working each way


async def test_https_redirect_and_back(window: Window) -> None:
    state = await window.access.access("ap2")
    if not state.https_served:
        pytest.skip("AP2 serves no HTTPS (nothing listens on its HTTPS port): the app refuses the redirect")
    for on in (True, False):
        change = HttpChange(redirect_https=on)
        plan = await window.access.plan_http("ap2", change)
        started = time.monotonic()
        result = await window.access.apply_http("ap2", change, plan.digest)
        _proven(f"redirect to HTTPS: {on}", result, started)
        await bridged_page(window)  # the bridge follows the redirect over TLS


async def test_a_throwaway_key_added_and_removed(window: Window) -> None:
    key = asyncssh.generate_private_key("ssh-ed25519", comment="owg-test@pc")  # never written anywhere
    line = key.export_public_key("openssh").decode("ascii").strip()
    for change in (KeysChange(add=(line,)), KeysChange(remove=(key.get_fingerprint("sha256"),))):
        plan = await window.access.plan_keys("ap2", change)
        started = time.monotonic()
        result = await window.access.apply_keys("ap2", change, plan.digest)
        _proven("key added" if change.add else "key removed", result, started)
        assert {c.name: c.ok for c in result.checks}["the app still logs in"] is True


async def test_ssh_port_followed_and_back(window: Window) -> None:
    state = await window.access.access("ap2")
    assert state.app_instance is not None, "no dropbear instance the app connects through"
    app = next(i for i in state.ssh if i.section == state.app_instance)
    assert app.port == APP_PORT
    for port in (TEST_PORT, APP_PORT):
        change = SshChange(instances=[_instance(app, port)])
        plan = await window.access.plan_ssh("ap2", change)
        assert plan.rollback, plan
        started = time.monotonic()
        result = await window.access.apply_ssh("ap2", change, plan.digest)
        _proven(f"SSH port {port}", result, started)
        rec = window.routers.get("ap2")
        assert rec is not None and rec.port == port, "the app did not follow the port"


async def test_a_kept_files_line_added_and_removed(window: Window) -> None:
    before = (await window.system.kept_files("ap2")).text
    assert KEPT_LINE not in before
    joined = before if not before or before.endswith("\n") else before + "\n"
    for text in (joined + KEPT_LINE + "\n", before):
        plan = await window.system.plan_kept_files("ap2", text)
        started = time.monotonic()
        result = await window.system.apply_kept_files("ap2", text, plan.digest)
        _proven(f"kept files ({len(text)} bytes)", result, started)


async def test_the_policy_section_created_and_removed(window: Window) -> None:
    if (await window.access.access("ap2")).policy is not None:
        pytest.skip("AP2 has a password policy already: this test only creates one and removes it")
    policy = PasswordPolicy(enabled=False)  # the section, checking nothing
    plan = await window.access.plan_policy("ap2", policy)
    started = time.monotonic()
    result = await window.access.apply_policy("ap2", policy, plan.digest)
    try:
        _proven("policy section created", result, started)
        assert (await window.access.access("ap2")).policy == policy
    finally:
        t = await window.raw()  # the app never removes the section (LuCI neither): put the absence back
        for command in ("uci -q delete rpcd.policy", "uci commit rpcd"):
            gone = await t.run(command)
            assert gone.ok, f"rpcd.policy was not removed ({command}): {gone.stderr.strip()}"


async def test_the_password_changed_and_put_back(window: Window, request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--allow-password"):
        pytest.skip("changing AP2's password needs the owner's own OK for it: --allow-password (D3)")
    t = await window.raw()
    before = (await t.run(s.PASSWORD_DIGEST)).stdout
    copy = await t.run(f"mkdir -p /tmp/owg && cp -p /etc/shadow {SHADOW_COPY} && chmod 600 {SHADOW_COPY}")
    assert copy.ok, f"the shadow copy failed: {copy.stderr.strip()}"
    timer = await t.run(
        f"start-stop-daemon -S -b -m -p {SHADOW_PID} -x /bin/sh -- -c "
        f"'sleep {SHADOW_TIMER_S}; cp -p {SHADOW_COPY} /etc/shadow; rm -f /tmp/owg/shadow.*'"
    )
    assert timer.ok, f"the restore timer did not arm: {timer.stderr.strip()}"
    try:
        password = secrets.token_urlsafe(18) + "aA1!"  # generated here, never printed or kept
        plan = await window.access.plan_password("ap2")
        started = time.monotonic()
        result = await window.access.apply_password("ap2", password, plan.digest)
        _proven("password", result, started)
    finally:
        back = await t.run(f"cp -p {SHADOW_COPY} /etc/shadow")
        await t.run(f"start-stop-daemon -K -p {SHADOW_PID}; rm -f /tmp/owg/shadow.*")
        assert back.ok, f"the shadow copy was not written back: {back.stderr.strip()}"
        assert (await t.run(s.PASSWORD_DIGEST)).stdout == before, "root's password is not as found"


async def test_a_fresh_backup_restored_and_back(window: Window, request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--allow-reboot"):
        pytest.skip("a restore reboots AP2: it needs the owner's own OK for it, --allow-reboot")
    saved = await window.system.create_backup("ap2")
    check = await window.system.check_restore("ap2", saved.name)
    assert not check.refusals, check.refusals
    plan = await window.system.plan_restore("ap2", saved.name)
    started = time.monotonic()
    await window.system.start_restore("ap2", saved.name, plan.digest)
    for _ in range(int(window.system.reboot_limit_s) + 60):  # the job ends by itself within the limit
        if not window.system.rebooting("ap2"):
            break
        await asyncio.sleep(1.0)
    job = window.system.reboot_job("ap2")
    print(f"\nrestore {saved.size} bytes: {time.monotonic() - started:.0f} s, {job}")
    assert job is not None and job.phase == "back" and job.error is None, job
