"""Throughput and the Traffic generator against AP2's recorded tools (tools.json, the 1.2b window,
2026-11-20): iperf3 3.21's --json-stream lines from the router as client (TCP, TCP -R, UDP) and as server,
and socat Listen's lines for a TCP and a UDP peer that sent `owg-test\\n`."""

import json
from pathlib import Path

import pytest

from openwrtgui.tools.sessions import ToolSessionView
from openwrtgui.tools.throughput import parse_iperf3_line
from openwrtgui.tools.traffic import listen_parser

RECORDED = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "tools.json").read_text("utf-8")
)
PC = "192.168.1.10"


def _view(kind: str) -> ToolSessionView:
    return ToolSessionView(
        id="c",
        router_id="ap2",
        kind=kind,  # type: ignore[arg-type]
        title="contract",
        command="",
        started_at=0,
        ends_at=0,
        running=True,
    )


@pytest.mark.parametrize("key", ["client_tcp", "client_tcp_reverse", "client_udp", "server"])
def test_iperf3_runs_parse_to_seconds_and_totals(key: str) -> None:
    view = _view("throughput")
    for line in RECORDED[key]:
        view = parse_iperf3_line(view, line)
    assert view.error is None and view.notes == []
    assert len(view.intervals) >= 4 and all(i.mbps > 0 for i in view.intervals)
    summary = view.summary
    assert summary is not None and summary.cpu_pct is not None
    # the router as server only receives: its own "sent" total is 0
    assert max(summary.sent_mbps or 0, summary.received_mbps or 0) > 0


def test_udp_from_the_router_has_jitter_and_loss_only_in_the_totals() -> None:
    """AP2 window: the sender's per-second lines carry no jitter or loss (only the receiver measures them);
    they come with the end's totals."""
    view = _view("throughput")
    for line in RECORDED["client_udp"]:
        view = parse_iperf3_line(view, line)
    assert all(i.jitter_ms is None and i.lost_pct is None and i.retransmits is None for i in view.intervals)
    assert (
        view.summary is not None and view.summary.jitter_ms is not None and view.summary.lost_pct is not None
    )


@pytest.mark.parametrize("key", ["listen_tcp", "listen_udp"])
def test_listen_sees_the_pcs_peer(key: str) -> None:
    parse = listen_parser()
    view = _view("listen")
    for line in RECORDED[key]:
        view = parse(view, line)
    assert [(p.address, p.bytes, p.first_hex) for p in view.peers] == [(PC, 9, b"owg-test\n".hex())]
    assert view.notes == []
