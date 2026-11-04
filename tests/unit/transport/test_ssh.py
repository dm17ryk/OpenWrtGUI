import logging
import socket
from pathlib import Path

import asyncssh
import pytest
from sshserver import TEST_PASSWORD, SshServer, start_server

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.onboard.wizard import OnboardService, SshConnector, Step
from openwrtgui.store import keys as keys_module
from openwrtgui.store.keys import load_or_create_app_key
from openwrtgui.store.routers import RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import (
    AuthFailed,
    HostKeyChanged,
    HostKeyInfo,
    HostKeyUnknown,
    KeyFileError,
    TransportError,
    Unreachable,
)
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key


async def _pinned(srv: SshServer, tmp_path: Path) -> HostKeyStore:
    store = HostKeyStore(tmp_path / "known_hosts")
    store.pin("127.0.0.1", srv.port, await fetch_host_key("127.0.0.1", srv.port))
    return store


async def test_fetch_and_pin_then_password_login(ssh_server: SshServer, tmp_path: Path) -> None:
    info = await fetch_host_key("127.0.0.1", ssh_server.port)
    assert info.fingerprint == ssh_server.fingerprint
    assert info.public.startswith("ssh-ed25519 ")
    store = HostKeyStore(tmp_path / "known_hosts")
    store.pin("127.0.0.1", ssh_server.port, info)
    assert store.get("127.0.0.1", ssh_server.port) == ssh_server.fingerprint
    t = await SshTransport.connect(
        "127.0.0.1", ssh_server.port, "root", host_keys=store, password=TEST_PASSWORD
    )
    try:
        assert (await t.run("echo hi")).stdout == "hi\n"
        r = await t.run("nope")
        assert r.exit_status == 127 and "unknown" in r.stderr
    finally:
        await t.close()


async def test_unpinned_host_is_refused(ssh_server: SshServer, tmp_path: Path) -> None:
    with pytest.raises(HostKeyUnknown) as exc:
        await SshTransport.connect(
            "127.0.0.1",
            ssh_server.port,
            "root",
            host_keys=HostKeyStore(tmp_path / "kh"),
            password=TEST_PASSWORD,
        )
    assert exc.value.actual.fingerprint == ssh_server.fingerprint


async def test_changed_host_key_is_refused_with_both_fingerprints(
    ssh_server: SshServer, tmp_path: Path
) -> None:
    old = asyncssh.generate_private_key("ssh-ed25519")
    old_info = HostKeyInfo(
        "ssh-ed25519", old.get_fingerprint("sha256"), old.export_public_key("openssh").decode().strip()
    )
    store = HostKeyStore(tmp_path / "known_hosts")
    store.pin("127.0.0.1", ssh_server.port, old_info)
    with pytest.raises(HostKeyChanged) as exc:
        await SshTransport.connect(
            "127.0.0.1", ssh_server.port, "root", host_keys=store, password=TEST_PASSWORD
        )
    assert exc.value.expected == old_info.fingerprint
    assert exc.value.actual.fingerprint == ssh_server.fingerprint
    assert "reflash" in str(exc.value)


async def test_wrong_password_is_auth_failed(ssh_server: SshServer, tmp_path: Path) -> None:
    store = await _pinned(ssh_server, tmp_path)
    with pytest.raises(AuthFailed):
        await SshTransport.connect("127.0.0.1", ssh_server.port, "root", host_keys=store, password="wrong")


async def test_app_key_login_and_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)
    app_key = load_or_create_app_key(tmp_path / "keys", comment="openwrtgui@TEST")
    srv = await start_server(authorized=[app_key.public_line])
    try:
        store = await _pinned(srv, tmp_path)
        t = await SshTransport.connect(
            "127.0.0.1", srv.port, "root", host_keys=store, key_paths=[app_key.private_path]
        )
        try:
            assert (await t.run_stdin("cat", "x\n")).stdout == "x\n"
        finally:
            await t.close()
    finally:
        srv.server.close()
        await srv.server.wait_closed()


async def test_a_missing_key_file_is_not_unreachable(ssh_server: SshServer, tmp_path: Path) -> None:
    store = await _pinned(ssh_server, tmp_path)
    with pytest.raises(KeyFileError) as exc:
        await SshTransport.connect(
            "127.0.0.1", ssh_server.port, "root", host_keys=store, key_paths=[tmp_path / "gone"]
        )
    assert not isinstance(exc.value, Unreachable)
    assert isinstance(exc.value, TransportError)  # so the pool marks the router offline, with the reason
    assert str(tmp_path / "gone") in str(exc.value)


async def test_a_key_with_a_passphrase_is_a_key_file_error(ssh_server: SshServer, tmp_path: Path) -> None:
    store = await _pinned(ssh_server, tmp_path)
    locked = tmp_path / "id_ed25519"
    asyncssh.generate_private_key("ssh-ed25519").write_private_key(
        str(locked), format_name="pkcs8-pem", passphrase="secret"
    )
    with pytest.raises(KeyFileError):
        await SshTransport.connect("127.0.0.1", ssh_server.port, "root", host_keys=store, key_paths=[locked])


