"""authorized_keys as LuCI's SSH-Keys page reads it (plan D5): keys, their options and fingerprints; any
other line is kept as written."""

from __future__ import annotations

import asyncssh
import pytest

from openwrtgui.system.sshkeys import check_key_line, label, parse_authorized_keys, render_authorized_keys


def _public(algorithm: str = "ssh-ed25519", comment: str = "bob@pc") -> tuple[str, str]:
    key = asyncssh.generate_private_key(algorithm, comment=comment)
    return key.export_public_key("openssh").decode().strip(), key.get_fingerprint("sha256")


def test_authorized_keys_keep_unknown_lines() -> None:
    ed, ed_fp = _public()
    rsa, rsa_fp = _public("ssh-rsa", "user@pc")
    text = f'command="uptime",no-pty {ed}\ngarbage\n\n{rsa}\n'
    lines = parse_authorized_keys(text)
    assert [line.index for line in lines] == [0, 1, 2, 3]
    first, junk, blank, last = lines
    assert (first.type, first.comment, first.options, first.fingerprint) == (
        "ssh-ed25519",
        "bob@pc",
        'command="uptime",no-pty',
        ed_fp,
    )
    assert (junk.type, junk.text, junk.fingerprint) == (None, "garbage", None)
    assert (blank.type, blank.text) == (None, "")
    assert (last.type, last.comment, last.fingerprint) == ("ssh-rsa", "user@pc", rsa_fp)
    assert render_authorized_keys([line.text for line in lines]) == text


def test_a_key_that_does_not_decode_is_kept_as_a_line() -> None:
    (line,) = parse_authorized_keys("ssh-ed25519 AAAAnotakey x@y\n")
    assert (line.type, line.fingerprint, line.text) == (None, None, "ssh-ed25519 AAAAnotakey x@y")


def test_check_key_line() -> None:
    ed, fp = _public()
    checked = check_key_line(f"  {ed}  ")
    assert (checked.type, checked.fingerprint, checked.text) == ("ssh-ed25519", fp, ed)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("", "Paste a public key"),
        ("ssh-ed25519 AAAA\nssh-ed25519 BBBB", "one key per line"),
        ("ssh-foo AAAAC3NzaC1lZDI1NTE5AAAAI x@y", "not an SSH public key"),
        ("ssh-ed25519 AAAA%%%% x@y", "does not decode"),
        ("ssh-ed25519 " + "A" * (16 * 1024), "at most 16 KiB"),
    ],
)
def test_key_line_refusals(line: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        check_key_line(line)


def test_labels() -> None:
    known = {"SHA256:harness": "dima_night"}
    assert label("SHA256:app", {"SHA256:app"}, known) == ("app", None)
    assert label("SHA256:harness", {"SHA256:app"}, known) == ("harness", "dima_night")
    assert label("SHA256:other", {"SHA256:app"}, known) == ("other", None)
    assert label(None, {"SHA256:app"}, known) == ("other", None)


def test_render_nothing() -> None:
    assert render_authorized_keys([]) == ""


def test_a_line_written_on_windows_keeps_its_crlf() -> None:
    """A key pasted from a Windows .pub ends in CRLF; rewriting the file for another key keeps that line as
    written (AP2, 2026-11-11: removing a test key turned it into LF)."""
    kept, kept_print = _public("ssh-rsa", "user@pc")
    gone, gone_print = _public()
    rows = parse_authorized_keys(f"{kept}\r\n{gone}\n")
    assert [(r.fingerprint, r.comment) for r in rows] == [(kept_print, "user@pc"), (gone_print, "bob@pc")]
    left = [r.text for r in rows if r.fingerprint != gone_print]
    assert render_authorized_keys(left) == f"{kept}\r\n"
    assert parse_authorized_keys(kept) == parse_authorized_keys(f"{kept}\n")  # no final newline: same rows
