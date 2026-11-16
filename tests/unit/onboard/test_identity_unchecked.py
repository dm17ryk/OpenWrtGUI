"""The wizard's unchecked identity read after a flash without settings: any failure is "no answer"."""

from __future__ import annotations

from types import TracebackType

import asyncssh
import pytest

from openwrtgui.onboard import wizard


class _Conn:
    """A connection whose channel is refused (a router still booting), and which records that it closed."""

    def __init__(self) -> None:
        self.closed = False

    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.closed = True

    async def run(self, command: str, *, check: bool, timeout: float) -> object:
        raise asyncssh.ChannelOpenError(asyncssh.OPEN_CONNECT_FAILED, "channel refused")


async def test_a_refused_read_is_no_answer_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _Conn()

    async def connect(*args: object, **kwargs: object) -> _Conn:
        assert kwargs["known_hosts"] is None  # nothing is checked, and nothing pinned
        return conn

    monkeypatch.setattr(wizard.asyncssh, "connect", connect)
    assert await wizard.read_identity_unchecked("192.168.1.1", 22) == ("", "")
    assert conn.closed


async def test_the_unchecked_read_looks_for_no_certificates_in_the_ssh_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # unset, asyncssh looks for ~/.ssh/ca-bundle.crt and ~/.ssh/crt, a folder the installed app may not enter
    seen: dict[str, object] = {}

    async def connect(*args: object, **kwargs: object) -> _Conn:
        seen.update(kwargs)
        return _Conn()

    monkeypatch.setattr(wizard.asyncssh, "connect", connect)
    await wizard.read_identity_unchecked("192.168.1.1", 22)
    assert "x509_trusted_certs" in seen and seen["x509_trusted_certs"] is None
    assert "x509_trusted_cert_paths" in seen and seen["x509_trusted_cert_paths"] is None


async def test_a_read_that_times_out_is_no_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _Conn()

    async def run(command: str, *, check: bool, timeout: float) -> object:
        raise TimeoutError

    conn.run = run  # type: ignore[method-assign]

    async def connect(*args: object, **kwargs: object) -> _Conn:
        return conn

    monkeypatch.setattr(wizard.asyncssh, "connect", connect)
    assert await wizard.read_identity_unchecked("192.168.1.1", 22) == ("", "")
    assert conn.closed
