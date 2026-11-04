from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import asyncssh
import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo
from openwrtgui.onboard.wizard import OnboardService, Step, install_key_command
from openwrtgui.simulator import SimConnector
from openwrtgui.store import keys as keys_module
from openwrtgui.store.keys import AppKey, load_or_create_app_key
from openwrtgui.store.routers import RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import AuthFailed, Transport, Unreachable
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
    tmp_path: Path,
    app_key: AppKey,
    connector: SimConnector,
    clock: Clock,
    live: bool = False,
    pc_keys: Sequence[Path] = (),
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
        pc_keys=lambda: list(pc_keys),
    )


def _pc_key(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = asyncssh.generate_private_key("ssh-ed25519")
    key.write_private_key(str(path))
    key.write_public_key(f"{path}.pub")
    return path


def _public(path: Path) -> str:
    return Path(f"{path}.pub").read_text(encoding="utf-8").strip()


def _audit_text(tmp_path: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "audit").glob("*.jsonl"))


async def _trusted(service: OnboardService) -> str:
    v = await service.start(NEW_HOST)
    v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
    return v.sid


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


# -- auto-login: the app key, then this PC's keys, then root/root --------------------------------


async def test_auto_login_uses_a_pc_key_and_writes_nothing(
    tmp_path: Path, app_key: AppKey, connector: SimConnector, clock: Clock
) -> None:
    pc = _pc_key(tmp_path / "home" / ".ssh" / "id_rsa")
    connector.state(NEW_HOST).authorized_keys.append(_public(pc))
    service = _service(tmp_path, app_key, connector, clock, pc_keys=[pc])
    v = await service.auto_login(await _trusted(service))
    assert v.step == Step.IDENTIFY and v.login_method == "pc_key" and v.key_path == str(pc)
    assert not v.key_installed
    v = await service.identify(v.sid)
    rec = await service.finish(v.sid, "AP4", v.proposed_port_labels)
    assert rec.auth == "key" and rec.key_path == str(pc) and rec.username == "root"
    assert connector.state(NEW_HOST).authorized_keys == [_public(pc)]
    assert _audit_text(tmp_path) == ""


async def test_auto_login_prefers_the_app_key(
    tmp_path: Path, app_key: AppKey, connector: SimConnector, clock: Clock
) -> None:
    pc = _pc_key(tmp_path / "home" / ".ssh" / "id_ed25519")
    connector.state(NEW_HOST).authorized_keys.extend([_public(pc), app_key.public_line])
    service = _service(tmp_path, app_key, connector, clock, pc_keys=[pc])
    v = await service.auto_login(await _trusted(service))
    assert v.step == Step.IDENTIFY and v.login_method == "app_key"
    assert v.key_installed and v.key_path is None
    v = await service.identify(v.sid)
    rec = await service.finish(v.sid, "AP4", v.proposed_port_labels)
    assert rec.auth == "key" and rec.key_path is None


async def test_auto_login_falls_back_to_root_root(service: OnboardService, connector: SimConnector) -> None:
    connector.state(NEW_HOST).root_password = "root"
    v = await service.auto_login(await _trusted(service))
    assert v.step == Step.INSTALL_KEY and v.login_method == "default_password"
    assert v.root_password == "set" and not v.key_installed
    await service.install_key(v.sid)
    v = await service.verify_key(v.sid)
    assert v.step == Step.IDENTIFY and v.key_installed


async def test_auto_login_leaves_the_form_when_nothing_works(service: OnboardService) -> None:
    sid = await _trusted(service)
    v = await service.auto_login(sid)
    assert v.step == Step.LOGIN and v.login_method is None and v.error is None
    v = await service.login(sid, password="sim-password")
    assert v.step == Step.INSTALL_KEY and v.login_method == "password"


async def test_auto_login_needs_the_host_key_accepted_first(service: OnboardService) -> None:
    v = await service.start(NEW_HOST)
    with pytest.raises(ValueError):
        await service.auto_login(v.sid)


