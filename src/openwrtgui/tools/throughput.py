"""Throughput (v1.2b R4): iperf3 runs on the router, as a client to a host you name or as a one-shot server
for your PC's iperf3. Both use `-J --json-stream --forceflush`, so a JSON object arrives each second."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from openwrtgui.tools.sessions import Interval, ThroughputSummary, ToolSessionView, add_note, session_command

HOST = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
HOST_TEXT = "A host is an IPv4 address or a name: letters, digits, dots and dashes."
SERVER_WAIT_S = 300
CLIENT_SLACK_S = 15  # iperf3's own connect and end, beyond the test itself
JSON_FLAGS = "-J --json-stream --forceflush"
CPU_WARNING = (
    "iperf3 runs on the router's CPU: on a small router the result is often the CPU's limit, not the link's."
)


def server_hint(router_host: str, port: int) -> str:
    return f"From your PC: iperf3 -c {router_host} -p {port}. The router waits up to 5 minutes for one test."


def check_host(host: str) -> str:
    """A host the router's tool may be given: no shell, no option, no socat address syntax (Review Focus
    1)."""
    if not HOST.fullmatch(host):
        raise ValueError(HOST_TEXT)
    return host


class ThroughputRequest(BaseModel):
    mode: Literal["client", "server"]
    host: str | None = None
    port: int = Field(5201, ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    reverse: bool = False
    duration_s: int = Field(10, ge=1, le=60)
    udp_mbps: int = Field(10, ge=1, le=1000)


class ThroughputStart(ThroughputRequest):
    digest: str


def iperf3_command(req: ThroughputRequest) -> tuple[str, int]:
    """The session's command and its limit in seconds."""
    if req.mode == "server":
        return session_command(SERVER_WAIT_S, f"iperf3 -s -1 -p {req.port} {JSON_FLAGS}"), SERVER_WAIT_S
    host = check_host(req.host or "")
    program = f"iperf3 -c {host} -p {req.port} -t {req.duration_s}"
    if req.protocol == "udp":
        program += f" -u -b {req.udp_mbps}M"
    if req.reverse:
        program += " -R"
    limit = req.duration_s + CLIENT_SLACK_S
    return session_command(limit, f"{program} {JSON_FLAGS}"), limit


def _mbps(part: dict[str, Any] | None) -> float | None:
    if not part or not isinstance(part.get("bits_per_second"), int | float):
        return None
    return round(float(part["bits_per_second"]) / 1e6, 1)


def _number(part: dict[str, Any] | None, key: str) -> float | None:
    value = (part or {}).get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _int(part: dict[str, Any] | None, key: str) -> int | None:
    value = (part or {}).get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _dict(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = data.get(key)
    return value if isinstance(value, dict) else None


def _interval(data: dict[str, Any]) -> Interval | None:
    total = _dict(data, "sum")
    mbps = _mbps(total)
    start, end = _number(total, "start"), _number(total, "end")
    if mbps is None or start is None or end is None:
        return None
    return Interval(
        start_s=start,
        end_s=end,
        mbps=mbps,
        retransmits=_int(total, "retransmits"),
        jitter_ms=_number(total, "jitter_ms"),
        lost_pct=_number(total, "lost_percent"),
    )


def _summary(data: dict[str, Any]) -> ThroughputSummary:
    total = _dict(data, "sum")
    sent = _dict(data, "sum_sent")
    received = _dict(data, "sum_received")
    return ThroughputSummary(
        sent_mbps=_mbps(sent) if sent else _mbps(total),
        received_mbps=_mbps(received) if received else _mbps(total),
        jitter_ms=_number(total, "jitter_ms"),
        lost_pct=_number(total, "lost_percent"),
        cpu_pct=_number(_dict(data, "cpu_utilization_percent"), "host_total"),
        retransmits=_int(sent, "retransmits"),
    )


def parse_iperf3_line(view: ToolSessionView, line: str) -> ToolSessionView:
    try:
        obj = json.loads(line)
    except ValueError:
        obj = None
    if not isinstance(obj, dict) or "event" not in obj:
        return add_note(view, line) if line.strip() else view
    event, data = obj.get("event"), obj.get("data")
    if event == "error":
        return view.model_copy(update={"error": f"iperf3: {data}"})
    if not isinstance(data, dict):
        return view
    if event == "interval" and (interval := _interval(data)) is not None:
        return view.model_copy(update={"intervals": [*view.intervals, interval]})
    if event == "end":
        return view.model_copy(update={"summary": _summary(data)})
    return view  # start, and events this version does not know
