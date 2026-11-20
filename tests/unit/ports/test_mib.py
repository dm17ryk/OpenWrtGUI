"""Switch MIB counters per port (v1.2a Task 3): `swconfig dev <switch> show` prints them after `mib:`."""

from __future__ import annotations

from bridgeenv import BridgeEnv

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.net.commands import swconfig_show
from openwrtgui.ports.mib import NO_SWITCH, PortTotals, port_stats, totals
from openwrtgui.ports.parse import parse_port_mib
from openwrtgui.ports.service import PortsService
from openwrtgui.probe.board import SwitchPort
from openwrtgui.transport.base import CommandResult

SHOW = (
    "Global attributes:\n"
    "\tenable_vlan: 1\n"
    "\tmib: Switch MIB counters\n"
    "PPE_AC_BCNT0: 0\n"
    "\n"
    "Port 0:\n"
    "\tmib: Port 0 MIB counters\n"
    "TxGPC      : 0\n"
    "TxGOC      : 0\n"
    "RxGPC      : 0\n"
    "\n"
    "\tenable: 1\n"
    "\tlink: port:0 link:down\n"
    "Port 1:\n"
    "\tenable: 1\n"
    "\tlink: port:1 link:down\n"
    "Port 6:\n"
    "\tmib: Port 6 MIB counters\n"
    "TxGPC      : 58138\n"
    "TxBOC      : 0\n"
    "TxGOC      : 1448000972\n"
    "TxEPC      : 0\n"
    "RxGPC      : 45392\n"
    "RxBOC      : 0\n"
    "RxGOC      : 2151276205\n"
    "RxEPC1     : 0\n"
    "RxEPC2     : ???\n"
    "\n"
    "\tenable: ???\n"
    "\tlink: port:6 link:up speed:1000baseT full-duplex \n"
)

BOARD = (
    SwitchPort(num=6, role=None, label=None, cpu=True, device="eth0"),
    SwitchPort(num=1, role="lan", label="LAN2", cpu=False, device=None),
    SwitchPort(num=0, role="lan", label="LAN1", cpu=False, device=None),
)


def test_mib_parses_each_port() -> None:
    mib = parse_port_mib(SHOW)
    assert set(mib) == {0, 6}  # port 1 has no mib: line; the switch's own counters are not a port's
    assert mib[0] == {"TxGPC": 0, "TxGOC": 0, "RxGPC": 0}
    assert mib[6] == {
        "TxGPC": 58138,
        "TxBOC": 0,
        "TxGOC": 1448000972,
        "TxEPC": 0,
        "RxGPC": 45392,
        "RxBOC": 0,
        "RxGOC": 2151276205,
        "RxEPC1": 0,
    }  # RxEPC2 is ??? and left out


def test_totals_add_known_names() -> None:
    assert totals({"RxEPC1": 2, "RxEPC2": 3, "RxGOC": 10, "TxGPC": 7}) == PortTotals(
        rx_packets=None, rx_bytes=10, rx_errors=5, tx_packets=7, tx_bytes=None, tx_errors=None
    )
    assert totals({"Foo": 1}) == PortTotals(
        rx_packets=None, rx_bytes=None, rx_errors=None, tx_packets=None, tx_bytes=None, tx_errors=None
    )


def test_port_stats_from_one_show() -> None:
    stats = port_stats(
        "switch0", BOARD, {1: "Desk"}, CommandResult("swconfig dev switch0 show", SHOW, "", 0), 99.5
    )
    assert (stats.switch, stats.read_at, stats.note) == ("switch0", 99.5, None)
    assert [
        (p.num, p.label, p.link, p.speed_mbps) for p in stats.ports
    ] == [  # by label as on Ports, CPU last
        (1, "Desk", False, None),  # the label the router's record gives it
        (0, "LAN1", False, None),
        (6, "CPU", True, 1000),
    ]
    assert stats.ports[0].raw == {} and stats.ports[0].totals.rx_bytes is None  # no counters: "No counters"
    assert (stats.ports[2].totals.rx_bytes, stats.ports[2].totals.tx_packets) == (2151276205, 58138)


def test_each_counter_says_its_width_and_column() -> None:
    """The mt7620 counts packets and errors in 16 bits (AP2: 1.4 GB over 58138 packets is impossible else)
    and octets in 32: the page needs each width to tell a wrap from a reset (final review C1)."""
    stats = port_stats("switch0", BOARD, {}, CommandResult("swconfig dev switch0 show", SHOW, "", 0), 1.0)
    cpu = stats.ports[2]
    assert {n: cpu.bits[n] for n in ("TxGPC", "TxGOC", "TxBOC", "TxEPC", "RxGPC", "RxGOC", "RxEPC1")} == {
        "TxGPC": 16,
        "TxGOC": 32,
        "TxBOC": 32,
        "TxEPC": 16,
        "RxGPC": 16,
        "RxGOC": 32,
        "RxEPC1": 16,
    }
    assert cpu.columns == {
        "TxGPC": "tx_packets",
        "TxGOC": "tx_bytes",
        "TxEPC": "tx_errors",
        "RxGPC": "rx_packets",
        "RxGOC": "rx_bytes",
        "RxEPC1": "rx_errors",
    }  # the bad-octet counters are in no column
    other = port_stats(
        "switch0",
        (SwitchPort(num=0, role="lan", label="LAN1", cpu=False, device=None),),
        {},
        CommandResult("", "Port 0:\n\tmib: Port 0 MIB counters\nFoo : 3\n\n", "", 0),
        1.0,
    ).ports[0]
    assert (other.bits, other.columns) == ({"Foo": 32}, {})  # another driver's counter: 32-bit, no column


def test_port_stats_notes() -> None:
    assert port_stats(None, (), {}, None, 1.0).note == NO_SWITCH
    failed = CommandResult("swconfig dev switch0 show", "", "swconfig: no such device\nmore\n", 1)
    stats = port_stats("switch0", BOARD, {}, failed, 1.0)
    assert (stats.ports, stats.note) == ([], "Could not read the switch counters: swconfig: no such device")


def test_show_is_read_only() -> None:
    assert is_read_only_command(swconfig_show("switch0"))


async def test_a_dsa_router_has_no_switch_counters(bridge: BridgeEnv) -> None:
    ports = PortsService(
        pool=bridge.pool,
        routers=bridge.routers,
        guard=bridge.guard,
        audit=bridge.audit,
        descriptions=bridge.descriptions,
        runner=bridge.runner,
        now=lambda: 5.0,
    )
    stats = await ports.stats("ap5")
    assert (stats.switch, stats.ports, stats.note, stats.read_at) == (None, [], NO_SWITCH, 5.0)