async def test_auto_login_skips_a_key_it_cannot_read(
    tmp_path: Path, app_key: AppKey, connector: SimConnector, clock: Clock
) -> None:
    connector.state(NEW_HOST).root_password = "root"
    service = _service(tmp_path, app_key, connector, clock, pc_keys=[tmp_path / "gone" / "id_rsa"])
    v = await service.auto_login(await _trusted(service))
    assert v.step == Step.INSTALL_KEY and v.login_method == "default_password"


async def test_auto_login_on_a_router_without_password(
    service: OnboardService, connector: SimConnector
) -> None:
    # A router with no root password lets any login in, keys included: that proves no key.
    connector.state(NEW_HOST).root_password = None
    v = await service.auto_login(await _trusted(service))
    assert v.step == Step.INSTALL_KEY and v.login_method == "no_password"
    assert v.root_password == "none" and not v.key_installed and v.key_path is None


class _GoneConnector(SimConnector):
    async def connect(self, host: str, port: int, **kwargs: object) -> Transport:
        raise Unreachable(f"{host}:{port}: timed out")


async def test_auto_login_reports_a_router_that_stopped_answering(
    tmp_path: Path, app_key: AppKey, clock: Clock
) -> None:
    service = _service(tmp_path, app_key, _GoneConnector(SIM_DIR), clock)
    with pytest.raises(Unreachable):
        await service.auto_login(await _trusted(service))


class _RecordingConnector(SimConnector):
    def __init__(self, sim_dir: Path) -> None:
        super().__init__(sim_dir)
        self.usernames: list[str] = []
        self.attempts: list[tuple[list[str], str | None, bool]] = []

    async def connect(self, host: str, port: int, **kwargs: object) -> Transport:
        self.usernames.append(str(kwargs["username"]))
        keys = [Path(str(p)).name for p in kwargs["key_paths"]]  # type: ignore[attr-defined]
        self.attempts.append((keys, kwargs["password"], bool(kwargs.get("prove", False))))  # type: ignore[arg-type]
        return await super().connect(host, port, **kwargs)  # type: ignore[arg-type]


async def test_auto_login_order_and_only_the_last_try_may_get_in_without_credentials(
    tmp_path: Path, app_key: AppKey, clock: Clock
) -> None:
    connector = _RecordingConnector(SIM_DIR)
    pc = _pc_key(tmp_path / "home" / ".ssh" / "id_rsa")
    service = _service(tmp_path, app_key, connector, clock, pc_keys=[pc])  # type: ignore[arg-type]
    v = await service.auto_login(await _trusted(service))
    assert v.step == Step.LOGIN
    assert connector.attempts == [
        (["id_ed25519"], None, True),  # the app key
        (["id_rsa"], None, True),  # this PC's key
        ([], "root", True),  # root / root, offered without any key
        ([], None, False),  # nothing at all: only a router without a root password lets this in
    ]


async def test_a_new_login_forgets_an_earlier_key_proof(
    tmp_path: Path, app_key: AppKey, connector: SimConnector, clock: Clock
) -> None:
    pc = _pc_key(tmp_path / "home" / ".ssh" / "id_rsa")
    connector.state(NEW_HOST).authorized_keys.append(_public(pc))
    service = _service(tmp_path, app_key, connector, clock, pc_keys=[pc])
    v = await service.auto_login(await _trusted(service))
    assert v.login_method == "pc_key"
    v = await service.login(v.sid, password="sim-password")
    assert v.step == Step.INSTALL_KEY and v.key_path is None and not v.key_installed
    v = await service.identify(v.sid)
    rec = await service.finish(v.sid, "AP4", v.proposed_port_labels)
    assert rec.auth == "none" and rec.key_path is None


async def test_login_with_another_user_is_kept(tmp_path: Path, app_key: AppKey, clock: Clock) -> None:
    connector = _RecordingConnector(SIM_DIR)
    service = _service(tmp_path, app_key, connector, clock)
    sid = await _trusted(service)
    v = await service.login(sid, password="sim-password", username="admin")
    assert v.username == "admin"
    await service.install_key(sid)
    await service.verify_key(sid)
    v = await service.identify(sid)
    rec = await service.finish(sid, "AP4", v.proposed_port_labels)
    assert rec.username == "admin"
    assert connector.usernames == ["admin", "admin"]
