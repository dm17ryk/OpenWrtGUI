import logging
import socket
from pathlib import Path

import asyncssh
import pytest
from sshserver import TEST_PASSWORD, SshServer, start_server

from openwrtgui.store import keys as keys_module
from openwrtgui.store.keys import load_or_create_app_key
from openwrtgui.transport.base import AuthFailed, HostKeyChanged, HostKeyInfo, HostKeyUnknown, Unreachable
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