async def test_no_key_paths_offers_no_default_keys_and_ignores_ssh_config(
    ssh_server: SshServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # asyncssh turns client_keys=[] into "load ~/.ssh/id_*" and config=() into "read ~/.ssh/config".
    store = await _pinned(ssh_server, tmp_path)
    seen: dict[str, object] = {}

    async def fake_connect(*args: object, **kwargs: object) -> object:
        seen.update(kwargs)
        raise asyncssh.PermissionDenied("stop here")

    monkeypatch.setattr(asyncssh, "connect", fake_connect)
    with pytest.raises(AuthFailed):
        await SshTransport.connect("127.0.0.1", ssh_server.port, "root", host_keys=store, password="x")
    assert seen["client_keys"] is None and seen["config"] == [] and seen["agent_path"] is None
    assert seen["disable_trivial_auth"] is False


async def test_proving_a_login_refuses_a_router_that_asks_for_nothing(tmp_path: Path) -> None:
    srv = await start_server(no_login=True)
    try:
        store = await _pinned(srv, tmp_path)
        with pytest.raises(AuthFailed):
            await SshTransport.connect(
                "127.0.0.1", srv.port, "root", host_keys=store, password="root", prove=True
            )
        t = await SshTransport.connect("127.0.0.1", srv.port, "root", host_keys=store)
        await t.close()
    finally:
        srv.server.close()
        await srv.server.wait_closed()


def _pc_key(tmp_path: Path) -> tuple[Path, str]:
    pc = asyncssh.generate_private_key("ssh-ed25519")
    pc_path = tmp_path / "home" / ".ssh" / "id_rsa"
    pc_path.parent.mkdir(parents=True)
    pc.write_private_key(str(pc_path))
    return pc_path, pc.export_public_key("openssh").decode().strip()


def _wizard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pc_keys: list[Path]) -> OnboardService:
    monkeypatch.setattr(keys_module, "restrict_to_user", lambda path: None)
    host_keys = HostKeyStore(tmp_path / "known_hosts")

    async def no_pool(rec: object) -> object:
        raise AssertionError("pool not used by the wizard")

    return OnboardService(
        connector=SshConnector(host_keys),
        host_keys=host_keys,
        app_key=load_or_create_app_key(tmp_path / "keys", comment="openwrtgui@TEST"),
        routers=RouterStore(tmp_path / "routers.json"),
        guard=BenchGuard(GuardWatchList(lock_files=[], processes=[]), lister=list),
        audit=AuditLog(tmp_path / "audit"),
        pool=ConnectionPool(no_pool),  # type: ignore[arg-type]
        pc_keys=lambda: pc_keys,
    )


async def _stop(service: OnboardService, srv: SshServer) -> None:
    """Close the wizard's connections first: wait_closed() waits for every open one."""
    for sid in list(service._sessions):
        await service.cancel(sid)
    srv.server.close()
    await srv.server.wait_closed()


async def test_wizard_auto_login_finds_a_pc_key_over_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pc_path, pc_public = _pc_key(tmp_path)
    srv = await start_server(authorized=[pc_public])
    service = _wizard(tmp_path, monkeypatch, [tmp_path / "home" / ".ssh" / "id_ed25519", pc_path])
    try:
        v = await service.start("127.0.0.1", srv.port)
        v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
        v = await service.auto_login(v.sid)
        assert v.step == Step.IDENTIFY and v.login_method == "pc_key" and v.key_path == str(pc_path)
    finally:
        await _stop(service, srv)


async def test_wizard_auto_login_on_a_router_that_asks_for_no_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Such a router lets every key "work"; none of them is proven, and nothing may be recorded as one.
    pc_path, pc_public = _pc_key(tmp_path)
    srv = await start_server(authorized=[pc_public], no_login=True)
    service = _wizard(tmp_path, monkeypatch, [pc_path])
    try:
        v = await service.start("127.0.0.1", srv.port)
        v = await service.trust(v.sid, v.host_key.fingerprint)  # type: ignore[union-attr]
        v = await service.auto_login(v.sid)
        assert v.step == Step.INSTALL_KEY and v.login_method == "no_password"
        assert v.key_path is None and not v.key_installed
    finally:
        await _stop(service, srv)


async def test_shell_channel(ssh_server: SshServer, tmp_path: Path) -> None:
    store = await _pinned(ssh_server, tmp_path)
    t = await SshTransport.connect(
        "127.0.0.1", ssh_server.port, "root", host_keys=store, password=TEST_PASSWORD
    )
    try:
        shell = await t.open_shell(80, 24)
        assert "shell>" in await shell.read()
        await shell.write("ls\n")
        out = ""
        while "you typed ls" not in out:
            chunk = await shell.read()
            assert chunk, "shell closed early"
            out += chunk
        await shell.close()
    finally:
        await t.close()


async def test_closed_port_is_unreachable(tmp_path: Path) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(Unreachable):
        await fetch_host_key("127.0.0.1", port, timeout=3)


async def test_password_never_logged(
    ssh_server: SshServer, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    store = await _pinned(ssh_server, tmp_path)
    t = await SshTransport.connect(
        "127.0.0.1", ssh_server.port, "root", host_keys=store, password=TEST_PASSWORD
    )
    await t.run("echo hi")
    await t.close()
    assert TEST_PASSWORD not in caplog.text


def test_host_key_store_port_format_and_forget(tmp_path: Path) -> None:
    key = asyncssh.generate_private_key("ssh-ed25519")
    info = HostKeyInfo(
        "ssh-ed25519", key.get_fingerprint("sha256"), key.export_public_key("openssh").decode().strip()
    )
    store = HostKeyStore(tmp_path / "known_hosts")
    store.pin("192.168.1.2", 22, info)
    store.pin("192.168.1.9", 2222, info)
    text = store.path.read_text(encoding="utf-8")
    assert text.startswith("192.168.1.2 ssh-ed25519 ") and "[192.168.1.9]:2222 ssh-ed25519 " in text
    store.pin("192.168.1.2", 22, info)
    assert store.path.read_text(encoding="utf-8").count("192.168.1.2 ") == 1
    store.forget("192.168.1.2", 22)
    assert store.get("192.168.1.2", 22) is None and store.get("192.168.1.9", 2222) == info.fingerprint
