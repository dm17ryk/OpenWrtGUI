"""Traffic generator (v1.2b R5, R6): socat listens and shows each peer's bytes, or sends zeros or a line."""

from __future__ import annotations

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.tools.sessions import Peer, SessionView
from openwrtgui.tools.throughput import HOST_TEXT
from openwrtgui.tools.traffic import (
    SIZE_CAP,
    TEXT_RULE,
    ListenRequest,
    SendRequest,
    listen_command,
    listen_parser,
    send_command,
    send_result,
)
from openwrtgui.transport.base import CommandResult

HOSTILE_HOSTS = ["x; reboot", "$(id)", "-p", "a,b", "a:b", "a b", "a" * 254]
HELLO = "D4300=00000000  68 65 6c 6c 6f 0a                                 |hello.|"


def _view() -> SessionView:
    return SessionView(
        id="s2",
        router_id="ap2",
        kind="listen",
        title="Traffic listen",
        command="socat",
        started_at=0.0,
        ends_at=60.0,
        running=True,
    )


def _feed(*lines: str) -> SessionView:
    parse = listen_parser()
    view = _view()
    for line in lines:
        view = parse(view, line)
    return view


def test_tcp_listen_command() -> None:
    command, limit = listen_command(ListenRequest(protocol="tcp", port=9100, duration_s=60))
    assert command == (
        'echo "OWG-PID $$"; exec timeout -s KILL 60 socat TCP-LISTEN:9100,reuseaddr,fork '
        "SYSTEM:'exec 1>&2; echo C$$ $SOCAT_PEERADDR $SOCAT_PEERPORT; hexdump -v -C | sed s/^/D$$=/' 2>&1"
    )
    assert limit == 60
    assert not is_read_only_command(command)


def test_udp_listen_command() -> None:
    command, _limit = listen_command(ListenRequest(protocol="udp", port=9100, duration_s=20))
    assert command.startswith('echo "OWG-PID $$"; exec timeout -s KILL 20 socat -T 2 UDP-RECVFROM:9100,fork ')
    assert not is_read_only_command(command)


def test_listen_limits() -> None:
    for kw in (
        {"port": 0},
        {"port": 65536},
        {"port": 9100, "duration_s": 9},
        {"port": 9100, "duration_s": 301},
    ):
        with pytest.raises(ValueError):
            ListenRequest(protocol="tcp", **kw)  # type: ignore[arg-type]


def test_one_peer() -> None:
    view = _feed("C4300 192.168.1.10 51515", HELLO, "D4300=00000006")
    assert view.peers == [Peer(address="192.168.1.10", port=51515, bytes=6, first_hex="68656c6c6f0a")]
    assert view.notes == []


def test_two_pids_of_one_peer_add_up() -> None:
    view = _feed("C4300 192.168.1.10 51515", HELLO, "C4301 192.168.1.10 51515", HELLO.replace("4300", "4301"))
    assert len(view.peers) == 1 and view.peers[0].bytes == 12


def test_two_peers() -> None:
    view = _feed("C4300 192.168.1.10 51515", "C4301 192.168.1.20 40000", HELLO.replace("4300", "4301"))
    assert [(p.address, p.bytes) for p in view.peers] == [("192.168.1.10", 0), ("192.168.1.20", 6)]


def test_first_bytes_stop_at_64() -> None:
    row = "00 " * 16
    lines = [f"D4300={i * 16:08x}  {row} |................|" for i in range(13)]  # 208 bytes
    view = _feed("C4300 192.168.1.10 51515", *lines)
    assert view.peers[0].bytes == 208 and view.peers[0].first_hex == "0" * 128


def test_a_socat_error_is_a_note() -> None:
    line = "2026/11/20 10:00:00 socat[77] E bind(5, {AF=2 0.0.0.0:9100}, 16): Address in use"
    assert _feed(line).notes == [line]


def test_the_size_cap() -> None:
    view = _view().model_copy(
        update={"peers": [Peer(address="192.168.1.10", port=1, bytes=SIZE_CAP, first_hex="")]}
    )
    parse = listen_parser()
    view = parse(view, "C4300 192.168.1.10 1")
    view = parse(view, HELLO)
    assert view.error == "Stopped at the size cap (50 MB)"


def test_send_bytes_command() -> None:
    req = SendRequest(protocol="tcp", host="192.168.1.10", port=9101, what="bytes", count=1000)
    command = send_command(req)
    assert command == (
        "head -c 1000 /dev/zero | timeout -s KILL 30 socat -u - TCP:192.168.1.10:9101,connect-timeout=5 2>&1"
    )
    assert not is_read_only_command(command)


def test_send_text_command_is_quoted() -> None:
    req = SendRequest(protocol="tcp", host="192.168.1.10", port=9101, what="text", text="it's $(id)")
    assert send_command(req) == (
        "printf '%s\\n' 'it'\\''s $(id)' | timeout -s KILL 30 socat -u - "
        "TCP:192.168.1.10:9101,connect-timeout=5 2>&1"
    )


def test_send_udp_command() -> None:
    req = SendRequest(protocol="udp", host="pc.lan", port=9101, what="bytes", count=5)
    command = send_command(req)
    assert command == "head -c 5 /dev/zero | timeout -s KILL 30 socat -u - UDP-SENDTO:pc.lan:9101 2>&1"
    assert not is_read_only_command(command)


@pytest.mark.parametrize("text", ["two\nlines", "", "café", "a" * 201, "tab\there"])
def test_bad_text_is_refused(text: str) -> None:
    req = SendRequest(protocol="tcp", host="192.168.1.10", port=9101, what="text", text=text)
    with pytest.raises(ValueError, match=f"^{TEXT_RULE}$"):
        send_command(req)


@pytest.mark.parametrize("host", HOSTILE_HOSTS)
def test_hostile_hosts_are_refused(host: str) -> None:
    req = SendRequest(protocol="tcp", host=host, port=9101, what="bytes")
    with pytest.raises(ValueError, match=f"^{HOST_TEXT}$"):
        send_command(req)


def test_send_ports_out_of_range() -> None:
    for port in (0, 65536):
        with pytest.raises(ValueError):
            SendRequest(protocol="tcp", host="pc", port=port, what="bytes")


def test_result_texts() -> None:
    zeros = SendRequest(protocol="tcp", host="192.168.1.10", port=9101, what="bytes", count=1000)
    line = SendRequest(protocol="udp", host="192.168.1.10", port=9101, what="text", text="owg-line")
    ok = CommandResult("x", "", "", 0)
    assert send_result(zeros, ok).detail == "Sent 1000 bytes to 192.168.1.10 port 9101 over TCP."
    assert send_result(line, ok).detail == (
        "Sent the line (9 bytes with its newline) to 192.168.1.10 port 9101 over UDP."
    )
    stuck = send_result(zeros, CommandResult("x", "", "", 137))
    assert (stuck.ok, stuck.detail) == (False, "Stopped after 30 s: the other side did not take the data.")
    refused = CommandResult(
        "x",
        "2026/11/20 10:00:00 socat[77] E connect(5, AF=2 192.168.1.10:1, 16): Connection refused\n",
        "",
        1,
    )
    failed = send_result(zeros, refused)
    assert (failed.ok, failed.detail) == (False, "connect(5, AF=2 192.168.1.10:1, 16): Connection refused")
    assert send_result(zeros, CommandResult("x", "", "", 2)).detail == "exit 2"
