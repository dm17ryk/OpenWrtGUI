"""Throughput (v1.2b R4): iperf3 on the router as client or one-shot server, its JSON lines read each
second."""

from __future__ import annotations

import json

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.tools.sessions import Interval, SessionView
from openwrtgui.tools.throughput import (
    HOST_TEXT,
    ThroughputRequest,
    check_host,
    iperf3_command,
    parse_iperf3_line,
)

HOSTILE_HOSTS = ["x; reboot", "$(id)", "-p", "a,b", "a:b", "a b", "a" * 254, "", "host\n"]


def _view() -> SessionView:
    return SessionView(
        id="s1",
        router_id="ap2",
        kind="throughput",
        title="Throughput",
        command="iperf3",
        started_at=0.0,
        ends_at=25.0,
        running=True,
    )


def _line(event: str, data: object) -> str:
    return json.dumps({"event": event, "data": data})


def test_client_command() -> None:
    command, limit = iperf3_command(ThroughputRequest(mode="client", host="192.168.1.10"))
    assert command == (
        'echo "OWG-PID $$"; exec timeout -s KILL 25 '
        "iperf3 -c 192.168.1.10 -p 5201 -t 10 -J --json-stream --forceflush 2>&1"
    )
    assert limit == 25
    assert not is_read_only_command(command)


def test_udp_reverse_client_command() -> None:
    req = ThroughputRequest(mode="client", host="pc.lan", protocol="udp", udp_mbps=20, reverse=True)
    command, _limit = iperf3_command(req)
    assert command == (
        'echo "OWG-PID $$"; exec timeout -s KILL 25 '
        "iperf3 -c pc.lan -p 5201 -t 10 -u -b 20M -R -J --json-stream --forceflush 2>&1"
    )
    assert not is_read_only_command(command)


def test_server_command() -> None:
    command, limit = iperf3_command(ThroughputRequest(mode="server"))
    assert command == (
        'echo "OWG-PID $$"; exec timeout -s KILL 300 iperf3 -s -1 -p 5201 -J --json-stream --forceflush 2>&1'
    )
    assert limit == 300
    assert not is_read_only_command(command)


def test_a_client_needs_a_host() -> None:
    with pytest.raises(ValueError, match=f"^{HOST_TEXT}$"):
        iperf3_command(ThroughputRequest(mode="client"))


@pytest.mark.parametrize("host", HOSTILE_HOSTS)
def test_hostile_hosts_are_refused(host: str) -> None:
    with pytest.raises(ValueError, match=f"^{HOST_TEXT}$"):
        check_host(host)
    with pytest.raises(ValueError, match=f"^{HOST_TEXT}$"):
        iperf3_command(ThroughputRequest(mode="client", host=host))


def test_good_hosts_pass() -> None:
    for host in ("192.168.1.10", "pc.lan", "my-pc", "a" * 253):
        assert check_host(host) == host


def test_ports_out_of_range_are_refused() -> None:
    for port in (0, 65536):
        with pytest.raises(ValueError):
            ThroughputRequest(mode="client", host="pc", port=port)


def test_tcp_interval() -> None:
    line = _line(
        "interval", {"streams": [], "sum": {"start": 0, "end": 1, "bits_per_second": 1.0e8, "retransmits": 2}}
    )
    view = parse_iperf3_line(_view(), line)
    assert view.intervals == [
        Interval(start_s=0, end_s=1, mbps=100.0, retransmits=2, jitter_ms=None, lost_pct=None)
    ]


def test_udp_interval() -> None:
    data = {"sum": {"start": 1, "end": 2, "bits_per_second": 2.0e7, "jitter_ms": 0.05, "lost_percent": 0.5}}
    view = parse_iperf3_line(_view(), _line("interval", data))
    assert view.intervals == [
        Interval(start_s=1, end_s=2, mbps=20.0, retransmits=None, jitter_ms=0.05, lost_pct=0.5)
    ]


def test_tcp_end() -> None:
    data = {
        "sum_sent": {"bits_per_second": 9.5e7, "retransmits": 3},
        "sum_received": {"bits_per_second": 9.4e7},
        "cpu_utilization_percent": {"host_total": 42.5},
    }
    summary = parse_iperf3_line(_view(), _line("end", data)).summary
    assert summary is not None
    assert (summary.sent_mbps, summary.received_mbps, summary.retransmits, summary.cpu_pct) == (
        95.0,
        94.0,
        3,
        42.5,
    )
    assert summary.jitter_ms is None and summary.lost_pct is None


def test_udp_end_from_sum() -> None:
    data = {
        "sum": {"bits_per_second": 2.0e7, "jitter_ms": 0.07, "lost_percent": 1.5},
        "cpu_utilization_percent": {"host_total": 12.0},
    }
    summary = parse_iperf3_line(_view(), _line("end", data)).summary
    assert summary is not None
    assert (summary.sent_mbps, summary.received_mbps, summary.jitter_ms, summary.lost_pct) == (
        20.0,
        20.0,
        0.07,
        1.5,
    )


def test_error_event() -> None:
    view = parse_iperf3_line(_view(), _line("error", "unable to connect to server: Connection refused"))
    assert view.error == "iperf3: unable to connect to server: Connection refused"


def test_start_and_unknown_events_are_ignored() -> None:
    for event in ("start", "whatever"):
        assert parse_iperf3_line(_view(), _line(event, {"cookie": "x"})) == _view()


def test_a_line_that_is_not_json_is_a_note() -> None:
    assert parse_iperf3_line(_view(), "iperf3: error - bad option").notes == ["iperf3: error - bad option"]
    assert parse_iperf3_line(_view(), "[1, 2]").notes == ["[1, 2]"]
