"""Traffic generator (v1.2b R5, R6). Listen: socat forks a shell per peer (`SYSTEM:`), which names the peer
and hexdumps its data to the session's stream. Send: zeros or one line of text, at most 30 s, as one
command."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from openwrtgui.tools.sessions import LineParser, Peer, ToolSessionView, add_note, session_command
from openwrtgui.tools.throughput import check_host
from openwrtgui.transport.base import CommandResult
from openwrtgui.uci import shell_quote

# no commas, quotes or spaces inside the sed expression: socat's address parser keeps it whole
PER_PEER = "exec 1>&2; echo C$$ $SOCAT_PEERADDR $SOCAT_PEERPORT; hexdump -v -C | sed s/^/D$$=/"
SIZE_CAP = 50 * 2**20
SIZE_CAP_TEXT = "Stopped at the size cap (50 MB)"
FIRST_HEX = 128  # the first 64 bytes
SEND_LIMIT_S = 30
UDP_IDLE_S = 2  # a UDP sender's child ends 2 s after its last datagram
TEXT_RULE = "A line is 1 to 200 printable ASCII characters."
_TEXT = re.compile(r"[\x20-\x7e]{1,200}")
_PEER = re.compile(r"C(\d+) (\S+) (\d+)")
_DATA = re.compile(r"D(\d+)=[0-9a-f]{8}  (.*)")
_LAST_OFFSET = re.compile(r"D\d+=[0-9a-f]{8}")
_HEX_BYTE = re.compile(r"[0-9a-f]{2}")


class ListenRequest(BaseModel):
    protocol: Literal["tcp", "udp"]
    port: int = Field(ge=1, le=65535)
    duration_s: int = Field(60, ge=10, le=300)


class ListenStart(ListenRequest):
    digest: str


class SendRequest(BaseModel):
    protocol: Literal["tcp", "udp"]
    host: str
    port: int = Field(ge=1, le=65535)
    what: Literal["bytes", "text"]
    count: int = Field(1000, ge=1, le=10_000_000)
    text: str = ""


class SendApply(SendRequest):
    digest: str


class SendResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    detail: str


def listen_command(req: ListenRequest) -> tuple[str, int]:
    """The session's command and its limit in seconds."""
    child = f"SYSTEM:{shell_quote(PER_PEER)}"
    if req.protocol == "tcp":
        program = f"socat TCP-LISTEN:{req.port},reuseaddr,fork {child}"
    else:
        program = f"socat -T {UDP_IDLE_S} UDP-RECVFROM:{req.port},fork {child}"
    return session_command(req.duration_s, program), req.duration_s


def _with_bytes(peer: Peer, data: list[str]) -> Peer:
    room = max(0, FIRST_HEX - len(peer.first_hex))
    return peer.model_copy(
        update={"bytes": peer.bytes + len(data), "first_hex": peer.first_hex + "".join(data)[:room]}
    )


def listen_parser() -> LineParser:
    """A parser for one Listen session: it keeps which child pid serves which peer."""
    owners: dict[str, tuple[str, int]] = {}

    def parse(view: ToolSessionView, line: str) -> ToolSessionView:
        if m := _PEER.fullmatch(line):
            key = (m.group(2), int(m.group(3)))
            owners[m.group(1)] = key
            if all((p.address, p.port) != key for p in view.peers):
                peer = Peer(address=key[0], port=key[1], bytes=0, first_hex="")
                return view.model_copy(update={"peers": [*view.peers, peer]})
            return view
        if m := _DATA.fullmatch(line):
            owner = owners.get(m.group(1))
            if owner is None:
                return add_note(view, line)
            data = _HEX_BYTE.findall(m.group(2).split("|", 1)[0])
            peers = [_with_bytes(p, data) if (p.address, p.port) == owner else p for p in view.peers]
            view = view.model_copy(update={"peers": peers})
            if sum(p.bytes for p in peers) > SIZE_CAP:
                view = view.model_copy(update={"error": SIZE_CAP_TEXT})
            return view
        if _LAST_OFFSET.fullmatch(line) or not line.strip():
            return view
        return add_note(view, line)

    return parse


def _target(req: SendRequest) -> str:
    host = check_host(req.host)
    if req.protocol == "tcp":
        return f"TCP:{host}:{req.port},connect-timeout=5"
    return f"UDP-SENDTO:{host}:{req.port}"


def send_command(req: SendRequest) -> str:
    target = _target(req)
    if req.what == "text":
        if not _TEXT.fullmatch(req.text):
            raise ValueError(TEXT_RULE)
        source = f"printf '%s\\n' {shell_quote(req.text)}"
    else:
        source = f"head -c {req.count} /dev/zero"
    return f"{source} | timeout -s KILL {SEND_LIMIT_S} socat -u - {target} 2>&1"


def _sent(req: SendRequest) -> str:
    where = f"to {req.host} port {req.port} over {req.protocol.upper()}."
    if req.what == "text":
        return f"Sent the line ({len(req.text) + 1} bytes with its newline) {where}"
    return f"Sent {req.count} bytes {where}"


def send_result(req: SendRequest, result: CommandResult) -> SendResult:
    if result.exit_status == 0:
        return SendResult(ok=True, detail=_sent(req))
    if result.exit_status == 137:
        return SendResult(ok=False, detail="Stopped after 30 s: the other side did not take the data.")
    lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    last = lines[-1] if lines else ""
    detail = last.split(" E ", 1)[1].strip() if " E " in last else f"exit {result.exit_status}"
    return SendResult(ok=False, detail=detail)
