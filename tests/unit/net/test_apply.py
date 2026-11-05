"""The apply runner: plain (commit + reload), and with rpcd's rollback, reconnect, confirm, address follow."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import asyncssh
import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, ProcessInfo
from openwrtgui.net.apply import ApplyRunner, NetCheck, net_plan, saved_check
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import CommandResult, HostKeyInfo, HostKeyUnknown, Transport, Unreachable
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore
from openwrtgui.uci import UciOp, parse_uci_show

RUN = ProcessInfo(18244, ("python.exe", "dima_night.py"), datetime(2026, 11, 5, 21, 4))
NETWORK = "network.lan=interface\nnetwork.lan.proto='static'\nnetwork.lan.ipaddr='192.168.1.2/24'\n"
SNAPSHOT = parse_uci_show(NETWORK)


def _key() -> HostKeyInfo:
    key = asyncssh.generate_private_key("ssh-ed25519")
    return HostKeyInfo(
        type=key.get_algorithm(),
        fingerprint=key.get_fingerprint("sha256"),
        public=key.export_public_key("openssh").decode("ascii").strip(),
    )


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 5, 15, 0)

    def now(self) -> datetime:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@dataclass
class Bench:
    """One simulated router: which addresses answer when, its host key, and every command per connection."""

    clock: Clock
    key: HostKeyInfo
    answers_at: Callable[[str, datetime], bool]
    log: list[tuple[int, str, str]] = field(default_factory=list)  # (connection, host, command)
    connections: int = 0
    respond: Callable[[str], CommandResult | None] = lambda command: None
    on_command: Callable[[str], None] = lambda command: None


class FakeT:
    def __init__(self, bench: Bench, host: str) -> None:
        bench.connections += 1
        self.n, self.host, self.bench = bench.connections, host, bench

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.bench.log.append((self.n, self.host, command))
        self.bench.on_command(command)
        answer = self.bench.respond(command)
        if answer is not None:
            return answer
        if command.startswith("ubus call session create"):
            return CommandResult(command, json.dumps({"ubus_rpc_session": "S"}), "", 0)
        if command == "uci -X show network":
            return CommandResult(command, NETWORK, "", 0)
        return CommandResult(command, "", "", 0)

    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult:
        return await self.run(command, timeout=timeout)

    async def open_shell(self, cols: int, rows: int):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def close(self) -> None:
        return None


@dataclass
class Env:
    runner: ApplyRunner
    routers: RouterStore
    host_keys: HostKeyStore
    bench: Bench
    clock: Clock
    pool: ConnectionPool
    processes: list[ProcessInfo]
    guard: BenchGuard
    audit: AuditLog

    @property
    def rec(self) -> RouterRecord:
        rec = self.routers.get("ap2")
        assert rec is not None
        return rec

    def commands(self) -> list[str]:
        return [c for _, _, c in self.bench.log]


@pytest.fixture
def env(tmp_path: Path) -> Env:
    clock = Clock()
    key = _key()
    bench = Bench(clock, key, answers_at=lambda host, now: host == "192.168.1.2")
    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(
        RouterRecord(id="ap2", name="AP2 · office", host="192.168.1.2", auth="key", added_at=clock.t)
    )
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    host_keys.pin("192.168.1.2", 22, key)

    async def factory(rec: RouterRecord) -> Transport:
        if not bench.answers_at(rec.host, clock.now()):
            raise Unreachable(f"{rec.host}: no route to host")
        if host_keys.get(rec.host, rec.port) is None:
            raise HostKeyUnknown(rec.host, bench.key)
        return FakeT(bench, rec.host)

    processes: list[ProcessInfo] = []
    guard = BenchGuard(GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: processes)
    guard.check_local()
    pool = ConnectionPool(factory)
    audit = AuditLog(tmp_path / "audit")
    runner = ApplyRunner(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        host_keys=host_keys,
        clock=clock.now,
        sleep=clock.sleep,
    )
    return Env(runner, routers, host_keys, bench, clock, pool, processes, guard, audit)


async def _verify_ok(t: Transport) -> list[NetCheck]:
    return [NetCheck("interface lan", True, "up with 192.168.1.12/24")]


def _lan_plan(target: str | None = "192.168.1.12") -> object:
    return net_plan(
        router_id="ap2",
        screen="Network",
        config="network",
        ops=[UciOp("set", "network.lan.ipaddr", "192.168.1.12/24")],
        current=SNAPSHOT,
        rollback=True,
        target_host=target,
    )


async def test_plain_apply_commits_reloads_and_verifies(env: Env) -> None:
    plan = net_plan(
        router_id="ap2",
        screen="Network",
        config="dhcp",
        ops=[UciOp("set", "dhcp.lan.start", "50")],
        current={"dhcp.lan": "dhcp", "dhcp.lan.start": "100"},
        reloads=("/etc/init.d/dnsmasq reload",),
    )
    assert plan.lines == (
        "set -e",
        "uci set dhcp.lan.start='50'",
        "uci commit dhcp",
        "/etc/init.d/dnsmasq reload",
    )
    t = await env.pool.get(env.rec)

    async def saved(_: Transport) -> list[NetCheck]:
        return [NetCheck("saved", True, "dhcp.lan.start = 50")]

    result = await env.runner.run(env.rec, t, plan, saved)
    assert env.commands() == [
        "set -e\nuci set dhcp.lan.start='50'\nuci commit dhcp",
        "/etc/init.d/dnsmasq reload",
    ]
    assert result.applied and result.verified and result.error is None
    assert [e.verify for e in env.audit.query() if e.command == "verify dhcp"] == ["pass"]


def test_rollback_preview_shows_every_step_with_a_session_placeholder() -> None:
    plan = _lan_plan()
    assert plan.lines == (  # type: ignore[attr-defined]
        "ubus call session create '{\"timeout\":300}'",
        'ubus call session grant \'{"objects":[["network","read"],["network","write"]],'
        '"scope":"uci","ubus_rpc_session":"<session>"}\'',
        "set -e",
        "mkdir -p /var/run/rpcd/uci-<session>",
        "uci -P /var/run/rpcd/uci-<session> set network.lan.ipaddr='192.168.1.12/24'",
        'ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"<session>"}\'',
        'ubus call uci confirm \'{"ubus_rpc_session":"<session>"}\'',
        'ubus call session destroy \'{"ubus_rpc_session":"<session>"}\'',
    )


def test_nothing_to_apply_is_refused() -> None:
    with pytest.raises(ValueError, match="Nothing to apply: the router already has these settings."):
        net_plan(
            router_id="ap2",
            screen="Network",
            config="network",
            ops=[UciOp("set", "network.lan.ipaddr", "192.168.1.2/24")],
            current=SNAPSHOT,
            rollback=True,
        )


async def test_rollback_apply_confirms_after_reconnect(env: Env) -> None:
    t = await env.pool.get(env.rec)
    result = await env.runner.run(env.rec, t, _lan_plan(target=None), _verify_ok, SNAPSHOT)  # type: ignore[arg-type]
    log = env.bench.log
    assert [c for _, _, c in log[:4]] == [
        "ubus call session create '{\"timeout\":300}'",
        'ubus call session grant \'{"objects":[["network","read"],["network","write"]],'
        '"scope":"uci","ubus_rpc_session":"S"}\'',
        "set -e\nmkdir -p /var/run/rpcd/uci-S\n"
        "uci -P /var/run/rpcd/uci-S set network.lan.ipaddr='192.168.1.12/24'",
        'ubus call uci apply \'{"rollback":true,"timeout":60,"ubus_rpc_session":"S"}\'',
    ]
    confirm = next(entry for entry in log if entry[2] == 'ubus call uci confirm \'{"ubus_rpc_session":"S"}\'')
    assert confirm[0] == 2  # on a new connection
    assert log[-1][2] == 'ubus call session destroy \'{"ubus_rpc_session":"S"}\''
    assert result.applied and result.verified
    assert [(c.name, c.ok) for c in result.checks] == [
        ("reconnected", True),
        ("confirmed", True),
        ("interface lan", True),
    ]


async def test_changed_address_followed_and_record_updated(env: Env) -> None:
    env.bench.answers_at = lambda host, now: host == "192.168.1.12"  # the change moved lan at once
    t = FakeT(env.bench, "192.168.1.2")
    result = await env.runner.run(env.rec, t, _lan_plan(), _verify_ok, SNAPSHOT)  # type: ignore[arg-type]
    assert result.applied and result.verified and result.host == "192.168.1.12"
    assert env.routers.get("ap2").host == "192.168.1.12"  # type: ignore[union-attr]
    assert env.host_keys.get("192.168.1.12", 22) == env.bench.key.fingerprint
    assert any(h == "192.168.1.12" and c.startswith("ubus call uci confirm") for _, h, c in env.bench.log)


async def test_new_address_with_other_host_key_is_not_confirmed(env: Env) -> None:
    env.bench.answers_at = lambda host, now: host == "192.168.1.12" or now >= env.clock.t + timedelta(days=1)
    t = FakeT(env.bench, "192.168.1.2")
    env.bench.key = _key()  # whatever answers at .12 has another key
    result = await env.runner.run(env.rec, t, _lan_plan(), _verify_ok, SNAPSHOT)  # type: ignore[arg-type]
    assert not result.applied and result.host == "192.168.1.2"
    assert env.routers.get("ap2").host == "192.168.1.2"  # type: ignore[union-attr]
    assert not any(c.startswith("ubus call uci confirm") for c in env.commands())
    assert result.error is not None and "different host key" in result.error


async def test_unreachable_after_apply_reports_restored(env: Env) -> None:
    applied_at: list[datetime] = []

    def note(command: str) -> None:
        if command.startswith("ubus call uci apply"):
            applied_at.append(env.clock.t)

    env.bench.on_command = note
    # nothing answers for 64 s after the apply; then the old address is back (the router restored itself)
    env.bench.answers_at = lambda host, now: (
        host == "192.168.1.2" and (not applied_at or now >= applied_at[0] + timedelta(seconds=64))
    )
    t = FakeT(env.bench, "192.168.1.2")
    result = await env.runner.run(env.rec, t, _lan_plan(target=None), _verify_ok, SNAPSHOT)  # type: ignore[arg-type]
    assert not result.applied and not result.verified
    assert result.error == (
        "Not applied: AP2 · office did not answer at 192.168.1.2 within 40 s. "
        "The router restores its previous network settings 60 s after the change."
    )
    checks = {c.name: c.ok for c in result.checks}
    assert checks == {"reconnected": False, "restored": True}
    assert not any(c.startswith("ubus call uci confirm") for c in env.commands())


async def test_change_that_cuts_the_path_late_is_never_confirmed(env: Env) -> None:
    """The reload runs a few seconds after `uci apply` (procd's trigger delay, a busy router): a confirm
    sent while the old path still works would cancel the rollback of a change that then cuts the app off."""
    applied_at: list[datetime] = []

    def note(command: str) -> None:
        if command.startswith("ubus call uci apply"):
            applied_at.append(env.clock.t)

    def cut(now: datetime) -> bool:  # the change takes effect 6 s after the apply; rpcd restores at 60 s
        return bool(applied_at) and timedelta(seconds=6) <= now - applied_at[0] < timedelta(seconds=64)

    def respond(command: str) -> CommandResult | None:
        if cut(env.clock.t):
            raise Unreachable("192.168.1.2: no route to host")
        return None

    env.bench.on_command = note
    env.bench.respond = respond
    env.bench.answers_at = lambda host, now: host == "192.168.1.2" and not cut(now)

    async def verify_lan(t: Transport) -> list[NetCheck]:  # polls the router, as the real verifiers do
        for _ in range(10):
            await t.run("ubus call network.interface.lan status")
            await env.clock.sleep(1.0)
        return [NetCheck("interface lan", True, "up with 192.168.1.2/30")]

    t = FakeT(env.bench, "192.168.1.2")
    result = await env.runner.run(env.rec, t, _lan_plan(target=None), verify_lan, SNAPSHOT)  # type: ignore[arg-type]
    assert not any(c.startswith("ubus call uci confirm") for c in env.commands())
    assert not result.applied
    assert {c.name: c.ok for c in result.checks} == {"reconnected": False, "restored": True}


async def test_guard_live_after_apply_still_confirms(env: Env) -> None:
    def go_live(command: str) -> None:
        if command.startswith("ubus call uci apply"):
            env.processes.append(RUN)
            env.guard.check_local()

    env.bench.on_command = go_live
    t = await env.pool.get(env.rec)
    result = await env.runner.run(env.rec, t, _lan_plan(target=None), _verify_ok, SNAPSHOT)  # type: ignore[arg-type]
    assert any(c.startswith("ubus call uci confirm") for c in env.commands())
    assert result.applied
    assert result.error is not None and result.error.startswith("Confirmed although Bench Guard went live")


async def test_script_refused_sends_no_apply(env: Env) -> None:
    def refuse(command: str) -> CommandResult | None:
        if command.startswith("set -e"):
            return CommandResult(command, "", "uci: Invalid argument\n", 1)
        return None

    env.bench.respond = refuse
    t = await env.pool.get(env.rec)
    result = await env.runner.run(env.rec, t, _lan_plan(target=None), _verify_ok, SNAPSHOT)  # type: ignore[arg-type]
    assert not any(c.startswith("ubus call uci apply") for c in env.commands())
    assert env.commands()[-1] == 'ubus call session destroy \'{"ubus_rpc_session":"S"}\''
    assert not result.applied and result.error == "The router refused the change: uci: Invalid argument"


DHCP_BEFORE = parse_uci_show(
    "dhcp.cfg01411c=dnsmasq\ndhcp.cfg01411c.domain='lan'\ndhcp.cfg01411c.cachesize='1000'\n"
    "dhcp.cfg02f37d=host\ndhcp.cfg02f37d.mac='e4:5f:01:aa:bb:01'\ndhcp.cfg02f37d.ip='192.168.1.50'\n"
    "dhcp.cfg03a1b2=host\ndhcp.cfg03a1b2.mac='e4:5f:01:aa:bb:02'\ndhcp.cfg03a1b2.ip='192.168.1.51'\n"
)
DHCP_OPS = [
    UciOp("add_list", "dhcp.cfg01411c.server", "1.1.1.1"),
    UciOp("set", "dhcp.cfg02f37d.ip", "192.168.1.60"),
    UciOp("delete", "dhcp.cfg03a1b2"),
]
# After the commit libuci names every anonymous section anew from its content (cfg<n><hash>).
DHCP_AFTER = (
    "dhcp.cfg01e6a0=dnsmasq\ndhcp.cfg01e6a0.domain='lan'\ndhcp.cfg01e6a0.cachesize='1000'\n"
    "dhcp.cfg01e6a0.server='1.1.1.1'\n"
    "dhcp.cfg0277c4=host\ndhcp.cfg0277c4.mac='e4:5f:01:aa:bb:01'\ndhcp.cfg0277c4.ip='192.168.1.60'\n"
)


class Shown:
    def __init__(self, text: str) -> None:
        self.text = text

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        return CommandResult(command, self.text, "", 0)


async def test_saved_check_finds_renamed_anonymous_sections_by_content() -> None:
    check = await saved_check(Shown(DHCP_AFTER), "uci -X show dhcp", DHCP_OPS, DHCP_BEFORE)  # type: ignore[arg-type]
    assert check == NetCheck("saved", True, "the router has the change")


async def test_saved_check_still_catches_a_change_the_router_does_not_hold() -> None:
    stale = DHCP_AFTER.replace("192.168.1.60", "192.168.1.50")
    check = await saved_check(Shown(stale), "uci -X show dhcp", DHCP_OPS, DHCP_BEFORE)  # type: ignore[arg-type]
    assert check == NetCheck("saved", False, "not as asked: dhcp.cfg02f37d")
    kept = DHCP_AFTER + (
        "dhcp.cfg03b9e1=host\ndhcp.cfg03b9e1.mac='e4:5f:01:aa:bb:02'\ndhcp.cfg03b9e1.ip='192.168.1.51'\n"
    )
    check = await saved_check(Shown(kept), "uci -X show dhcp", DHCP_OPS, DHCP_BEFORE)  # type: ignore[arg-type]
    assert check == NetCheck("saved", False, "not as asked: dhcp.cfg03a1b2")


def test_carry_pins_only_identical_key(tmp_path: Path) -> None:
    store = HostKeyStore(tmp_path / "known_hosts")
    mine, other = _key(), _key()
    store.pin("192.168.1.2", 22, mine)
    assert not store.carry("192.168.1.2", "192.168.1.12", 22, other)
    assert store.get("192.168.1.12", 22) is None
    assert store.carry("192.168.1.2", "192.168.1.12", 22, mine)
    assert store.get("192.168.1.12", 22) == mine.fingerprint
    assert not store.carry("10.0.0.1", "10.0.0.2", 22, mine)  # nothing pinned for the old address
