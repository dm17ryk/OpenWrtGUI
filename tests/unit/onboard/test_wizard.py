from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo
from openwrtgui.onboard.wizard import OnboardService, Step, install_key_command
from openwrtgui.simulator import SimConnector
from openwrtgui.store import keys as keys_module
from openwrtgui.store.keys import AppKey, load_or_create_app_key
from openwrtgui.store.routers import RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import AuthFailed
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
NEW_HOST = "192.168.1.4"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 3, 12, 0)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def app_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppKey:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)
    return load_or_create_app_key(tmp_path / "keys", comment="openwrtgui@TEST")


def _guard(live: bool = False) -> BenchGuard:
    procs = [ProcessInfo(18244, ("dima_night.py",), datetime(2026, 11, 3, 21, 4))] if live else []
    g = BenchGuard(GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: procs)
    g.check_local()
    return g


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def connector() -> SimConnector:
    return SimConnector(SIM_DIR)


def _service(
    tmp_path: Path, app_key: AppKey, connector: SimConnector, clock: Clock, live: bool = False
) -> OnboardService:
    async def factory(rec: object) -> object:
        raise AssertionError("pool not used by the wizard")

    return OnboardService(
        connector=connector,
        host_keys=HostKeyStore(tmp_path / "known_hosts"),
        app_key=app_key,
        routers=RouterStore(tmp_path / "routers.json"),
        guard=_guard(live),
        audit=AuditLog(tmp_path / "audit"),
        pool=ConnectionPool(factory),  # type: ignore[arg-type]
        clock=clock,
    )


@pytest.fixture
def service(tmp_path: Path, app_key: AppKey, connector: SimConnector, clock: Clock) -> OnboardService:
    return _service(tmp_path, app_key, connector, clock)


async def test_happy_path_installs_key_once(
    service: OnboardService, app_key: AppKey, connector: SimConnector
) -> None:
    v = await service.start(NEW_HOST)
    assert v.step == Step.HOST_KEY and v.host_key is not None and not v.known_before
    v = await service.trust(v.sid, v.host_key.fingerprint)
    assert v.step == Step.LOGIN
    v = await service.login(v.sid, password="sim-password")
    assert v.step == Step.INSTALL_KEY and v.root_password == "set"
    assert service.install_key_preview(v.sid) == [install_key_command(app_key.public_line)]
    await service.install_key(v.sid)
    await service.install_key(v.sid)
    assert connector.state(NEW_HOST).authorized_keys == [app_key.public_line]
    v = await service.verify_key(v.sid)
    assert v.key_installed
    v = await service.identify(v.sid)
    assert v.step == Step.PORTS and v.proposed_port_labels[0] == "LAN4"
    assert v.summary is not None and v.summary.protocols["qmi"] == 25
    rec = await service.finish(v.sid, "AP4 · test", v.proposed_port_labels)
    assert rec.auth == "key" and rec.id == "ap4-test" and rec.host == NEW_HOST
    assert rec.port_labels[6] == "CPU (eth0)"


def test_install_key_command_exact() -> None:
    line = "ssh-ed25519 AAAAC3Nz openwrtgui@PC"
    assert install_key_command(line) == (
        "mkdir -p /etc/dropbear && touch /etc/dropbear/authorized_keys && "
        "chmod 600 /etc/dropbear/authorized_keys && "
        "(grep -qxF 'ssh-ed25519 AAAAC3Nz openwrtgui@PC' /etc/dropbear/authorized_keys || "
        "echo 'ssh-ed25519 AAAAC3Nz openwrtgui@PC' >> /etc/dropbear/authorized_keys)"
    )


async def test_wrong_fingerprint_is_rejected(service: OnboardService, tmp_path: Path) -> None:
    v = await service.start(NEW_HOST)
    with pytest.raises(ValueError):
        await service.trust(v.sid, "SHA256:not-it")
    assert HostKeyStore(tmp_path / "known_hosts").get(NEW_HOST, 22) is None


async def test_wrong_password_is_auth_failed(service: OnboardService) -> None:
    v = await service.start(NEW_HOST)
    v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
    with pytest.raises(AuthFailed):
        await service.login(v.sid, password="nope")


async def test_password_is_not_kept_or_logged(service: OnboardService, tmp_path: Path) -> None:
    v = await service.start(NEW_HOST)
    v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
    v = await service.login(v.sid, password="sim-password")
    await service.install_key(v.sid)
    session = service._sessions[v.sid]
    kept = {k: val for k, val in vars(session).items() if k != "transport"}
    assert "sim-password" not in repr(kept)
    audit_text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "audit").glob("*.jsonl"))
    assert "sim-password" not in audit_text and "authorized_keys" in audit_text


async def test_install_key_blocked_during_run(
    tmp_path: Path, app_key: AppKey, connector: SimConnector, clock: Clock
) -> None:
    service = _service(tmp_path, app_key, connector, clock, live=True)
    v = await service.start(NEW_HOST)
    v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
    v = await service.login(v.sid, password="sim-password")
    with pytest.raises(GuardLocked):
        await service.install_key(v.sid)
    assert connector.state(NEW_HOST).authorized_keys == []


async def test_skipping_key_gives_auth_none(service: OnboardService) -> None:
    v = await service.start(NEW_HOST)
    v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
    v = await service.login(v.sid, password="sim-password")
    v = await service.identify(v.sid)
    rec = await service.finish(v.sid, "AP5", v.proposed_port_labels)
    assert rec.auth == "none"


async def test_set_password_only_when_none(
    service: OnboardService, connector: SimConnector, tmp_path: Path
) -> None:
    v = await service.start(NEW_HOST)
    v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
    v = await service.login(v.sid, password="sim-password")
    with pytest.raises(ValueError):
        await service.set_password(v.sid, "brand-new-pw")
    connector.state(NEW_HOST).root_password = None
    v = await service.login(v.sid, password="sim-password")
    assert v.root_password == "none"
    v = await service.set_password(v.sid, "brand-new-pw")
    assert v.root_password == "set" and connector.state(NEW_HOST).root_password == "brand-new-pw"
    audit_text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "audit").glob("*.jsonl"))
    assert "brand-new-pw" not in audit_text and "passwd root" in audit_text


async def test_idle_session_expires(service: OnboardService, clock: Clock) -> None:
    v = await service.start(NEW_HOST)
    clock.now += timedelta(seconds=901)
    with pytest.raises(KeyError):
        await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]


async def test_changed_host_key_is_reported(service: OnboardService, tmp_path: Path) -> None:
    v = await service.start(NEW_HOST)
    await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
    await service.cancel(v.sid)
    other = SimConnector(SIM_DIR)  # new process, new simulated host keys: like a reflash
    service._connector = other
    v2 = await service.start(NEW_HOST)
    assert v2.changed_from == v.host_key.fingerprint  # type: ignore[union-attr]
    assert not v2.known_before
